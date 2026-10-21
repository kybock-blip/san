import os
import re
import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
API_KEY = os.getenv("FOREST_API_KEY", "")
if not API_KEY:
    print("[경고] FOREST_API_KEY가 .env에 없습니다. 산림청 실시간 검색·사진·숲길이 동작하지 않습니다.")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")

openai_client = OpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None

app = FastAPI(title="San Curator API")

CACHE_FILE = os.path.join(BASE_DIR, "mountains_cache.json")
cached_mountains = []

# 공공데이터 높이 결측치(0m) 보정 매핑 테이블
ELEVATION_CORRECTIONS = {
    "114100801": 836.5,  # 북한산 (서대문 자락 레코드 -> 주봉 백운대 기준 836.5m)
    "431502001": 604.0,  # 제천 무등산 (604m)
    "437701101": 431.8,  # 음성 소속리산 (431.8m)
    "282601001": 84.6,   # 인천 서구 금정산 (84.6m)
    "418203701": 849.1,  # 가평 청계산 (849.1m)
    "448100301": 677.6,  # 예산 덕산_가야산 (677.6m)
}

if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        cached_mountains = json.load(f)
    for m in cached_mountains:
        if m.get("code") in ELEVATION_CORRECTIONS and (not m.get("height") or m.get("height") == 0):
            m["height"] = ELEVATION_CORRECTIONS[m["code"]]

# 지역 버튼 → 주소 키워드 매핑 (광역시·특별자치도 포함)
REGION_KEYWORDS = {
    "서울": ["서울"],
    "경기": ["경기", "인천"],
    "강원": ["강원"],
    "충청": ["충청", "충북", "충남", "대전", "세종"],
    "전라": ["전라", "전북", "전남", "광주"],
    "경상": ["경상", "경북", "경남", "대구", "부산", "울산"],
    "제주": ["제주"],
}

def match_region(region: Optional[str], address: str) -> bool:
    if not region or region == "전체":
        return True
    keywords = REGION_KEYWORDS.get(region, [region])
    return any(k in (address or "") for k in keywords)

def parse_height(text: str) -> float:
    """'1,023m', '836.5 m', '' 등 다양한 높이 표기를 안전하게 숫자로 변환 (실패 시 0)"""
    try:
        return float(re.sub(r"[^0-9.]", "", text or "") or 0)
    except ValueError:
        return 0.0

def clean_details(text: str) -> str:
    """산림청 설명에서 마침표·괄호만 있는 빈 줄을 제거"""
    lines = [ln.strip() for ln in (text or "").replace("\r", "\n").split("\n")]
    return "\n".join(ln for ln in lines if re.search(r"[0-9A-Za-z가-힣]", ln)).strip()

CODE_PATTERN = re.compile(r"^\d{1,15}$")

