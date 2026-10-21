"""외부 API 실호출 검증 스크립트 (선생님 PC에서 실행)
실행: py -3 verify_live.py
결과: live_check_result.txt 에 저장됩니다. (API 키는 기록하지 않습니다)
OpenAI 비용: gpt-4o-mini 1회 + gpt-4o 웹검색 2회 정도
"""
import os, sys, json, time, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE, ".env"))
FKEY = os.getenv("FOREST_API_KEY", "")
OKEY = os.getenv("OPENAI_API_KEY", "")
OUT = []
def log(*a):
    line = " ".join(str(x) for x in a); print(line); OUT.append(line)

ROOT = "http://apis.data.go.kr/1400000/service/cultureInfoService2/"
def forest(op, **params):
    url = ROOT + op + "?serviceKey=" + FKEY + "&" + urllib.parse.urlencode(params)
    t = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        body = r.read().decode("utf-8", errors="replace")
    root = ET.fromstring(body)
    code = root.findtext(".//resultCode") or root.findtext(".//returnReasonCode")
    msg = root.findtext(".//resultMsg") or root.findtext(".//returnAuthMsg")
    return root, round(time.time() - t, 2), code, msg

log("=== 0. 환경 ===")
log("python", sys.version.split()[0], "| FOREST_API_KEY", "있음" if FKEY else "없음", "| OPENAI_API_KEY", "있음" if OKEY else "없음")
try:
    import openai, fastapi; log("openai", openai.__version__, "| fastapi", fastapi.__version__)
except Exception as e: log("패키지 오류:", e)

log("\n=== 1. 산림청 산정보 검색 (mntInfoOpenAPI2) ===")
for word in ["북한산", "광교산", "아차산", "민둥산", "없는산999"]:
    try:
        root, sec, code, msg = forest("mntInfoOpenAPI2", searchWrd=word, numOfRows=20)
        items = root.findall(".//item")
        log(f"[{word}] {sec}s 결과코드={code} {msg} 건수={len(items)}")
        for it in items:
            log("   ", it.findtext("mntilistno"), it.findtext("mntiname"), it.findtext("mntihigh"), "|", it.findtext("mntiadd"), "| 100대:", bool((it.findtext("mntitop") or "").strip()))
    except Exception as e:
        log(f"[{word}] 실패: {type(e).__name__} {e}")

log("\n=== 2. 이미지 / 숲길 (불암산 113500101, 청계산 116500601) ===")
for c in ["113500101", "116500601"]:
    for op, tag in [("mntInfoImgOpenAPI2", "imgfilename"), ("frtrlSectnOpenAPI2", "frtrlsectnnm")]:
        try:
            root, sec, code, msg = forest(op, mntiListNo=c)
            vals = [i.findtext(tag) for i in root.findall(".//item")]
            log(f"[{c} {op}] {sec}s 코드={code} 건수={len(vals)} 예시={vals[:3]}")
            if op.startswith("mntInfoImg") and vals:
                u = "https://www.forest.go.kr/images/data/down/mountain/" + vals[0]
                try:
                    with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=10) as r:
                        log("    이미지 URL 접근:", r.status, r.headers.get("Content-Type"))
                except Exception as e:
                    log("    이미지 URL 접근 실패:", e)
        except Exception as e:
            log(f"[{c} {op}] 실패: {type(e).__name__} {e}")

log("\n=== 3. OpenAI ===")
if OKEY:
    from openai import OpenAI
    cli = OpenAI(api_key=OKEY)
    try:
        t = time.time()
        r = cli.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": "한 단어로 답: 서울에서 가장 높은 산은?"}], max_tokens=20)
        log(f"[gpt-4o-mini] {time.time()-t:.1f}s 정상:", r.choices[0].message.content)
    except Exception as e:
        log("[gpt-4o-mini] 실패:", type(e).__name__, str(e)[:300])
    for tool in ["web_search_preview", "web_search"]:
        try:
            t = time.time()
            r = cli.responses.create(model="gpt-4o", tools=[{"type": tool}],
                input="광주 무등산 증심사(증심사 종점)로 가는 광주 시내버스 노선 번호를 웹 검색으로 확인해서 번호만 쉼표로 나열하고, 출처 사이트 이름을 덧붙여 주세요.")
            log(f"[gpt-4o + {tool}] {time.time()-t:.1f}s 정상:", r.output_text[:500].replace("\n", " "))
        except Exception as e:
            log(f"[gpt-4o + {tool}] 실패:", type(e).__name__, str(e)[:300])
else:
    log("OPENAI_API_KEY 없음 - 건너뜀")

with open(os.path.join(BASE, "live_check_result.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(OUT))
print("\n>> live_check_result.txt 저장 완료. Claude에게 '실행했어요'라고 알려주세요.")
