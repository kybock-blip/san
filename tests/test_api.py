"""산림 큐레이터 백엔드 자동 테스트 (외부 API는 모두 가짜 응답으로 대체)
실행: py -3 -m pytest tests -v
"""
import os, sys, json, types
import xml.etree.ElementTree as ET
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main
from fastapi.testclient import TestClient

client = TestClient(main.app)


def xml_items(items):
    body = "".join("<item>" + "".join(f"<{k}>{v}</{k}>" for k, v in it.items()) + "</item>" for it in items)
    return ET.fromstring(f"<response><body><items>{body}</items></body></response>")


class FakeOpenAI:
    """chat.completions / responses 호출을 기록하고 지정한 응답을 돌려주는 가짜 클라이언트"""
    def __init__(self, chat_text="추천 결과", resp_text="{}", raise_exc=None):
        self.calls = []
        outer = self
        def chat_create(**kw):
            outer.calls.append(("chat", kw))
            if raise_exc: raise raise_exc
            msg = types.SimpleNamespace(content=chat_text)
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])
        def resp_create(**kw):
            outer.calls.append(("responses", kw))
            if raise_exc: raise raise_exc
            return types.SimpleNamespace(output_text=resp_text)
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=chat_create))
        self.responses = types.SimpleNamespace(create=resp_create)


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    """실제 tips_cache.json·외부 네트워크를 건드리지 않도록 격리"""
    monkeypatch.setattr(main, "TIP_CACHE_FILE", str(tmp_path / "tips.json"))
    monkeypatch.setattr(main, "tips_cache", {})
    monkeypatch.setattr(main, "live_mountains_store", {})
    def no_network(url):
        raise AssertionError(f"예상치 못한 외부 호출: {url}")
    monkeypatch.setattr(main, "fetch_xml", no_network)
    monkeypatch.setattr(main, "openai_client", FakeOpenAI())


# ---------- 화면 / 목록 ----------
def test_index_page():
    r = client.get("/")
    assert r.status_code == 200 and "산림 큐레이터" in r.text

def test_all_mountains_loaded():
    assert len(client.get("/api/mountains").json()) == len(main.cached_mountains) >= 33

def test_seoul_top100():
    names = [m["name"] for m in client.get("/api/mountains", params={"region": "서울", "top100_only": True}).json()]
    assert set(names) == {"북한산_백운대", "관악산", "도봉산_자운봉", "청계산_매봉"}

def test_every_mountain_has_region():
    total = set()
    for r in ["서울", "경기", "강원", "충청", "전라", "경상", "제주"]:
        total |= {m["code"] for m in client.get("/api/mountains", params={"region": r}).json()}
    assert len(total) == len(main.cached_mountains)

def test_elevation_partition():
    n = sum(len(client.get("/api/mountains", params={"elevation": e}).json()) for e in ["low", "mid", "high"])
    assert n == len(main.cached_mountains)

def test_cached_search_does_not_call_api():
    r = client.get("/api/mountains", params={"q": "북한산"})
    assert r.status_code == 200 and r.json()[0]["name"].startswith("북한산")


# ---------- 실시간 검색 (산림청 API 모킹) ----------
def test_live_search_fallback(monkeypatch):
    monkeypatch.setattr(main, "fetch_xml", lambda url: xml_items([
        {"mntilistno": "999", "mntiname": "수리산", "mntihigh": "489", "mntiadd": "경기도 군포시", "mntitop": ""}]))
    data = client.get("/api/mountains", params={"q": "수리산"}).json()
    assert [m["name"] for m in data] == ["수리산"]
    assert data[0]["image"] == "", "실시간 검색 산에 엉뚱한 기본 사진을 넣지 않음"
    assert "999" in main.live_mountains_store

def test_live_search_bad_height_keeps_other_items(monkeypatch):
    monkeypatch.setattr(main, "fetch_xml", lambda url: xml_items([
        {"mntilistno": "1", "mntiname": "가산", "mntihigh": "1,023m", "mntiadd": "경기도"},
        {"mntilistno": "2", "mntiname": "나산", "mntihigh": "300", "mntiadd": "경기도"}]))
    names = [m["name"] for m in client.get("/api/mountains", params={"q": "테스트산"}).json()]
    assert names == ["가산", "나산"], "높이 형식 하나가 잘못돼도 나머지 결과는 보여야 함"

def test_live_search_api_error_returns_empty(monkeypatch):
    def boom(url): raise TimeoutError("timeout")
    monkeypatch.setattr(main, "fetch_xml", boom)
    r = client.get("/api/mountains", params={"q": "없는산999"})
    assert r.status_code == 200 and r.json() == []

