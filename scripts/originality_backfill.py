"""originality_backfill.py — 기발행 글에 독창성 층(표·도구·화면) 소급 적용 (2026-10-10). 멱등(MARK)."""
import base64
import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import originality as O


def main():
    dry = os.getenv("DRY", "1") != "0"
    cfg = json.load(open("config.json", encoding="utf-8"))
    wp = cfg.get("wordpress", {}) or {}
    base = wp["site_url"].rstrip("/")
    tok = base64.b64encode(f"{wp['username']}:{wp['app_password']}".encode()).decode()
    H = {"User-Agent": "Mozilla/5.0 (ScriptoBot)", "Authorization": f"Basic {tok}", "Content-Type": "application/json"}
    cats = {c["id"]: c["slug"] for c in requests.get(f"{base}/wp-json/wp/v2/categories?per_page=100&_fields=id,slug", headers=H, timeout=30).json()}
    posts, pg = [], 1
    while True:
        r = requests.get(f"{base}/wp-json/wp/v2/posts", headers=H, timeout=60,
                         params={"per_page": 50, "page": pg, "status": "publish", "context": "edit", "_fields": "id,title,content,categories"})
        if not r.ok: break
        b = r.json(); posts += b
        if len(b) < 50: break
        pg += 1
    done, skip, fail, by = 0, 0, [], {}
    for p in posts:
        slugs = [cats.get(c, "") for c in p.get("categories", [])]
        sub = next((s for s in slugs if s in O.PLAN), None)
        raw = (p.get("content") or {}).get("raw") or ""
        new, ch = O.enrich_html(raw, sub)
        if not ch:
            skip += 1; continue
        by[sub] = by.get(sub, 0) + 1
        if dry:
            print(f"  · #{p['id']} [{sub}] 표/도구/화면 삽입 예정 — {p['title']['raw'][:36]}")
            continue
        u = requests.post(f"{base}/wp-json/wp/v2/posts/{p['id']}", headers=H, timeout=60, json={"content": new})
        (print(f"  ✓ #{p['id']} [{sub}]") if u.ok else fail.append(f"#{p['id']} {u.status_code}"))
        done += u.ok; time.sleep(0.4)
    msg = f"🧩 독창성 층 {'미리보기' if dry else '적용'} — {sum(by.values())}편 (영역별 {by}) · 해당 없음/기적용 {skip}" + (f" · 실패 {fail}" if fail else "")
    print(msg)
    t, c = os.getenv("TELEGRAM_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if t and c and not dry:
        try: requests.post(f"https://api.telegram.org/bot{t}/sendMessage", data={"chat_id": c, "text": msg}, timeout=20)
        except Exception: pass
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