def fetch_xml(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return ET.fromstring(resp.read().decode("utf-8", errors="replace"))

# 실시간 검색된 산 정보 임시 저장소 (상세 모달 조회용)
live_mountains_store = {}

@app.get("/api/mountains")
def get_mountains(
    q: Optional[str] = None,
    region: Optional[str] = None,
    elevation: Optional[str] = None,
    top100_only: bool = False
):
    results = cached_mountains

    if top100_only:
        results = [m for m in results if m.get("is_top100")]

    if region and region != "전체":
        results = [m for m in results if match_region(region, m.get("address", ""))]

    if elevation == "low":
        results = [m for m in results if m.get("height", 0) <= 500]
    elif elevation == "mid":
        results = [m for m in results if 500 < m.get("height", 0) <= 1000]
    elif elevation == "high":
        results = [m for m in results if m.get("height", 0) > 1000]

    if q:
        q_lower = q.strip().lower()
        filtered = [m for m in results if q_lower in m.get("name", "").lower() or q_lower in m.get("address", "").lower()]
        
        # 캐시에 없으면 산림청 OpenAPI 실시간 호출
        if not filtered:
            try:
                url = f"http://apis.data.go.kr/1400000/service/cultureInfoService2/mntInfoOpenAPI2?serviceKey={API_KEY}&searchWrd={urllib.parse.quote(q.strip())}&numOfRows=10"
                root = fetch_xml(url)
                for item in root.findall(".//item"):
                    code = item.findtext("mntilistno", "").strip()
                    name = item.findtext("mntiname", "").strip()
                    top_reason = item.findtext("mntitop", "").strip()
                    addr = item.findtext("mntiadd", "").strip()
                    high = parse_height(item.findtext("mntihigh", "0"))
                    if high == 0 and code in ELEVATION_CORRECTIONS:
                        high = ELEVATION_CORRECTIONS[code]
                    
                    is_top = bool(top_reason)

                    # 8번 오류 해결: 실시간 검색 결과에도 사용자의 필터 조건 엄격 적용
                    if top100_only and not is_top:
                        continue
                    if not match_region(region, addr):
                        continue
                    if elevation == "low" and high > 500:
                        continue
                    elif elevation == "mid" and not (500 < high <= 1000):
                        continue
                    elif elevation == "high" and high <= 1000:
                        continue

                    m_obj = {
                        "code": code,
                        "name": name,
                        "height": high,
                        "address": addr,
                        "is_top100": is_top,
                        "top100_reason": top_reason,
                        "details": clean_details(item.findtext("mntidetails", ""))[:1000],
                        "admin": item.findtext("mntiadmin", "").strip(),
                        "admin_phone": item.findtext("mntiadminnum", "").strip(),
                        "image": ""
                    }
                    filtered.append(m_obj)
                    # 7번 오류 해결: 실시간 검색 산도 상세 조회 가능하도록 저장소에 등록
                    live_mountains_store[code] = m_obj
            except Exception as e:
                print("OpenAPI live search error:", e)

        return filtered

    return results

@app.get("/api/mountain/{code}")
def get_mountain_detail(code: str):
    if not CODE_PATTERN.match(code):
        raise HTTPException(status_code=400, detail="잘못된 산 코드입니다.")
    # 7번 오류 해결: 캐시에서 먼저 찾고, 없으면 실시간 검색 저장소에서 탐색
    base_info = next((m for m in cached_mountains if m["code"] == code), None)
    if not base_info and code in live_mountains_store:
        base_info = live_mountains_store[code]
    if not base_info:
        raise HTTPException(status_code=404, detail="산 정보를 찾을 수 없습니다. 목록에서 다시 검색해 주세요.")
    
    # 1. 이미지 실시간 조회
    images = []
    try:
        url = f"http://apis.data.go.kr/1400000/service/cultureInfoService2/mntInfoImgOpenAPI2?serviceKey={API_KEY}&mntiListNo={urllib.parse.quote(code)}"
        root = fetch_xml(url)
        for item in root.findall(".//item"):
            fname = item.findtext("imgfilename", "").strip()
            title = item.findtext("imgname", "").strip()
            if fname:
                images.append({
                    "url": f"https://www.forest.go.kr/images/data/down/mountain/{fname}",
                    "title": title
                })
    except Exception as e:
        print("Image API error:", e)

    # 2. 숲길/탐방로 구간 실시간 조회
    trails = []
    try:
        url = f"http://apis.data.go.kr/1400000/service/cultureInfoService2/frtrlSectnOpenAPI2?serviceKey={API_KEY}&mntiListNo={urllib.parse.quote(code)}"
        root = fetch_xml(url)
        for item in root.findall(".//item"):
            t_name = item.findtext("frtrlsectnnm", "").strip()
            if t_name:
                trails.append(t_name)
    except Exception as e:
        print("Trail API error:", e)

    return {
        "mountain": base_info,
        "images": images,
        "trails": trails
    }

class RecommendRequest(BaseModel):
    query: str


# ---------- AI 추천용 조건 해석 ----------
REGION_TERMS = [  # (질문 속 표현, 주소에 포함될 문자열들, 표시명)
    (("서울 근교", "서울근교", "수도권"), ("서울", "경기", "인천"), "서울·경기·인천"),
    (("충청남도", "충남"), ("충청남도", "충남"), "충청남도"),
    (("충청북도", "충북"), ("충청북도", "충북"), "충청북도"),
    (("전라남도", "전남"), ("전라남도", "전남"), "전라남도"),
    (("전라북도", "전북"), ("전라북도", "전북"), "전라북도"),
    (("경상남도", "경남"), ("경상남도", "경남"), "경상남도"),
    (("경상북도", "경북"), ("경상북도", "경북"), "경상북도"),
    (("충청도", "충청"), ("충청", "충북", "충남", "대전", "세종"), "충청권"),
    (("전라도", "전라", "호남"), ("전라", "전북", "전남", "광주"), "전라권"),
    (("경상도", "경상", "영남"), ("경상", "경북", "경남", "대구", "부산", "울산"), "경상권"),
    (("강원",), ("강원",), "강원"), (("제주",), ("제주",), "제주"), (("경기",), ("경기",), "경기"),
    (("서울",), ("서울",), "서울"), (("인천",), ("인천",), "인천"), (("부산",), ("부산",), "부산"),
    (("대구",), ("대구",), "대구"), (("대전",), ("대전",), "대전"), (("울산",), ("울산",), "울산"),
    (("광주광역시", "광주 "), ("광주광역시",), "광주"),
]

GENTLE_WORDS = re.compile(r"무릎|완만|초보|가벼운|가볍게|쉬운|쉽게|부모님|[789]0대|산책|힘들지 않")
GENTLE_MAX_HEIGHT = 800

def short_name(m: dict) -> str:
    return re.sub(r"\(.*?\)", "", m["name"]).split("_")[0].strip()

def display_name(m: dict) -> str:
    return m["name"].replace("_", " ")

def filter_candidates(query: str):
    """질문에서 지역·100대 명산 조건을 읽어 후보 산을 먼저 거른다 (AI가 조건을 무시하지 못하도록)"""
    q = query.replace(" ", " ")
    labels, region_keys, used = [], [], ""
    for terms, keys, label in REGION_TERMS:
        hit = next((t for t in terms if t in q and t not in used), None)
        if hit:
            region_keys += list(keys); labels.append(label); used += hit + " "
            if label in ("충청남도", "충청북도", "전라남도", "전라북도", "경상남도", "경상북도", "서울·경기·인천"):
                used += "충청 전라 경상 서울 경기 인천 "  # 상위 권역 중복 인식 방지
    result = cached_mountains
    if region_keys:
        result = [m for m in result if any(k in m.get("address", "") for k in region_keys)]
    if "100대" in q:
        result = [m for m in result if m.get("is_top100")]
        labels.append("100대 명산")
    if GENTLE_WORDS.search(q):
        gentle = [m for m in result if 0 < (m.get("height") or 0) <= GENTLE_MAX_HEIGHT]
        if gentle:
            result = sorted(gentle, key=lambda m: m.get("height") or 0)
            labels.append(f"완만한 산({GENTLE_MAX_HEIGHT}m 이하)")
    return result, (", ".join(labels) if labels else "전국")

def parse_count(query: str, n: int) -> int:
    m = re.search(r"(\d)\s*(곳|개|군데)", query)
    k = int(m.group(1)) if m else 3
    return max(1, min(k, 3, n))

@app.post("/api/recommend")
def recommend_mountains(req: RecommendRequest):
    if not openai_client:
        return {"recommendation": "OpenAI API 키가 설정되지 않았습니다. .env 파일을 확인해 주세요."}

    query = (req.query or "").strip()
    if not query:
        return {"recommendation": "원하시는 산행 조건을 입력해 주세요. (예: 무릎에 무리 없는 서울 근교 산)"}
    if len(query) > 300:
        return {"recommendation": "질문이 너무 깁니다. 300자 이내로 줄여서 다시 입력해 주세요."}

    try:
        candidates, cond_label = filter_candidates(query)
        if not candidates:
            return {"recommendation": f"말씀하신 조건({cond_label})에 맞는 산이 목록에 없습니다. 지역이나 조건을 바꿔 다시 물어봐 주세요.", "mountains": []}
        want = parse_count(query, len(candidates))

        # 후보 산에 짧은 번호를 붙여 근거 자료로 전달 (검증된 들머리·교통·시니어 팁 포함)
        lines = []
        for i, m in enumerate(candidates, 1):
            info = master_mountain_info.get(m["code"], {})
            line = (f"[{i}] {display_name(m)} | 고도 {m['height']}m | {m['address']} | "
                    f"100대명산 {'예' if m['is_top100'] else '아니오'}")
            if m.get("top100_reason"):
                line += f" | 선정이유: {m['top100_reason'][:120]}"
            if info:
                line += (f" | 들머리: {info['trailhead']} | 교통: {info['transit'][:150]}"
                         f" | 시니어 팁: {info['tip'][:200]}")
            lines.append(line)
        prompt_context = "\n".join(lines)

        system_prompt = f"""당신은 60대 이상 시니어를 돕는 친절한 산행 안내자입니다.
아래 [후보 산]은 사용자의 조건({cond_label})에 맞춰 이미 걸러진 목록입니다. 이 목록 안에서만 사용자 요청에 가장 잘 맞는 산 {want}곳을 고르세요.

[후보 산]
{prompt_context}

[반드시 지킬 규칙]
- 후보 번호(no)와 산 이름(name)은 [후보 산]에 적힌 그대로 쓰세요.
- 추천 이유·들머리·교통·주의할 점은 [후보 산]에 적힌 내용만 근거로 쓰고, 없는 장소·버스 번호·식당은 지어내지 마세요.
- 바위·계단이 많은 산은 그 사실을 주의할 점에 분명히 적으세요.
- 사용자가 무릎·완만·초보·가벼운·부모님·70대 등을 언급하면 고도가 낮고(대략 700m 이하) 시니어 팁에 완만한 코스가 적힌 산을 우선하고, 1,000m가 넘는 고산은 피하세요.
- 마크다운 기호 없이 짧고 쉬운 문장으로 쓰세요.

[출력 형식] 반드시 아래 JSON 하나만 출력하세요.
{{"items": [{{"no": 후보번호, "name": "산 이름", "reason": "추천 이유 한두 문장", "access": "들머리와 교통 한 문장", "caution": "주의할 점 한 문장"}}]}}
"""

        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query}
            ],
            temperature=0.3,
            response_format={"type": "json_object"}
        )

        raw = response.choices[0].message.content or ""
        try:
            items = json.loads(raw).get("items", [])
        except (ValueError, AttributeError):
            items = []

        # 검증: 후보 번호가 범위 안이고 이름이 일치하는 항목만 채택 (번호가 틀리면 이름으로 보정)
        picked = []
        for it in items if isinstance(items, list) else []:
            if not isinstance(it, dict):
                continue
            m = None
            try:
                no = int(it.get("no"))
                if 1 <= no <= len(candidates):
                    m = candidates[no - 1]
            except (TypeError, ValueError):
                pass
            name = str(it.get("name") or "").strip()
            if m is None or (name and short_name(m) not in name and name not in display_name(m)):
                m = next((c for c in candidates if name and (short_name(c) == name or display_name(c) == name or short_name(c) in name)), None)
            if m and all(m["code"] != p["code"] for p, _ in picked):
                picked.append((m, it))
            if len(picked) == want:
                break

        if not picked:
            return {"recommendation": "추천 결과를 만들지 못했습니다. 조건을 조금 바꿔 다시 물어봐 주세요.", "mountains": []}

        parts = []
        for i, (m, it) in enumerate(picked, 1):
            parts.append(f"{i}. {display_name(m)}\n"
                         f"추천 이유: {str(it.get('reason', '')).strip()}\n"
                         f"들머리와 교통: {str(it.get('access', '')).strip()}\n"
                         f"주의할 점: {str(it.get('caution', '')).strip()}")
        text = f"[조건: {cond_label}]\n\n" + "\n\n".join(parts) + "\n\n자세한 길찾기는 아래 산 카드를 눌러 확인하세요."
        cards = [{k: m.get(k) for k in ("code", "name", "height", "address", "is_top100", "image")} for m, _ in picked]
        return {"recommendation": text, "mountains": cards}
    except Exception as e:
        # 10번 오류 해결: AI 호출 중 오류 발생 시 먹통 방지 및 안내 문구 반환
        print("Recommend API error:", e)
        return {"recommendation": "일시적으로 AI 추천 서버와 연결이 원활하지 않습니다. 아래 지역 및 고도 필터 카드를 통해 마음에 드는 명산을 둘러보세요."}

