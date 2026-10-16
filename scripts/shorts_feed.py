"""shorts_feed.py — 원더랜드 공개 글 → "부모님 폰 30초" 쇼츠 원고 공급 (2026-10-16, F 승인·C 제작).

C(캐스토)가 OneShorts 채널로 쇼츠를 만들 때 쓸 원고를 매일 dashboard/data/shorts_feed.json 에 쌓는다.
LLM 없이 공개 글에서 결정적으로 뽑는다(비용 0, 지어내기 0): 제목·후킹·핵심 3줄(소제목)·CTA·링크.
- 공개(publish) 글만, 최근 순, 이미 피드에 있는 글은 건너뜀(멱등)
- 무결성 감사 경고(잘림 의심 등)가 있는 글은 제외 — 깨진 글을 영상으로 퍼뜨리지 않는다
- C가 소비하면 used=true 로 표시(C 쪽에서), S는 덮어쓰지 않는다
URL: https://one2k87.github.io/Scripto/dashboard/data/shorts_feed.json (GitHub Pages)
"""
import html
import json
import os
import re
from datetime import datetime

import requests

FEED = "dashboard/data/shorts_feed.json"
SKIP_H2 = ("함께 보면 좋은 글", "자주 묻는 질문", "실행 체크리스트")


def _text(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def main():
    cfg = json.load(open("config.json", encoding="utf-8"))
    base = (cfg.get("wordpress", {}) or {}).get("site_url", "https://wontheland.com").rstrip("/")
    feed = {"updated_at": "", "items": []}
    if os.path.exists(FEED):
        try:
            feed = json.load(open(FEED, encoding="utf-8"))
        except Exception:
            pass
    have = {it["post_id"] for it in feed.get("items", [])}
    warn = {}
    try:
        warn = (json.load(open("dashboard/data/integrity_audit.json", encoding="utf-8")).get("warnings") or {})
    except Exception:
        pass

    r = requests.get(f"{base}/wp-json/wp/v2/posts", timeout=30,
                     params={"per_page": 20, "_fields": "id,link,title,date,content"})
    r.raise_for_status()
    added = 0
    for p in r.json():
        pid = p["id"]
        if pid in have or str(pid) in warn:
            continue
        c = p["content"]["rendered"]
        hook = _text((re.search(r'<p class="hook"[^>]*>(.*?)</p>', c, re.S) or [None, ""])[1]) if re.search(r'<p class="hook"', c) else ""
        h2s = [_text(m) for m in re.findall(r"<h2[^>]*>(.*?)</h2>", c, re.S)]
        h2s = [h for h in h2s if h and not any(k in h for k in SKIP_H2)][:3]
        if len(h2s) < 2:
            continue
        title = _text(p["title"]["rendered"])
        feed["items"].insert(0, {
            "post_id": pid, "url": p["link"], "date": p["date"][:10],
            "title": title,
            "hook": hook or title,
            "lines": h2s,
            "cta": "자세한 순서는 프로필 링크 · 원더랜드 블로그에서 확인하세요",
            "used": False,
        })
        added += 1
    feed["items"] = feed["items"][:60]
    feed["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    os.makedirs(os.path.dirname(FEED), exist_ok=True)
    json.dump(feed, open(FEED, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"[shorts_feed] +{added}편, 총 {len(feed['items'])}편 (미사용 {sum(1 for i in feed['items'] if not i.get('used'))})")


if __name__ == "__main__":
    main()
