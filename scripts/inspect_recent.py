"""URL Inspection API로 '색인 요청'을 재발명한다 (2026-08-31).

왜 이 방식인가 — 색인 요청 버튼의 목적은 결국 두 가지다:
  ① 구글이 이 URL을 다시 가져가게(재크롤) 만드는 것
  ② 색인됐는지 확인하는 것
버튼에는 API가 없지만, URL Inspection API(하루 2,000회)는
  ①을 부분적으로 대체하고(검사가 구글의 페이지 fetch를 유발해 재크롤을
     앞당기는 효과가 보고돼 있다 — 보장은 아님),
  ②를 완전히 대체한다(verdict·마지막 크롤 시각·색인 상태를 그대로 준다).
게다가 insights.py가 쓰는 서비스 계정을 그대로 재사용하므로 추가 세팅이 0이다.

매일 실행: 최근 수정 글을 검사 → dashboard/data/index_status.json에 신호등 기록
(결과 커밋 단계가 저장소에 올려 대시보드가 읽는다).
덤: 사이트맵 재제출(sitemaps.submit)도 시도한다 — 쓰기 권한이 없으면 조용히 건너뜀.
"""
import json
import datetime
from urllib.parse import unquote

import requests

cfg = json.load(open("config.json", encoding="utf-8"))
ins = cfg.get("insights", {}) or {}
site = (cfg.get("wordpress", {}) or {}).get("site_url", "").rstrip("/")
sc_site = (ins.get("sc_site_url") or site).rstrip("/") + "/"

raw = ins.get("service_account_json") or ""
if not raw or not site or "your-blog" in site:
    print("[inspect] 서비스 계정 또는 site_url 없음 — 건너뜀")
    raise SystemExit(0)

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    info = json.loads(raw) if raw.strip().startswith("{") else json.load(open(raw, encoding="utf-8"))
    # inspect는 readonly로 충분, sitemaps.submit은 쓰기 스코프 필요 → 둘 다 요청
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/webmasters"])
    svc = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
except Exception as e:
    print(f"[inspect] 인증 실패: {e}")
    raise SystemExit(0)

# 최근 14일 내 수정된 공개 글 (검사 우선순위 = 최근 손본 순, 최대 30개/일)
diag = {}
try:
    r = requests.get(f"{site}/wp-json/wp/v2/posts",
                     params={"per_page": 30, "orderby": "modified", "_fields": "link,modified"},
                     headers={"User-Agent": "Mozilla/5.0 (ScriptoBot)"}, timeout=20)
    diag = {"http": r.status_code, "body_head": r.text[:120]}
    posts = r.json() if r.ok else []
except Exception as e:
    print(f"[inspect] 글 목록 실패: {e}")
    diag = {"err": str(e)[:150]}
    posts = []

cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%S")
# ⚠️ WP API는 한글 슬러그를 %인코딩해 주는데, Inspection API에 그대로 보내면
# 색인된 글도 'URL is unknown to Google'로 나온다(2026-09-01 실측 — SC UI·site: 검색
# 교차 확인으로 12편+ 색인 확인, API만 0/29 오답). 디코딩해 보내야 정답이 나온다.
urls = [site + "/"] + [unquote(p["link"]) for p in posts if p.get("modified", "") >= cutoff]

results, ok_n = [], 0
for u in urls[:30]:
    try:
        res = svc.urlInspection().index().inspect(
            body={"inspectionUrl": u, "siteUrl": sc_site}).execute()
        idx = (res.get("inspectionResult", {}) or {}).get("indexStatusResult", {}) or {}
        verdict = idx.get("verdict", "?")            # PASS = 색인됨
        results.append({"url": u, "verdict": verdict,
                        "state": idx.get("coverageState", ""),
                        "lastCrawl": (idx.get("lastCrawlTime") or "")[:10]})
        ok_n += 1
    except Exception as e:
        results.append({"url": u, "verdict": "ERROR", "state": str(e)[:100], "lastCrawl": ""})

passed = sum(1 for x in results if x["verdict"] == "PASS")

# 고스트 감지(2026-09-01 신설): 사이트에서 삭제한 글이 구글 검색에 잔재로 남는 문제.
# wontheland 실측 — 404+noindex 처리한 니치 밖 옛 글 6편이 site: 검색에 그대로 노출돼
# 심사관에게 니치 오염으로 보일 뻔했다. data/removed_urls.json의 URL을 매일 검사해
# 아직 색인에 남아 있으면(ghosts) 기록한다 → 대시보드/텔레그램이 'SC 삭제 도구' 카드를 띄운다.
ghosts = []
try:
    removed = (json.load(open("data/removed_urls.json", encoding="utf-8")) or {}).get("urls", [])
except Exception:
    removed = []
for u in removed[:20]:
    try:
        res = svc.urlInspection().index().inspect(
            body={"inspectionUrl": unquote(u), "siteUrl": sc_site}).execute()
        idx = (res.get("inspectionResult", {}) or {}).get("indexStatusResult", {}) or {}
        if idx.get("verdict") == "PASS":
            ghosts.append(unquote(u))
    except Exception:
        pass
if ghosts:
    print(f"[inspect] ⚠️ 삭제 글 검색 잔재(고스트) {len(ghosts)}건 — SC 삭제 도구로 제거 필요")

