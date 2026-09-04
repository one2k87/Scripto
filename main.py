"""
main.py - 카테고리 집중 애드센스 수익형 파이프라인 (한국어 전용).

하루 흐름:
1) 히스토리(과거 발행 제목) 로드 → 중복 방지용
2) 선택한 고단가 카테고리 안에서 주제 생성
     long   = 저경쟁 롱테일 (상위노출 쉬움)
     season = 시즌/이벤트 선점 (2~4주 미리)
3) (옵션) 네이버 검색량 실측으로 저경쟁 후보 선별
4) 각 주제로 수익형 글 생성 (이전 글로 내부링크 → 카테고리 클러스터)
5) (옵션) WordPress 게시 / 복붙 HTML 저장
6) 히스토리 갱신 + 구글시트 로깅 + 대시보드 데이터 저장

실행: python main.py   설정: config.json
"""

import os
import json
import time
import html as html_mod
from datetime import datetime

import random
import topics
import metrics
import images
import quality
import strategy
import ramp
import accuracy
import monitor
import notify
import insights
import supabase_client
from llm import chat
from generator import generate_article, generate_series
from publisher import (publish_to_wordpress, upload_media, add_update_banner,
                       submit_indexnow, get_post, update_post_content, trash_post)
from sheets import log_rows

BASE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE, "output")
DASH_DATA = os.path.join(BASE, "dashboard", "data")
HISTORY = os.path.join(DASH_DATA, "history.json")


def load_config():
    path = os.path.join(BASE, "config.json")
    if not os.path.exists(path):
        raise SystemExit("config.json 이 없습니다. config.example.json 을 복사해 만드세요.")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_history():
    if os.path.exists(HISTORY):
        try:
            with open(HISTORY, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"articles": []}   # [{title, slug, url, kind, keyword, date}]


def save_history(hist):
    os.makedirs(DASH_DATA, exist_ok=True)
    with open(HISTORY, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)


def get_categories(cfg):
    """config에서 카테고리 목록을 만든다(구버전 site.category 호환)."""
    if cfg.get("categories"):
        return [{"name": c.get("name", ""), "desc": c.get("desc", ""),
                 "wp_category": c.get("wp_category", c.get("name", "")),
                 "wp_slug": c.get("wp_slug", "")} for c in cfg["categories"]]
    site = cfg.get("site", {})
    return [{"name": site.get("category", ""), "desc": site.get("category_desc", ""),
             "wp_category": site.get("category", ""), "wp_slug": ""}]


def collect_lane(cfg, cat, lane, n_slots, exclude):
    """
    한 카테고리(cat) 안에서 한 갈래(lane)의 주제를 n_slots개 확보한다.
      1) 후보 생성 → 2) 저경쟁/시즌 지속 판별 → 3) long은 네이버 실측 선별
    """
    mcfg = cfg.get("metrics", {}) or {}
    measured = mcfg.get("provider", "none") not in ("none", None)
    pool = max(3, n_slots + 2)

    raw = chat(topics.build_topic_prompt(cat["name"], cat["desc"], lane, pool, exclude=exclude,
                                         winners=cfg.get("_insight_hints"),
                                         intent=cfg.get("_today_intent")),
               cfg["llm"], max_tokens=900, temperature=0.9)
    cand = topics.parse_topics(raw, pool)
    # 금지·위험 주제 필터(성인/도박/과장의료/저작권/전쟁 등 자동 제외)
    extra_block = (cfg.get("safety", {}) or {}).get("blocklist_extra", [])
    before = len(cand)
    cand = [c for c in cand if not topics.is_blocked(c["keyword"], extra_block)]
    if len(cand) < before:
        print(f"  · 금지·위험 주제 {before - len(cand)}개 제외")
    # 일반인이 클릭 안 하는 기업·전문가·B2B 주제 제거(안전망)
    before = len(cand)
    cand = [c for c in cand if not topics.is_corporate(c["keyword"])]
    if len(cand) < before:
        print(f"  · 기업·전문가용 주제 {before - len(cand)}개 제외(일반인 관점 유지)")

    # 지속 판별(저경쟁 vs 시즌). 속도 위해 perf.classify=false 면 건너뜀
    # (이미 lane별 프롬프트로 생성했으므로 끄더라도 분류 자체는 유지됨)
    if cfg.get("perf", {}).get("classify", True):
        print(f"  · 주제 판별(저경쟁/시즌) 중…")
        topics.classify_topics(cand, cat["name"], chat, cfg["llm"])
        match = [c for c in cand if c.get("lane_ai") == lane]
        ordered = match + [c for c in cand if c.get("lane_ai") != lane]  # 부족하면 나머지로 보충
    else:
        ordered = cand

    # 3) long은 네이버 실측 + '비율(traffic_ratio)'로 선별
    #    traffic_ratio: 검색량 우선의 비율(0~100). 0=상위노출만, 100=검색량만, 30=상위노출 위주+검색량 약간
    ratio = cfg.get("traffic_ratio")
    if ratio is None:  # 구버전 keyword_strategy 호환
        ratio = {"rankable": 0, "traffic": 100, "balanced": 30}.get(
            (cfg.get("keyword_strategy") or "balanced").lower(), 30)
    ratio = max(0, min(100, int(ratio)))
    traffic_set = set()

    if lane == "long" and measured:
        print(f"  · 저경쟁 후보 검색량 측정(네이버)… (검색량 비율={ratio}%)")
        metrics.enrich(ordered, mcfg, geo="KR", want_steadiness=True)
        floor = mcfg.get("low_volume_floor", 1000)
        comp_rank = {"낮음": 0, "중간": 1, "높음": 2, "": 1}

        def v(x):
            return x.get("volume") if x.get("volume") is not None else (x.get("interest") or 0)

        above = [x for x in ordered if (x.get("volume") is None or v(x) >= floor)] or ordered
        n_traffic = round(n_slots * ratio / 100.0)          # 검색량 우선으로 뽑을 개수
        n_rank = n_slots - n_traffic                        # 상위노출(경쟁낮음) 우선 개수
        rank_sorted = sorted(above, key=lambda x: (comp_rank.get(str(x.get("competition", "")), 1), -v(x)))
        traffic_sorted = sorted(above, key=lambda x: -v(x))

        picked = []
        for x in rank_sorted:                               # 상위노출 몫 먼저
            if len(picked) >= n_rank:
                break
            if x not in picked:
                picked.append(x)
        for x in traffic_sorted:                            # 검색량 몫
            if len([p for p in picked if id(p) in traffic_set]) >= n_traffic:
                break
            if x not in picked:
                picked.append(x); traffic_set.add(id(x))
        for x in rank_sorted + traffic_sorted:              # 모자라면 채우기
            if len(picked) >= n_slots:
                break
            if x not in picked:
                picked.append(x)
        print("  · 선별(검색량/경쟁):", [(p["keyword"], p.get("volume"), p.get("competition")) for p in picked[:n_slots]])
        ordered = picked

    sel = ordered[:n_slots]
    # 상위노출 강화 대상 표시: 검색량 몫으로 뽑혔거나 경쟁도 중간/높음이면 강화 글로 작성
    for kw in sel:
        comp = str(kw.get("competition", ""))
        kw["competitive"] = (id(kw) in traffic_set) or (comp in ("중간", "높음")) or (ratio >= 60 and not measured)
    return sel


