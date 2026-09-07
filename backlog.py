"""backlog.py — 초안 백로그를 '주제 재고'로 전환 (#49, 2026-09-07)

원칙(사용자 확정): 옛 초안의 본문은 폐기 대상(구규격 + 시점 경과), **주제 선정만** 자산으로
재활용한다. 재고 주제도 봐주지 않는다 — 신규 주제와 똑같이 전체 검증 체인을 통과해야 발행된다.

- extract(cfg): WP 초안 전량 순회 → 제목을 주제로 정제 → 정적 검증(빈 제목·중복·기발행 유사)
  → dashboard/data/topic_queue.json 적재. 멱등(같은 초안 id는 재적재 안 함).
- draw(category, n, exclude): 매일 생성 때 카테고리별 pending 주제 n개를 꺼내 후보에 합류.
  꺼낸 뒤엔 main의 기존 검증(금지·기업 필터 → 저경쟁/시즌 판별 → 네이버 실측 → 본문 최신성
  검증)을 그대로 거친다. 시점 민감(dated) 주제는 키워드에서 옛 연월을 벗겨 현재 기준으로 넘긴다.
- 케이던스 불변: draw는 후보만 보탤 뿐 발행량을 늘리지 않는다(대량 생산 정책 리스크 차단).
"""
import json
import os
import re

import requests

QUEUE = "dashboard/data/topic_queue.json"
DATED_RE = re.compile(r"20\d{2}\s*년(\s*\d{1,2}\s*월)?|기준|환급|지원금|보조금|혜택|이자율|금리")
YEARMONTH_RE = re.compile(r"\s*20\d{2}\s*년(\s*\d{1,2}\s*월)?\s*")


def _norm(s):
    return re.sub(r"[\s\W]+", "", str(s or "")).lower()


def load_queue():
    try:
        return json.load(open(QUEUE, encoding="utf-8"))
    except Exception:
        return {"topics": [], "extracted_at": ""}


def save_queue(q):
    os.makedirs(os.path.dirname(QUEUE), exist_ok=True)
    json.dump(q, open(QUEUE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def _wp_headers(wp):
    h = {"User-Agent": "Mozilla/5.0 (ScriptoBot)"}
    try:
        from publisher import _auth_header
        h.update(_auth_header(wp["username"], wp["app_password"]))
    except Exception:
        pass
    return h


def extract(cfg):
    """초안 전량에서 주제를 추출해 큐에 적재한다(1회성·멱등·초안은 건드리지 않음)."""
    wp = cfg.get("wordpress", {}) or {}
    if not (wp.get("enabled") and wp.get("site_url")):
        print("[backlog] WP 설정 없음 — 종료"); return None
    base = wp["site_url"].rstrip("/")
    H = _wp_headers(wp)

    # 카테고리 id → 이름
    cat_map = {}
    try:
        r = requests.get(f"{base}/wp-json/wp/v2/categories",
                         headers=H, params={"per_page": 100, "_fields": "id,name"}, timeout=30)
        cat_map = {c["id"]: c["name"] for c in (r.json() if r.ok else [])}
    except Exception as e:
        print(f"[backlog] 카테고리 조회 실패: {e}")

    # 기발행 이력(중복 방지 기준): history.json 제목 + 발행 글 제목
    seen = set()
    try:
        hist = json.load(open("dashboard/data/history.json", encoding="utf-8"))
        for a in hist.get("articles", []):
            seen.add(_norm(a.get("title") or a.get("keyword")))
    except Exception:
        pass

    q = load_queue()
    have = {t["id"] for t in q["topics"]}
    in_queue = {_norm(t["kw"]) for t in q["topics"]}

    added = skipped_dup = page = 0
    while True:
        page += 1
        try:
            r = requests.get(f"{base}/wp-json/wp/v2/posts", headers=H,
                             params={"per_page": 100, "page": page, "status": "draft",
                                     "context": "edit", "_fields": "id,title,categories"},
                             timeout=60)
            if not r.ok:
                break
            batch = r.json()
        except Exception as e:
            print(f"[backlog] 초안 조회 중단(p{page}): {e}"); break
        for it in batch:
            if it["id"] in have:
                continue
            t = it.get("title") or {}
            kw = re.sub(r"<[^>]+>", "", t.get("raw") or t.get("rendered") or "").strip()
            if len(kw) < 8:                       # 정적 검증 ①: 빈약한 제목
                continue
            nk = _norm(kw)
            if nk in seen or nk in in_queue:      # 정적 검증 ②: 기발행·큐 중복
                skipped_dup += 1
                continue
            cat = cat_map.get((it.get("categories") or [0])[0], "")
            q["topics"].append({"id": it["id"], "kw": kw, "cat": cat,
                                "dated": bool(DATED_RE.search(kw)), "st": "pending"})
            in_queue.add(nk); added += 1
        if len(batch) < 100:
            break
    from datetime import datetime
    q["extracted_at"] = datetime.now().isoformat()[:19]
    save_queue(q)
    pend = sum(1 for t in q["topics"] if t["st"] == "pending")
    print(f"[backlog] 추출 +{added} (중복 제외 {skipped_dup}) · 큐 대기 {pend}개")
    return {"added": added, "dup": skipped_dup, "pending": pend}


def draw(category, n, exclude=None):
    """카테고리에 맞는 pending 주제 n개를 꺼낸다(같은 카테고리 우선, 없으면 미분류)."""
    if n <= 0:
        return []
    q = load_queue()
    if not q["topics"]:
        return []
    ex = {_norm(x) for x in (exclude or [])}
    catn = _norm(category)
    picked = []
    for prefer_cat in (True, False):
        for t in q["topics"]:
            if len(picked) >= n:
                break
            if t["st"] != "pending":
                continue
            tc = _norm(t.get("cat"))
            if prefer_cat and tc != catn:
                continue
            if (not prefer_cat) and tc and tc != catn:   # 남의 카테고리 주제는 안 가져간다
                continue
            if _norm(t["kw"]) in ex:
                t["st"] = "dup"; continue
            kw = t["kw"]
            if t.get("dated"):
                # 시점 민감 주제: 옛 연월을 벗겨 '현재 기준 재조사'로 넘긴다(최신성 검증이 마무리)
                kw = YEARMONTH_RE.sub(" ", kw).strip(" ,·-")
            t["st"] = "used"
            picked.append({"keyword": kw, "backlog": True, "src_id": t["id"]})
    if picked:
        save_queue(q)
    return picked


if __name__ == "__main__":
    cfg = json.load(open("config.json", encoding="utf-8"))
    res = extract(cfg)
    tok, chat_id = os.getenv("TELEGRAM_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if res and tok and chat_id:
        try:
            requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                          data={"chat_id": chat_id,
                                "text": (f"📦 스크립토 백로그 주제 추출: +{res['added']}개 "
                                         f"(중복 제외 {res['dup']}) · 대기 {res['pending']}개\n"
                                         "이제 매일 발행분의 절반이 이 재고에서 재검증을 거쳐 나갑니다. "
                                         "옛 초안 본문은 앱 설정 > '초안 전부 휴지통으로'로 정리해도 됩니다.")},
                          timeout=20)
        except Exception:
            pass
