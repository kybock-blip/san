"""산림청 전체 산 목록(3,368개) 내려받기 + 아차산·민둥산 교체용 데이터 추출
실행: py -3 verify_live2.py   (약 30~40초, 산림청 API만 사용 / OpenAI 비용 없음)
결과: all_mountains.json, replace_candidates.json
"""
import os, json, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from dotenv import load_dotenv
BASE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE, ".env"))
KEY = os.getenv("FOREST_API_KEY", "")
URL = "http://apis.data.go.kr/1400000/service/cultureInfoService2/mntInfoOpenAPI2"
FIELDS = ["mntilistno","mntiname","mntihigh","mntiadd","mntitop","mntidetails","mntiadmin","mntiadminnum","mntisname","mntisummary"]
allm, page = [], 1
while True:
    q = URL + "?serviceKey=" + KEY + "&" + urllib.parse.urlencode({"pageNo": page, "numOfRows": 200})
    root = ET.fromstring(urllib.request.urlopen(urllib.request.Request(q, headers={"User-Agent": "Mozilla/5.0"}), timeout=20).read().decode("utf-8", "replace"))
    items = root.findall(".//item")
    if not items: break
    allm += [{f: (it.findtext(f) or "").strip() for f in FIELDS} for it in items]
    total = int(root.findtext(".//totalCount") or 0)
    print(f"page {page}: 누적 {len(allm)}/{total}")
    if len(allm) >= total: break
    page += 1
json.dump(allm, open(os.path.join(BASE, "all_mountains.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
cand = [m for m in allm if m["mntilistno"] == "112150201" or "민둥" in m["mntiname"] or ("정선" in m["mntiadd"] and "남면" in m["mntiadd"])]
json.dump(cand, open(os.path.join(BASE, "replace_candidates.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("후보", len(cand), "건:", [(c["mntilistno"], c["mntiname"], c["mntiadd"]) for c in cand])
print(">> 완료. Claude에게 알려주세요.")