def test_live_search_query_is_url_encoded(monkeypatch):
    seen = []
    monkeypatch.setattr(main, "fetch_xml", lambda url: (seen.append(url), xml_items([]))[1])
    client.get("/api/mountains", params={"q": "a&numOfRows=9999"})
    assert "&numOfRows=9999" not in seen[0]


# ---------- 상세 ----------
def test_detail_cached(monkeypatch):
    def fake(url):
        if "Img" in url: return xml_items([{"imgfilename": "a.jpg", "imgname": "풍경"}])
        return xml_items([{"frtrlsectnnm": "1구간"}])
    monkeypatch.setattr(main, "fetch_xml", fake)
    d = client.get("/api/mountain/113500101").json()
    assert d["mountain"]["name"] == "불암산" and len(d["images"]) == 1 and d["trails"] == ["1구간"]

def test_detail_unknown_code_is_404(monkeypatch):
    monkeypatch.setattr(main, "fetch_xml", lambda url: xml_items([]))
    r = client.get("/api/mountain/000000000")
    assert r.status_code == 404, "모르는 산 코드는 mountain=null 대신 404여야 화면이 처리 가능"

def test_detail_code_injection_blocked(monkeypatch):
    seen = []
    monkeypatch.setattr(main, "fetch_xml", lambda url: (seen.append(url), xml_items([]))[1])
    client.get("/api/mountain/113500101&numOfRows=999")
    assert all("&numOfRows=999" not in u for u in seen)

def test_detail_api_error_still_returns_info(monkeypatch):
    def boom(url): raise TimeoutError()
    monkeypatch.setattr(main, "fetch_xml", boom)
    d = client.get("/api/mountain/113500101").json()
    assert d["mountain"]["name"] == "불암산" and d["images"] == [] and d["trails"] == []


# ---------- AI 추천 ----------
def items_json(*items):
    return json.dumps({"items": [dict(no=n, name=nm, reason="이유", access="교통", caution="주의") for n, nm in items]}, ensure_ascii=False)

def test_recommend_ok(monkeypatch):
    fake = FakeOpenAI(chat_text=items_json((1, "북한산 백운대")))
    monkeypatch.setattr(main, "openai_client", fake)
    r = client.post("/api/recommend", json={"query": "서울 산 1곳"}).json()
    assert r["recommendation"].startswith("[조건: 서울]") and "1. 북한산 백운대" in r["recommendation"]
    assert [m["code"] for m in r["mountains"]] == ["113050202"]

def test_recommend_region_filter_in_prompt(monkeypatch):
    fake = FakeOpenAI(chat_text=items_json((1, "계룡산 천황봉")))
    monkeypatch.setattr(main, "openai_client", fake)
    client.post("/api/recommend", json={"query": "충청남도에 있는 가을 단풍이 절경인 100대 명산 3곳"})
    prompt = fake.calls[0][1]["messages"][0]["content"]
    assert "계룡산" in prompt and "칠갑산" in prompt
    assert "내장산" not in prompt and "덕산 가야산" not in prompt and "덕항산" not in prompt, "충남·100대 조건 밖의 산은 후보에서 제외"

def test_recommend_text_and_cards_match(monkeypatch):
    """안내문 산과 카드 산이 반드시 같아야 함 (예전 오류: 안내문 내장산·계룡산 / 카드 덕항산·삼악산)"""
    cands, _ = main.filter_candidates("충청남도 100대 명산 3곳")
    names = [main.display_name(m) for m in cands]
    fake = FakeOpenAI(chat_text=items_json((1, names[0]), (99, "내장산"), (2, names[1]), (3, "엉뚱한이름")))
    monkeypatch.setattr(main, "openai_client", fake)
    r = client.post("/api/recommend", json={"query": "충청남도 100대 명산 3곳"}).json()
    card_names = [main.display_name(m) for m in r["mountains"]]
    assert "내장산" not in r["recommendation"], "후보 밖 산은 안내문에서도 제외"
    for i, n in enumerate(card_names, 1):
        assert f"{i}. {n}" in r["recommendation"]
    assert all("충청남도" in m["address"] and m["is_top100"] for m in r["mountains"])

def test_recommend_wrong_number_fixed_by_name(monkeypatch):
    cands, _ = main.filter_candidates("충청남도 100대 명산")
    target = cands[-1]
    fake = FakeOpenAI(chat_text=items_json((1, main.display_name(target))))
    monkeypatch.setattr(main, "openai_client", fake)
    r = client.post("/api/recommend", json={"query": "충청남도 100대 명산 1곳"}).json()
    assert r["mountains"][0]["code"] == target["code"], "번호와 이름이 다르면 이름 기준으로 보정"

