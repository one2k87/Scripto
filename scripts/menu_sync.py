"""menu_sync.py — 사이트 메뉴를 현재 니치에 맞춘다(2026-09-15).

문제(실측): 주제를 전환해도 워드프레스 상단 메뉴가 옛 카테고리를 가리켜,
메뉴를 누르면 "찾지 못함"(글 0편 아카이브)이 나왔다. 심사관이 메뉴부터 눌러보는
것을 생각하면 치명적이고, "이 사이트가 무슨 사이트인지"를 흐린다.

동작(멱등):
  1) site_categories.json의 현재 카테고리 = 정답
  2) 메뉴의 '카테고리 항목'만 검사 — 현재 카테고리가 아니면 현재 것으로 교체
     (남는 옛 카테고리 항목은 삭제. 페이지 항목(소개·문의·약관 등)은 절대 건드리지 않는다)
  3) 현재 카테고리가 메뉴에 없으면 추가
주제를 또 바꿔도 이 스크립트 한 번이면 메뉴가 따라온다.
"""
import base64
import json
import os
import sys

import requests


def main():
    cfg = json.load(open("config.json", encoding="utf-8"))
    wp = cfg.get("wordpress", {}) or {}
    if not (wp.get("site_url") and wp.get("username") and wp.get("app_password")):
        print("WP 자격 부족"); return 1
    base = wp["site_url"].rstrip("/")
    tok = base64.b64encode(f"{wp['username']}:{wp['app_password']}".encode()).decode()
    H = {"User-Agent": "Mozilla/5.0 (ScriptoBot)", "Authorization": f"Basic {tok}"}

    site = json.load(open("data/site_categories.json", encoding="utf-8"))
    want_names = [c.get("wp_category") or c.get("name") for c in (site.get("categories") or [])]
    if not want_names:
        print("카테고리 정의 없음"); return 1

    # 현재 카테고리 id 확보
    cats = requests.get(f"{base}/wp-json/wp/v2/categories", headers=H,
                        params={"per_page": 100, "_fields": "id,name,slug,count"}, timeout=30).json()
    want = [c for c in cats if c["name"] in want_names]
    if not want:
        print(f"WP에 현재 카테고리 없음(want={want_names}) — 첫 글 발행 후 다시 실행"); return 1
    want_ids = {c["id"] for c in want}

    # 메뉴 조회(인증 필요 — 관리자 앱 비밀번호)
    menus = requests.get(f"{base}/wp-json/wp/v2/menus", headers=H,
                         params={"per_page": 20, "_fields": "id,name,slug"}, timeout=30)
    if not menus.ok:
        print(f"메뉴 조회 실패 {menus.status_code} — 권한(edit_theme_options) 확인 필요"); return 1
    steps = []
    for menu in menus.json():
        items = requests.get(f"{base}/wp-json/wp/v2/menu-items", headers=H,
                             params={"menus": menu["id"], "per_page": 100,
                                     "_fields": "id,title,type,object,object_id,menu_order"},
                             timeout=30).json()
        cat_items = [i for i in items if i.get("type") == "taxonomy" and i.get("object") == "category"]
        stale = [i for i in cat_items if i.get("object_id") not in want_ids]
        present = {i.get("object_id") for i in cat_items if i.get("object_id") in want_ids}
        pool = [c for c in want if c["id"] not in present]

        for it in stale:
            old = (it.get("title") or {}).get("rendered", "")
            if pool:                      # 옛 카테고리 항목을 새 카테고리로 교체(자리·순서 유지)
                c = pool.pop(0)
                r = requests.post(f"{base}/wp-json/wp/v2/menu-items/{it['id']}", headers=H,
                                  json={"title": c["name"], "object_id": c["id"],
                                        "object": "category", "type": "taxonomy"}, timeout=30)
                steps.append(f"교체 {old}→{c['name']} {'✓' if r.ok else '✗'+str(r.status_code)}")
                present.add(c["id"])
            else:                          # 남는 옛 항목은 제거(빈 아카이브로 가는 링크 제거)
                r = requests.delete(f"{base}/wp-json/wp/v2/menu-items/{it['id']}", headers=H,
                                    params={"force": True}, timeout=30)
                steps.append(f"제거 {old} {'✓' if r.ok else '✗'+str(r.status_code)}")

        for c in pool:                     # 메뉴에 없던 현재 카테고리 추가
            r = requests.post(f"{base}/wp-json/wp/v2/menu-items", headers=H,
                              json={"title": c["name"], "object_id": c["id"], "object": "category",
                                    "type": "taxonomy", "menus": menu["id"], "status": "publish",
                                    "menu_order": 3}, timeout=30)
            steps.append(f"추가 {c['name']} {'✓' if r.ok else '✗'+str(r.status_code)}")

    msg = "🧭 메뉴 동기화 — " + (" · ".join(steps) if steps else "변경 없음(이미 현재 니치와 일치)")
    print(msg)
    tokn, chat_id = os.getenv("TELEGRAM_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if tokn and chat_id and steps:
        try:
            requests.post(f"https://api.telegram.org/bot{tokn}/sendMessage",
                          data={"chat_id": chat_id, "text": msg}, timeout=20)
        except Exception:
            pass
    return 0 if all("✗" not in s for s in steps) else 1


if __name__ == "__main__":
    sys.exit(main())
