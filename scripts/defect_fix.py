"""defect_fix.py — 원더랜드 결함 A항목 일괄 제거 (2026-11-19, 보드 s-defect-fix 승인).

대상: data/cleanup_plan_1117.json 의 keep 글(301·410 대상 글은 손대지 않는다).
① 제목과 맞지 않는 체크 위젯(orig-tool)·표·공공 캡처 제거(originality.fits 기준)
② 'AI로 연출' 장식 사진 제거, 도해는 제목과 가장 겹치는 1장만 남김(대표 이미지는 WP featured라 무관)
④ 링크 없는 문단의 출처 없는 비용·통계 문장 삭제(%·원·명·건)
⑤ 바이라인 '날짜 확인·정리' → '정리일 YYYY-MM-DD', '🔎 …기준으로 내용을 확인했습니다' → 정리일 + 화면 차이 안내
⑥ 대상·감정형 제목 → plan.titles (슬러그 유지)
사람이 고친 글 보호: modified가 발행 후 1시간 넘게 지났고 2026-11-13 07:00(UTC) 이후면 건드리지 않고 보고.
DRY=1 기본(전체 집계 + 2편 전후), DRY=0 적용(원문 data/defect_backup/<id>.html). ONLY·LIMIT 지원. LLM 호출 없음.
"""
import base64, json, os, re, sys, time, html as H
from datetime import datetime, timedelta
import requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import originality as O

PLAN = json.load(open("data/cleanup_plan_1117.json", encoding="utf-8"))
TOOL_KEY = {"부모님 폰, 이것만": "setup_list", "요금제, 이 정도면": "plan_fit", "전화·문자, 위험한가요": "scam_check",
            "정부 앱 발급 전": "gov_ready", "키오스크 연습": "kiosk_drill"}
NUM = re.compile(r"\d[\d,\.]*\s?(?:%|퍼센트|만 ?원|천 ?원|원|만 ?명|명|만 ?건|건)(?![가-힣]*(?:단계|번째))")
SKIP_P = re.compile(r'class="(?:byline|verified|freshness|ai-notice|author-box|hook)')
T = lambda s: H.unescape(re.sub(r"<[^>]+>", "", s or ""))
GUARD = datetime(2026, 11, 13, 7, 0)


def _auth():
    wp = json.load(open("config.json", encoding="utf-8"))["wordpress"]
    base = wp["site_url"].rstrip("/")
    tok = base64.b64encode(f"{wp['username']}:{wp['app_password']}".encode()).decode()
    return base, {"User-Agent": "Mozilla/5.0 (ScriptoBot)", "Authorization": f"Basic {tok}", "Content-Type": "application/json"}


def _blocks(html, open_re):
    """open_re로 시작하는 div 블록의 (start,end) 목록(중첩 균형)."""
    out = []
    for m in re.finditer(open_re, html):
        i, depth = m.start(), 0
        for t in re.finditer(r"<div\b|</div>", html[i:]):
            depth += 1 if t.group(0).startswith("<div") else -1
            if depth == 0:
                out.append((i, i + t.end())); break
    return out


def _cut(html, spans):
    for a, b in sorted(spans, reverse=True):
        html = html[:a] + html[b:]
    return html


