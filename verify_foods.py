"""마스터 DB 맛집 실재 여부 웹 검증 (선생님 PC에서 실행)
실행: py -3 verify_foods.py      (gpt-4o 웹검색 33회, 약 1~2달러, 1~2분)
결과: foods_check.json  ※ 마스터 DB는 수정하지 않습니다. Claude가 결과를 검토한 뒤 반영합니다.
"""
import os, json, time
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from openai import OpenAI
BASE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE, ".env"))
cli = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
cache = {m["code"]: m for m in json.load(open(os.path.join(BASE, "mountains_cache.json"), encoding="utf-8"))}
master = json.load(open(os.path.join(BASE, "mountain_master_info.json"), encoding="utf-8"))

def check(code):
    m, info = cache[code], master[code]
    names = [f["title"] for f in info.get("foods", [])]
    prompt = f"""산: {m['name'].split('_')[0]} ({m['address']}), 들머리: {info['trailhead']}
아래 식당들이 들머리 인근(차로 15분 이내)에 실제로 존재하고 현재 영업 중인지 반드시 웹 검색(지도·플레이스·최근 리뷰)으로 확인하세요.
식당 목록: {json.dumps(names, ensure_ascii=False)}
또한 들머리 인근에서 웹 검색으로 실재가 확인된 시니어에게 적합한 식당 2곳을 추가로 제시하세요.
마크다운 없이 순수 JSON만 출력:
{{"checks":[{{"title":"원래 상호","status":"확인|미확인|폐업","real_name":"실제 정식 상호(다르면)","address":"주소","source":"출처 URL"}}],
 "suggestions":[{{"title":"상호","tag":"메뉴 분류","desc":"대표 메뉴와 특징 한 줄","address":"주소","source":"출처 URL"}}]}}"""
    for attempt in range(2):
        try:
            t = time.time()
            r = cli.responses.create(model="gpt-4o", tools=[{"type": "web_search"}], input=prompt)
            raw = r.output_text
            data = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
            data.update(code=code, name=m["name"], sec=round(time.time() - t, 1))
            print(f"✔ {m['name']}: " + ", ".join(f"{c['title']}={c['status']}" for c in data.get("checks", [])))
            return data
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:200]}"
    print(f"✘ {m['name']}: {err}")
    return {"code": code, "name": m["name"], "error": err}

with ThreadPoolExecutor(max_workers=5) as ex:
    results = list(ex.map(check, master.keys()))
json.dump(results, open(os.path.join(BASE, "foods_check.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\n>> foods_check.json 저장 완료. Claude에게 알려주세요.")
