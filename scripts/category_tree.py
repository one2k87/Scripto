"""category_tree.py — 사이트 카테고리를 '상위 1 + 하위 N'(토픽 클러스터)으로 맞춘다.

2026-09-16 사용자 요청: "상위 카테고리로 다양한 주제를 포괄할 수 있게".
site_categories.json의 wp_category=상위, subtopics=하위가 정답이고 이 스크립트가 WP를 거기에 맞춘다(멱등).

설계 이유: 니치 정체성("무슨 블로그인지 한 문장")은 상위 하나로 지키고, 다루는 폭은 하위로 넓힌다.
6회차 반려의 '저경쟁 사냥 목록으로 보임' 문제를 되풀이하지 않으면서 주제 고갈도 피하는 구조.

동작:
  1) 상위 카테고리 보장(없으면 생성)
  2) 기존 카테고리 중 하위 슬러그와 일치하는 것은 '이름 갱신 + 상위 연결'(URL 유지 → 404 방지)
  3) 없는 하위는 생성(상위 아래)
  4) 니치 밖 옛 카테고리는 건드리지 않는다(글이 남아 있을 수 있음 — 판단은 사람 몫)
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
    cat = (site.get("categories") or [{}])[0]
    parent_name = cat.get("wp_category") or cat.get("name")
    parent_slug = cat.get("wp_slug") or ""
    subs = cat.get("subtopics") or []
    if not parent_name:
        print("상위 카테고리 정의 없음"); return 1

    cur = requests.get(f"{base}/wp-json/wp/v2/categories", headers=H,
                       params={"per_page": 100, "_fields": "id,name,slug,parent,count"}, timeout=30).json()
    by_slug = {c["slug"]: c for c in cur}
    by_name = {c["name"]: c for c in cur}
    steps = []

    # 1) 상위 보장
    p = by_slug.get(parent_slug) or by_name.get(parent_name)
    if p:
        pid = p["id"]
        if p["name"] != parent_name or p["slug"] != parent_slug:
            r = requests.post(f"{base}/wp-json/wp/v2/categories/{pid}", headers=H,
                              json={"name": parent_name, "slug": parent_slug, "parent": 0}, timeout=30)
            steps.append(f"상위 정비 {p['name']}→{parent_name} {'✓' if r.ok else '✗'+str(r.status_code)}")
    else:
        r = requests.post(f"{base}/wp-json/wp/v2/categories", headers=H,
                          json={"name": parent_name, "slug": parent_slug}, timeout=30)
        if not r.ok:
            print(f"상위 생성 실패 {r.status_code} {r.text[:120]}"); return 1
        pid = r.json()["id"]
        steps.append(f"상위 생성 {parent_name} ✓")

    # 2~3) 하위 정비
    for s in subs:
        name, slug = s["name"], s.get("slug", "")
        ex = by_slug.get(slug) or by_name.get(name)
        if ex:
            need = (ex["name"] != name) or (ex.get("parent") != pid)
            if need:
                r = requests.post(f"{base}/wp-json/wp/v2/categories/{ex['id']}", headers=H,
                                  json={"name": name, "parent": pid}, timeout=30)
                steps.append(f"하위 연결 {ex['name']}→{name} {'✓' if r.ok else '✗'+str(r.status_code)}")
        else:
            r = requests.post(f"{base}/wp-json/wp/v2/categories", headers=H,
                              json={"name": name, "slug": slug, "parent": pid}, timeout=30)
            steps.append(f"하위 생성 {name} {'✓' if r.ok else '✗'+str(r.status_code)}")

    msg = "🗂 카테고리 트리 — " + (" · ".join(steps) if steps else "변경 없음(이미 상위/하위 구조 일치)")
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