def _toks(s):
    return {w for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", s.lower())}


def fix(html, title):
    st = dict(widget=0, table=0, ai_photo=0, diagram=0, shot=0, numsent=0, byline=0, verified=0)
    # ① 위젯·표
    rm = []
    for a, b in _blocks(html, r'<div class="orig-tool"'):
        head = T(html[a:a + 600])
        key = next((v for k, v in TOOL_KEY.items() if k in head), None)
        if not O.fits(key, title):
            rm.append((a, b)); st["widget"] += 1
    for a, b in _blocks(html, r'<div class="orig-table"'):
        if not O.fits("mvnohub_senior", title):
            rm.append((a, b)); st["table"] += 1
    html = _cut(html, rm)
    # ② 이미지
    figs = list(re.finditer(r"<figure\b.*?</figure>", html, re.S))
    rm, diag = [], []
    for m in figs:
        cap = T((re.search(r"<figcaption[^>]*>(.*?)</figcaption>", m.group(0), re.S) or [None, ""])[1])
        if "AI로 연출" in cap:
            rm.append(m.span()); st["ai_photo"] += 1
        elif "실제 캡처(공공 사이트)" in cap:
            if not O.fits("mvnohub", title):
                rm.append(m.span()); st["shot"] += 1
        else:
            diag.append((len(_toks(cap) & _toks(title)), m.span()))
    if len(diag) > 1:
        diag.sort(key=lambda x: -x[0])
        for _, sp in diag[1:]:
            rm.append(sp); st["diagram"] += 1
    html = _cut(html, rm)
    # ④ 출처 없는 수치 문장
    def para(m):
        tag, inner = m.group(1), m.group(2)
        if SKIP_P.search(tag) or "<a " in inner or "<img" in inner:
            return m.group(0)
        parts = re.split(r"(?<=[.!?。])\s+", inner)
        keep = [p for p in parts if not NUM.search(T(p))]
        if len(keep) == len(parts):
            return m.group(0)
        st["numsent"] += len(parts) - len(keep)
        return f"{tag}{' '.join(keep)}</p>" if T(" ".join(keep)).strip() else ""
    html = re.sub(r"(<p\b[^>]*>)(.*?)</p>", para, html, flags=re.S)
    # ⑤ 허위 확인 문구
    def kd(y, mo, d):
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    html, n = re.subn(r"(<p class=\"byline\"[^>]*>.*?)(\d{4})년 (\d{1,2})월 (\d{1,2})일 확인·정리",
                      lambda m: f"{m.group(1)}정리일 {kd(m.group(2), m.group(3), m.group(4))}", html, count=1, flags=re.S)
    html, n2 = re.subn(r"(<p class=\"byline\"[^>]*>.*?)\d{4}년 최신 확인·정리", r"\1정리", html, count=1, flags=re.S)
    st["byline"] = n + n2
    html, n = re.subn(r"🔎 (\d{4})년 (\d{1,2})월 (\d{1,2})일 기준으로 내용을 확인했습니다\.",
                      lambda m: f"🗓️ 정리일 {kd(m.group(1), m.group(2), m.group(3))} · 화면과 메뉴 이름은 기기·소프트웨어 버전에 따라 다를 수 있습니다.", html)
    st["verified"] = n
    return html, st


def main():
    dry = os.getenv("DRY", "1") != "0"
    only = {int(x) for x in re.split(r"[,\s]+", os.getenv("ONLY", "")) if x.isdigit()}
    limit = int(os.getenv("LIMIT", "0") or 0)
    keep = set(PLAN["keep"]) if not only else only & set(PLAN["keep"])
    base, Hh = _auth()
    posts, pg = [], 1
    while True:
        r = requests.get(f"{base}/wp-json/wp/v2/posts", headers=Hh, timeout=60,
                         params={"per_page": 50, "page": pg, "status": "publish", "context": "edit",
                                 "_fields": "id,title,content,date_gmt,modified_gmt"})
        if not r.ok: break
        b = r.json(); posts += b
        if len(b) < 50: break
        pg += 1
    todo, guarded, tot = [], [], {}
    for p in posts:
        if p["id"] not in keep: continue
        d, mo = datetime.fromisoformat(p["date_gmt"]), datetime.fromisoformat(p["modified_gmt"])
        if mo - d > timedelta(hours=1) and mo > GUARD:
            guarded.append(f"#{p['id']} 수정 {p['modified_gmt'][:16]}"); continue   # 사람 수정 가능성 → 보호
        raw = p["content"]["raw"]; title = p["title"]["raw"]
        new, st = fix(raw, title)
        nt = PLAN["titles"].get(str(p["id"]))
        if nt and nt != title: st["title"] = 1
        for k, v in st.items(): tot[k] = tot.get(k, 0) + v
        if new != raw or st.get("title"):
            todo.append((p, raw, new, nt, st))
    if limit: todo = todo[:limit]
    print(f"남길 글 {len(keep)}편 중 변경 대상 {len(todo)}편 {'(미리보기)' if dry else '(적용)'}")
    print("합계:", json.dumps(tot, ensure_ascii=False))
    print(f"보호(11/13 07:00 UTC 이후 수정된 글, 건드리지 않음) {len(guarded)}편:", guarded[:20])
    for p, raw, new, nt, st in todo[:3]:
        print(f"\n── #{p['id']} {p['title']['raw'][:40]}\n  {st}\n  글자수 {len(T(raw))} → {len(T(new))}" + (f"\n  제목 → {nt}" if nt else ""))
    if dry: return 0
    os.makedirs("data/defect_backup", exist_ok=True)
    done, fail = 0, []
    for p, raw, new, nt, st in todo:
        open(f"data/defect_backup/{p['id']}.html", "w", encoding="utf-8").write(json.dumps({"title": p["title"]["raw"], "content": raw}, ensure_ascii=False))
        body = {"content": new}
        if nt: body["title"] = nt
        u = requests.post(f"{base}/wp-json/wp/v2/posts/{p['id']}", headers=Hh, timeout=90, json=body)
        if u.ok: done += 1
        else: fail.append(f"#{p['id']} {u.status_code}")
        time.sleep(0.6)
    print(f"적용 {done}편 · 실패 {fail}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
