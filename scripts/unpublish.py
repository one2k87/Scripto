"""unpublish.py — 발행된 글을 초안으로 되돌린다(2026-09-17 신설).

왜 필요한가: 심사 중인 사이트에 '내려야 할 글'이 올라가는 일은 반드시 또 생긴다
(9/17 실측 — 주제 프롬프트 누출로 '블로그 수익 주제' 글이 발행됨). 그때마다
워드프레스에 사람이 들어가는 대신, 글 번호만 넣고 원탭으로 내린다.

삭제가 아니라 status=draft — 원인 분석과 재작성에 원문이 필요하다.
POST_IDS="2562,2563" 형식. REASON은 기록용(대장·텔레그램에 남는다).
"""
import base64
import json
import os
import sys

import requests


def main():
    ids = [x.strip() for x in os.getenv("POST_IDS", "").replace(" ", ",").split(",") if x.strip()]
    if not ids:
        print("POST_IDS 비어 있음 — 할 일 없음"); return 0
    reason = os.getenv("REASON", "").strip() or "(사유 미기재)"

    cfg = json.load(open("config.json", encoding="utf-8"))
    wp = cfg.get("wordpress", {}) or {}
    if not (wp.get("site_url") and wp.get("username") and wp.get("app_password")):
        print("WP 자격 부족"); return 1
    base = wp["site_url"].rstrip("/")
    tok = base64.b64encode(f"{wp['username']}:{wp['app_password']}".encode()).decode()
    H = {"User-Agent": "Mozilla/5.0 (ScriptoBot)", "Authorization": f"Basic {tok}",
         "Content-Type": "application/json"}

    done, fail = [], []
    for pid in ids:
        g = requests.get(f"{base}/wp-json/wp/v2/posts/{pid}", headers=H, timeout=20,
                         params={"context": "edit", "_fields": "id,title,status,link"})
        title = ""
        if g.ok:
            title = (g.json().get("title") or {}).get("raw", "")[:50]
            if g.json().get("status") == "draft":
                print(f"  · #{pid} 이미 초안 — 건너뜀"); continue
        r = requests.post(f"{base}/wp-json/wp/v2/posts/{pid}", headers=H, timeout=20,
                          json={"status": "draft"})
        if r.ok:
            done.append(f"#{pid} {title}")
            print(f"  ✓ #{pid} 초안으로 내림 — {title}")
        else:
            fail.append(f"#{pid} {r.status_code}")
            print(f"  ✗ #{pid} {r.status_code} {r.text[:120]}")

    msg = (f"📥 글 내림 {len(done)}건 (사유: {reason})\n"
           + "\n".join("· " + d for d in done)
           + (f"\n⚠️ 실패 {len(fail)}건: {fail}" if fail else "")
           + "\n※ 삭제 아님 — WP 관리자 '초안'에서 확인·재작성 가능")
    print(msg)
    t, c = os.getenv("TELEGRAM_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if t and c:
        try:
            requests.post(f"https://api.telegram.org/bot{t}/sendMessage",
                          data={"chat_id": c, "text": msg}, timeout=20)
        except Exception:
            pass
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
