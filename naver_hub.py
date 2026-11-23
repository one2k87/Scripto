# -*- coding: utf-8 -*-
"""NAVER API HUB 공용 모듈 (2026-11-23 신설) — 픽담·원더랜드 어디에나 **이 파일 하나만** 복사해 쓴다.

왜 만들었나
  네이버 오픈API가 2026-06-25 네이버 클라우드의 NAVER API HUB 로 옮겨 갔다
  (기존 openapi.naver.com 방식은 2027-06-30 지원 종료). HUB 가 주는 것은 셋이다.
    ① 검색 API(블로그·웹문서·뉴스…)   월 775,000건
    ② 데이터랩 검색어 트렌드            월 50,000건
    ③ 데이터랩 쇼핑인사이트             월 50,000건      — 한시적 무료(유료 전환 시 사전 공지)
  **서치어드바이저의 노출·클릭 통계는 HUB 에도 없다**(공식 개요의 제공 목록에 없음).
  그래서 "내 글이 실제로 얼마나 노출됐나"는 여전히 서치어드바이저 화면에서만 나온다.
  대신 이 모듈로 자동화되는 것:
    · trend_profile()  키워드가 에버그린인지·시즌형인지·지금 뜨는지 — 글감 배분(강화/에버그린/핫이슈)의 근거
    · shopping_trend() 쇼핑 클릭 추이 — 유행템이 진짜 오르는 중인지
    · site_rank()      웹문서 검색에서 내 사이트가 몇 위인지 — 노출의 대리 지표

약관 주의(2026-09-07 시행 검색 API 특약 — 공식 원문은 직접 확인하지 못했다. 2차 자료 기준)
  검색 API 결과는 가공·요약·AI 입력·장기 저장·광고 수익화가 제한된다고 알려져 있다.
  그래서 site_rank() 는 **순위 숫자와 총 문서 수만** 돌려주고, 남의 글 제목·본문은 돌려주지 않는다.
  이 모듈이 돌려준 검색 결과를 LLM 프롬프트에 넣거나 글 본문에 싣지 말 것.

키: 환경변수 NAVER_HUB_KEY_ID / NAVER_HUB_KEY (금고 → 각 레포 Secrets). 값은 어디에도 출력하지 않는다.
의존성: requests 뿐. 다른 프로젝트 모듈을 import 하지 않는다.
"""
import datetime as _dt
import os
import re
import statistics as _st
import time
from urllib.parse import urlparse

import requests

BASE = os.getenv("NAVER_HUB_BASE", "https://naverapihub.apigw.ntruss.com")
PATHS = {
    "search": "/search/v1/{kind}",                       # GET  ?query=&display=&start=&format=json
    "trend": "/search-trend/v1/search",                  # POST 데이터랩 검색어 트렌드
    "shop_keywords": "/shopping/v1/category/keywords",   # POST 쇼핑인사이트 키워드별 클릭 추이
}
LAST_ERR = ""      # 마지막 실패 사유(키 값은 담기지 않는다)


def _headers(json_body=False):
    kid = os.getenv("NAVER_HUB_KEY_ID", "").strip()
    key = os.getenv("NAVER_HUB_KEY", "").strip()
    if not (kid and key):
        return None
    h = {"X-NCP-APIGW-API-KEY-ID": kid, "X-NCP-APIGW-API-KEY": key}
    if json_body:
        h["Content-Type"] = "application/json"
    return h


def available():
    return _headers() is not None


def _fail(msg):
    global LAST_ERR
    LAST_ERR = str(msg)[:200]
    return None


def _err_text(r):
    """HUB 는 오류 모양이 둘이다 — 검색 파라미터 오류(errorCode/errorMessage)와 게이트웨이 오류(error{…})."""
    try:
        j = r.json()
    except Exception:
        return (r.text or "")[:120]
    if isinstance(j, dict):
        if j.get("errorMessage"):
            return f"{j.get('errorCode', '')} {j.get('errorMessage')}"[:120]
        e = j.get("error")
        if isinstance(e, dict):
            return f"{e.get('errorCode', '')} {e.get('message', '')} {e.get('details', '')}"[:120]
    return str(j)[:120]


def _call(method, path, retries=2, **kw):
    h = _headers(json_body=(method == "POST"))
    if not h:
        return _fail("no-key: NAVER_HUB_KEY_ID / NAVER_HUB_KEY 가 없다")
    for i in range(retries + 1):
        try:
            r = requests.request(method, BASE + path, headers=h, timeout=30, **kw)
        except Exception as e:
            _fail(f"{type(e).__name__}")
            time.sleep(1.5 * (i + 1))
            continue
        if r.status_code == 200:
            try:
                return r.json()
            except Exception:
                return _fail("200 인데 JSON 이 아니다")
        if r.status_code == 429 and i < retries:      # 키당 50 RPS · 월 한도 초과 모두 429
            time.sleep(2.0 * (i + 1))
            continue
        return _fail(f"HTTP {r.status_code} {_err_text(r)}")
    return None


