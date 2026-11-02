"""retitle.py — 발행 글 제목만 교체(2026-10-01 신설).

왜 필요한가: 부검의 '기계 제목'(조사 없는 명사 연쇄) 같은 지표는 제목 한 줄만
고치면 해소되는데, 그때마다 워드프레스에 사람이 들어가야 했다. 신청 직전
게이트를 맞추는 일이라 손이 빨라야 한다.

본문·슬러그·발행일은 건드리지 않는다(슬러그를 바꾸면 색인이 끊긴다).
RETITLE='2602=새 제목' 형식, 여러 건은 '||'로 구분. '2602=slug:new-slug'면 슬러그 교체(옛 주소는 WP가 301).
"""
import base64
import json
import os
import sys

import requests


def _tag_ids(base, H, names):
    """태그 이름 → ID(없으면 생성). publisher.ensure_tags와 같은 규칙."""
    ids = []
    for name in names:
        try:
            r = requests.get(f"{base}/wp-json/wp/v2/tags", params={"search": name}, headers=H, timeout=20)
            f = next((t for t in r.json() if t.get("name", "").lower() == name.lower()), None)
            if f:
                ids.append(f["id"]); continue
            c = requests.post(f"{base}/wp-json/wp/v2/tags", json={"name": name}, headers=H, timeout=20)
            if c.status_code in (200, 201):
                ids.append(c.json()["id"])
        except Exception as e:
            print(f"  태그 실패({name}): {e}")
    return ids


def main():
    raw = os.getenv("RETITLE", "").strip()
    if not raw and os.path.exists("data/retitle_queue.txt"):
        # 2026-11-02 famto: 대량 교체는 파일로(입력칸 길이·오타 위험 회피). '#' 줄은 주석.
        raw = "||".join(l.strip() for l in open("data/retitle_queue.txt", encoding="utf-8")
                        if l.strip() and not l.startswith("#"))
    if not raw:
        print("RETITLE 비어 있음"); return 1
    jobs = []
    for chunk in raw.split("||"):
        if "=" in chunk:
            pid, t = chunk.split("=", 1)
            if pid.strip().isdigit() and t.strip():
                jobs.append((pid.strip(), t.strip()))
    if not jobs:
        print("형식 오류 — 'ID=새 제목' 이어야 함"); return 1

    cfg = json.load(open("config.json", encoding="utf-8"))
    wp = cfg.get("wordpress", {}) or {}
    if not (wp.get("site_url") and wp.get("username") and wp.get("app_password")):
        print("WP 자격 부족"); return 1
    base = wp["site_url"].rstrip("/")
    tok = base64.b64encode(f"{wp['username']}:{wp['app_password']}".encode()).decode()
    H = {"User-Agent": "Mozilla/5.0 (ScriptoBot)", "Authorization": f"Basic {tok}",
         "Content-Type": "application/json"}

    done, fail = [], []
    for pid, new_t in jobs:
        tags = []
        if "##" in new_t:   # 2026-11-02 famto: 'ID=제목##검색어1,검색어2' → 검색어는 태그+포커스 키워드로
            new_t, tg = new_t.split("##", 1)
            new_t, tags = new_t.strip(), [x.strip() for x in tg.split(",") if x.strip()]
        g = requests.get(f"{base}/wp-json/wp/v2/posts/{pid}", headers=H, timeout=20,
                         params={"context": "edit", "_fields": "id,title,slug,tags"})
        old = (g.json().get("title") or {}).get("raw", "") if g.ok else "?"
        if new_t.startswith("slug:"):   # 2026-10-08: 슬러그 교체 — WP가 옛 slug를 보관해 옛 주소는 301된다
            payload = {"slug": new_t[5:].strip()}
        else:
            payload = {"title": new_t}    # 제목만: slug는 그대로(색인 보호)
            if tags:
                cur = (g.json().get("tags") or []) if g.ok else []
                payload["tags"] = sorted(set(cur) | set(_tag_ids(base, H, tags)))
                payload["meta"] = {"rank_math_focus_keyword": ",".join(tags)}
        r = requests.post(f"{base}/wp-json/wp/v2/posts/{pid}", headers=H, timeout=20, json=payload)
        if r.ok:
            done.append(f"#{pid}\n   전: {old}\n   후: {new_t}" + (f"\n   태그: {', '.join(tags)}" if tags else ""))
            print(f"  ✓ #{pid}\n     전: {old}\n     후: {new_t}")
        else:
            fail.append(f"#{pid} {r.status_code}")
            print(f"  ✗ #{pid} {r.status_code} {r.text[:120]}")

    msg = "✏️ 제목 교체 " + str(len(done)) + "건\n" + "\n".join(done) + \
          (f"\n⚠️ 실패: {fail}" if fail else "") + "\n※ 슬러그·본문·발행일 불변"
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