IMG_ERRS = []   # 이미지 생성 실패 사유 수집(관측용)

def make_image_resolver(cfg, auto_publish, category="", budget=None):
    """[[IMG:설명]] → 실제 이미지 자동 생성 후 <figure> 반환하는 콜백(카테고리별).
    budget={"used":n,"max":N} 로 실행 1회당 이미지 개수를 제한(비용 상한)."""
    imgcfg = dict(cfg.get("images", {}) or {})
    if imgcfg.get("provider") in ("gemini", "imagen", "google", "free") and not imgcfg.get("api_key"):
        imgcfg["api_key"] = cfg["llm"].get("api_key", "")   # Gemini 키 재사용(free도 도해 1순위)
    wp_cfg = cfg.get("wordpress", {})
    out = os.path.join(OUT_DIR, "images")

    if imgcfg.get("provider", "none") in ("none", None, ""):
        return None

    def resolver(desc, idx):
        if budget is not None and budget.get("used", 0) >= budget.get("max", 10 ** 9):
            return None                      # 비용 상한 초과 → 자리표시로 대체
        path = images.generate_image(desc, imgcfg, out, idx, category=category)
        if not path:
            err = getattr(images, "LAST_ERR", "")
            if err:
                IMG_ERRS.append(err[:180])
            return None
        if budget is not None:
            budget["used"] = budget.get("used", 0) + 1
        alt = getattr(images, "LAST_DESC", "") or desc   # 스타일 태그 뗀 순수 묘사
        src = None
        if auto_publish and wp_cfg.get("enabled"):
            src = upload_media(path, wp_cfg, alt=alt)
        if not src:
            src = images.to_data_uri(path)     # 미게시/업로드 실패 시 인라인
        # 스타일별 정직한 캡션(AI 생성 고지 유지 — 애드센스 정직성)
        _notes = {"diagram": "이해를 돕기 위한 도해입니다",
                  "illust": "내용을 표현한 일러스트입니다",
                  "photo": "AI로 연출한 참고 이미지입니다",
                  "object": "AI로 연출한 참고 이미지입니다"}
        note = (_notes.get(getattr(images, "LAST_STYLE", ""), None)
                if getattr(images, "LAST_KIND", "") == "ai" else None)
        return images.figure_html(src, alt, note)

    return resolver


def save_copy_html(article):
    os.makedirs(OUT_DIR, exist_ok=True)
    safe = "".join(c for c in article["keyword"][:40] if c.isalnum() or c in " _-").strip()
    cat = "".join(c for c in article.get("category", "")[:10] if c.isalnum())
    fname = f"{datetime.now():%Y%m%d}_{cat}_{article['kind']}_{safe}.html"
    path = os.path.join(OUT_DIR, fname)
    doc = (f'<!doctype html><html lang="ko"><head><meta charset="utf-8">'
           f'<title>{html_mod.escape(article["title"])}</title>'
           f'<meta name="description" content="{html_mod.escape(article["meta"])}"></head>'
           f'<body>{article["html"]}</body></html>')
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    return path


def _category_active_today(cat):
    """카테고리별 '격일' 운영. active_days: all(기본)/odd(홀수날)/even(짝수날).
    day-of-year 기준이라 요일과 무관하게 정확히 하루걸러 하루 실행된다."""
    mode = str(cat.get("active_days") or "all").strip().lower()
    if mode not in ("odd", "even"):
        return True
    doy_is_odd = (datetime.now().timetuple().tm_yday % 2 == 1)
    return doy_is_odd if mode == "odd" else (not doy_is_odd)


def _theme_guard(cats, hist, topic_width=None):
    """주제(카테고리) 전환 완충 장치.

    왜: 카테고리를 바꾸면 다음 실행부터 새 주제가 최대 물량으로 나간다.
    승인 직후 주제가 갑자기 바뀌는 것은 '검수 없는 대량 발행'과 함께
    애드센스가 가장 싫어하는 신호다(실제로 인테리어 블로그에 자격증
    초안이 하루 만에 생성된 사고가 있었다).

    규칙:
      · 그 주제로 이미 발행된 글 수(n)에 따라 하루 상한을 둔다
        n 0~4편 → 하루 1편, 5~9 → 2편, 10~14 → 3편, 15편↑ → 제한 없음
      · 램프의 topic_width(단계별 주제 폭)를 실제로 집행한다 —
        기존 주제를 우선하고, 폭을 넘는 '새' 주제는 이번 단계에선 보류
      · 블로그 자체가 새것(총 기록 10편 미만)이면 제한하지 않는다
        (승인 준비 단계의 첫 주제가 여기 해당)
    """
    arts = (hist or {}).get("articles") or []
    counts = {}
    for a in arts:
        c = a.get("category")
        if c:
            counts[c] = counts.get(c, 0) + 1
    total = sum(counts.values())
    if total < 10:
        return cats, []

    kept, notes = [], []
    ranked = sorted(cats, key=lambda c: -counts.get(c.get("name", ""), 0))
    width = len(ranked) if not topic_width else max(1, int(topic_width))
    for i, c in enumerate(ranked):
        n = counts.get(c.get("name", ""), 0)
        if i >= width and n == 0:
            notes.append(f"'{c['name']}' 보류 — 현 단계 주제 폭({width})을 넘는 새 주제")
            continue
        c = dict(c)
        if n < 15:
            cap = 1 + n // 5
            c["_daily_cap"] = cap
            notes.append(f"'{c['name']}' 완충 — 누적 {n}편이라 하루 최대 {cap}편(시리즈 금지)")
        kept.append(c)
    if not kept and ranked:            # 전부 보류되는 극단은 막는다
        c = dict(ranked[0]); c["_daily_cap"] = 1; kept = [c]
        notes.append(f"'{c['name']}' 최소 1편 유지")
    return kept, notes