out = {"updated_at": datetime.datetime.now().isoformat()[:19],
       "site": site, "checked": ok_n, "indexed": passed, "ghosts": ghosts,
       "posts_diag": diag, "posts_n": len(posts), "results": results}
json.dump(out, open("dashboard/data/index_status.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print(f"[inspect] {ok_n}개 검사 — 색인됨 {passed} / 미색인 {ok_n - passed}")

# ── 색인 정체 경보(2026-10-08 신설) ─────────────────────────────────────────
# 실측: 9/18~10/7 20일 연속 "색인 1(홈뿐)"이 매일 이 파일에 기록됐는데 아무도 못 봤다.
# 그 사이 유입 0의 원인이 색인이라는 걸 25일 뒤에야 알았다. 숫자가 있으면 소리를 내야 한다.
try:
    import os as _os
    import requests as _rq
    hist_p = "dashboard/data/index_history.json"
    hist = json.load(open(hist_p, encoding="utf-8")) if _os.path.exists(hist_p) else []
    today = out["updated_at"][:10]
    hist = [h for h in hist if h.get("d") != today] + [{"d": today, "posts": len(posts), "indexed": passed, "checked": ok_n}]
    hist = hist[-60:]
    json.dump(hist, open(hist_p, "w", encoding="utf-8"), ensure_ascii=False)
    out["history"] = hist[-14:]
    # 글은 있는데 글 색인(홈 제외)이 7일 연속 0이면 경보
    post_idx = sum(1 for r in results if r.get("verdict") == "PASS" and r.get("url", "").rstrip("/") != site.rstrip("/"))
    out["post_indexed"] = post_idx
    stale = [h for h in hist[-7:] if h.get("posts", 0) >= 5 and (h.get("indexed", 0) <= 1)]
    if len(hist) >= 7 and len(stale) >= 7:
        msg = (f"🚨 색인 정체 7일+ — 발행 {len(posts)}편 중 글 색인 {post_idx}편 (홈 제외)\n"
               "구글이 새 글을 가져가지 않고 있습니다. 랭킹 문제가 아니라 크롤 문제입니다.\n"
               "→ GSC에서 '색인 생성 요청'(하루 ~10개) · 앱 글 탭 브리핑 참고")
        print(msg)
        tok, chat = _os.getenv("TELEGRAM_TOKEN", ""), _os.getenv("TELEGRAM_CHAT_ID", "")
        if tok and chat:
            _rq.post(f"https://api.telegram.org/bot{tok}/sendMessage", data={"chat_id": chat, "text": msg}, timeout=20)
    json.dump(out, open("dashboard/data/index_status.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
except Exception as _e:
    print("[inspect] 경보 단계 건너뜀:", _e)

# 사이트맵+RSS 피드 제출(크롤 넛지) — 권한 없으면 건너뜀.
# RSS를 사이트맵으로 제출하면 구글 발견이 빨라진다(WebSub와 짝).
# 종전엔 'SC에서 피드 수동 제출(1회)'이 이용자 할 일이었는데 API로 지워버렸다(2026-08-31).
submitted = []
for feed in (f"{site}/wp-sitemap.xml", f"{site}/feed/"):
    try:
        svc.sitemaps().submit(siteUrl=sc_site, feedpath=feed).execute()
        submitted.append(feed.rsplit("/", 2)[-2] or "sitemap")
    except Exception as e:
        print(f"[inspect] 제출 건너뜀 {feed} ({str(e)[:60]})")
if submitted:
    print(f"[inspect] SC 제출 완료: {submitted}")
    out["sitemaps_submitted"] = submitted

# 죽은 레거시 사이트맵 정리(2026-09-01 신설): 옛 SEO 플러그인이 제출해 둔 사이트맵이
# 404가 된 채 SC에 '가져올 수 없음'으로 남아 신호를 오염시킨다(wontheland 실측:
# /post-sitemap.xml). 사이트에서 404인 제출 항목만 골라 SC에서 제거한다.
try:
    ours = {f"{site}/wp-sitemap.xml", f"{site}/feed/", f"{site}/feed"}
    listed = (svc.sitemaps().list(siteUrl=sc_site).execute() or {}).get("sitemap", [])
    cleaned = []
    for sm in listed:
        path = (sm.get("path") or "").rstrip()
        if not path or path.rstrip("/") in {p.rstrip("/") for p in ours}:
            continue
        try:
            code = requests.head(path, timeout=15, allow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0 (ScriptoBot)"}).status_code
        except Exception:
            continue                      # 네트워크 오류는 판단 보류(삭제하지 않음)
        if code == 404:
            try:
                svc.sitemaps().delete(siteUrl=sc_site, feedpath=path).execute()
                cleaned.append(path)
            except Exception as e:
                print(f"[inspect] 사이트맵 정리 실패 {path} ({str(e)[:60]})")
    if cleaned:
        print(f"[inspect] 죽은 사이트맵 정리: {cleaned}")
        out["sitemaps_cleaned"] = cleaned
except Exception as e:
    print(f"[inspect] 사이트맵 목록 확인 건너뜀: {str(e)[:80]}")

json.dump(out, open("dashboard/data/index_status.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
