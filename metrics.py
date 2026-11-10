"""
metrics.py - 키워드의 '실제 검색량 수치'와 '경쟁도', '꾸준함(상록성)'을 측정.

지원 제공자(config.metrics.provider):
  - "naver"      : 네이버 검색광고 키워드도구 API. 한국 키워드 월간 검색수(정확·무료). 표준 라이브러리만 사용.
  - "google_ads" : Google Ads 키워드플래너 API. 구글 월평균 검색수(정확). google-ads 라이브러리 필요.
  - "trends"     : Google Trends(pytrends). 절대량 아님(0~100 상대지수)이나 무료·무설정. 꾸준함 측정용.
  - "none"       : 측정 안 함(이전처럼 트렌드/LLM 판단만).

꾸준함(steadiness): Google Trends 최근 12개월 관심도의 변동계수(CV)로 계산.
  1에 가까울수록 계절/유행 없이 '매달 일정하게' 검색됨 → 낮은 경쟁력(상록성) 판별 핵심 지표.
"""

import time
import json
import hmac
import base64
import hashlib
import statistics
import urllib.parse
import urllib.request


# ---------------------------------------------------------------------------
# 공통 유틸
# ---------------------------------------------------------------------------
def _to_int(v):
    if v is None:
        return 0
    s = str(v).replace(",", "").replace("<", "").replace(">", "").strip()
    try:
        return int(float(s))
    except Exception:
        return 0


def _norm(kw):
    return kw.replace(" ", "").upper()


# ---------------------------------------------------------------------------
# 1) 네이버 검색광고 키워드도구 (한국 월간 검색수, 무료)
# ---------------------------------------------------------------------------
def _naver_sig(ts, method, path, secret):
    msg = f"{ts}.{method}.{path}"
    dig = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).digest()
    return base64.b64encode(dig).decode()


def naver_volumes(hints, ncfg):
    """
    hints: 키워드 리스트(최대 5개 권장). 반환: {정규화키워드: {volume, pc, mobile, comp}}
    ncfg: {api_key, secret_key, customer_id}
    """
    base = "https://api.searchad.naver.com"
    path = "/keywordstool"
    ts = str(int(time.time() * 1000))
    sig = _naver_sig(ts, "GET", path, ncfg["secret_key"])
    hint_param = ",".join(h.replace(" ", "") for h in hints if h)
    q = urllib.parse.urlencode({"hintKeywords": hint_param, "showDetail": "1"})
    req = urllib.request.Request(f"{base}{path}?{q}")
    req.add_header("X-Timestamp", ts)
    req.add_header("X-API-KEY", ncfg["api_key"])
    req.add_header("X-Customer", str(ncfg["customer_id"]))
    req.add_header("X-Signature", sig)

    out = {}
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
        for it in data.get("keywordList", []):
            kw = it.get("relKeyword", "")
            pc = _to_int(it.get("monthlyPcQcCnt"))
            mo = _to_int(it.get("monthlyMobileQcCnt"))
            out[_norm(kw)] = {
                "volume": pc + mo, "pc": pc, "mobile": mo,
                "comp": it.get("compIdx", ""), "source": "naver",
            }
        try:
            import monitor
            monitor.mark("naver")            # 헬스체크: 네이버 성공
        except Exception:
            pass
    except Exception as e:
        print(f"[metrics] 네이버 API 실패: {e}")
        return None                          # 측정 불가(키·네트워크) — '수요 없음'과 구분
    return out


def _apply_naver(items, ncfg):
    """items(키워드 dict 리스트)에 네이버 실측 volume/comp를 채운다. 5개씩 배치."""
    # 문장형 주제는 keywordstool 응답과 맞을 일이 없어 짧은 검색어(query)로 잰다(2026-11-11).
    for i in range(0, len(items), 5):
        batch = [(it.get("query") or it["keyword"]) for it in items[i:i + 5]]
        vol = naver_volumes(batch, ncfg)
        if vol is None:
            continue
        for it in items[i:i + 5]:
            it["measured"] = True            # 응답은 왔음 → 빠진 키워드는 '등록조차 안 된 희귀어'
            m = vol.get(_norm(it.get("query") or it["keyword"]))
            if m:
                it["volume"] = m["volume"]
                it["competition"] = m["comp"]
                it["metric_source"] = "naver"
        time.sleep(0.15)  # rate limit 여유(축소)


