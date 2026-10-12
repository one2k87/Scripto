"""diag_indexnow.py — IndexNow 실제 제출 1회로 키·keyLocation 유효성 확인 (2026-10-12, 마크토 422 보고 검증)."""
import json
import requests

site = json.load(open("data/site_categories.json", encoding="utf-8"))
inx = site.get("indexnow") or {}
key, loc = inx.get("key"), inx.get("key_location")
print("key:", key, "| keyLocation:", loc)
r = requests.get(loc, timeout=20, allow_redirects=False)
print("keyLocation GET:", r.status_code, r.headers.get("Content-Type"), "| body==key:", r.text.strip() == key)
posts = requests.get("https://wontheland.com/wp-json/wp/v2/posts?per_page=2&_fields=link", timeout=30).json()
urls = [p["link"] for p in posts]
payload = {"host": "wontheland.com", "key": key, "keyLocation": loc, "urlList": urls}
for ep in ("https://searchadvisor.naver.com/indexnow", "https://www.bing.com/indexnow", "https://api.indexnow.org/indexnow"):
    try:
        r = requests.post(ep, json=payload, timeout=20, headers={"Content-Type": "application/json; charset=utf-8"})
        print(ep, "->", r.status_code, r.text[:160].replace("\n", " "))
    except Exception as e:
        print(ep, "EXC", e)
