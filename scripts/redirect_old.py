"""redirect_old.py — 내린 옛 글 URL을 새 글로 301 (2026-10-08 신설).

왜 필요한가(실측): 9/12 주제 전환이 색인된 30편을 한꺼번에 404로 만들었고, 그 뒤 25일간
새 글 36편 중 0편이 색인됐다(홈 마지막 크롤 9/19). 구글은 아직 옛 URL을 색인에 들고
주기적으로 확인한다 — 404면 거기서 끝이지만 301이면 그 방문이 새 글로 이어진다.
죽은 색인 30개가 새 글로 가는 크롤 경로 30개로 바뀐다.

방법: 워드프레스 코어 동작을 쓴다. 글의 slug를 바꾸면 WP가 옛 slug를 `_wp_old_slug`
메타에 자동 보관하고, 그 옛 주소 요청을 글로 301한다(wp_old_slug_redirect).
그래서 대상 새 글의 slug를 잠깐 옛 slug로 바꿨다가 원래대로 되돌리면 끝이다.
REST로 보호 메타(_접두)를 직접 쓸 수 없어서 이 우회가 필요하다.

매핑: 옛 글 제목과 새 글 제목의 단어 겹침이 있으면 그쪽, 없으면(인테리어→시니어라
대부분 없음) 강한 새 글 상위 N편에 라운드로빈 — 크롤이 한 글에 몰리지 않게.
DRY=1 이면 매핑만 출력. 적용 후 옛 URL을 실제로 쳐서 301인지 검증한다.
"""
import base64
import json
import os
import re
import sys
import time
from urllib.parse import unquote

import requests

PIVOT_DAY = "2026-09-12"      # 이 날 이전 발행분 = 옛 주제(초안으로 내려가 있음)
try:                          # topic_pivot.py가 전환일을 기록해 두면 그걸 따른다(재전환 대비)
    PIVOT_DAY = json.load(open("dashboard/data/pivot_marker.json", encoding="utf-8")).get("pivot_day") or PIVOT_DAY
except Exception:
    pass
PIVOT_DAY = os.getenv("PIVOT_DAY") or PIVOT_DAY
TOP_N = 12                    # 라운드로빈 대상(강한 글)


def _auth():
    cfg = json.load(open("config.json", encoding="utf-8"))
    wp = cfg.get("wordpress", {}) or {}
    if not (wp.get("site_url") and wp.get("username") and wp.get("app_password")):
        print("WP 자격 부족"); sys.exit(1)
    base = wp["site_url"].rstrip("/")
    tok = base64.b64encode(f"{wp['username']}:{wp['app_password']}".encode()).decode()
    return base, {"User-Agent": "Mozilla/5.0 (ScriptoBot)", "Authorization": f"Basic {tok}",
                  "Content-Type": "application/json"}


def _all(base, H, status, fields):
    out, pg = [], 1
    while True:
        r = requests.get(f"{base}/wp-json/wp/v2/posts", headers=H, timeout=30,
                         params={"per_page": 100, "page": pg, "status": status,
                                 "context": "edit", "_fields": fields})
        if not r.ok:
            break
        b = r.json(); out += b
        if len(b) < 100:
            break
        pg += 1
    return out


def _words(t):
    return set(w for w in re.split(r"[^가-힣a-zA-Z0-9]+", (t or "").lower()) if len(w) >= 2)


