# 산림 큐레이터 (San Curator) — 작업 인수인계

60대 이상 시니어를 위한 산행 안내 웹 서비스. 산림청 공공데이터 + OpenAI로 산 추천, 들머리 대중교통, 하산 후 식당을 안내한다.
2026-10-20 정밀 검증으로 오류 44건을 수정했고 산 목록을 107개(산림청 100대 명산 전체 포함)로 확장했다.
상세 내역: `오류점검_수정내역.md`, `Service_Plan261020.md` 끝의 "정밀 검증 이력".

## 실행·테스트 (Windows)
- 서버: `start_server.bat` 더블클릭 → http://localhost:8000 (`py -3 -m uvicorn main:app --port 8000 --reload`)
- 백엔드 테스트: `py -3 -m pytest tests -v` (30건, 외부 API는 모킹 — 네트워크·비용 없음). 코드 수정 후 반드시 실행
- 화면 E2E: `tests/e2e/e2e.js` + `tests/e2e/e2e_server.py` (Playwright, 외부 API 가짜 응답)
- 패키지: `requirements.txt`. API 키는 `.env`의 `FOREST_API_KEY`, `OPENAI_API_KEY` (코드에 키를 쓰지 말 것)

## 파일 구조
| 파일 | 역할 |
|---|---|
| `main.py` | FastAPI 서버 전부 (산 목록·검색·상세·AI 추천·들머리 팁 API) |
| `static/index.html` | 화면 전부 (Tailwind CDN, Lucide 아이콘, 바닐라 JS) |
| `mountains_cache.json` | 목록에 보이는 산 107개 (산림청 정보 + 사진 URL) |
| `mountain_master_info.json` | 산별 검증 데이터: 들머리·교통·시니어 팁·식당·지도 좌표 |
| `tips_cache.json` | 목록에 없는 산을 검색했을 때 AI 웹검색 결과 캐시 |
| `all_mountains.json` | 산림청 전체 4,705개 원본 (git 제외, `verify_live2.py`로 재생성) |
| `verify_*.py` | 사용자 PC에서 돌리는 외부 API·데이터 검증 스크립트 |
| `build_top100.py`, `top100_*` | 100대 명산 73개 추가 때의 검증 중간 산출물 (출처 추적용) |
| `_backup_20261020/` | 수정 전 원본 (git 제외) |

## 데이터 형식 (mountain_master_info.json, 키 = 산림청 코드)
```json
{"trailhead": "청계산 원터골입구", "tip": "...", "transit": "...",
 "foods": [{"title": "청계산장수촌", "tag": "닭요리", "desc": "...", "kakao_id": "9367373", "verified": "2026-10-20"}],
 "dest": {"name": "청계산 원터골 입구", "kakao_id": "26562319", "wx": 512222, "wy": 1095621, "lat": 37.443622, "lng": 127.055246},
 "level": "checked"}
```
- `level` 없음 = 사전 검증(기존 35개), `"checked"` = 지도 확인(100대 명산 신규 73개). 화면에 등급 배지로 표시된다
- `dest.wx/wy` = 카카오맵 내부 좌표(WCONGNAMUL). 위경도 변환: TM(lat_0=38, lon_0=127, k=1, x_0=200000, y_0=500000, GRS80)에 wx/2.5, wy/2.5 (오차 0m 검증됨)
- `foods[].kakao_id` = 카카오맵 장소 ID → 식당 버튼이 `https://place.map.kakao.com/{id}`로 연결

## 반드시 지킬 설계 원칙 (어기면 과거 오류가 재발함)
1. **AI 추천 조건은 서버가 먼저 거른다** (`filter_candidates`): 지역·100대 명산·완만(800m 이하). AI는 걸러진 후보 번호만 고르고, 안내문과 카드는 서버가 같은 데이터로 만든다. AI에게 조건 판단이나 코드 작성을 맡기지 말 것
2. **AI가 만든 사실을 검증 없이 마스터 DB에 넣지 않는다**: 식당은 카카오맵 장소 ID와 주소(들머리와 같은 읍·면)로, 들머리는 카카오맵 장소·좌표로 확인. 확인 안 된 정보는 빈 값 또는 "지도로 확인" 안내
3. **지도 길찾기**: 도착지(들머리 좌표)만 넣고 출발지는 사용자가 지도에서 입력. 카카오 `?target=traffic&rt=,,{wx},{wy}&rt2={name}`, 네이버 `/p/directions/-/{x},{y},{name},,ADDRESS_POI/-/transit` (x,y = 웹 메르카토르)
4. **화면에 넣는 외부 문자열은 `esc()`로 처리**, 비동기 응답은 요청 순번(`modalRequestSeq`, `listRequestSeq`)으로 늦은 응답 무시
5. 동명 산 주의: 이름이 같은 산이 많다(아차산·민둥산·백운산 등). 항상 산림청 코드와 주소로 확인

## 주의사항
- `.json` 데이터를 고치면 서버가 자동으로 다시 읽지 않는다 (`--reload`는 `.py`만 감시) → 서버 재시작
- 산림청·OpenAI·카카오맵은 사용자 PC 네트워크에서만 접근 가능 (클라우드 환경에서는 차단될 수 있음)
- 산림청 가이드 문서(.docx)는 오퍼레이션명을 `mntInfoOpenAPI`로 적었지만 실제로는 `*OpenAPI2`만 동작
- 맛집·버스는 바뀐다. 발표·배포 전 `verify_foods.py`로 재검증 권장
- 과거 코드에 산림청 API 키가 하드코딩되어 있었음(제거 완료) → 재발급 검토

## 남은 과제
- 교통 노선 미확인 12곳, 들머리 주변 식당 미확인 5곳(덕항산·방장산·운장산·태화산·황장산), 산림청 사진 없음 10곳
- AI 추천의 시·군 단위 지역 인식 (예: "단양 근처")
- 추가 기능: 큰 글씨 모드, 음성 안내(TTS), 한줄 리뷰, 주변 즐길거리