def _plan_slots(cfg, cat=None):
    """각 갈래의 슬롯을 (series/single)로 계획. 시리즈=1슬롯(여러 편 생성).
    카테고리 dict에 'counts'가 있으면 그 카테고리 전용 발행량으로 우선 사용(없으면 전역 기본값)."""
    c = (cat or {}).get("counts") or cfg.get("counts", {})
    smin = c.get("series_min_parts", 2)
    smax = c.get("series_max_parts", 3)

    def parts():
        return random.randint(smin, smax)

    slots = []
    for _ in range(c.get("long_series", 2)):
        slots.append(("long", "series", parts()))
    for _ in range(c.get("long_single", 2)):
        slots.append(("long", "single", 1))
    for _ in range(c.get("season_series", 1)):
        slots.append(("season", "series", parts()))
    for _ in range(c.get("season_single", 1)):
        slots.append(("season", "single", 1))

    # 주제 전환 완충: 새 주제는 슬롯 수를 줄이고 시리즈(한 번에 여러 편)를 금지한다.
    cap = (cat or {}).get("_daily_cap")
    if cap:
        slots = [(lane, "single", 1) for lane, _m, _n in slots][:int(cap)]
    return slots


def _recent_for_template(hist, limit=30):
    """템플릿성 비교용 최근 글 목록. history.json에는 본문이 없으므로 제목만 사용한다
    (제목 어미 중복은 제목만으로 판정 가능. 도입부 비교는 같은 실행 내 글끼리 이뤄진다)."""
    arts = (hist or {}).get("articles", []) or []
    return [{"title": a.get("title", ""), "html": "", "opening": ""} for a in arts[-limit:]]


