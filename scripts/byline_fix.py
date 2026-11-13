"""byline_fix.py — 발행 글 상단 바이라인의 잘린 소개문을 걷어내고 글 끝 author-box로 옮긴다 (2026-11-13).

원인: main.py가 페르소나 소개를 [:120]으로 잘라 바이라인에 넣어 '…순서로 다시 정 ·'처럼
문장 중간에서 끊긴 채 글 첫머리에 노출됐다(11/9 실측 71/79편).
조치: 바이라인은 '✍️ 이름 · 날짜 확인·정리'만 남기고, 잘리지 않은 소개 전문을 AI 고지 바로 앞에 둔다.
본문 문장은 건드리지 않는다. DRY=1(기본) 미리보기, DRY=0 적용(원문은 data/byline_backup/<id>.html).
ONLY=2604,2611 특정 글만. LIMIT=n 상한(기본 0=전체).
"""
import base64, json, os, re, sys, time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import generator

BIO_SPAN = re.compile(r'(<p class="byline"[^>]*>)(.*?)\s*<span[^>]*>\s*·.*?</span>(.*?</p>)', re.S)


def _auth():
    cfg = json.load(open("config.json", encoding="utf-8"))
    wp = cfg.get("wordpress", {}) or {}
    base = wp["site_url"].rstrip("/")
    tok = base64.b64encode(f"{wp['username']}:{wp['app_password']}".encode()).decode()
    return base, {"User-Agent": "Mozilla/5.0 (ScriptoBot)", "Authorization": f"Basic {tok}",
                  "Content-Type": "application/json"}


def fix(html, author, bio):
    """(새 html, 바뀌었는지)"""
    new = BIO_SPAN.sub(lambda m: m.group(1) + m.group(2) + m.group(3), html, count=1)
    if new == html:
        return html, False
    if "author-box" not in new:
        box = generator._author_box_html(author, bio)
        i = new.find('<p class="ai-notice"')
        new = new[:i] + box + new[i:] if i >= 0 else new + box
    return new, True


def main():
    dry = os.getenv("DRY", "1") != "0"
    only = {int(x) for x in os.getenv("ONLY", "").replace(" ", ",").split(",") if x.strip().isdigit()}
    limit = int(os.getenv("LIMIT", "0") or 0)
    pj = json.load(open("data/persona.json", encoding="utf-8"))
    pa = pj.get(pj.get("mode", "auto")) or {}
    author, bio = pa.get("pen_name") or "이음", pa.get("identity") or ""
    base, H = _auth()
    posts, pg = [], 1
    while True:
        r = requests.get(f"{base}/wp-json/wp/v2/posts", headers=H, timeout=60,
                         params={"per_page": 50, "page": pg, "status": "publish", "context": "edit",
                                 "_fields": "id,title,content"})
        if not r.ok:
            break
        b = r.json(); posts += b
        if len(b) < 50:
            break
        pg += 1
    if only:
        posts = [p for p in posts if p["id"] in only]
    todo = []
    for p in posts:
        raw = (p.get("content") or {}).get("raw") or ""
        new, ch = fix(raw, author, bio)
        if ch:
            todo.append((p, raw, new))
    if limit:
        todo = todo[:limit]
    print(f"발행 {len(posts)}편 중 잘린 소개 바이라인 {len(todo)}편 {'(미리보기)' if dry else '(적용)'}")
    for p, raw, new in todo[:2]:
        b0 = re.search(r'<p class="byline".*?</p>', raw, re.S).group(0)
        b1 = re.search(r'<p class="byline".*?</p>', new, re.S).group(0)
        print(f"\n── #{p['id']}\n  전: {re.sub(r'<[^>]+>', '', b0)}\n  후: {re.sub(r'<[^>]+>', '', b1)}")
        ab = re.search(r'<p class="author-box".*?</p>', new, re.S)
        print("  글 끝 소개:", re.sub(r"<[^>]+>", "", ab.group(0)) if ab else "-")
    if dry:
        return 0
    os.makedirs("data/byline_backup", exist_ok=True)
    done, fail = 0, []
    for p, raw, new in todo:
        open(f"data/byline_backup/{p['id']}.html", "w", encoding="utf-8").write(raw)
        u = requests.post(f"{base}/wp-json/wp/v2/posts/{p['id']}", headers=H, timeout=60, json={"content": new})
        if u.ok:
            done += 1
        else:
            fail.append(f"#{p['id']} {u.status_code}")
        time.sleep(0.5)
    print(f"적용 {done}편, 실패 {len(fail)} {fail}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
