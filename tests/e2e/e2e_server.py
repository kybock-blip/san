# E2E용 서버: 외부 API를 가짜로 대체 (XSS 문자열, 지연 응답 포함)
import sys, time, types, json, xml.etree.ElementTree as ET
sys.path.insert(0, sys.argv[1])
import main
EVIL = "악성<img src=x onerror=window.__xss=1>산"
def x(items):
    b="".join("<item>"+"".join(f"<{k}>{v}</{k}>" for k,v in it.items())+"</item>" for it in items)
    return ET.fromstring(f"<r><items>{b}</items></r>")
def fake(url):
    from xml.sax.saxutils import escape
    if "mntInfoOpenAPI2" in url and "searchWrd" in url:
        if "%EC%95%85%EC%84%B1" in url:  # '악성'
            return x([{"mntilistno":"900000001","mntiname":escape(EVIL),"mntihigh":"300","mntiadd":"경기도 테스트시","mntitop":""}])
        if "%EB%8A%90%EB%A6%B0" in url:  # '느린'
            return x([{"mntilistno":"900000002","mntiname":"느린산","mntihigh":"400","mntiadd":"경기도","mntitop":""}])
        return x([])
    return x([])
main.fetch_xml = fake
def resp_create(**kw):
    if "느린산" in kw["input"]: time.sleep(3)
    name = "느린산" if "느린산" in kw["input"] else "악성산"
    return types.SimpleNamespace(output_text=json.dumps({"trailhead": f"{name} 입구","tip":f"{name} 팁","transit":f"{name} 교통 정보 테스트 문장입니다 1234567890",
        "foods":[{"title":"할매's <b>집</b>","tag":"한식","desc":"<script>window.__xss2=1</script>"}]}, ensure_ascii=False))
main.openai_client = types.SimpleNamespace(responses=types.SimpleNamespace(create=resp_create),
    chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=lambda **k: types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="추천: 불암산 <b>굵게</b>"))]))))
main.TIP_CACHE_FILE = "/tmp/tips_e2e.json"; main.tips_cache = {}
import uvicorn; uvicorn.run(main.app, port=8770, log_level="warning")
