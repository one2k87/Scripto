"""새로 공개된 글을 검색엔진에 자동 통지한다 — '등록해두면 알아서'의 실체.
① IndexNow: 네이버·빙·얀덱스 즉시 등록(구글 불참)
② WebSub: 구글이 지원하는 RSS 푸시 알림(즉시 발견 신호)
예약 발행(WP 크론)은 파이프라인이 모르는 사이에 공개되므로,
매일 실행 때 최근 36시간 공개 글을 조회해 통지한다(재통지는 무해)."""
import json, datetime, os, sys
import requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 2026-10-30: scripts/에서 실행 시 publisher 못 찾던 버그
from publisher import submit_indexnow, websub_ping

cfg = json.load(open("config.json", encoding="utf-8"))
wp = cfg.get("wordpress", {}) or {}
site = (wp.get("site_url") or "").rstrip("/")
if not site or "your-blog" in site:
    print("[ping] site_url 없음 — 건너뜀"); raise SystemExit(0)

since = (datetime.datetime.utcnow() - datetime.timedelta(hours=36)).strftime("%Y-%m-%dT%H:%M:%S")
try:
    r = requests.get(f"{site}/wp-json/wp/v2/posts",
                     params={"per_page": 20, "status": "publish", "after": since,
                             "_fields": "link,date_gmt"}, timeout=20)
    urls = [p["link"] for p in (r.json() if r.ok else [])]
except Exception as e:
    print(f"[ping] 목록 조회 실패: {e}"); urls = []

if urls:
    key = wp.get("indexnow_key")
    if key:
        submit_indexnow(urls, key, site, key_location=wp.get("indexnow_key_location"))
    else:
        print("[ping] IndexNow 키 없음 — 네이버·빙 통지 건너뜀")
    websub_ping(f"{site}/feed/")
    print(f"[ping] 최근 36시간 공개 글 {len(urls)}개 통지 완료")
else:
    print("[ping] 최근 36시간 새 공개 글 없음")