# ── ① 검색 ────────────────────────────────────────────────────────────
def _host(u):
    try:
        return (urlparse(u if "//" in u else "//" + u).netloc or "").lower().removeprefix("www.")
    except Exception:
        return ""


def site_rank(query, domain, kind="webkr", depth=100):
    """네이버 {kind} 검색에서 domain 이 처음 나오는 순위.

    반환 {"rank": 3 | None, "total": 12345, "url": "내 글 주소" | None} · 조회 실패 시 None.
    rank=None 은 '상위 depth 위 안에 없다'는 뜻이다(조회 실패와 구분된다).
    남의 글 제목·본문은 돌려주지 않는다(모듈 머리말의 약관 주의 참조)."""
    dom = _host(domain)
    if not (dom and (query or "").strip()):
        return _fail("query·domain 이 비었다")
    seen, total = 0, None
    while seen < depth:
        n = min(100, depth - seen)
        j = _call("GET", PATHS["search"].format(kind=kind),
                  params={"query": query, "display": n, "start": seen + 1, "format": "json"})
        if j is None:
            return None
        total = j.get("total", total)
        items = j.get("items") or []
        for k, it in enumerate(items):
            link = it.get("link") or ""
            if _host(link) == dom or _host(link).endswith("." + dom):
                return {"rank": seen + k + 1, "total": total, "url": link}
        if len(items) < n:
            break
        seen += n
    return {"rank": None, "total": total, "url": None}


def doc_count(query, kind="blog"):
    """그 말로 나오는 문서 수 — 경쟁 강도의 거친 가늠자. 실패 시 None."""
    j = _call("GET", PATHS["search"].format(kind=kind),
              params={"query": query, "display": 1, "format": "json"})
    return None if j is None else j.get("total")


# ── ② 데이터랩 검색어 트렌드 ───────────────────────────────────────────
def search_trend(keywords, start=None, end=None, time_unit="week"):
    """키워드 묶음 하나의 검색 추이. 반환 [(기간 시작일 'YYYY-MM-DD', ratio 0~100), …] · 실패 시 None.

    ratio 는 **그 요청 안에서의 상대값**(최댓값=100)이다. 절대 검색량이 아니다 —
    절대량은 검색광고 키워드도구(demand.py)로 재고, 여기서는 **모양**만 본다.
    그래서 한 번에 한 묶음만 보낸다(여러 묶음을 같이 보내면 큰 키워드에 눌려 작은 쪽이 0~2 로 뭉개진다)."""
    kws = [k.strip() for k in ([keywords] if isinstance(keywords, str) else keywords) if k and k.strip()][:5]
    if not kws:
        return _fail("키워드가 비었다")
    end = end or (_dt.date.today() - _dt.timedelta(days=2))
    start = start or (end - _dt.timedelta(days=364 * 2))
    body = {"startDate": str(start), "endDate": str(end), "timeUnit": time_unit,
            "keywordGroups": [{"groupName": kws[0][:20], "keywords": kws}]}
    j = _call("POST", PATHS["trend"], json=body)
    if j is None:
        return None
    res = (j.get("results") or [{}])[0].get("data") or []
    return [(d.get("period"), float(d.get("ratio") or 0)) for d in res]


