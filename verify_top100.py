"""100대 명산(미등록 73개) 들머리·교통·시니어팁·맛집 후보 웹조사 (선생님 PC에서 실행)
실행: py -3 verify_top100.py      (gpt-4o 웹검색 약 73회, 대략 2~4달러, 3~5분)
결과: top100_candidates.json  ※ 앱 데이터는 수정하지 않습니다. Claude가 지도·출처로 검증 후 반영합니다.
중간에 멈춰도 다시 실행하면 이미 받은 산은 건너뜁니다.
"""
import os, json, time, threading
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from openai import OpenAI
BASE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE, ".env"))
cli = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
OUT = os.path.join(BASE, "top100_candidates.json")
allm = json.load(open(os.path.join(BASE, "all_mountains.json"), encoding="utf-8"))
cache = {m["code"] for m in json.load(open(os.path.join(BASE, "mountains_cache.json"), encoding="utf-8"))}
targets = [m for m in allm if m["mntitop"].strip() and m["mntilistno"] not in cache]
done = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
lock = threading.Lock()

def ask(m):
    code = m["mntilistno"]
    if code in done and "error" not in done[code]:
        return
    name = m["mntiname"].replace("_", " ")
    addr = " ".join(m["mntiadd"].split())
    prompt = f"""산: {name} (해발 {m['mntihigh']}m, 소재지: {addr}) — 산림청 100대 명산
60대 이상 시니어가 대중교통으로 산행할 때 필요한 정보를 반드시 웹 검색(국립공원·지자체·관광공사 공식 페이지, 최근 산행기, 지도·맛집 플랫폼)으로 확인해 작성하세요.
확인되지 않은 정보는 지어내지 말고 빈 값("")으로 두세요. 거리·시간은 출처 표현 그대로 쓰고 직선거리를 도보거리로 바꾸지 마세요.
마크다운 없이 순수 JSON만 출력:
{{
 "trailhead": "가장 대표적이고 대중교통 접근이 쉬운 들머리의 정식 명칭(카카오맵에서 그대로 검색되는 이름: 탐방지원센터·매표소·주차장·사찰 등, 괄호 없이)",
 "trailhead_address": "들머리 주소(시·군·읍·면·리까지)",
 "transit": "들머리까지 대중교통: 가까운 기차역·터미널·지하철역 이름과 실제 버스 번호·하차 정류장명. 출처에 있는 내용만.",
 "transit_sources": ["교통 정보의 출처 URL들"],
 "tip": "시니어용 무릎 부담(바위·계단·급경사 여부), 가장 완만한 추천 코스와 소요시간, 준비물을 3문장 이내로",
 "tip_sources": ["출처 URL"],
 "foods": [{{"title": "들머리 인근(차로 15분 이내) 실제 영업 중인 식당 정식 상호", "tag": "메뉴 분류", "desc": "대표 메뉴 한 줄", "address": "도로명 주소"}}]
}}
식당은 2~3곳."""
    for attempt in range(2):
        try:
            t = time.time()
            r = cli.responses.create(model="gpt-4o", tools=[{"type": "web_search"}], input=prompt)
            raw = r.output_text
            data = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
            data.update(code=code, name=name, address=addr, sec=round(time.time() - t, 1))
            break
        except Exception as e:
            data = {"code": code, "name": name, "error": f"{type(e).__name__}: {str(e)[:200]}"}
    with lock:
        done[code] = data
        json.dump(done, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(("✘ " if "error" in data else "✔ ") + f"{name}  ({len(done)}/{len(targets)})")

print(f"대상 {len(targets)}개 / 이미 완료 {sum(1 for v in done.values() if 'error' not in v)}개")
with ThreadPoolExecutor(max_workers=6) as ex:
    list(ex.map(ask, targets))
err = [v["name"] for v in done.values() if "error" in v]
print(f"\n>> 완료. 실패 {len(err)}개 {err if err else ''}  (실패가 있으면 한 번 더 실행하세요)")
