# -*- coding: utf-8 -*-
"""제목 격차 찾기 (2026-11-23 신설) — 네이버에서 실제로 들어오는 검색어가 **글 제목에 들어 있는지** 대조한다.

왜 만들었나
  픽담 실측(11/23): 노출 5,483을 받는 글 5편의 CTR 이 0.3~0.4% 였다. 원인을 손으로 찾아보니
  들어오는 말이 제목에 없었다 — 「통돌이 삶음 기능」으로 81번 노출되는데 제목엔 '통돌이'가 없고,
  「콘센트형 센서등」으로 93번 노출되는데 제목엔 '콘센트형'이 없었다. 그 대조를 기계가 하게 한다.

하는 일 (읽기 전용 — 글을 고치지 않는다)
  1) data/naver_seed_keywords.json 의 유입 검색어를 읽는다(서치어드바이저에서 사람이 옮긴 값)
  2) 워드프레스 공개 REST 로 발행 글의 제목·본문을 읽는다(인증·키 불필요)
  3) 검색어마다 담당 글을 찾고(post_id 가 적혀 있으면 그것, 없으면 본문에 그 말이 가장 많이 든 글)
  4) 그 말이 제목에 얼마나 들어 있는지 잰다 → 글별로 '제목에 없는 유입 노출'을 합산해 순서를 매긴다
  새 제목 문장은 여기서 만들지 않는다. 기계가 끼워 넣은 제목은 읽기 나쁘다 —
  이 표를 보고 사람이(또는 세션이) 문장을 쓰고, 사용자 승인 뒤 각 레포의 제목 교체 경로로 넣는다.

환경변수  SITE_DOMAIN(없으면 BLOG_URL·WP_SITE·config.json) · GAP_MIN_IMPR(기본 5)
다른 레포에 그대로 복사해 쓴다. 의존: requests, naver_hub.py(문자열 정리 함수만).
"""
import datetime as dt
import html
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests

import naver_hub as nh

OUT_JSON = os.path.join("dashboard", "data", "naver_title_gap.json")
OUT_MD = os.path.join("data", "naver_title_gap.md")


def _load(path):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return None


def site_domain():
    for k in ("SITE_DOMAIN", "BLOG_URL", "WP_SITE"):
        v = (os.getenv(k) or "").strip()
        if v and "your-blog" not in v:
            return nh._host(v)
    cfg = _load("config.json") or {}
    for v in ((cfg.get("wordpress") or {}).get("site_url"), cfg.get("blog_url")):
        if v and "your-blog" not in v:
            return nh._host(v)
    return ""


def norm(s):
    """띄어쓰기·기호를 없앤 소문자. '비데 설치 비용' 과 '비데설치비용' 을 같게 본다."""
    return re.sub(r"[^0-9a-z가-힣]", "", html.unescape(re.sub(r"<[^>]+>", " ", str(s or ""))).lower())


def grams(s):
    s = norm(s)
    return {s[i:i + 2] for i in range(len(s) - 1)} or ({s} if s else set())


def cover(keyword, text_grams):
    """검색어의 두 글자 조각 중 몇 %가 text 에 있는가(0~1)."""
    g = grams(keyword)
    return (len(g & text_grams) / len(g)) if g else 0.0


def missing_words(keyword, title):
    """제목에 없는 낱말. 붙여 쓴 검색어('비데설치비용')는 낱말로 못 쪼개므로 빈 목록이 나올 수 있다."""
    t = norm(title)
    return [w for w in re.split(r"\s+", keyword.strip()) if len(norm(w)) >= 2 and norm(w) not in t]


