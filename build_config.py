"""
build_config.py - 환경변수(GitHub Actions 시크릿)에서 config.json 생성 (카테고리 집중판).
로컬은 config.json 을 직접 편집해도 됩니다.

주의: GitHub Actions 는 '등록 안 한 시크릿'을 빈 문자열("")로 넘깁니다.
그래서 os.getenv(name, default) 의 default 가 무시되므로, 아래 helper 로 '빈 값이면 기본값' 처리를 합니다.
"""
import os, json


def envs(name, default=""):
    """환경변수 문자열: 없거나 빈 값이면 default."""
    v = os.getenv(name)
    return v if (v is not None and v.strip() != "") else default


def envi(name, default):
    """환경변수 정수: 없거나 빈 값/이상값이면 default(int)."""
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return int(default)
    try:
        return int(str(v).strip())
    except ValueError:
        return int(default)


def envf(name, default):
    """환경변수 실수: 없거나 빈 값/이상값이면 default(float)."""
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return float(default)
    try:
        return float(str(v).strip())
    except ValueError:
        return float(default)


def b(name, default=False):
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def envj(name, default):
    """환경변수 JSON: 없거나 파싱 실패면 default. (제휴 링크 목록 등)"""
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default
    try:
        return json.loads(v)
    except (ValueError, TypeError):
        return default


def _safety_block():
    """안전/품질 강도 프리셋 → 개별 env가 있으면 그 값으로 덮어씀."""
    presets = {
        # 2026-08 상향: 애드센스 '낮은 가치' 판정 경계가 올라갔다. 얇은 글은
        # 한 편만 있어도 사이트 단위로 감점되므로 하한을 통째로 끌어올린다.
        "느슨":  {"force_draft": False, "min_chars": 800,  "max_similarity": 0.65, "verify_accuracy": "off"},
        "표준":  {"force_draft": True,  "min_chars": 1000, "max_similarity": 0.50, "verify_accuracy": "flag"},
        "엄격":  {"force_draft": True,  "min_chars": 1200, "max_similarity": 0.40, "verify_accuracy": "strict"},
    }
    # 발행량을 하루 5편으로 줄인 만큼(비용 여유 생김) 기본 강도를 '엄격'으로 상향.
    # YMYL(금융/건강) 비중이 있는 만큼 품질 기준을 높게 잡는 게 정책 리스크 대비에 유리.
    strength = envs("SAFETY_STRENGTH", "엄격")
    p = presets.get(strength, presets["표준"])
    return {
        "strength": strength,
        "force_draft": (b("FORCE_DRAFT", p["force_draft"]) if os.getenv("FORCE_DRAFT", "").strip() else p["force_draft"]),
        "min_chars": envi("QUALITY_MIN_CHARS", p["min_chars"]),
        "min_h2": envi("QUALITY_MIN_H2", 3),
        "stuffing_count": envi("QUALITY_STUFFING_COUNT", 8),
        "max_keyword_density": envf("QUALITY_MAX_DENSITY", 0.03),
        "max_similarity": envf("QUALITY_MAX_SIMILARITY", p["max_similarity"]),
        # 최신성 검증은 항상 수행한다. 제도·금액은 수시로 바뀌어 '틀린 정보'가
        # 애드센스 정책 위반이자 신뢰 손상으로 직결되므로 off를 허용하지 않는다.
        "verify_accuracy": (lambda v: "flag" if str(v).lower() == "off" else v)(
            envs("VERIFY_ACCURACY", p["verify_accuracy"] if p["verify_accuracy"] != "off" else "flag")),
        "auto_revise": b("AUTO_REVISE", True),
        "relink_old": b("RELINK_OLD", True),           # 옛글↔새글 자동 내부링크(무비용, 신선도 신호)
        "refresh_days": envi("REFRESH_DAYS", 60),       # 60일 지난 글을 주기적으로 최신화(사람 손 안 감)
        "refresh_max_per_run": envi("REFRESH_MAX_PER_RUN", 2),
        "drip_hours": envf("DRIP_HOURS", 0),
        # 하루 5편을 하루 종일 자연스럽게 나눠 발행(한꺼번에 안 몰리게) — 2~5시간 랜덤 간격
        "drip_min_hours": envf("DRIP_MIN_HOURS", 2),
        "drip_max_hours": envf("DRIP_MAX_HOURS", 5),
        "blocklist_extra": [w.strip() for w in envs("BLOCKLIST_EXTRA", "").split(",") if w.strip()],
    }


def _singles(n):
    """단일글만 n편(시리즈 없음) — 발행량을 정확히 예측 가능하게(격일/소량 운영용)."""
    return {"long_series": 0, "long_single": n, "season_series": 0, "season_single": 0}


