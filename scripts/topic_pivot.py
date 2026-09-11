"""topic_pivot.py — 주제 전환 집행(2026-09-11, 사용자 확정: 셀프 인테리어 → 시니어 디지털).

하는 일:
  1) 공개 발행 글 전부 → 초안(비공개 보관, 삭제 아님·복구 가능)
     — 6회차 반려 원인 중 '주제 혼재'의 재발을 막는다. 새 주제 글만 공개된다.
  2) 사이트 태그라인을 새 주제로 교체(사이트 제목 '원더랜드'는 유지)
  3) 결과 텔레그램 통보
소개 페이지·메뉴는 앱의 '한 번에 고치기'가 새 니치 기준으로 재생성한다(별도).
"""
import json
import os
import sys
import time

import requests

TAGLINE = "부모님 스마트폰과 디지털 생활, 자녀의 마음으로 대신 알아봐 드립니다"


def main():
    cfg = json.load(open("config.json", encoding="utf-8"))
    wp = cfg.get("wordpress", {}) or {}
    if not (wp.get("enabled") and wp.get("site_url")):
        print("WP 설정 없음 — 종료"); return 1
    base = wp["site_url"].rstrip("/")
    # 자립형 인증(2026-09-11 실측: publisher import가 미설치 의존성을 끌고 와 8초 실패)
    import base64
    tok = base64.b64encode(f"{wp['username']}:{wp['app_password']}".encode()).decode()
    H = {"User-Agent": "Mozilla/5.0 (ScriptoBot)", "Authorization": f"Basic {tok}"}

    # 1) 공개 글 전량 → 초안
    moved, fail = [], []
    while True:
        r = requests.get(f"{base}/wp-json/wp/v2/posts", headers=H,
                         params={"per_page": 50, "status": "publish", "_fields": "id,title"},
                         timeout=30)
        batch = r.json() if r.ok else []
        if not batch:
            break
        for it in batch:
            pid = it["id"]
            t = (it.get("title") or {}).get("rendered", "")[:40]
            u = requests.post(f"{base}/wp-json/wp/v2/posts/{pid}", headers=H,
                              json={"status": "draft"}, timeout=30)
            (moved if u.ok else fail).append(f"{pid}:{t}")
            print(("  ✓ 비공개 " if u.ok else "  ✗ 실패 ") + f"#{pid} {t}")
            time.sleep(0.15)
        if len(batch) < 50:
            break

    # 2) 태그라인 교체(제목은 유지)
    tag_ok = False
    try:
        r = requests.post(f"{base}/wp-json/wp/v2/settings", headers=H,
                          json={"description": TAGLINE}, timeout=30)
        tag_ok = r.ok
        print(("  ✓" if r.ok else "  ✗") + f" 태그라인: {TAGLINE}")
    except Exception as e:
        print("  ✗ 태그라인:", e)

    msg = (f"🔄 주제 전환 집행 완료 — 셀프 인테리어 → 시니어 디지털\n"
           f"· 기존 글 비공개(초안 보관): {len(moved)}편" + (f" · 실패 {len(fail)}편" if fail else "") +
           f"\n· 태그라인 교체: {'✓' if tag_ok else '✗'}"
           f"\n· 내일 발행부터 새 주제·새 페르소나('이음')로 나갑니다. 소개 페이지는 앱 '한 번에 고치기'로 재생성하세요.")
    tok, chat_id = os.getenv("TELEGRAM_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if tok and chat_id:
        try:
            requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                          data={"chat_id": chat_id, "text": msg}, timeout=20)
        except Exception:
            pass
    print(msg)
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main())