def guess_post(kw, posts):
    """담당 글 추정 — **본문에서 그 말의 낱말이 얼마나 자주, 얼마나 드물게 나오는가**로 고른다.

    2026-11-23 스크립토 실측: 예전 방식(본문에 조각이 들어 있는가 + 제목 가점)은 본문이 길면 거의 모든 글이
    조각을 다 품어 동점이 되고, 결국 제목 낱말 하나('먹통')가 승부를 갈라 엉뚱한 글에 붙었다
    (「휴대폰 터치 먹통」 → 전화 먹통 글). 그래서
      · 낱말마다 본문 등장 횟수를 세고(많을수록 그 글의 주제다)
      · 여러 글에 흔한 낱말('휴대폰')은 낮게, 드문 낱말('터치')은 높게 친다
      · 제목이 검색어의 낱말을 전부 품고 있으면 그 글로 본다(그 경우 격차는 '없음'으로 나온다)
    2차 실측(같은 날): 본문만 보면 「휴대폰 터치 먹통」의 임자(#2688)를 놓친다 — '먹통'이 제목에만 있었다.
    그래서 제목도 본문과 함께 세고, 낱말이 안 맞는 합성어는 두 글자 조각으로 잇는다."""
    import math
    toks = [norm(t) for t in re.split(r"\s+", kw.strip()) if len(norm(t)) >= 2] or [norm(kw)]
    n = len(posts)
    doc = lambda x: x["tt"] + " " + x["bt"]            # 제목도 그 글의 글자다(「터치 먹통」이 제목에만 있는 글이 있었다)
    # 낱말 그대로 + 낱말 안의 두 글자 조각. 조각이 있어야 「알뜰요금제」가 「알뜰폰 요금제」 글을 찾고,
    # 붙여 쓴 「셀프싱크대문교체」도 쪼개진다. 낱말 경계는 넘지 않는다(「폰터」 같은 헛조각 방지).
    units = {}
    for t in toks:
        units[t] = 1.0
        for i in range(len(t) - 1):
            units.setdefault(t[i:i + 2], 0.5)
    df = {u: sum(1 for x in posts if u in doc(x)) for u in units}

    def score(x):
        d = doc(x)
        sc = 0.0
        for u, w in units.items():
            tf = d.count(u)
            if tf:
                sc += w * math.log(1 + tf) * math.log(1 + n / (1 + df[u]))
        if all(t in x["tt"] for t in toks):            # 제목이 검색어의 낱말을 전부 품었다 = 그 글이 맞다
            sc += 3.0
        return sc

    best = max(posts, key=score, default=None)
    return best if (best is not None and score(best) > 0.5) else None


def fetch_posts(domain):
    out, page = [], 1
    while page <= 10:
        r = requests.get(f"https://{domain}/wp-json/wp/v2/posts", timeout=40,
                         params={"per_page": 100, "page": page, "_fields": "id,title,link,content"})
        if r.status_code != 200:
            if page == 1:
                print(f"::warning::글 목록 조회 실패 HTTP {r.status_code}")
            break
        rows = r.json()
        if not isinstance(rows, list) or not rows:
            break
        for p in rows:
            title = html.unescape(re.sub(r"<[^>]+>", "", (p.get("title") or {}).get("rendered") or ""))
            body = (p.get("content") or {}).get("rendered") or ""
            out.append({"id": p.get("id"), "title": title, "link": p.get("link"),
                        "tg": grams(title), "bg": grams(body), "bt": norm(body), "tt": norm(title)})
        if len(rows) < 100:
            break
        page += 1
    return out


