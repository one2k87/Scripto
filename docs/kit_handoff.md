# 엔진 인계 문서 — 스크립토 → 키토(K)

> 작성: 스크립토, 2026-11-20 · 대상: 크몽 키트(워드프레스 자동 발행) 전담 키토
> 원칙: 시크릿은 **이름만** 적는다(값 금지, 레포 공개). 이 문서는 "지금 원더랜드에서 돌고 있는 그대로"를 기록한 것이고, 키트로 일반화할 때 뗄 곳은 4장에 따로 모았다.

## 1. 폴더 구조 (Scripto 레포 루트)

| 위치 | 역할 | 키트 포함 |
|---|---|---|
| `main.py` | 하루 실행의 진입점. 카테고리별 주제 수집 → 생성 → 품질 검사 → 발행 → 기록 | 포함 |
| `topics.py` · `trends.py` · `metrics.py` · `naver_search.py` | 주제 후보 수집, 검색량 측정(네이버 검색광고), 클릭 점수 | 포함 |
| `generator.py` · `llm.py` | 원고 생성 프롬프트, 제목 후보·채점, LLM 호출(공급자 전환) | 포함 |
| `quality.py` · `integrity.py` · `accuracy.py` | 분량·H2 수·유사도·밀도 검사, 사실 무결성 검사 | 포함 |
| `publisher.py` | 워드프레스 REST 발행(글·이미지·Rank Math 메타) | 포함 |
| `images.py` | 대표 이미지(생성/스톡) | 포함 |
| `originality.py` | 실측 표·체크 위젯·공공 화면 삽입(주제가 맞을 때만) | 구조만, 키워드 사전은 교체 |
| `build_config.py` · `config.example.json` | 시크릿 → `config.json` 조립. 로컬 `config.json`은 자리표시자, 실제 값은 GitHub Secrets에만 | 포함 |
| `notify.py` · `report.py` · `monitor.py` | 텔레그램 알림, 주간 리포트, 상태 기록 | 포함(선택) |
| `scripts/` | 일회성·자가치유 도구(아래 2장) | 일부만 |
| `dashboard/` · `data/` · `records/` | 결과 기록(대시보드가 읽음), 백업 | 빈 틀만 |
| `supabase/` · `supabase_client.py` · `saas/` | 앱 설정 저장(Supabase) — 원더랜드 전용 운영 | 제외 권장 |
| `wordpress_mu-plugin_rankmath-rest.php` | Rank Math 메타를 REST로 쓰게 하는 mu-plugin. 구매자 WP에 1회 업로드 | 포함(필수) |
| `wordpress_snippets_url_cleanup_1119.php` | 원더랜드 301/410·아카이브 규칙(현재 Code Snippets #5에 적용) | 제외 |
| `설치_가이드_상세.md` · `랭크매스_승인용_설정가이드.md` · `사이트맵_마무리_가이드.md` | 기존 설치 문서 — 매뉴얼 재료 | 재작성해 포함 |

## 2. 워크플로(.github/workflows)와 실행 순서

### 매일 자동(핵심) — `daily-blog.yml`
현재 크론은 **주석 처리(11/17~23 정지)**. 11/24 재개 예정이지만, 아래 ⑪~⑮가 11/19 URL 정리(410·임시글 41편)와 충돌하는지 점검 후 켠다.

| 순서 | 단계 | 키트 |
|---|---|---|
| ① | 한글 폰트 설치(코드 썸네일용) | 포함 |
| ② | 의존성 설치 · ③ 진단(버전 출력) | 포함 |
| ④ | **필수 키 확인** — `LLM_API_KEY` 비면 즉시 실패 | 포함(doctor 대상) |
| ⑤ | **config.json 생성(시크릿에서)** | 포함 |
| ⑥ | 카테고리 저장소 파일 적용 | 포함 |
| ⑦ | 중복 실행 가드(KST 기준 같은 날 재생성 방지, 백업 크론 대비) | 포함 |
| ⑧ | 프롬프트 조립 무연기 시험(생성 전 크래시 차단) | 포함 |
| ⑨ | 독창성 층 갱신 | 선택 |
| ⑩ | **블로그 생성 실행**(`main.py`) | 포함 |
| ⑪ | 새 글 자동 색인 통지(IndexNow) | 포함 |
| ⑫ | 색인 검사·기록(Search Console Inspection API, 읽기 전용) | 선택 |
| ⑬ | 옛 URL 301 자가치유(`redirect_old.py`) | 제외(원더랜드 이력 전용) |
| ⑭ | 구조화 데이터 자가치유(`schema_repair.py`) | 포함 |
| ⑮ | 사이트 점검·자동 수리(`daily_check_fix.py`) | 검토 후 |
| ⑯ | 쇼츠 원고 공급(캐스토 연동) | 제외 |
| ⑰ | 가이드 허브·도구 페이지 갱신(`hub_pages.py`) | 제외 |
| ⑱ | 검색 상위노출 루프(`serp_loop.py`) | 선택 |
| ⑲ | 결과 커밋(대시보드용) | 포함 |

### 수동 실행(workflow_dispatch) — 기본값은 DRY(미리보기)
`unpublish`(글 내리기→임시글) · `post-patch`(본문 수정) · `retitle` · `byline-fix` · `defect-fix` · `originality-backfill` · `redirect-old` · `schema-repair` · `reimage` · `keyword-intro` · `humanize` · `diag`(진단) · `autopsy` · `cleanup` · `fresh-start` · `topic-pivot` · `persona-gen/apply` · `evidence-capture` · `backlog-extract`.
정기: `weekly-report`, `weekly-strategy`, `supabase-keepalive`, `check`.
→ 키트에는 **daily-blog + unpublish + post-patch + diag(doctor로 재작성)** 만 넣는 것을 권장.

## 3. 시크릿 이름(값은 적지 않음)

| 구분 | 이름 | 키트 |
|---|---|---|
| 워드프레스 | `WP_SITE` · `WP_USER` · `WP_APP_PASSWORD` · `BLOG_URL` | **필수** |
| LLM | `LLM_PROVIDER` · `LLM_API_KEY` · `LLM_MODEL` · `LLM_API_KEY_PAID` | `LLM_*` 3개 필수 |
| 알림 | `TELEGRAM_TOKEN` · `TELEGRAM_CHAT_ID` | 선택 |
| 이미지 | `IMAGE_PROVIDER` · `IMAGE_API_KEY` · `PEXELS_API_KEY` · `UNSPLASH_ACCESS_KEY` · `CF_API_TOKEN` · `CF_ACCOUNT_ID` | 1종 선택 |
| 검색량·검색 | `NAVER_AD_API_KEY` · `NAVER_AD_SECRET` · `NAVER_AD_CUSTOMER_ID` · `NAVER_HUB_KEY_ID` · `NAVER_HUB_KEY` · `METRICS_PROVIDER` | 선택(없으면 측정 생략) |
| 색인 | `INDEXNOW_KEY` · `GSC_SITE_URL` · `SC_SITE_URL` · `GOOGLE_SERVICE_ACCOUNT_JSON` | 선택 |
| 분석·광고 | `GA4_PROPERTY_ID` · `ADSENSE_ACCOUNT` · `ADSENSE_REFRESH_TOKEN` · `GOOGLE_OAUTH_CLIENT_ID` · `GOOGLE_OAUTH_CLIENT_SECRET` | 제외 |
| 제휴 | `COUPANG_ENABLED` · `COUPANG_WIDGET_HTML` · `AFFILIATE_ENABLED` · `AFFILIATE_LINKS` · `INSERT_ADS` · `ADS_BOOST` | 선택 |
| Supabase | `SUPABASE_URL` · `SUPABASE_SERVICE_KEY` · `SUPABASE_ACCESS_TOKEN` · `SUPABASE_DB_PASSWORD` | 제외 |
| 운영 설정(값이 비밀은 아님) | `CATEGORIES_JSON` · `KEYWORD_STRATEGY` · `TRAFFIC_RATIO` · `SAFETY_STRENGTH` · `QUALITY_MIN_CHARS` · `QUALITY_MIN_H2` · `QUALITY_MAX_SIMILARITY` · `QUALITY_MAX_DENSITY` · `REFRESH_DAYS` · `REFRESH_MAX_PER_RUN` · `DRIP_MIN_HOURS` · `DRIP_MAX_HOURS` · `FORCE_DRAFT` · `AUTO_REVISE` · `RELINK_OLD` · `VERIFY_ACCURACY` · `BLOCKLIST_EXTRA` · `LONG_SINGLE` · `LONG_SERIES` · `SEASON_SINGLE` · `SEASON_SERIES` · `AUTHOR_TYPE` · `AUTHOR_NAME` · `AUTHOR_BIO` | **설정 파일 1개로 옮길 것**(구매자가 시크릿 40개를 넣게 하면 안 됨) |

## 4. 자주 나는 오류 5가지 → doctor 진단 항목

| doctor 항목 | 실제로 겪은 증상 | 원인 | 해결 |
|---|---|---|---|
| **키** | '필수 키 확인'에서 즉시 실패 / LLM 403 / 네이버 HUB 401 "이 Application에서 활성화되어 있지 않음" | 시크릿 비어 있음, 키 권한(사용 API) 미설정 | 키 존재·형식 확인 → 공급자 콘솔에서 해당 API 사용 설정 |
| **권한** | 글은 올라가는데 Rank Math 제목·설명·포커스 키워드가 비어 있음 / REST 401·403 | mu-plugin 미설치, 사용자 역할이 편집자 미만, 보안 플러그인이 REST 차단 | `wordpress_mu-plugin_rankmath-rest.php`를 `wp-content/mu-plugins/`에 업로드, 사용자 역할 확인, 보안 플러그인 REST 허용 |
| **주소** | JSON 대신 HTML이 돌아옴(실측: retitle 6회차 실패) / POST가 GET으로 바뀌어 401 | `WP_SITE`의 http↔https·www·끝 슬래시 불일치로 301, 호스팅 보안 페이지 | `/wp-json/` 응답이 JSON인지 먼저 확인, 주소를 리다이렉트 없는 최종 주소로 통일, 연속 요청에 간격·재시도 |
| **앱 비밀번호** | 401 `rest_cannot_create` · `incorrect_password` | 로그인 비밀번호를 넣음, 앱 비밀번호 공백 처리, 2단계 인증 플러그인 간섭 | 사용자 → 프로필 → 애플리케이션 비밀번호 새로 발급(공백 포함 그대로 저장), 2FA 플러그인 REST 예외 |
| **한도** | LLM 429 / 이미지 업로드 413 / GitHub가 정기 크론을 건너뜀(실측 9/1) | API 일·분 한도, 서버 업로드 크기 제한, Actions 크론 지연 | 공급자 한도·요금제 확인, 이미지 크기 축소(또는 서버 `client_max_body_size`), 백업 크론 + 중복 실행 가드 |

## 5. 키트로 일반화할 때 떼어 낼 원더랜드 전용 부분

- **주제·톤**: `topics.py`·`generator.py` 프롬프트 속 시니어 디지털·"부모님" 맥락, 제목 규칙의 대상 수식어 처리, `AUTHOR_BIO`(이음 페르소나), `persona_*` 스크립트.
- **독창성 층**: `originality.py`의 `FIT_KW` 사전(갤럭시·정부24 등)과 체크 위젯 문구 → 구매자 분야별 사전으로 교체하거나 꺼 둠.
- **이력 기반 도구**: `redirect_old.py`(주제 전환 이력), `topic_pivot.py`, `defect_fix.py`, `byline_fix.py`, `data/cleanup_plan_1117.json`, `data/core30_queries.json`, `hub_pages.py`.
- **다른 앱 연동**: `shorts_feed.py`(캐스토), Supabase 설정 공유(9/8 사고: 세 앱이 설정 레코드 하나를 공유했던 문제 — 키트에서는 아예 쓰지 말 것).
- **사이트 규칙**: Code Snippets #5(301/410·robots·IndexNow 키 파일·아카이브 noindex·사이트맵) — 구매자 사이트에는 robots·사이트맵 부분만 일반화해 제공.
- **카테고리**: `CATEGORIES_JSON`과 카테고리 저장소 파일은 원더랜드 분류 → 설치 마법사에서 구매자가 2~3개 입력.

## 6. 키토와의 약속
- 질문은 `inbox/scripto.md`에 남기면 다음 스크립토 시작 때 답한다.
- 11/24부터 매일 자동 발행 성공/실패를 `_Master_Context/kit_gate_log.md`에 한 줄씩 남긴다(형식: `YYYY-MM-DD | 성공/실패 | 글 ID 또는 실패 단계 | 복구`).
- 엔진 코드를 바꾸면 이 문서의 해당 표를 같은 커밋에서 고친다.
