"""cleanup_defaults.py — 워드프레스 설치 시 딸려오는 기본 콘텐츠를 휴지통으로 이동.

대상: 'Hello world!' 기본 글(slug: hello-world), 'Sample Page' 기본 페이지(slug: sample-page),
      기본 댓글(있다면 그대로 둠 — 글이 휴지통 가면 함께 사라짐).
안전: 영구 삭제(force)가 아니라 휴지통 이동 — WP 관리자에서 언제든 복구 가능.
이유: 구글에 site: 검색 시 기본 글이 색인돼 있어 사이트 품질 신호를 깎는다(2026-09-05 실측).

환경: GitHub Actions에서 build_config.py로 config.json 생성 후 실행.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests

from publisher import _auth_header

TARGET_SLUGS = {"posts": ["hello-world"], "pages": ["sample-page"]}


def main():
    cfg = json.load(open("config.json", encoding="utf-8"))
    wp = cfg.get("wordpress", {})
    if not (wp.get("enabled") and wp.get("site_url")):
        print("WP 설정 없음 — 종료"); return
    base = wp["site_url"].rstrip("/")
    headers = _auth_header(wp["username"], wp["app_password"])

    moved = []
    for kind, slugs in TARGET_SLUGS.items():
        for slug in slugs:
            r = requests.get(f"{base}/wp-json/wp/v2/{kind}",
                             headers=headers, params={"slug": slug, "status": "publish"},
                             timeout=30)
            items = r.json() if r.status_code == 200 else []
            for it in items:
                pid = it["id"]
                # force 미지정 = 휴지통 이동(복구 가능). 영구 삭제 아님.
                d = requests.delete(f"{base}/wp-json/wp/v2/{kind}/{pid}",
                                    headers=headers, timeout=30)
                if d.status_code in (200, 201):
                    moved.append(f"{kind}/{slug}(id={pid})")
                    print(f"✓ 휴지통 이동: {kind}/{slug} (id={pid})")
                else:
                    print(f"✗ 실패 {d.status_code}: {kind}/{slug} — {d.text[:100]}")

    summary = ("기본 콘텐츠 정리: " + ", ".join(moved)) if moved else "정리할 기본 콘텐츠 없음(이미 깨끗)"
    print(summary)
    tok, chat = os.getenv("TELEGRAM_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if tok and chat:
        try:
            requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                          data={"chat_id": chat, "text": f"🧹 {wp['site_url']} {summary}"}, timeout=20)
        except Exception:
            pass


if __name__ == "__main__":
    main()