class TipRequest(BaseModel):
    name: str
    height: Optional[float] = None
    address: str = ""
    details: str = ""
    code: Optional[str] = None
    departure: Optional[str] = None

MASTER_INFO_FILE = os.path.join(BASE_DIR, "mountain_master_info.json")
master_mountain_info = {}
if os.path.exists(MASTER_INFO_FILE):
    try:
        with open(MASTER_INFO_FILE, "r", encoding="utf-8") as f:
            master_mountain_info = json.load(f)
    except Exception as e:
        print("Master info load error:", e)

TIP_CACHE_FILE = os.path.join(BASE_DIR, "tips_cache.json")
tips_cache = {}
if os.path.exists(TIP_CACHE_FILE):
    try:
        with open(TIP_CACHE_FILE, "r", encoding="utf-8") as f:
            tips_cache = json.load(f)
    except Exception:
        tips_cache = {}

def clean_markdown_artifacts(text: str) -> str:
    """웹 검색 결과에 포함된 마크다운 링크 찌꺼기([출처](url) 등)를 깔끔하게 제거"""
    if not text:
        return ""
    text = re.sub(r'\(\s*\[[^\]]+\]\([^)]+\)\s*\)', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'\(\s*\)', '', text)
    text = re.sub(r'\s{2,}', ' ', text)
    return text.strip()

