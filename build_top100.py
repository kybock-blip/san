"""100대 명산 검증 결과(카카오맵 1·2차) + 웹조사 후보 → 마스터 DB 항목 생성 (미리보기 파일만 생성)"""
import json, re
from pyproj import Transformer
T = Transformer.from_crs("+proj=tmerc +lat_0=38 +lon_0=127 +k=1 +x_0=200000 +y_0=500000 +ellps=GRS80 +units=m", "EPSG:4326", always_xy=True)
cand = json.load(open('top100_candidates.json', encoding='utf-8'))
stage = {m['code']: m for m in json.load(open('top100_stage_cache.json', encoding='utf-8'))}

def parse_th(s):
    if not s: return None
    p = s.split('^')
    if len(p) < 6 or not p[3]: return None
    return dict(name=p[0], addr=p[1], cat=p[2], id=p[3], rt=p[4], q=p[5])
def parse_food(s):
    out = []
    for it in filter(None, s.split('#')):
        p = it.split('~')
        if p[0] == 'X': continue
        if len(p) == 5: out.append(dict(src='ai', want=p[0], name=p[1], addr=p[2], cat=p[3], id=p[4]))
        elif len(p) == 4: out.append(dict(src='near', name=p[0], addr=p[1], cat=p[2], id=p[3]))
    return out

th1, f1, th2, f2 = {}, {}, {}, {}
for line in open('top100_pass1.txt', encoding='utf-8').read().splitlines():
    code, th, fd = line.split('|', 2)
    th1[code] = parse_th(th); f1[code] = parse_food(fd)
for line in open('top100_pass2.txt', encoding='utf-8').read().splitlines():
    kind, code, rest = line.split('|', 2)
    if kind == 'T': th2[code] = parse_th(rest)
    else: f2[code] = parse_food(rest)

NOT_FOOD = re.compile(r'카페|찻집|커피|도넛|간식|토스트')
EXTRA_KEYS = {'482201101': ['봉수'], '412500201': ['평화로29']}
BAD_TH = re.compile(r'주유|S-OIL|해수욕장|수도권1호선')
def area(addr):
    for t in addr.split():
        if re.search(r'(읍|면)$', t): return t
    return None
def road(addr):
    for t in addr.split():
        if re.search(r'(로|길)\d*(번길)?$', t): return re.sub(r'\d+(번길)?$', '', t)
    return None
def clean(t):
    t = re.sub(r'\(\s*\[[^\]]*\]\([^)]*\)\s*\)', '', t or '')
    t = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', t)
    t = re.sub(r'\(?\s*(각\s*)?출처[^)。.]*(내용만|표현 그대로|명시된 경로[^)]*|기재|표기함|입력함)[^)]*\)?\.?', '', t)
    t = re.sub(r'출처에 있는 내용만\.?', '', t)
    t = re.sub(r'\s*–\s*출처에 있는 내용만 기재', '', t)
    t = re.sub(r'\s{2,}', ' ', t).strip(' ;,')
    return t.strip()

result, report = {}, []
for code, c in cand.items():
    st = stage[code]
    short = re.sub(r'\(.*?\)', '', st['name']).split('_')[0]
    th = th2.get(code) or th1.get(code)
    if th and BAD_TH.search(th['name'] + th['cat']): th = th2.get(code)
    dest = None
    if th and th.get('rt'):
        wx, wy = [int(v) for v in th['rt'].split(',')[2:4]]
        lng, lat = T.transform(wx / 2.5, wy / 2.5)
        dname = re.sub(r'분기점$', '', th['name']).strip()
        if dname in ('주차장',): dname = th['q']
        if short not in dname and th['cat'] in ('주차장', '공영주차장', '지명', '등산정보', '매표소'): dname = f"{short} {dname}"
        dest = dict(name=dname, kakao_id=th['id'], wx=wx, wy=wy, lat=round(lat, 6), lng=round(lng, 6))
    # 식당: 들머리 읍·면(또는 같은 길/관광지명) 기준
    th_area = area(th['addr']) if th else None
    th_road = road(th['addr']) if th else None
    keys = {short} | ({th_road} if th_road else set())
    if th:
        for w in re.findall(r'[가-힣]+', th['name']):
            root = re.sub(r'(탐방지원센터|탐방안내소|유원지|주차장|광장|관광단지|자연휴양림|매표소|관리사무소|분기점|국립공원|도립공원|공원)$', '', w)
            if len(root) >= 2 and root not in ('경주', '국립', '월악산', '설악산'): keys.add(root)
        dong = next((t for t in th['addr'].split() if t.endswith('동') and len(t) >= 3), None)
        if dong: keys.add(dong[:-1])
    keys |= set(EXTRA_KEYS.get(code, []))
    mt_areas = {t for t in st['address'].replace(',', ' ').split() if re.search(r'(읍|면)$', t)}
    def rank(f):
        """0: 들머리와 같은 읍·면/지명, 1: 산 소재지 읍·면, None: 제외"""
        if NOT_FOOD.search(f['cat']): return None
        a = area(f['addr'])
        if a and a == th_area: return 0
        if not (th_area and a) and any(k and k in f['addr'] for k in keys): return 0
        if a and a in mt_areas: return 1
        return None
    foods, seen = [], set()
    ai_desc = {(x.get('title') or '').strip(): x for x in c.get('foods', [])}
    pool = [f for f in f1.get(code, []) + f2.get(code, []) if rank(f) is not None]
    pool.sort(key=rank)
    for f in pool:
        if f['id'] in seen: continue
        seen.add(f['id'])
        loc = ' '.join(f['addr'].split()[2:]).replace(' 1층', '')
        d = (ai_desc.get(f.get('want', ''), {}) or {}).get('desc', '') if f['src'] == 'ai' else ''
        foods.append(dict(title=f['name'], tag=f['cat'], desc=(f"{loc}. {d}" if d else loc), kakao_id=f['id'], verified="2026-10-20"))
        if len(foods) == 3: break
    transit = clean(c.get('transit', ''))
    if not transit:
        transit = "버스 노선이 확인되지 않았습니다. 아래 지도 길찾기 버튼으로 대중교통 경로를 확인하세요."
    tip = clean(c.get('tip', '')) or "등산화와 스틱을 준비하고, 무리하지 않는 짧은 코스를 선택하세요."
    trailhead = dest['name'] if dest else (c.get('trailhead') or f"{short} 등산로 입구")
    result[code] = dict(trailhead=trailhead, tip=tip, transit=transit, foods=foods, level="checked")
    if dest: result[code]['dest'] = dest
    report.append(f"{st['name']:<10} | 들머리: {trailhead} ({th['addr'] if th else '-'}) | 식당 {len(foods)}: {', '.join(f['title'] for f in foods)}")
json.dump(result, open('top100_master_preview.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print('\n'.join(report))
print("\n좌표없음:", [stage[k]['name'] for k, v in result.items() if 'dest' not in v])
print("식당0:", [stage[k]['name'] for k, v in result.items() if not v['foods']])
print("교통미확인:", sum(1 for v in result.values() if v['transit'].startswith('버스 노선이 확인되지')))
