"""diag_robots.py — robots.txt·sitemap 301의 원인 진단 (2026-10-12).
크롬은 302/301 헤더를 못 보고(opaqueredirect), 샌드박스는 사이트에 못 닿아 Actions에서 돈다.
출력: 활성 플러그인 목록, /robots.txt·/sitemap.xml 응답 체인(상태·Location·Server), 홈 응답 헤더."""
import base64
import json
import sys

import requests

cfg = json.load(open("config.json", encoding="utf-8"))
wp = cfg.get("wordpress", {}) or {}
base = wp["site_url"].rstrip("/")
tok = base64.b64encode(f"{wp['username']}:{wp['app_password']}".encode()).decode()
H = {"User-Agent": "Mozilla/5.0 (ScriptoBot)", "Authorization": f"Basic {tok}"}
UA = {"User-Agent": "Mozilla/5.0 (compatible; Yeti/1.1; +https://naver.me/spd)"}   # 네이버 봇 UA로도 확인


def chain(path, headers=UA):
    url = base + path
    out = []
    for _ in range(5):
        r = requests.get(url, headers=headers, allow_redirects=False, timeout=30)
        out.append(f"{url} -> {r.status_code} server={r.headers.get('Server','-')} "
                   f"x-redirect-by={r.headers.get('X-Redirect-By','-')} ct={r.headers.get('Content-Type','-')} "
                   f"loc={r.headers.get('Location','-')} cache={r.headers.get('X-LiteSpeed-Cache', r.headers.get('X-Cache','-'))}")
        if r.status_code in (301, 302, 307, 308) and r.headers.get("Location"):
            url = r.headers["Location"] if r.headers["Location"].startswith("http") else base + r.headers["Location"]
            continue
        if r.status_code == 200:
            out.append("   body: " + r.text[:200].replace("\n", " | "))
        break
    return "\n".join(out)


print("== robots.txt (브라우저 UA)");  print(chain("/robots.txt", {"User-Agent": "Mozilla/5.0"}))
print("== robots.txt (Yeti UA)");      print(chain("/robots.txt"))
print("== sitemap.xml");              print(chain("/sitemap.xml"))
print("== wp-sitemap.xml");           print(chain("/wp-sitemap.xml"))
print("== 홈 헤더")
r = requests.get(base + "/", headers=UA, timeout=30, allow_redirects=False)
for k in ("Server", "X-Powered-By", "X-Redirect-By", "Link", "X-LiteSpeed-Cache", "CF-Cache-Status", "Via"):
    if r.headers.get(k):
        print(f"  {k}: {r.headers[k]}")
print("== 활성 플러그인")
r = requests.get(base + "/wp-json/wp/v2/plugins", headers=H, timeout=30)
if r.ok:
    for p in r.json():
        print(f"  [{p.get('status')}] {p.get('name')} {p.get('version')}  ({p.get('plugin')})")
else:
    print("  플러그인 조회 실패", r.status_code, r.text[:200])
print("== 설정")
r = requests.get(base + "/wp-json/wp/v2/settings", headers=H, timeout=30)
if r.ok:
    s = r.json()
    print("  permalink:", s.get("permalink_structure"), "| url:", s.get("url"), "| home:", s.get("home") if "home" in s else "-")
sys.exit(0)