# ---------------------------------------------------------------------------
# 2) Google Ads 키워드플래너 (구글 월평균 검색수) - 선택
# ---------------------------------------------------------------------------
def google_ads_volumes(keywords, gcfg):
    """
    gcfg: {developer_token, client_id, client_secret, refresh_token, login_customer_id, language_id, geo_target_id}
    반환: {정규화키워드: {volume, comp}}
    google-ads 라이브러리 필요: pip install google-ads
    """
    out = {}
    try:
        from google.ads.googleads.client import GoogleAdsClient
        client = GoogleAdsClient.load_from_dict({
            "developer_token": gcfg["developer_token"],
            "client_id": gcfg["client_id"],
            "client_secret": gcfg["client_secret"],
            "refresh_token": gcfg["refresh_token"],
            "login_customer_id": str(gcfg["login_customer_id"]),
            "use_proto_plus": True,
        })
        svc = client.get_service("KeywordPlanIdeaService")
        req = client.get_type("GenerateKeywordHistoricalMetricsRequest")
        req.customer_id = str(gcfg["login_customer_id"])
        req.keywords.extend(keywords)
        req.language = f"languageConstants/{gcfg.get('language_id','1012')}"   # 1012=한국어
        req.geo_target_constants.append(
            f"geoTargetConstants/{gcfg.get('geo_target_id','2410')}")          # 2410=대한민국
        resp = svc.generate_keyword_historical_metrics(request=req)
        for r in resp.results:
            m = r.keyword_metrics
            out[_norm(r.text)] = {
                "volume": int(m.avg_monthly_searches or 0),
                "comp": m.competition.name if m.competition else "",
                "source": "google_ads",
            }
    except Exception as e:
        print(f"[metrics] Google Ads API 실패: {e}")
    return out


def _apply_google_ads(items, gcfg):
    kws = [it["keyword"] for it in items]
    for i in range(0, len(kws), 10):
        vol = google_ads_volumes(kws[i:i + 10], gcfg)
        for it in items[i:i + 10]:
            m = vol.get(_norm(it["keyword"]))
            if m:
                it["volume"] = m["volume"]
                it["competition"] = m["comp"]
                it["metric_source"] = "google_ads"


# ---------------------------------------------------------------------------
# 3) Google Trends (pytrends) - 상대지수 + 꾸준함(상록성)
# ---------------------------------------------------------------------------
def trends_interest_and_steadiness(keyword, geo="KR"):
    """반환: (avg_interest 0~100 또는 None, steadiness 0~1 또는 None)"""
    try:
        from pytrends.request import TrendReq
        py = TrendReq(hl="ko-KR", tz=540)
        py.build_payload([keyword], timeframe="today 12-m", geo=geo)
        df = py.interest_over_time()
        if df is None or df.empty or keyword not in df:
            return None, None
        series = [v for v in df[keyword].tolist() if isinstance(v, (int, float))]
        if not series:
            return None, None
        mean = statistics.mean(series)
        if mean == 0:
            return 0.0, 0.0
        cv = statistics.pstdev(series) / mean          # 변동계수(작을수록 꾸준)
        steadiness = max(0.0, min(1.0, 1 - cv))        # 1=매우 꾸준(상록성)
        return round(mean, 1), round(steadiness, 2)
    except Exception as e:
        print(f"[metrics] Trends 실패('{keyword}'): {e}")
        return None, None


def _apply_trends(items, geo, want_steadiness):
    for it in items:
        interest, steady = trends_interest_and_steadiness(it["keyword"], geo)
        if it.get("volume") is None and interest is not None:
            it["volume"] = None            # 절대량 아님을 표시
            it["interest"] = interest       # 0~100 상대지수
            it["metric_source"] = it.get("metric_source") or "trends"
        if want_steadiness and steady is not None:
            it["steadiness"] = steady
        time.sleep(0.5)


# ---------------------------------------------------------------------------
# 공개 진입점: 후보 키워드에 수치를 채운다
# ---------------------------------------------------------------------------
def enrich(items, mcfg, geo="KR", want_steadiness=False):
    """
    items: [{"keyword":..., ...}, ...] 를 in-place로 보강.
      추가 필드: volume(월검색수·정수 또는 None), competition, steadiness(0~1), interest(0~100), metric_source
    mcfg: 해당 트랙(언어)의 metrics 설정 dict. geo: 트렌드/꾸준함 측정 지역(KR, US 등).
    """
    mcfg = mcfg or {}
    for it in items:
        it.setdefault("volume", None)
        it.setdefault("competition", "")
        it.setdefault("steadiness", None)
        it.setdefault("interest", None)
        it.setdefault("metric_source", "")

    provider = mcfg.get("provider", "none")

    if provider == "naver" and mcfg.get("naver"):
        _apply_naver(items, mcfg["naver"])
    elif provider == "google_ads" and mcfg.get("google_ads"):
        _apply_google_ads(items, mcfg["google_ads"])

    # 꾸준함(상록성)은 트렌드로 별도 측정 (낮은 경쟁력 판별용).
    use_trends = mcfg.get("use_trends_steadiness", True)
    if provider == "trends":
        _apply_trends(items, geo, want_steadiness)
    elif want_steadiness and use_trends:
        _apply_trends(items, geo, True)

    return items