def test_recommend_gentle_filter():
    cands, label = main.filter_candidates("무릎이 약한 70대가 갈 만한 완만한 산 3곳")
    assert cands and all(0 < m["height"] <= 800 for m in cands) and "완만" in label
    cands, _ = main.filter_candidates("강원도 단풍 100대 명산")
    assert any(m["height"] > 1000 for m in cands), "완만 조건이 없으면 고산도 후보"

def test_recommend_no_candidates(monkeypatch):
    fake = FakeOpenAI(chat_text=items_json((1, "x")))
    monkeypatch.setattr(main, "openai_client", fake)
    r = client.post("/api/recommend", json={"query": "제주 100대 명산 아닌 곳은 없나"}).json()
    assert r["mountains"] == [] or all("제주" in m["address"] for m in r["mountains"])

def test_recommend_empty_query_not_sent():
    r = client.post("/api/recommend", json={"query": "   "})
    assert main.openai_client.calls == [], "빈 입력은 서버에서도 OpenAI 호출 차단"
    assert r.status_code in (200, 400, 422)

def test_recommend_too_long_query_rejected():
    client.post("/api/recommend", json={"query": "가" * 5000})
    assert main.openai_client.calls == [], "과도하게 긴 입력은 비용 방지를 위해 차단"

def test_recommend_openai_error(monkeypatch):
    monkeypatch.setattr(main, "openai_client", FakeOpenAI(raise_exc=RuntimeError("down")))
    r = client.post("/api/recommend", json={"query": "추천"})
    assert r.status_code == 200 and "일시적으로" in r.json()["recommendation"]

def test_recommend_no_key(monkeypatch):
    monkeypatch.setattr(main, "openai_client", None)
    assert "API 키" in client.post("/api/recommend", json={"query": "추천"}).json()["recommendation"]


# ---------- 들머리·교통·맛집 ----------
TIP_BODY = {"name": "수리산", "height": 489, "address": "경기도 군포시", "details": "", "code": "999"}
GOOD = json.dumps({"trailhead": "수리산 성불사 입구 (군포)", "tip": "완만 [출처](http://x.com)",
                   "transit": "수원역 ➔ 13번 버스 ➔ 광교공원 하차 ([블로그](http://y.com))",
                   "foods": [{"title": "보리밥집", "tag": "한식", "desc": "맛있음 [링크](http://z)"}]}, ensure_ascii=False)

def test_tip_master_db_no_ai_call():
    r = client.post("/api/mountain-tip", json={**TIP_BODY, "name": "청계산_매봉", "code": "116500601", "departure": "잠실역"}).json()
    assert r["trailhead"] == "청계산 원터골입구" and "잠실역" in r["transit"]
    assert main.openai_client.calls == []
    assert r["source"] == "verified" and r["dest"]["kakao_id"]

def test_tip_web_search_cleans_links_and_caches(monkeypatch):
    fake = FakeOpenAI(resp_text="```json\n" + GOOD + "\n```")
    monkeypatch.setattr(main, "openai_client", fake)
    r = client.post("/api/mountain-tip", json=TIP_BODY).json()
    assert "http" not in r["transit"] + r["tip"] + r["foods"][0]["desc"]
    assert fake.calls[0][1]["tools"][0]["type"].startswith("web_search")
    assert os.path.exists(main.TIP_CACHE_FILE)
    assert r["source"] == "ai" and "(" not in r["trailhead"]

def test_tip_departure_change_reuses_cache(monkeypatch):
    fake = FakeOpenAI(resp_text=GOOD)
    monkeypatch.setattr(main, "openai_client", fake)
    client.post("/api/mountain-tip", json={**TIP_BODY, "departure": "잠실역"})
    client.post("/api/mountain-tip", json={**TIP_BODY, "departure": "수원역"})
    assert len(fake.calls) == 1, "출발지만 바뀌면 웹 검색(유료)을 다시 하지 않아야 함"

def test_tip_garbage_response_fallback(monkeypatch):
    monkeypatch.setattr(main, "openai_client", FakeOpenAI(resp_text="죄송합니다. 찾을 수 없습니다."))
    r = client.post("/api/mountain-tip", json=TIP_BODY)
    assert r.status_code == 200 and r.json()["trailhead"].startswith("수리산")
    assert main.tips_cache == {}

def test_tip_openai_error_fallback(monkeypatch):
    monkeypatch.setattr(main, "openai_client", FakeOpenAI(raise_exc=RuntimeError("timeout")))
    r = client.post("/api/mountain-tip", json=TIP_BODY)
    assert r.status_code == 200 and "지도" in r.json()["transit"]

def test_tip_missing_optional_fields():
    r = client.post("/api/mountain-tip", json={"name": "청계산_매봉", "code": "116500601"})
    assert r.status_code == 200, "높이·주소가 없는 실시간 산도 팁 요청이 실패하면 안 됨"