def _log_hold(cfg, article, reason):
    """보류 사유를 누적 기록한다(dashboard/data/quality_log.json).

    나중에 이 로그를 통째로 AI에게 넘기면, 어떤 사유가 반복되는지 보고
    생성 로직(프롬프트·임계값)을 한 번에 고칠 수 있다.
    """
    path = os.path.join("dashboard", "data", "quality_log.json")
    try:
        log = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {"entries": [], "counts": {}}
    except Exception:
        log = {"entries": [], "counts": {}}
    items = quality.classify(reason)
    entry = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "title": article.get("title", ""),
        "keyword": article.get("keyword", ""),
        "category": article.get("category", ""),
        "reason": reason,
        "codes": [c["code"] for c in items],
        "kind": "discard" if quality.is_discard(reason) else "retry",
    }
    log.setdefault("entries", []).append(entry)
    log["entries"] = log["entries"][-1000:]          # 너무 커지지 않게 최근 1000건만
    counts = log.setdefault("counts", {})
    for c in items:
        counts[c["code"]] = counts.get(c["code"], 0) + 1
    log["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    # 가장 많이 걸리는 사유 = 로직을 고쳐야 할 지점
    log["top"] = sorted(counts.items(), key=lambda kv: -kv[1])[:5]
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        json.dump(log, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[품질로그] 기록 실패: {e}")


def _run_category(cfg, cat, hist, auto_publish, img_budget=None):
    """한 카테고리에 대해 슬롯 계획대로 글을 생성해 리스트로 반환."""
    name = cat["name"]
    blog_url = cfg.get("blog_url", "") or cfg.get("site", {}).get("blog_url", "")
    insert_ads = cfg.get("ads", {}).get("insert_slots", True)
    author = cfg.get("author") or "편집부"
    author_bio = cfg.get("author_bio") or ""
    author_type = cfg.get("author_type") or "Organization"
    wp_cfg = cfg.get("wordpress", {})
    resolver = make_image_resolver(cfg, auto_publish, name, img_budget)

    # 이 카테고리의 과거 글만으로 중복방지 + 내부링크
    cat_hist = [a for a in hist["articles"] if a.get("category") == name]
    exclude = [a["title"] for a in cat_hist] + [a.get("keyword", "") for a in cat_hist]
    related_pool = list(reversed(cat_hist))[:6]

    print(f"\n########## [{name}] ##########")
    slots = _plan_slots(cfg, cat)
    need = {"long": sum(1 for s in slots if s[0] == "long"),
            "season": sum(1 for s in slots if s[0] == "season")}
    topic_q = {}
    for lane in ("long", "season"):
        if need[lane] <= 0:
            continue
        label = "저경쟁 롱테일" if lane == "long" else "시즌 선점"
        print(f"[{label}] 슬롯 {need[lane]}개용 주제 확보…")
        got = collect_lane(cfg, cat, lane, need[lane], exclude)
        topic_q[lane] = got
        print(f"  · 주제:", [t["keyword"] for t in got])
        exclude += [t["keyword"] for t in got]

    # 슬롯 → 작업 목록 구성(주제 배정). 내부링크는 과거 글 기준(병렬 안전).
    related = [{"title": r["title"], "slug": r.get("slug", ""),
                "url": r.get("post_url") or r.get("url", "")} for r in related_pool[:3]]
    jobs = []
    slot_count = {"long": 0, "season": 0}
    for lane, mode, n_parts in slots:
        q = topic_q.get(lane, [])
        if not q:
            continue
        kw = q.pop(0)
        if not kw["keyword"]:
            continue
        slot_count[lane] += 1
        jobs.append((lane, mode, n_parts, kw))

    def gen_job(job):
        lane, mode, n_parts, kw = job
        comp = bool(kw.get("competitive"))
        try:
            if mode == "series":
                print(f"-> [시리즈 {n_parts}편][{lane}]{'[상위노출강화]' if comp else ''} {kw['keyword']}")
                arts = generate_series(kw["keyword"], lane, n_parts, cfg["llm"],
                                       category=name, related=related, blog_url=blog_url,
                                       insert_ads=insert_ads, image_resolver=resolver, author=author,
                                       author_bio=author_bio, author_type=author_type,
                                       competitive=comp)
            else:
                print(f"-> [단일][{lane}]{'[상위노출강화]' if comp else ''} {kw['keyword']}")
                arts = generate_article(kw["keyword"], lane, cfg["llm"],
                                        category=name, related=related, blog_url=blog_url,
                                        insert_ads=insert_ads, image_resolver=resolver, author=author,
                                        author_bio=author_bio, author_type=author_type,
                                        competitive=comp)
        except Exception as e:
            print(f"[오류] '{kw['keyword']}' 글 생성 실패(건너뜀): {e}")
            return []
        for a in arts:
            a["category"] = name
            a["wp_category"] = cat.get("wp_category", name)
            a["wp_category_slug"] = cat.get("wp_slug", "")
            a["volume"] = kw.get("volume")
            a["competition"] = kw.get("competition", "")
            a["steadiness"] = kw.get("steadiness")
            a["interest"] = kw.get("interest")
            a["lane_reason"] = kw.get("lane_reason", "")
        return arts

    # 생성은 병렬(이미지·글 대기시간 겹치기), 게시/저장은 순차(WP 안정)
    workers = max(1, int(cfg.get("perf", {}).get("workers", 3)))
    generated = []
    if workers > 1 and len(jobs) > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for arts in ex.map(gen_job, jobs):
                generated += arts
    else:
        for job in jobs:
            generated += gen_job(job)

    # 품질 게이트: 분량·구조·키워드 스터핑·중복 검사 (같은 실행 글끼리 유사도 비교)
    safety = cfg.get("safety", {}) or {}
    force_draft = safety.get("force_draft", True)
    # 템플릿성 비교용: 최근 생성/발행 글(제목·도입부)
    recent_ref = _recent_for_template(hist, limit=int(safety.get("template_window", 30)))
    for i, a in enumerate(generated):
        others = [b["html"] for j, b in enumerate(generated) if j != i]
        peers = recent_ref + [{"title": b.get("title", ""), "html": b.get("html", "")}
                              for j, b in enumerate(generated) if j < i]
        ok, reason = quality.check(a, others, safety, recent=peers)
        a["quality"] = "통과" if ok else "보류"
        a["quality_reason"] = reason
        # 최신성·정확성 검증(연도/진행상태/불확실 주장) → 문제 있으면 '글을 다시 씀'
        try:
            hold, summ = accuracy.check(a, chat, cfg.get("llm", {}), safety)
            a["accuracy_summary"] = summ
            # 점검에서 끝내지 않고 실제 재작성(자동). safety.auto_revise=false면 표시만.
            auto_revise = safety.get("auto_revise", True) and str(safety.get("verify_accuracy", "flag")).lower() != "off"
            if auto_revise and (a.get("accuracy") in ("warn", "stale") or a.get("accuracy_issues")):
                if accuracy.revise(a, chat, cfg.get("llm", {})):
                    print(f"  · 최신성 재작성 완료: {a['keyword']}")
                    # 재작성 후 다시 점검해 상태 갱신
                    hold, summ = accuracy.check(a, chat, cfg.get("llm", {}), safety)
                    a["accuracy_summary"] = summ
                    # 재작성으로 분량 등이 바뀌었을 수 있어 품질도 재확인
                    others2 = [b["html"] for b in generated if b is not a]
                    ok2, reason2 = quality.check(a, others2, safety)
                    a["quality"] = "통과" if ok2 else "보류"
                    a["quality_reason"] = reason2
            if hold and a["quality"] == "통과":
                a["quality"] = "보류"
                a["quality_reason"] = (a.get("quality_reason") or "") + ("; " if a.get("quality_reason") else "") + "최신성 문제(" + summ + ")"
        except Exception as e:
            print(f"  · 정확도 검증/재작성 건너뜀: {e}")

    # 폐기 직전 구제(2026-09-01): '보류' 글을 버리기 전에 감점 사유를 명시한 보강 재작성 1회.
    # 실측 계기: 9/1 아침 글이 '실전신호없음' 하나로 폐기돼 그날 새 글이 0편이 됐다.
    # 서버 점검·수리(daily_check_fix)의 재작성 루틴이 평균 96점을 검증했으므로 같은 패턴을
    # 생성 단계에도 적용한다. 주제 중복(discard)은 고쳐도 또 겹치므로 구제하지 않는다.
    for a in generated:
        # 버그 수정(2026-09-02 실측): is_discard()는 '사유가 있으면 무조건 True'라
        # 보류 글 전부가 구제 대상에서 빠져 이 루프가 데드 코드였다(픽담 연속 폐기로 발견).
        # 구제 제외는 원래 의도대로 '주제 중복'만 — 중복은 다시 써도 또 겹친다.
        _rsn = a.get("quality_reason", "") or ""
        if a.get("quality") != "보류" or ("중복" in _rsn or "유사" in _rsn):
            continue
        try:
            import re as _re
            fix_prompt = (
                "아래 한국어 블로그 글 HTML을 같은 주제로 다시 쓰세요. 반드시 고칠 것:\n"
                f"- 현재 감점 사유: {a.get('quality_reason','')}\n"
                "- 자주 나는 실수·실패 시나리오·조건 분기(예: '벽이 석고보드라면 A, 콘크리트라면 B')·"
                "방법 2가지 장단 비교 중 3개 이상 포함 (겪지 않은 1인칭 경험담은 창작 금지)\n"
                "- 실측형 수치 4개 이상(규격·가격대·시간·개수). 원문에 없는 수치는 범위로\n"
                "- 분량 절대 기준: 본문 텍스트 1,800자 이상(원문이 짧아도 반드시 늘릴 것), H2 소제목 4개 이상\n"
                "- 소제목(h2/h3)·이미지·광고 자리(<div class=\"ad-slot\">)는 그대로 유지\n"
                "[출력] 순수 HTML 본문만. 코드블록 금지. <p>로 시작.\n\n[원문]\n" + a.get("html", ""))
            neo = chat(fix_prompt, cfg["llm"], max_tokens=16000, temperature=0.7)
            neo = _re.sub(r"^```html?\s*|\s*```$", "", (neo or "").strip())
            if neo and neo.lstrip().startswith("<"):
                trial = dict(a); trial["html"] = neo
                ok3, reason3 = quality.check(trial, [b["html"] for b in generated if b is not a], safety)
                if ok3:
                    a["html"] = neo
                    a["quality"], a["quality_reason"] = "통과", ""
                    print(f"  · 폐기 구제(보강 재작성 1회): {a['keyword']}")
                else:
                    print(f"  · 구제 실패(여전히 보류: {reason3}): {a['keyword']}")
        except Exception as e:
            print(f"  · 구제 재작성 건너뜀: {e}")

    # 드립(분산) 발행: 한 번에 다 올리지 않고 '랜덤 간격'으로 시간차 예약
    drip_min = float(safety.get("drip_min_hours", 0) or 0)
    drip_max = float(safety.get("drip_max_hours", 0) or 0)
    _legacy = float(safety.get("drip_hours", 0) or 0)   # 하위호환(고정 간격)
    if drip_max <= 0 and _legacy > 0:
        drip_min = drip_max = _legacy
    if drip_min <= 0:
        drip_min = drip_max
    drip_i = 0
    drip_offset = 0.0        # 누적 시간(시간 단위)
    for a in generated:      # 제휴 삽입(설정 시): 애드센스 슬롯과 겹치지 않게 각각 다른 위치에
        _apply_coupang(a, cfg)      # 쿠팡: 2번째 소제목 앞
        _apply_affiliate(a, cfg)    # 제휴 SaaS: 3번째 소제목 앞
    out = []
    for a in generated:
        if auto_publish and a["quality"] == "통과":
            # 초안 강제: 사람이 검토 후 발행(대량 자동 발행 방지)
            wp = dict(wp_cfg, status="draft") if force_draft else wp_cfg
            scheduled = False
            if not force_draft and drip_max > 0:
                from datetime import datetime as _dt, timedelta as _td
                if drip_i > 0:                      # 첫 글은 즉시, 이후는 랜덤 간격 누적
                    drip_offset += random.uniform(drip_min, drip_max)
                a["_schedule_date"] = (_dt.now() + _td(hours=drip_offset)).isoformat()
                scheduled = drip_i > 0
                drip_i += 1
            url = publish_to_wordpress(a, wp)
            if not url:
                a["status"] = "게시실패"
            elif force_draft:
                a["status"] = "초안저장됨"
            elif scheduled:
                a["status"] = "예약발행"
            else:
                a["status"] = "게시됨"
            a["post_url"] = url or ""
        elif auto_publish and a["quality"] == "보류":
            # 보류 사유를 두 갈래로 나눈다.
            #   discard(주제 중복) = 고쳐도 또 겹침 → 즉시 폐기, 다시 쓰지 않음
            #   retry(분량·구조·템플릿) = 고쳐서 다시 쓸 수 있음 → 재생성 대기
            # 운영 방침: 품질 게이트에 걸린 글은 사유를 불문하고 즉시 폐기한다.
            # (사유는 quality_log.json에 남겨 생성 로직을 고치는 근거로만 쓴다)
            reason = a.get("quality_reason", "")
            _log_hold(cfg, a, reason)
            a["hold_detail"] = quality.classify(reason)
            a["status"] = "폐기"
            a["discarded"] = True
            a["post_url"] = ""
            # 이미 워드프레스에 초안이 올라갔다면 휴지통으로 보낸다(복구 가능)
            if a.get("post_id") and wp_cfg.get("enabled"):
                if trash_post(wp_cfg, a["post_id"]):
                    a["trashed"] = True
                    print(f"  · 폐기 → 워드프레스 휴지통: {a['keyword']} — {reason}")
                else:
                    print(f"  · 폐기(휴지통 이동 실패, 수동 확인 필요): {a['keyword']} — {reason}")
            else:
                print(f"  · 폐기: {a['keyword']} — {reason}")
        else:
            a["status"] = "복붙대기"
            a["post_url"] = ""
        a["copy_file"] = save_copy_html(a)
        out.append(a)
    print(f"  → [{name}] 슬롯 {sum(slot_count.values())}건 · 글 {len(out)}편"
          f"(폐기 {sum(1 for a in out if a.get('status')=='폐기')}편 · "
          f"휴지통 {sum(1 for a in out if a.get('trashed'))}편)")
    return out


def _apply_coupang(a, cfg):
    """쿠팡 파트너스(API 불필요): 위젯 + 필수 고지문을 삽입.
    - 위젯은 '본문 중간'(2번째 소제목 뒤)에 넣어 전환율을 높인다(하단은 CTR 낮음).
    - 고지문은 글 첫 부분 규정 준수를 위해 위젯 바로 앞에 함께 붙인다.
    - 애드센스 슬롯([[AD]])과 위치가 겹치지 않게 독립적으로 배치된다.
    """
    c = cfg.get("coupang", {}) or {}
    if not c.get("enabled"):
        return
    widget = ""
    if c.get("widget_html"):
        widget = f'<div class="coupang-widget" style="margin:22px 0;text-align:center">{c["widget_html"]}</div>'
    notice = ""
    if c.get("disclosure", True):
        notice = ('<p class="coupang-notice" style="font-size:12px;color:#98a2b3;margin:10px 0 4px;'
                  'padding:8px 12px;background:#fafbfc;border-left:3px solid #ff5a5f">'
                  '이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.</p>')
    block = notice + widget
    if not block:
        return
    html = a.get("html", "") or ""
    # 본문 중간(2번째 <h2> 앞) 삽입 → 없으면 하단 append
    a["html"] = _insert_mid_body(html, block, nth_h2=2)


def _insert_mid_body(html, block, nth_h2=2):
    """<h2> 기준으로 본문 중간에 block을 끼워 넣는다(실패 시 하단 append)."""
    import re as _re
    idxs = [m.start() for m in _re.finditer(r"<h2\b", html)]
    if len(idxs) >= nth_h2:
        pos = idxs[nth_h2 - 1]           # nth번째 h2 '앞'에 삽입
        return html[:pos] + block + html[pos:]
    return html + block


def _apply_affiliate(a, cfg):
    """제휴 SaaS(쿠팡 외 일반 제휴): '추천 도구' 박스 + 고지문을 본문 중간에 삽입.
    - links: [{"name","url","desc"}] 목록을 카드형 박스로 렌더.
    - 링크는 rel='sponsored nofollow'(검색엔진 정책 준수).
    - 3번째 소제목 앞에 넣어 쿠팡(2번째)·애드센스 슬롯과 위치가 겹치지 않게 한다.
    """
    c = cfg.get("affiliate", {}) or {}
    if not c.get("enabled"):
        return
    links = [l for l in (c.get("links") or []) if l.get("url") and l.get("name")]
    if not links:
        return
    title = html_mod.escape(c.get("box_title") or "이 글에서 소개한 도구")
    items = ""
    for l in links:
        name = html_mod.escape(str(l.get("name", "")))
        url = html_mod.escape(str(l.get("url", "")), quote=True)
        desc = html_mod.escape(str(l.get("desc", "")))
        items += (
            f'<li style="margin:8px 0"><a href="{url}" target="_blank" '
            f'rel="sponsored nofollow noopener" style="font-weight:700;color:#2563eb;text-decoration:none">'
            f'{name} →</a>{(" — " + desc) if desc else ""}</li>')
    notice = ""
    if c.get("disclosure", True):
        notice = ('<p style="font-size:12px;color:#98a2b3;margin:0 0 6px">'
                  '※ 이 글에는 제휴 링크가 포함되어 있으며, 링크를 통해 가입·구매 시 '
                  '일정액의 수수료를 받을 수 있습니다(구매자 추가 부담 없음).</p>')
    box = (f'<div class="affiliate-box" style="margin:22px 0;padding:16px 18px;'
           f'border:1px solid #e5e7eb;border-radius:12px;background:#fafbfc">'
           f'<div style="font-weight:800;margin-bottom:6px">{title}</div>'
           f'{notice}<ul style="margin:6px 0 0;padding-left:18px">{items}</ul></div>')
    a["html"] = _insert_mid_body(a.get("html", "") or "", box, nth_h2=3)


def _kw_set(s):
    import re as _re
    return set(w for w in _re.findall(r"[가-힣A-Za-z0-9]+", str(s or "")) if len(w) > 1)


def _relink_old_posts(new_articles, hist, wp_cfg):
    """이번에 새로 쓴 글과 '같은 주제'인 과거 발행글을 찾아, 옛 글 상단에 최신글 링크 배너를 단다."""
    olds = [h for h in hist.get("articles", []) if h.get("post_id") and h.get("url")]
    if not olds:
        return
    done = 0
    for a in new_articles:
        if not a.get("post_url") or not a.get("post_id"):
            continue
        ka = _kw_set(a.get("keyword", ""))
        if not ka:
            continue
        linked = 0
        for h in olds:
            if h.get("category") != a.get("category"):
                continue
            kb = _kw_set(h.get("keyword", ""))
            if not kb:
                continue
            sim = len(ka & kb) / len(ka | kb)
            # 주제가 겹치면 옛 글 상단에 새 글 링크를 단다.
            # 제도·정책이 바뀌면 표현이 달라져 완전 일치하지 않으므로 기준을 55%로 둔다.
            if sim >= 0.55 and h.get("post_id") != a.get("post_id"):
                if add_update_banner(wp_cfg, h["post_id"], a["post_url"], a["title"]):
                    done += 1
                    linked += 1
                    if linked >= 3:      # 한 새 글이 옛 글 3개까지 갱신 표시
                        break
    if done:
        print(f"  · 예전글 {done}건에 최신글 링크 배너 추가")


STATUS_FILE = os.path.join(DASH_DATA, "status.json")
FREE_LLM_DAILY = 1000        # 무료 티어 하루 호출 여유(대략)
USD_KRW = 1400               # 대략 환율(예상비용 표시용)
IMAGEN_USD = 0.02            # 유료 이미지 1장(Imagen Fast)


def _save_status_and_notify(cfg, all_articles, start_t, ok=True, error=""):
    """헬스체크 + 사용량/비용 집계를 status.json 에 병합 저장하고 텔레그램 알림."""
    from datetime import date
    snap = monitor.snapshot()
    # 기존 status 로드(누적 유지)
    prev = {}
    try:
        with open(STATUS_FILE, encoding="utf-8") as f:
            prev = json.load(f)
    except Exception:
        prev = {}

    # 헬스: 이전 성공시각 + 이번 성공시각 병합
    health = dict(prev.get("health", {}))
    for name, ts in snap["marks"].items():
        health[name] = {"last_ok": ts}

    # 사용량 월 누적(월 바뀌면 리셋)
    month = date.today().strftime("%Y-%m")
    usage = prev.get("usage", {})
    if usage.get("month") != month:
        usage = {"month": month, "llm_calls": 0, "image_paid": 0, "image_free": 0}
    usage["llm_calls"] += snap["llm_calls"]
    usage["image_paid"] += snap["image_paid"]
    usage["image_free"] += snap["image_free"]
    cost_krw = int(usage["image_paid"] * IMAGEN_USD * USD_KRW)   # 텍스트는 무료 티어 가정=0

    # 어떤 연동이 '오늘 기대됐는데 실패'인지
    today = monitor.now_kst()[:10]
    expected = ["gemini"]
    if str(cfg.get("metrics", {}).get("provider")) == "naver":
        expected.append("naver")
    if cfg.get("wordpress", {}).get("enabled"):
        expected.append("wordpress")
    health_bad = [n for n in expected
                  if not str(health.get(n, {}).get("last_ok", "")).startswith(today)]

    published = sum(1 for a in all_articles if a.get("status") == "게시됨")
    draft = sum(1 for a in all_articles if a.get("status") == "초안저장됨")
    held = sum(1 for a in all_articles if a.get("quality") == "보류")
    stats = {
        "at": monitor.now_kst(), "ok": ok and not error,
        "articles": len(all_articles), "published": published, "draft": draft,
        "held": held, "failed": 0 if ok else 1,
        "duration_s": int(time.time() - start_t),
        "cost": {"month_krw": cost_krw, "llm_calls": usage["llm_calls"]},
        "health_bad": health_bad,
        "image_errors": IMG_ERRS[-5:],   # 이미지 실패가 조용히 사라지지 않게(2026-08-30)
    }

    status = {
        "updated_at": monitor.now_kst(),
        "last_run": stats,
        "health": health,
        "usage": {**usage, "est_cost_krw": cost_krw,
                  "free_llm_daily": FREE_LLM_DAILY,
                  "llm_today": snap["llm_calls"]},
    }
    try:
        os.makedirs(DASH_DATA, exist_ok=True)
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(status, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[status] 저장 실패: {e}")

    # 텔레그램 알림
    if error:
        notify.send(cfg, f"⛔ <b>Scripto 실행 실패</b>\n🕖 {monitor.now_kst()}\n{str(error)[:400]}")
    else:
        notify.send(cfg, notify.run_summary(cfg, stats))
    if snap["llm_calls"] >= FREE_LLM_DAILY * 0.8:
        notify.send(cfg, f"⚠️ 오늘 LLM 호출 {snap['llm_calls']}회 — 무료 한도({FREE_LLM_DAILY}) 근접")
    return status


def _refresh_old_posts(cfg, hist, wp_cfg):
    """오래된 발행글을 주기적으로 최신화(옛 정보 → 현재 기준으로 다시 씀)."""
    from datetime import datetime as _dt
    safety = cfg.get("safety", {}) or {}
    days = int(safety.get("refresh_days", 0) or 0)
    if days <= 0:
        return
    maxn = int(safety.get("refresh_max_per_run", 2) or 2)
    today = _dt.now().date()
    cands = []
    for h in hist.get("articles", []):
        if not h.get("post_id"):
            continue
        # 마지막 최신화(또는 최초 발행)로부터 days 이상 지난 글
        base = h.get("last_refreshed") or h.get("date")
        try:
            d0 = _dt.strptime(str(base)[:10], "%Y-%m-%d").date()
        except Exception:
            continue
        if (today - d0).days >= days:
            cands.append(h)
    cands = cands[:maxn]
    done = 0
    for h in cands:
        post = get_post(wp_cfg, h["post_id"])
        if not post or not post.get("html"):
            continue
        art = {"html": post["html"], "title": post.get("title", ""),
               "focus_keyword": h.get("keyword", "")}
        accuracy.check(art, chat, cfg.get("llm", {}), safety)
        if accuracy.revise(art, chat, cfg.get("llm", {})):
            if update_post_content(wp_cfg, h["post_id"], art["html"]):
                h["last_refreshed"] = today.strftime("%Y-%m-%d")
                done += 1
    if done:
        print(f"  · 오래된 글 {done}편 최신화 완료(주기 {days}일)")


def run():
    start_t = time.time()
    cfg = load_config()

    # 승인 후 수익 최적화(광고 3개 등)는 '애드센스 승인됨'일 때만 적용
    _approved = bool(cfg.get("adsense_approved"))
    _rev = cfg.get("revenue", {}) or {}
    import generator as _gen
    _gen.ADS_BOOST = _approved and bool(_rev.get("ads_boost", True))
    # v1.1 픽 라인: 이 사이트가 쿠팡 트랙이면 생성 프롬프트를 구매의도형으로 전환
    _gen.COMMERCE_MODE = (cfg.get("track") == "coupang")
    if _gen.COMMERCE_MODE:
        print("[트랙] 🛒 픽 라인(쿠팡) — 커머스 모드로 생성합니다")

    # 일시정지: 매일 자동 생성을 꺼둔 상태면 아무것도 하지 않고 종료(초안 안 쌓임, API 호출 0)
    if cfg.get("paused"):
        print("⏸️ 자동 생성 일시정지 상태 — 오늘 생성을 건너뜁니다.")
        try:
            notify.send(cfg, "⏸️ Scripto 일시정지 상태 — 오늘 자동 생성을 건너뛰었습니다.")
        except Exception:
            pass
        return

    wp_cfg = cfg.get("wordpress", {})
    auto_publish = wp_cfg.get("enabled", False)
    cats = get_categories(cfg)

    print(f"=== {datetime.now():%Y-%m-%d %H:%M} 수익형 글 생성 시작 · 카테고리 {len(cats)}개 ===")

    # --- LLM 사전 점검: 키/모델이 유효한지 먼저 확인(문제 시 명확히 실패) ---
    lcfg = cfg.get("llm", {})
    if not lcfg.get("api_key") or "여기에" in str(lcfg.get("api_key")):
        raise SystemExit("[치명적] LLM api_key 가 비어 있습니다. GitHub 시크릿 LLM_API_KEY 를 확인하세요.")
    try:
        t = chat("한 단어로 'OK' 만 답하세요.", lcfg, max_tokens=8, temperature=0)
        print(f"[preflight] LLM OK (provider={lcfg.get('provider')}, model={lcfg.get('model')}) → {str(t)[:30]!r}")
    except Exception as e:
        print("=" * 64)
        print("[치명적] LLM 호출 실패 — 키 또는 모델명을 확인하세요.")
        print(f"  provider={lcfg.get('provider')}  model={lcfg.get('model')}")
        print(f"  오류: {e}")
        print("  힌트: 모델을 'gemini-2.5-flash' → 'gemini-1.5-flash' 로 바꿔보거나,")
        print("        LLM_API_KEY 가 올바른 Gemini API 키(AIza...)인지 확인하세요.")
        print("=" * 64)
        raise SystemExit(1)

    hist = load_history()

    # 성과·수익 실측 연동(선택) → insights.json 저장 + 잘 되는 주제를 다음 주제 선정에 반영
    try:
        ins = insights.collect(cfg)
        if ins:
            os.makedirs(DASH_DATA, exist_ok=True)
            with open(os.path.join(DASH_DATA, "insights.json"), "w", encoding="utf-8") as f:
                json.dump(ins, f, ensure_ascii=False, indent=2)
            cfg["_insight_hints"] = insights.winner_topics(ins)
            if cfg["_insight_hints"]:
                print(f"[insights] 성과 피드백 반영: {cfg['_insight_hints'][:5]}")
    except Exception as e:
        print(f"[insights] 건너뜀: {e}")

    # 이미지 비용 상한: 실행 1회당 최대 개수(카테고리 합산)
    img_budget = {"used": 0, "max": int(cfg.get("images", {}).get("max_per_run", 10 ** 9))}

    # 승인→수익 램프: 단계에 맞춰 광고·발행량·깊이를 config에 덮어쓴다
    ramp.apply_to_config(cfg)
    _bias = cfg.get("_ramp_intent_bias", "auto")

    # 주제 전환 완충 — 새 주제가 하루아침에 물량을 차지하지 못하게 한다
    cats, _tnotes = _theme_guard(cats, hist, cfg.get("_ramp_topic_width"))
    for _tn in _tnotes:
        print(f"[주제 완충] {_tn}")
    try:  # 전략 탭이 전환 진행률을 보여줄 수 있게 남긴다
        _shift = {"at": datetime.now().isoformat(timespec="seconds"),
                  "notes": _tnotes,
                  "maturity": [{"category": c["name"],
                                "published": sum(1 for a in hist["articles"] if a.get("category") == c["name"]),
                                "daily_cap": c.get("_daily_cap")} for c in cats]}
        os.makedirs(DASH_DATA, exist_ok=True)
        with open(os.path.join(DASH_DATA, "theme_shift.json"), "w", encoding="utf-8") as f:
            json.dump(_shift, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[주제 완충] 상태 기록 건너뜀: {e}")

    # 오늘의 의도 배분(strategy.json 기반). 수익형/누적형을 요일별로 다르게 쓴다.
    _plan = strategy.load_plan()
    _todo = strategy.today_intents(_plan)
    # 램프 단계가 의도를 강제하면(승인 준비·전환 초기) 그쪽을 우선한다
    _ppd = int(cfg.get("_ramp_posts_per_day", 5))
    if _bias == "evergreen":
        _todo = {"revenue": 0, "evergreen": _ppd}
    elif _bias == "revenue":
        _todo = {"revenue": max(1, _ppd - 1), "evergreen": 1}
    elif _bias == "balanced":
        _todo = {"revenue": _ppd // 2, "evergreen": _ppd - _ppd // 2}
    _order = (["revenue"] * _todo.get("revenue", 0)) + (["evergreen"] * _todo.get("evergreen", 0))
    random.shuffle(_order)                      # 같은 의도가 몰려 보이지 않게 섞는다
    cfg["_intent_queue"] = _order
    print(f"[전략] 오늘 계획 — 수익형 {_todo.get('revenue',0)}편 · 누적형 {_todo.get('evergreen',0)}편"
          f" (기준 {_plan.get('data_status')})")
    if _plan.get("winners"):
        cfg["_insight_hints"] = _plan["winners"]

    all_articles = []
    for cat in cats:
        if not cat["name"]:
            continue
        if not _category_active_today(cat):
            print(f"[건너뜀] '{cat['name']}' — 오늘은 격일 휴무일(active_days={cat.get('active_days')})")
            continue
        q = cfg.get("_intent_queue") or []
        cfg["_today_intent"] = q.pop(0) if q else "evergreen"
        print(f"  · 의도: {'수익형' if cfg['_today_intent']=='revenue' else '누적형'}")
        try:
            all_articles += _run_category(cfg, cat, hist, auto_publish, img_budget)
        except Exception as e:
            import traceback
            print(f"[오류] '{cat['name']}' 카테고리 생성 실패(건너뜀): {e}")
            traceback.print_exc()

    # 예전글 → 최신글 링크: 이번에 발행한 글이 과거 글을 대체하면 옛 글 상단에 배너 추가
    if cfg.get("safety", {}).get("relink_old") and auto_publish:
        _relink_old_posts(all_articles, hist, wp_cfg)

    # 오래된 글 정기 리프레시(주기 설정 시): 옛 정보를 현재 기준으로 다시 씀
    if auto_publish:
        try:
            _refresh_old_posts(cfg, hist, wp_cfg)
        except Exception as e:
            print(f"  · 글 리프레시 건너뜀: {e}")

    today = datetime.now().strftime("%Y-%m-%d")
    for a in all_articles:
        hist["articles"].append({
            "title": a["title"], "slug": a.get("slug", ""), "url": a.get("post_url", ""),
            "post_id": a.get("post_id"), "status": a.get("status", ""),
            "kind": a["kind"], "keyword": a["keyword"], "category": a.get("category", ""),
            "intent": a.get("intent") or strategy.classify_intent(f"{a.get('title','')} {a.get('keyword','')}"),
            "date": today, "series_id": a.get("series_id", ""),
        })
    save_history(hist)
    log_rows(all_articles, cfg.get("sheets"))
    try:
        supabase_client.sync_backlog(cfg, all_articles, source="daily_run")
    except Exception as e:
        print(f"[supabase] 동기화 건너뜀: {e}")

    # 네이버·빙에 새 글 즉시 등록(IndexNow). 실제 '게시됨'(공개) 글만, 키가 있을 때만.
    inkey = wp_cfg.get("indexnow_key")
    if inkey:
        pub_urls = [a.get("post_url") for a in all_articles
                    if a.get("post_url") and a.get("status") == "게시됨"]
        if pub_urls:
            submit_indexnow(pub_urls, inkey, wp_cfg.get("site_url", ""),
                            key_location=wp_cfg.get("indexnow_key_location"))
        else:
            print("  · IndexNow: 공개 게시된 글이 없어 건너뜀(초안은 색인 대상 아님)")

    # 카테고리별 집계
    from collections import Counter
    per_cat = Counter(a.get("category", "") for a in all_articles)

    os.makedirs(DASH_DATA, exist_ok=True)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "categories": [c["name"] for c in cats],
        "auto_publish": auto_publish,
        "per_category": dict(per_cat),
        "total_all": len(hist["articles"]),
        "articles": all_articles,
    }
    for p in (os.path.join(DASH_DATA, f"{today}.json"), os.path.join(DASH_DATA, "latest.json")):
        with open(p, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    n_series = len({a.get("series_id") for a in all_articles if a.get("series_id")})
    print(f"\n=== 완료: 카테고리 {len(cats)}개 · 실제 글 {len(all_articles)}편"
          f"(시리즈 {n_series}개) · 전체 누적 {len(hist['articles'])}편 ===")

    # 운영 안전망: 헬스체크·비용 저장 + 텔레그램 알림
    _save_status_and_notify(cfg, all_articles, start_t, ok=True)


if __name__ == "__main__":
    _start = time.time()
    try:
        run()
    except SystemExit:
        raise
    except Exception as e:
        # 예기치 못한 실패도 텔레그램으로 알림
        import traceback
        traceback.print_exc()
        try:
            _save_status_and_notify(load_config(), [], _start, ok=False, error=str(e))
        except Exception:
            pass
        raise