# 하루 총 5편 목표(직장인 저시간 운영):
#   경제/IT(YMYL 아님, 리스크 낮음) → 매일 4편, 우선순위 카테고리
#   금융/재테크 → 홀수날에만 1편
#   건강/생활   → 짝수날에만 1편
# → 홀수날: 경제/IT 4 + 금융 1 = 5편 / 짝수날: 경제/IT 4 + 건강 1 = 5편
DEFAULT_CATS = [
    # 승인 단계 기본값: 니치 하나로 좁힌다(주제 분산이 반려 사유).
    # 자격증·시험 준비 — 승인 점수 87, 포화 낮음, 교재·인강 제휴로 RPM 중간.
    # 공부 과정·오답 정리가 그 자체로 고유 콘텐츠라 '가치 없는 콘텐츠' 판정을 피하기 쉽다.
    {"name": "자격증·시험 준비", "wp_category": "자격증",
     "desc": "시험 일정·응시료, 교재 비교, 독학 커리큘럼, 기출 분석, 합격 후 활용. "
             "실제 확인한 공고·요강을 근거로 쓰고, 겪지 않은 경험은 지어내지 않는다.",
     "counts": _singles(1), "active_days": "all"},
]
try:
    categories = json.loads(envs("CATEGORIES_JSON", "")) or DEFAULT_CATS
except Exception:
    categories = DEFAULT_CATS

