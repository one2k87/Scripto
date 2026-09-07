"""fresh_start.py — 죽은 글 정리 + 통계 새 출발 (2026-09-07 사용자 확정)

원칙: "예전 발행 글들은 다 우리가 죽인 글" — 주제는 이미 topic_queue로 추출됐으므로(#49)
옛 초안 본문은 정리하고, 통계는 '지금 살아 있는 발행 글'만으로 다시 센다.

동작(전부 복구 가능한 수준만):
1) 초안(draft) 전량 → 휴지통 이동. force 미지정 = 영구 삭제 아님, WP에서 30일간 복구 가능.
   발행 글·예약 글·페이지는 절대 건드리지 않는다.
2) history.json 재구성: 현재 '공개 발행 중'인 글과 일치하는 항목만 남긴다(필드 보존 —
   kind/keyword/series 등은 내부링크·시리즈·트렌드 통계에 계속 쓰인다). 지워진 옛 기록은
   history_archive.json으로 보존(통계에서만 제외, 데이터는 잃지 않음).
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests

from publisher import _auth_header

HISTORY = "dashboard/data/history.json"
ARCHIVE = "dashboard/data/history_archive.json"


def wp_pages(base, H, **params):
    pg = 0
    while True:
        pg += 1
        r = requests.get(f"{base}/wp-json/wp/v2/posts", headers=H,
                         params={"per_page": 100, "page": pg, **params}, timeout=60)
        if not r.ok:
            break
        b = r.json()
        yield from b
        if len(b) < 100:
            break


def main():
    cfg = json.load(open("config.json", encoding="utf-8"))
    wp = cfg.get("wordpress", {}) or {}
    if not (wp.get("enabled") and wp.get("site_url")):
        print("WP 설정 없음 — 종료"); return
    base = wp["site_url"].rstrip("/")
    H = _auth_header(wp["username"], wp["app_password"])

    # 1) 초안 전량 휴지통(복구 가능). 목록을 먼저 다 모으고 지운다(페이지 시프트 방지).
    drafts = [it["id"] for it in wp_pages(base, H, status="draft",
                                          context="edit", _fields="id")]
    print(f"[정리] 초안 {len(drafts)}편 → 휴지통 이동 시작")
    trashed = failed = 0
    for i, pid in enumerate(drafts):
        try:
            d = requests.delete(f"{base}/wp-json/wp/v2/posts/{pid}", headers=H, timeout=30)
            trashed += 1 if d.status_code in (200, 201) else 0
            failed += 0 if d.status_code in (200, 201) else 1
        except Exception:
            failed += 1
        if i % 50 == 49:
            print(f"  … {i+1}/{len(drafts)}")
        time.sleep(0.15)   # 서버 보호
    print(f"[정리] 휴지통 {trashed} · 실패 {failed}")

    # 2) 통계 재구성: 살아 있는 발행 글 기준
    live = {}
    for it in wp_pages(base, H, status="publish", _fields="id,slug"):
        live[str(it["id"])] = it["slug"]
    live_slugs = set(live.values())

    try:
        hist = json.load(open(HISTORY, encoding="utf-8"))
    except Exception:
        hist = {"articles": []}
    arts = hist.get("articles", [])
    keep, drop = [], []
    seen = set()
    for a in arts:
        key = str(a.get("post_id") or "") or a.get("slug") or a.get("title")
        alive = (str(a.get("post_id")) in live) or (a.get("slug") in live_slugs)
        if alive and key not in seen:
            seen.add(key); keep.append(a)
        else:
            drop.append(a)
    # 보존: 옛 기록은 아카이브로(데이터 유실 없음)
    try:
        old = json.load(open(ARCHIVE, encoding="utf-8"))
    except Exception:
        old = {"articles": []}
    old["articles"] += drop
    import datetime
    old["archived_at"] = datetime.datetime.now().isoformat()[:19]
    json.dump(old, open(ARCHIVE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    hist["articles"] = keep
    hist["rebased_at"] = old["archived_at"]
    json.dump(hist, open(HISTORY, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[통계] history 재구성: 유지 {len(keep)} · 아카이브 {len(drop)} (발행 글 {len(live)}편 기준)")

    tok, chat = os.getenv("TELEGRAM_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if tok and chat:
        try:
            requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                          data={"chat_id": chat,
                                "text": (f"🧽 스크립토 새 출발 정리 완료\n"
                                         f"· 옛 초안 {trashed}편 휴지통(복구 가능){' · 실패 '+str(failed) if failed else ''}\n"
                                         f"· 통계 재구성: 살아 있는 발행 글 {len(live)}편 기준 "
                                         f"(옛 기록 {len(drop)}건은 아카이브 보존)")},
                          timeout=20)
        except Exception:
            pass


if __name__ == "__main__":
    main()
