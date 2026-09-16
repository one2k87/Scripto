"""backfill_featured.py — 기발행 글의 대표이미지 소급 지정(2026-09-16).

실측 배경: upload_media가 미디어 id를 버리고 URL만 반환해 featured_media가 한 번도
설정되지 않았다(발행 글 전부 0). 대표이미지가 없으면 목록·관련글 썸네일이 비고,
검색·디스커버의 이미지 노출과 공유 카드에서 손해를 본다 — 전부 클릭률 손실.

동작(멱등): 공개 글 중 featured_media=0인 것만 골라, 본문 첫 이미지를 미디어 목록에서
역조회해 대표이미지로 지정한다. 본문 이미지가 없으면 건너뛴다(새 이미지 생성 안 함).
"""
import base64
import json
import os
import re
import sys
import time

import requests


def main():
    cfg = json.load(open("config.json", encoding="utf-8"))
    wp = cfg.get("wordpress", {}) or {}
    if not (wp.get("site_url") and wp.get("username") and wp.get("app_password")):
        print("WP 자격 부족"); return 1
    base = wp["site_url"].rstrip("/")
    tok = base64.b64encode(f"{wp['username']}:{wp['app_password']}".encode()).decode()
    H = {"User-Agent": "Mozilla/5.0 (ScriptoBot)", "Authorization": f"Basic {tok}",
         "Content-Type": "application/json"}

    # 미디어 URL → id 사전(한 번만 받아 재사용)
    media, pg = {}, 1
    while True:
        r = requests.get(f"{base}/wp-json/wp/v2/media", headers=H, timeout=30,
                         params={"per_page": 100, "page": pg, "_fields": "id,source_url"})
        if not r.ok:
            break
        b = r.json()
        for m in b:
            media[m.get("source_url", "")] = m["id"]
        if len(b) < 100:
            break
        pg += 1

    posts, pg = [], 1
    while True:
        r = requests.get(f"{base}/wp-json/wp/v2/posts", headers=H, timeout=30,
                         params={"per_page": 50, "page": pg, "status": "publish",
                                 "context": "edit", "_fields": "id,title,content,featured_media"})
        if not r.ok:
            break
        b = r.json()
        posts += b
        if len(b) < 50:
            break
        pg += 1

    todo = [p for p in posts if not p.get("featured_media")]
    done, skip, fail = 0, 0, 0
    for p in todo:
        body = (p.get("content") or {}).get("raw") or (p.get("content") or {}).get("rendered") or ""
        m = re.search(r'<img[^>]+src="([^"]+)"', body)
        url = m.group(1) if m else ""
        mid = media.get(url)
        if not mid:
            skip += 1
            print(f"  · 건너뜀 #{p['id']} — 본문 이미지의 미디어 id 없음")
            continue
        u = requests.post(f"{base}/wp-json/wp/v2/posts/{p['id']}", headers=H,
                          json={"featured_media": int(mid)}, timeout=20)
        if u.ok:
            done += 1
            print(f"  ✓ #{p['id']} ← media {mid}")
        else:
            fail += 1
            print(f"  ✗ #{p['id']} {u.status_code}")
        time.sleep(0.15)

    msg = (f"🖼 대표이미지 소급 — 대상 {len(todo)}편 / 설정 {done} · 건너뜀 {skip}"
           + (f" · 실패 {fail}" if fail else "")
           + f" (공개 글 {len(posts)}편 기준)")
    print(msg)
    tokn, chat_id = os.getenv("TELEGRAM_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if tokn and chat_id:
        try:
            requests.post(f"https://api.telegram.org/bot{tokn}/sendMessage",
                          data={"chat_id": chat_id, "text": msg}, timeout=20)
        except Exception:
            pass
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main())