cfg = {
    "paused": b("PAUSED", False),          # 매일 자동 생성 일시정지
    "adsense_approved": b("ADSENSE_APPROVED", False),   # 승인 후 수익 최적화 활성 여부
    "revenue": {
        "ads_boost": b("ADS_BOOST", True),
        "related_cards": b("RELATED_CARDS", True),
    },
    "blog_url": envs("BLOG_URL", envs("WP_SITE", "")),
    "categories": categories,
    # 작성자 정보(E-E-A-T 신뢰 신호). author_type=Person으로 하면 실명 저자로 구조화데이터에 표시됨.
    "author": envs("AUTHOR_NAME", "편집부"),
    "author_bio": envs("AUTHOR_BIO", ""),
    "author_type": envs("AUTHOR_TYPE", "Organization"),
    # 카테고리별 'counts'가 없을 때만 쓰는 전역 기본값(안전하게 소량). 카테고리별 실제 값은
    # DEFAULT_CATS(또는 CATEGORIES_JSON)의 각 카테고리 안 "counts"/"active_days"가 우선한다.
    "counts": {
        "long_series": envi("LONG_SERIES", 0),
        "long_single": envi("LONG_SINGLE", 1),
        "season_series": envi("SEASON_SERIES", 0),
        "season_single": envi("SEASON_SINGLE", 0),
        "series_min_parts": envi("SERIES_MIN", 2),
        "series_max_parts": envi("SERIES_MAX", 3),
    },
    # ads.code 가 비어 있으면 generator 가 광고 상자를 만들지 않는다(빈 "[ 광고 자리 ]" 방지).
    "ads": {"insert_slots": b("INSERT_ADS", True), "code": envs("ADS_CODE", "")},
    "coupang": {                                    # 쿠팡 파트너스(API 불필요)
        "enabled": b("COUPANG_ENABLED", False),
        "disclosure": b("COUPANG_DISCLOSURE", True),
        "widget_html": envs("COUPANG_WIDGET_HTML", ""),
    },
    "affiliate": {                                  # 제휴 SaaS(쿠팡 외 일반 제휴 링크)
        "enabled": b("AFFILIATE_ENABLED", False),
        "disclosure": b("AFFILIATE_DISCLOSURE", True),
        "box_title": envs("AFFILIATE_BOX_TITLE", "이 글에서 소개한 도구"),
        # [{"name":"GetResponse","url":"https://...ref=me","desc":"이메일 자동화"}]
        "links": envj("AFFILIATE_LINKS", []),
    },
    "supabase": {                                    # 초안 백로그 큐 동기화(선택). 없으면 조용히 건너뜀
        "url": envs("SUPABASE_URL", ""),
        "service_key": envs("SUPABASE_SERVICE_KEY", ""),
    },
    # 애드센스 안전장치(초안강제 + 품질게이트 + 금지주제 + 최신성검증). 강도 프리셋 후 개별 env로 덮어씀
    "safety": _safety_block(),
    # 검색량 우선 비율(0~100). 없으면 KEYWORD_STRATEGY로 환산
    # (rankable=0 / rankable_lean=15 / balanced=30 / traffic=100)
    # 기본을 rankable_lean으로: 신규 도메인은 대형 키워드 경쟁에서 못 이기므로
    # '실제로 잡히는' 저경쟁 키워드 비중을 높여야 초반 트래픽이 실제로 붙는다.
    "traffic_ratio": (envi("TRAFFIC_RATIO", -1) if os.getenv("TRAFFIC_RATIO", "").strip()
                      else {"rankable": 0, "rankable_lean": 15, "traffic": 100, "balanced": 30}.get(
                          envs("KEYWORD_STRATEGY", "rankable_lean"), 15)),
    "images": {
        # 폰/수동 실행에서 images=false 를 넘기면 이미지 생성 끔. 기본은 무료(free)
        "provider": ("none" if str(os.getenv("IMAGE_ENABLED", "")).strip().lower() == "false"
                     else envs("IMAGE_PROVIDER", "free")),
        "pexels_key": envs("PEXELS_API_KEY", ""),         # 무료 스톡(택1)
        "unsplash_key": envs("UNSPLASH_ACCESS_KEY", ""),  # 무료 스톡(택1)
        "model": envs("IMAGE_MODEL", "imagen-4.0-fast-generate-001"),  # 유료 provider일 때만
        "size": envs("IMAGE_SIZE", "1200x675"),                        # 디스커버/SNS 규격
        "max_per_run": envi("IMAGE_MAX_PER_RUN", 20),                   # 비용 상한(유료)
        "api_key": envs("IMAGE_API_KEY", ""),
    },
    "llm": {
        "provider": envs("LLM_PROVIDER", "gemini"),
        "api_key": envs("LLM_API_KEY", ""),
        # 무료 등급: 2.5-flash 는 하루 20회로 축소됨 → flash-lite 를 기본
        "model": envs("LLM_MODEL", "gemini-2.5-flash"),   # 품질 위해 flash(유료). 무료면 flash-lite 권장
        # 한도에 걸리면 아래 순서로 자동 전환
        "fallback_models": [s.strip() for s in envs(
            "FALLBACK_MODELS", "gemini-2.5-flash-lite,gemini-2.0-flash").split(",") if s.strip()],
    },
    "metrics": {
        "provider": envs("METRICS_PROVIDER", "naver"),
        "low_volume_floor": envi("LOW_VOLUME_FLOOR", 1000),    # 수익 나는 최소 검색량
        "low_volume_ceil": envi("LOW_VOLUME_CEIL", 30000),     # 이 이상은 대형(경쟁 과열) 제외
        "use_trends_steadiness": b("USE_TRENDS_STEADINESS", False),
        "naver": {
            "api_key": envs("NAVER_API_KEY", ""),
            "secret_key": envs("NAVER_SECRET_KEY", ""),
            "customer_id": envs("NAVER_CUSTOMER_ID", ""),
        },
    },
    "wordpress": {
        "enabled": b("WP_ENABLED", False),
        "site_url": envs("WP_SITE", ""),
        "username": envs("WP_USER", ""),
        "app_password": envs("WP_APP_PASSWORD", ""),
        "status": envs("WP_STATUS", "draft"),
        "indexnow_key": envs("INDEXNOW_KEY", ""),   # 네이버·빙 자동 등록 키
    },
    "sheets": {"enabled": False},
    "notify": {
        "telegram_token": envs("TELEGRAM_TOKEN", ""),      # 실행 완료/실패 알림(무료)
        "telegram_chat_id": envs("TELEGRAM_CHAT_ID", ""),
    },
    "insights": {                                          # 성과·수익 실측(무료 API)
        "service_account_json": envs("GOOGLE_SERVICE_ACCOUNT_JSON", ""),
        "sc_site_url": envs("SC_SITE_URL", envs("WP_SITE", "")),
        "ga4_property_id": envs("GA4_PROPERTY_ID", ""),
        "adsense_account": envs("ADSENSE_ACCOUNT", ""),
        "adsense_refresh_token": envs("ADSENSE_REFRESH_TOKEN", ""),  # 애드센스는 OAuth
        "oauth_client_id": envs("GOOGLE_OAUTH_CLIENT_ID", ""),
        "oauth_client_secret": envs("GOOGLE_OAUTH_CLIENT_SECRET", ""),
    },
    "perf": {
        "workers": envi("WORKERS", 4),      # 유료 등급이면 4~6 권장(빠름)
        "classify": b("CLASSIFY", True),
    },
}

with open("config.json", "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)
slots_each = (cfg["counts"]["long_series"] + cfg["counts"]["long_single"]
              + cfg["counts"]["season_series"] + cfg["counts"]["season_single"])
print("config.json 생성: 카테고리 %d개, 각 %d슬롯, images=%s, metrics=%s, wp=%s" % (
    len(cfg["categories"]), slots_each, cfg["images"]["provider"],
    cfg["metrics"]["provider"], cfg["wordpress"]["enabled"]))
