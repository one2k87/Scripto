"""diag_rankmath.py — robots/sitemap 301이 Rank Math 리디렉션 규칙인지 확인 (2026-10-12).
X-Redirect-By: WordPress 였으므로 플러그인 wp_redirect. Rank Math REST 라우트와 리디렉션 목록을 찾아본다."""
import base64
import json

import requests

cfg = json.load(open("config.json", encoding="utf-8"))
wp = cfg.get("wordpress", {}) or {}
base = wp["site_url"].rstrip("/")
tok = base64.b64encode(f"{wp['username']}:{wp['app_password']}".encode()).decode()
H = {"User-Agent": "Mozilla/5.0 (ScriptoBot)", "Authorization": f"Basic {tok}"}

r = requests.get(base + "/wp-json/", headers=H, timeout=30)
ns = r.json().get("namespaces", []) if r.ok else []
print("namespaces:", ns)
for n in ("rankmath/v1", "rankmath/v1/redirections"):
    r = requests.get(f"{base}/wp-json/{n}", headers=H, timeout=30)
    print(f"== {n} -> {r.status_code}")
    if r.ok:
        d = r.json()
        routes = list((d.get("routes") or {}).keys()) if isinstance(d, dict) else []
        print("  routes:", [x for x in routes if "redirect" in x.lower() or "sitemap" in x.lower() or "robots" in x.lower()][:30])
        if not routes:
            print("  body:", json.dumps(d, ensure_ascii=False)[:800])
# 리디렉션 후보 엔드포인트 몇 개 시도
for path in ("/wp-json/rankmath/v1/redirections", "/wp-json/rankmath/v1/redirection/list",
             "/wp-json/rankmath/v1/getRedirections", "/wp-json/rankmath/v1/redirections/list"):
    r = requests.get(base + path, headers=H, timeout=30)
    print(path, "->", r.status_code, r.text[:300].replace("\n", " "))
# 옵션 노출 여부(관리자 REST settings에 추가 필드가 있는지)
r = requests.get(base + "/wp-json/wp/v2/settings", headers=H, timeout=30)
if r.ok:
    print("settings keys:", list(r.json().keys()))
# robots.txt 요청 때 WP가 어떤 경로로 응답하는지: ?robots=1 직접 호출 헤더
r = requests.get(base + "/?robots=1", headers=H, timeout=30, allow_redirects=False)
print("?robots=1 direct ->", r.status_code, {k: v for k, v in r.headers.items() if k.lower() in ("x-redirect-by", "link", "x-robots-tag", "content-type")})
r = requests.get(base + "/robots.txt", headers=H, timeout=30, allow_redirects=False)
print("robots.txt (auth) ->", r.status_code, r.headers.get("Location", "-"), r.headers.get("X-Redirect-By", "-"))