def with_departure(data: dict, departure: Optional[str]) -> dict:
    """들머리 기준 교통 정보 앞에 출발지 → 지도 길찾기 안내를 붙임 (AI가 환승 경로를 지어내지 않도록)"""
    result = dict(data)
    if departure:
        result["transit"] = (
            f"[{departure} 출발 안내]\n"
            f"아래 지도 길찾기 버튼을 누르시면 {departure}에서 '{data.get('trailhead', '')}'까지의 실시간 환승 경로(지하철·버스·소요시간)가 연결됩니다.\n\n"
            f"[도착지 대중교통 정보]\n{data.get('transit', '')}"
        )
    return result

def fallback_tip(clean_name: str, transit: str) -> dict:
    return {
        "trailhead": f"{clean_name} 등산로 입구",
        "tip": "등산화와 스틱을 준비하고 무리하지 않는 코스를 선택하세요.",
        "transit": transit,
        "foods": []
    }

@app.post("/api/mountain-tip")
def get_mountain_tip(req: TipRequest):
    clean_name = req.name.split("_")[0].strip()
    code = req.code or ""
    departure = (req.departure or "").strip()

    # [1순위] 사전 검증 마스터 DB (즉시 응답)
    if code in master_mountain_info:
        info = master_mountain_info[code]
        return with_departure({
            "trailhead": info["trailhead"],
            "tip": info["tip"],
            "transit": info["transit"],
            "foods": info.get("foods", []),
            "dest": info.get("dest"),
            "source": info.get("level", "verified")
        }, departure)

    # [2순위] 동적 캐시 (산 기준 저장 → 출발지가 바뀌어도 웹 검색 재호출 없음)
    cache_key = code if code else clean_name
    cached = tips_cache.get(cache_key)
    if cached and "확인되지" not in cached.get("transit", ""):
        return with_departure({**cached, "source": "ai"}, departure)

    if not openai_client:
        return fallback_tip(clean_name, f"{req.address} 인근 역/터미널에서 시내버스 이용".strip())

    height_txt = f"{req.height}m" if req.height else "정보 없음"
    prompt = f"""산 이름: {clean_name} (높이: {height_txt}, 위치: {req.address})
산림청 설명: {req.details[:300]}

반드시 웹 검색을 수행하여 사실로 확인된 정보만 아래 JSON 형식으로 응답하세요 (마크다운 링크 표기 없이 순수 텍스트로만 작성, 마크다운 코드블록 없이 순수 JSON만 출력):
{{
  "trailhead": "카카오맵/네이버지도에서 그대로 검색되는 대표 등산로 입구·탐방지원센터의 정식 명칭만 (괄호·부연설명 없이, 예: 청계산 원터골입구, 북한산성탐방지원센터)",
  "tip": "60대 이상 시니어를 위한 무릎 부담도(계단/데크길 여부), 추천 완만 코스, 준비물 3줄 요약",
  "transit": "웹 검색으로 확인된 대표 들머리 대중교통 정보 (지하철 노선·역명·출구번호, 실제 정차 버스 번호·정류장명). 출발지에서의 환승 경로는 추측하지 말고 들머리 기준 도착역/정류장만 작성하세요. 거리·시간은 출처 표현 그대로 쓰고 직선거리를 도보거리로 바꾸지 마세요. 도보가 15분 이상이면 버스 이용을 먼저 안내하세요.",
  "foods": [
    {{"title": "웹 검색으로 확인된 산 입구 실제 유명 식당 상호명 또는 먹거리촌", "tag": "대표 메뉴 분류", "desc": "실제 대표 메뉴와 특징 한 줄"}}
  ]
}}"""

    try:
        resp = openai_client.responses.create(
            model="gpt-4o",
            tools=[{"type": "web_search"}],
            input=prompt
        )
        raw = resp.output_text.strip()
        if "```" in raw:
            raw = raw.split("```json")[-1].split("```")[0].strip()
        start, end = raw.find("{"), raw.rfind("}")
        data = json.loads(raw[start:end+1])

        # 마크다운 링크 찌꺼기 정제
        for key in ("transit", "tip", "trailhead"):
            if key in data:
                data[key] = clean_markdown_artifacts(str(data[key]))
        if not isinstance(data.get("foods"), list):
            data["foods"] = []
        for item in data["foods"]:
            if isinstance(item, dict) and "desc" in item:
                item["desc"] = clean_markdown_artifacts(item["desc"])

        data["trailhead"] = re.sub(r"\s*[\(（].*?[\)）]", "", str(data.get("trailhead", ""))).strip()

        # 유효한 응답인 경우에만 캐시 저장
        transit_text = data.get("transit", "")
        if data.get("trailhead") and "확인되지" not in transit_text and len(transit_text) > 20:
            tips_cache[cache_key] = data
            with open(TIP_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(tips_cache, f, ensure_ascii=False, indent=2)

        return with_departure({**data, "source": "ai"}, departure)
    except Exception as e:
        print("Tip API error:", e)
        return fallback_tip(clean_name, "하단 지도 길찾기 버튼을 눌러 실시간 대중교통 경로를 확인하세요.")

# 정적 파일 서빙
STATIC_DIR = os.path.join(BASE_DIR, "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
def read_root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