def classify_trend(series, today=None):
    """주 단위 2년 추이 → 글감 배분에 쓸 한 줄 판정.

    label
      에버그린   1년 내내 고르게 찾는다(변동계수 낮음)              → B 갈래
      급상승     최근 4주가 직전 12주의 1.5배 이상, 작년 같은 때보다도 높다 → C 갈래(핫이슈)
      시즌진입   최근 4주가 올랐지만 작년에도 이때 올랐다           → C 갈래(시즌 선점)
      시즌형     봉우리가 뚜렷한데 지금은 철이 아니다                → peak_month 1~2달 전에 쓴다
      하락       최근이 직전·작년보다 모두 낮다                     → 새 글을 쓰지 않는다
      자료부족   검색이 너무 적어 추이가 잡히지 않는다
    """
    vals = [v for _, v in (series or [])]
    if len(vals) < 30 or sum(1 for v in vals if v > 0) < 20:
        return {"label": "자료부족", "n": len(vals)}
    mean = _st.fmean(vals)
    cv = (_st.pstdev(vals) / mean) if mean else 9.9
    recent = _st.fmean(vals[-4:])
    base = _st.fmean(vals[-16:-4]) or 0.01
    rise = recent / base
    yoy = None
    if len(vals) >= 58:
        ly = _st.fmean(vals[-56:-52]) or 0.01          # 1년 전 같은 4주
        yoy = recent / ly
    # 봉우리 달: 주별 값을 달로 모아 평균이 가장 높은 달
    by_month = {}
    for p, v in series:
        try:
            by_month.setdefault(int(p[5:7]), []).append(v)
        except Exception:
            pass
    month_avg = {m: _st.fmean(x) for m, x in by_month.items() if x}
    peak_month = max(month_avg, key=month_avg.get) if month_avg else None
    peak_ratio = (max(month_avg.values()) / mean) if (month_avg and mean) else 1.0

    # 순서가 중요하다. 작년의 절반도 안 되는 말은 최근 몇 주가 조금 올라도 '하락'이다
    # (바닥에서의 잔물결을 시즌 진입으로 읽지 않도록 — 합성 자료 시험에서 실제로 오판했다).
    if yoy is not None and yoy <= 0.5 and rise < 1.5:
        label = "하락"
    elif rise >= 1.5 and (yoy is None or yoy >= 1.3):
        label = "급상승"
    elif rise >= 1.3 and peak_ratio >= 1.4 and (yoy is None or yoy >= 0.7):
        label = "시즌진입"
    elif rise <= 0.7 and (yoy is None or yoy <= 0.8):
        label = "하락"
    elif cv <= 0.28 and peak_ratio < 1.4:
        label = "에버그린"
    elif peak_ratio >= 1.4:
        label = "시즌형"
    else:
        label = "에버그린" if cv <= 0.4 else "시즌형"
    return {"label": label, "cv": round(cv, 2), "rise": round(rise, 2),
            "yoy": None if yoy is None else round(yoy, 2),
            "peak_month": peak_month, "peak_ratio": round(peak_ratio, 2),
            "recent": round(recent, 1), "n": len(vals)}


def trend_profile(keyword):
    """키워드 하나의 판정. 실패 시 {"label": "조회실패", "err": …}."""
    s = search_trend(keyword)
    if s is None:
        return {"label": "조회실패", "err": LAST_ERR}
    return classify_trend(s)


# ── ③ 데이터랩 쇼핑인사이트 ───────────────────────────────────────────
SHOP_CATEGORIES = {      # 네이버쇼핑 1차 분류 코드
    "패션의류": "50000000", "패션잡화": "50000001", "화장품/미용": "50000002",
    "디지털/가전": "50000003", "가구/인테리어": "50000004", "출산/육아": "50000005",
    "식품": "50000006", "스포츠/레저": "50000007", "생활/건강": "50000008",
}


def shopping_trend(keyword, category="50000008", days=90, time_unit="date"):
    """쇼핑 분야 안에서 그 키워드의 **클릭** 추이(상대값). 반환 [(날짜, ratio)] · 실패 시 None.
    검색이 아니라 쇼핑 클릭이라 '살 마음이 있는 관심'에 가깝다. 상품 목록·가격은 주지 않는다."""
    end = _dt.date.today() - _dt.timedelta(days=2)
    start = end - _dt.timedelta(days=days)
    cat = SHOP_CATEGORIES.get(category, category)
    body = {"startDate": str(start), "endDate": str(end), "timeUnit": time_unit, "category": cat,
            "keyword": [{"name": keyword[:20], "param": [keyword]}]}
    j = _call("POST", PATHS["shop_keywords"], json=body)
    if j is None:
        return None
    res = (j.get("results") or [{}])[0].get("data") or []
    return [(d.get("period"), float(d.get("ratio") or 0)) for d in res]


def shopping_momentum(keyword, category="50000008"):
    """최근 14일 클릭이 그 앞 28일의 몇 배인가. 유행템이 '지금 오르는 중'인지 본다. 실패·자료 부족 시 None."""
    s = shopping_trend(keyword, category, days=60)
    if not s or len(s) < 30:
        return None
    vals = [v for _, v in s]
    base = _st.fmean(vals[-42:-14]) or 0.01
    return round(_st.fmean(vals[-14:]) / base, 2)


def clean_keyword(text):
    """글 제목·긴 문장에서 조회용 키워드만. 쉼표 앞 첫 구절, 특수문자 제거, 30자 이내."""
    t = re.split(r"[,，:：?？|]", str(text or ""))[0]
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s가-힣]", " ", t)).strip()[:30]
