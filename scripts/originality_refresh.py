"""originality_refresh.py — 독창성 층의 원재료를 매일 갱신 (2026-10-10).

① 실측 데이터 표: 알뜰폰허브 시니어 요금제(서버 렌더 확인 — 카드 div.plan_card 텍스트 패턴 파싱)
② 공공 사이트 화면: Playwright로 캡처 → WP 미디어 업로드 → URL 기록(주 1회면 충분, 7일 지나면 재촬영)
결과는 dashboard/data/originality/*.json. 실패해도 생성을 막지 않는다(없으면 그 블록만 빠짐).
"""
import json
import os
import re
import sys
import time
from datetime import date, datetime

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import originality as O

OUT = O.DATA_DIR
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ScriptoBot/1.0"}
TODAY = date.today().isoformat()


def refresh_mvnohub():
    src = O.SOURCES["mvnohub_senior"]
    r = requests.get(src["url"], headers=UA, timeout=60)
    r.raise_for_status()
    html = r.text
    # 카드 단위로 자른다
    cards = re.findall(r'<div class="plan_card".*?(?=<div class="plan_card"|$)', html, re.S)
    rows = []
    for c in cards:
        t = re.sub(r"<[^>]+>", " ", c)
        t = re.sub(r"\s+", " ", t).strip()
        if "월" not in t or "데이터" not in t:
            continue
        name = re.search(r"\)\s*(.+?)\s+(SKT|KT|LGU\+|LG U\+)", t)
        net = re.search(r"\b(SKT|KT|LGU\+|LG U\+)\b", t)
        brand = re.search(r"(?:SKT|KT|LGU\+|LG U\+)\s+(?:망\s+)?(?:5G\s+|LTE\s+)?([가-힣A-Za-z0-9]+(?:모바일|텔레콤|유모바일|티플러스|프리텔레콤|엠모바일|플러스|모바일 )?)", t)
        promo = re.search(r"월\s*([\d,]+)\s*원", t)
        after = re.search(r"(\d+)개월\s*이후\s*([\d,]+)\s*원", t)
        data = re.search(r"데이터\s*([\d.]+\s*GB(?:\s*\+\s*[\d.]+Mbps)?|무제한|[\d.]+MB)", t)
        voice = re.search(r"통화\s*(무제한|\d+\s*분|기본제공)", t)
        sms = re.search(r"문자\s*(무제한|\d+\s*건|기본제공)", t)
        link = re.search(r'href="(/product/products/\d+\.do)"', c)
        if not (promo and data):
            continue
        p = int(promo.group(1).replace(",", ""))
        a = int(after.group(2).replace(",", "")) if after else p
        rows.append({"name": (name.group(1) if name else "")[:40], "net": (net.group(1) if net else "").replace("LG U+", "LGU+"),
                     "brand": (brand.group(1) if brand else "")[:16], "promo": p, "after": a,
                     "months": int(after.group(1)) if after else 0,
                     "data": data.group(1).replace(" ", ""), "voice": (voice.group(1) if voice else "").replace(" ", ""),
                     "sms": (sms.group(1) if sms else "").replace(" ", ""),
                     "link": ("https://www.mvnohub.kr" + link.group(1)) if link else src["url"]})
    # 시니어에게 의미 있는 순서 = '프로모 끝난 뒤 요금' 오름차순
    rows.sort(key=lambda x: (x["after"], x["promo"]))
    table = {"title": "알뜰폰허브 65세 이상 시니어 요금제 — 이후 요금 기준 저렴한 순 10개", "checked": TODAY,
             "columns": ["요금제", "망", "월 요금(프로모)", "이후 요금", "데이터", "통화", "문자"],
             "rows": [[x["name"] or x["brand"], x["net"], f"{x['promo']:,}원", (f"{x['after']:,}원 ({x['months']}개월 후)" if x["months"] else f"{x['after']:,}원"),
                       x["data"], x["voice"], x["sms"]] for x in rows[:10]],
             "n_total": len(rows), "source": src["url"]}
    os.makedirs(OUT, exist_ok=True)
    if len(rows) >= 3:
        json.dump(table, open(os.path.join(OUT, "mvnohub_senior.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"[orig] 알뜰폰허브 시니어 요금제 {len(rows)}개 파싱 → 표 10개 저장")
    else:
        print(f"[orig] ⚠️ 파싱 결과 {len(rows)}개 — 페이지 구조가 바뀌었을 수 있음. 기존 표 유지")
    return len(rows)


def refresh_shots():
    """공공 사이트 화면 캡처(7일 캐시) → WP 업로드."""
    p = os.path.join(OUT, "shots.json")
    shots = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    need = [k for k, v in O.SHOTS.items() if not shots.get(k) or (datetime.now() - datetime.fromisoformat(shots[k].get("taken", "2000-01-01"))).days >= 7]
    if not need:
        print("[orig] 화면 캡처 전부 7일 이내 — 건너뜀"); return 0
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print("[orig] playwright 없음 — 화면 캡처 건너뜀"); return 0
    cfg = json.load(open("config.json", encoding="utf-8"))
    wp = cfg.get("wordpress", {}) or {}
    from publisher import upload_media
    done = 0
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": 1280, "height": 900}, locale="ko-KR")
        for k in need:
            meta = O.SHOTS[k]
            try:
                pg.goto(meta["url"], wait_until="networkidle", timeout=45000)
                pg.wait_for_timeout(1500)
                path = f"/tmp/shot_{k}.png"
                pg.screenshot(path=path, full_page=False)
                url = upload_media(path, wp, alt=f"{meta['label']} 실제 화면") if wp.get("site_url") else None
                if url:
                    shots[k] = {"url": url, "taken": TODAY, "src": meta["url"]}; done += 1
                    print(f"[orig] 📸 {k} 캡처·업로드")
                else:
                    print(f"[orig] ⚠️ {k} 업로드 실패")
            except Exception as e:
                print(f"[orig] ⚠️ {k} 캡처 실패: {type(e).__name__}: {str(e)[:80]}")
        b.close()
    os.makedirs(OUT, exist_ok=True)
    json.dump(shots, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return done


if __name__ == "__main__":
    try:
        refresh_mvnohub()
    except Exception as e:
        print("[orig] ⚠️ 데이터 표 갱신 실패:", type(e).__name__, str(e)[:120])
    try:
        refresh_shots()
    except Exception as e:
        print("[orig] ⚠️ 화면 캡처 실패:", type(e).__name__, str(e)[:120])
