"""네이버 검색(API HUB) — 블로그·웹문서 상위 글과 총 문서 수 (2026-11-17).
호출 방식은 Casto trend_sources.py와 같다(HUB 경로 /search/v1/{kind}, format=json, 헤더 X-NCP-APIGW-*).
키: NAVER_HUB_KEY_ID / NAVER_HUB_KEY (금고 → Scripto Secrets). 값은 출력하지 않는다.
"""
import os, re, html
import requests

BASE = os.getenv("NAVER_HUB_BASE", "https://naverapihub.apigw.ntruss.com")


def _headers():
    kid, key = os.getenv("NAVER_HUB_KEY_ID", "").strip(), os.getenv("NAVER_HUB_KEY", "").strip()
    if not (kid and key):
        return None
    return {"X-NCP-APIGW-API-KEY-ID": kid, "X-NCP-APIGW-API-KEY": key}


def search(query, kind="blog", display=5):
    """(status, total, items[{title, link, desc}]). kind: blog | webkr. 실패 시 total=None."""
    h = _headers()
    if not h:
        return "no-key", None, []
    try:
        r = requests.get(f"{BASE}/search/v1/{kind}", headers=h, timeout=30,
                         params={"query": query, "display": display, "format": "json"})
    except Exception as e:
        return f"err {type(e).__name__}", None, []
    if r.status_code != 200:
        return f"HTTP {r.status_code} {r.text[:120]}", None, []
    d = r.json()
    clean = lambda s: html.unescape(re.sub(r"<[^>]+>", "", s or ""))
    items = [{"title": clean(i.get("title")), "link": i.get("link"), "desc": clean(i.get("description"))[:120]}
             for i in d.get("items", [])]
    return "200", d.get("total"), items