def main():
    domain = site_domain()
    seed = _load(os.path.join("data", "naver_seed_keywords.json")) or {}
    kws = [k for k in (seed.get("keywords") or []) if (k.get("keyword") or "").strip()]
    if not domain or not kws:
        print("::warning::도메인 또는 유입 검색어(data/naver_seed_keywords.json)가 없어 건너뜁니다.")
        return 0
    posts = fetch_posts(domain)
    if not posts:
        return 0
    by_id = {p["id"]: p for p in posts}
    min_impr = int(os.getenv("GAP_MIN_IMPR") or 5)
    print(f"도메인 {domain} · 글 {len(posts)}편 · 유입 검색어 {len(kws)}개")

    rows = []
    for k in kws:
        kw, impr, clicks = k["keyword"].strip(), int(k.get("impr") or 0), int(k.get("clicks") or 0)
        p = by_id.get(k.get("post_id"))
        how = "지정"
        if not p:
            best = guess_post(kw, posts)
            if best is not None and cover(kw, best["bg"] | best["tg"]) >= 0.6:
                p, how = best, "추정"
        if not p:
            rows.append({"keyword": kw, "impr": impr, "clicks": clicks, "post_id": None,
                         "verdict": "담당 글 불명", "cover": None})
            continue
        c = cover(kw, p["tg"])
        rows.append({"keyword": kw, "impr": impr, "clicks": clicks, "post_id": p["id"], "matched": how,
                     "title": p["title"], "link": p["link"], "cover": round(c, 2),
                     "verdict": "제목에 있음" if c >= 0.8 else ("일부만" if c >= 0.4 else "제목에 없음"),
                     "missing": missing_words(kw, p["title"])})

    posts_out = {}
    for r in rows:
        if r["post_id"] is None:
            continue
        o = posts_out.setdefault(r["post_id"], {"post_id": r["post_id"], "title": r["title"], "link": r["link"],
                                                "impr": 0, "clicks": 0, "gap_impr": 0, "gap_keywords": []})
        o["impr"] += r["impr"]
        o["clicks"] += r["clicks"]
        if r["cover"] < 0.8 and r["impr"] >= min_impr:
            o["gap_impr"] += r["impr"]
            o["gap_keywords"].append({"keyword": r["keyword"], "impr": r["impr"], "cover": r["cover"],
                                      "missing": r["missing"]})
    ranked = sorted(posts_out.values(), key=lambda o: -o["gap_impr"])
    for o in ranked:
        o["gap_keywords"].sort(key=lambda g: -g["impr"])
        o["gap_share"] = round(o["gap_impr"] / o["impr"], 2) if o["impr"] else 0.0
    orphans = [r for r in rows if r["post_id"] is None]

    out = {"at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "site": domain,
           "seed_collected": seed.get("collected"), "posts": ranked, "keywords": rows}
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    json.dump(out, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    todo = [o for o in ranked if o["gap_impr"] > 0]
    L = [f"# 제목 격차 — {out['at']}", "",
         f"도메인 `{domain}` · 유입 검색어 {len(kws)}개(수집 {seed.get('collected', '?')}) · 대조한 글 {len(ranked)}편",
         "", f"**제목을 손볼 글 {len(todo)}편** — 들어오는 말이 제목에 없는 노출이 큰 순서", ""]
    if todo:
        L += ["| 글 | 지금 제목 | 제목에 없는 유입어(노출) | 그 노출 합 | 비중 |", "|---|---|---|---:|---:|"]
        for o in todo:
            gk = " · ".join(f"{g['keyword']}({g['impr']})" for g in o["gap_keywords"][:4])
            L.append(f"| #{o['post_id']} | {o['title'][:44]} | {gk} | {o['gap_impr']} | {int(o['gap_share'] * 100)}% |")
    else:
        L.append("없음 — 유입 검색어가 전부 제목에 들어 있습니다.")
    if orphans:
        L += ["", "## 담당 글을 찾지 못한 유입어 — 새 글 후보", "",
              "| 검색어 | 노출 | 클릭 |", "|---|---:|---:|"]
        L += [f"| {r['keyword']} | {r['impr']} | {r['clicks']} |" for r in sorted(orphans, key=lambda x: -x["impr"])]
    L += ["", "> 이 표는 **클릭이 1회 이상 난 검색어**만으로 만든다(서치어드바이저 목록이 클릭순이라서).",
          "> 노출만 많고 클릭이 0인 검색어는 여기 잡히지 않는다."]
    os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
    open(OUT_MD, "w", encoding="utf-8").write("\n".join(L) + "\n")
    for o in todo[:8]:
        print(f"  #{o['post_id']} 격차 노출 {o['gap_impr']} ← " +
              ", ".join(g["keyword"] for g in o["gap_keywords"][:3]))
    print(f"손볼 글 {len(todo)}편 · 담당 글 불명 {len(orphans)}개 · 저장: {OUT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