def main():
    dry = os.getenv("DRY", "1") != "0"
    extra = [s.strip() for s in os.getenv("EXTRA_SLUGS", "").split(",") if s.strip()]
    base, H = _auth()

    # 실측(10/8): 조건 없이 잡으면 '발행된 적 없는 생성 초안' 수백 편까지 걸려 40분 넘게 돈다.
    # 구글이 색인에 들고 있을 수 있는 건 '한 번이라도 공개됐던 글'뿐 — WP는 그런 글에만
    # date_gmt를 남긴다(발행 전 초안은 null). 그걸로 거른다.
    old = [p for p in _all(base, H, "draft,trash,private", "id,slug,title,date,date_gmt,status")
           if (p.get("date") or "")[:10] < PIVOT_DAY and p.get("date_gmt")]
    print(f"공개된 적 있는 옛 글 {len(old)}편 선별")
    new = _all(base, H, "publish", "id,slug,title,date,content")
    if not new:
        print("공개 글 0편 — 중단"); return 1
    # 강한 글 순(이미지 수·분량)
    def strength(p):
        c = (p.get("content") or {}).get("raw") or ""
        return (c.count("<img") * 1000) + len(re.sub(r"<[^>]+>", "", c))
    new.sort(key=strength, reverse=True)
    top = new[:TOP_N]

    jobs = []   # (옛 slug, 옛 제목, 대상 글)
    rr = 0
    for p in old:
        slug = unquote(p.get("slug") or "")
        if not slug or slug == "post":
            continue
        ow = _words((p.get("title") or {}).get("raw") or "")
        best, score = None, 0
        for q in new:
            s = len(ow & _words((q.get("title") or {}).get("raw") or ""))
            if s > score:
                best, score = q, s
        if score < 2:                         # 겹침이 빈약하면 강한 글에 고르게
            best = top[rr % len(top)]; rr += 1
        jobs.append((slug, ((p.get("title") or {}).get("raw") or "")[:30], best))
    for slug in extra:                        # WP에 없는 유령 URL(옛날 옛적 글)도 같은 방식
        best = top[rr % len(top)]; rr += 1
        jobs.append((unquote(slug).strip("/"), "(유령)", best))

    print(f"옛 글 {len(old)}편 + 추가 {len(extra)} → 리다이렉트 {len(jobs)}건 {'(드라이런)' if dry else ''}")
    for slug, t, q in jobs:
        print(f"  /{slug[:34]}  ←{t:30}→  #{q['id']} /{q['slug']}")
    if dry:
        return 0

    ok, fail, skipped = 0, [], 0
    UA = {"User-Agent": "Mozilla/5.0 (ScriptoBot)"}
    for slug, _t, q in jobs:
        pid, orig = q["id"], q["slug"]
        try:
            # 이미 301이면 손대지 않는다 — 매일 자가치유로 돌려도 글의 수정일이 매번 바뀌지 않게
            pre = requests.get(f"{base}/{slug}/", headers=UA, timeout=20, allow_redirects=False)
            if pre.status_code in (301, 302):
                skipped += 1; continue
            r1 = requests.post(f"{base}/wp-json/wp/v2/posts/{pid}", headers=H, timeout=20, json={"slug": slug})
            r2 = requests.post(f"{base}/wp-json/wp/v2/posts/{pid}", headers=H, timeout=20, json={"slug": orig})
            if not (r1.ok and r2.ok):
                fail.append(f"{slug}: {r1.status_code}/{r2.status_code}"); continue
            # WP가 요청 slug를 정규화(sanitize_title)할 수 있어, 실제로 저장됐던 slug로 검증
            saved = r1.json().get("slug") or slug
            print(f"  · {slug[:30]} → #{pid}", flush=True)
            chk = requests.get(f"{base}/{saved}/", headers={"User-Agent": "Mozilla/5.0 (ScriptoBot)"},
                               timeout=20, allow_redirects=False)
            if chk.status_code in (301, 302) and f"/{orig}/" in (chk.headers.get("Location") or ""):
                ok += 1
            else:
                fail.append(f"{slug}: 검증 {chk.status_code} → {chk.headers.get('Location','')[:60]}")
        except Exception as e:
            fail.append(f"{slug}: {type(e).__name__}")
        time.sleep(0.3)

    if not ok and not fail:
        print(f"옛 URL 301 — 이미 전부 적용됨({skipped}건), 할 일 없음"); return 0
    msg = (f"↪️ 옛 URL 301 적용 — 성공 {ok}/{len(jobs)-skipped}" + (f" (기적용 {skipped})" if skipped else "")
           + (f"\n⚠️ 실패 {len(fail)}:\n" + "\n".join("· " + f for f in fail[:8]) if fail else "")
           + "\n※ 죽은 색인이 새 글 크롤 경로로 바뀜. 구글이 옛 URL을 다시 확인할 때 효과")
    print(msg)
    t, c = os.getenv("TELEGRAM_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if t and c:
        try:
            requests.post(f"https://api.telegram.org/bot{t}/sendMessage", data={"chat_id": c, "text": msg}, timeout=20)
        except Exception:
            pass
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main())
