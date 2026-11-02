"""serp_loop.py — 검색 상위노출·클릭 개선 루프 (2026-11-02, 사용자 지시).

"찾고 → 검증하고 → 고치고 → 다시 재는" 순환을 매일 자동으로 돈다. 데이터는 전부 실측(GSC).

① 측정: Search Console 검색어×페이지(28일) — 노출·클릭·CTR·평균 순위
② 진단(페이지별):
   - CTR 미달  : 순위 1~12위인데 노출 대비 클릭이 기대치보다 낮음 → 제목·메타를 '실제 검색어'로 교체
   - 순위 정체 : 8~30위에서 노출이 나는데 그 검색어가 본문에 답으로 없음 → 검색어 Q&A 섹션 보강
   - 무반응    : 발행 21일 지났는데 노출 0 → 보고(통합/보강 후보)
③ 검색어 갭: 노출은 나는데 맞는 글이 없는(순위 15위 밖·제목 불일치) 검색어 → 새 주제 씨앗
   → dashboard/data/query_gaps.json (main.py가 주제 생성 때 최우선으로 씀)
④ 검증(실험 대장): 바꾼 글은 14일 뒤 같은 길이 기간으로 전후 비교 → 좋아지면 유지,
   나빠지면 제목 원복. 결과는 dashboard/data/serp_experiments.json 에 누적(판매용 증거도 됨).

안전장치: 하루 수정 상한 2편, 같은 글은 21일 안에 다시 안 건드림, 노출이 적으면(표본 부족) 손대지 않음,
제목은 상투어(quality._TITLE_CLICHE) 금지·40자 이내·원래 기종명 유지. DRY=1 이면 계획만 출력.
"""
import base64
import json
import os
import re
import sys
from datetime import date, datetime, timedelta

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import insights  # noqa: E402
from llm import chat  # noqa: E402

DATA = "dashboard/data"
EXP = f"{DATA}/serp_experiments.json"
OUT = f"{DATA}/serp_loop.json"
GAPS = f"{DATA}/query_gaps.json"
DRY = os.getenv("SERP_DRY", "") in ("1", "true")
MAX_ACT = int(os.getenv("SERP_MAX_ACTIONS", "2"))
COOLDOWN = 21
EVAL_AFTER = 14
# 순위별 기대 CTR(보수적 하한, 업계 공개 곡선의 대략값 — 절대값보다 '미달 여부' 판정용)
EXPECTED = [(1, .20), (2, .12), (3, .08), (5, .05), (10, .025), (12, .012)]


def _exp_ctr(pos):
    for p, c in EXPECTED:
        if pos <= p:
            return c
    return 0.005


def _load(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def _save(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(obj, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def gsc_rows(icfg, creds, start, end, dims, page=None, limit=1000):
    svc = insights._build("searchconsole", "v1", creds)
    body = {"startDate": start.isoformat(), "endDate": end.isoformat(),
            "dimensions": dims, "rowLimit": limit}
    if page:
        body["dimensionFilterGroups"] = [{"filters": [{"dimension": "page", "operator": "equals",
                                                       "expression": page}]}]
    r = svc.searchanalytics().query(siteUrl=icfg["sc_site_url"], body=body).execute()
    return r.get("rows", [])


def page_stats(icfg, creds, page, start, end):
    rows = gsc_rows(icfg, creds, start, end, ["page"], page=page, limit=1)
    if not rows:
        return {"impr": 0, "clicks": 0, "ctr": 0.0, "pos": 0.0}
    r = rows[0]
    return {"impr": r.get("impressions", 0), "clicks": r.get("clicks", 0),
            "ctr": round(r.get("ctr", 0), 4), "pos": round(r.get("position", 0), 1)}


def wp_session(cfg):
    wp = cfg.get("wordpress", {}) or {}
    tok = base64.b64encode(f"{wp['username']}:{wp['app_password']}".encode()).decode()
    return wp["site_url"].rstrip("/"), {"Authorization": f"Basic {tok}", "User-Agent": "ScriptoBot"}


def live_posts(base, H):
    out, page = [], 1
    while True:
        r = requests.get(f"{base}/wp-json/wp/v2/posts", headers=H, timeout=30,
                         params={"per_page": 100, "page": page, "status": "publish",
                                 "_fields": "id,link,date,title,content,meta", "context": "edit"})
        if r.status_code != 200:
            break
        b = r.json()
        out += b
        if len(b) < 100:
            break
        page += 1
    return out


def _norm(s):
    return re.sub(r"\s+", "", str(s)).lower()


def _txt(html):
    return re.sub(r"<[^>]+>", " ", html or "")


def new_title(llm, old, queries):
    from quality import _TITLE_CLICHE
    qs = "\n".join(f"- {q} (노출 {i})" for q, i in queries[:5])
    prompt = (f"블로그 글 제목을 검색 클릭률이 오르도록 다시 쓴다.\n현재 제목: {old}\n"
              f"이 글이 실제로 노출된 구글 검색어(많은 순):\n{qs}\n"
              "규칙: ①1위 검색어의 핵심 단어를 제목 앞쪽에 그대로 넣는다 ②40자 이내 ③기종명·대상(부모님 등)은 유지 "
              "④글이 실제로 주는 해결책(몇 단계, 어디 메뉴 등)을 구체적으로 ⑤과장·낚시·'총정리/완벽' 금지 ⑥물음표 남발 금지.\n"
              "제목 한 줄만 출력.")
    t = re.sub(r"\s+", " ", str(chat(prompt, llm, max_tokens=120, temperature=0.4))).strip().strip('"「」')
    t = t.splitlines()[0] if t else ""
    if not (8 <= len(t) <= 48) or any(c in t for c in _TITLE_CLICHE):
        return None
    return t


def new_meta(llm, title, queries):
    prompt = (f"제목: {title}\n관련 검색어: {', '.join(q for q, _ in queries[:3])}\n"
              "검색 결과 설명문(메타 디스크립션)을 80~120자로. 첫 문장에 검색어의 답을 바로 주고, "
              "무엇을 몇 단계로 알려주는지 구체적으로. 과장 금지. 한 줄만 출력.")
    m = re.sub(r"\s+", " ", str(chat(prompt, llm, max_tokens=200, temperature=0.4))).strip()
    return m if 40 <= len(m) <= 160 else None


def qa_section(llm, title, body_text, queries):
    """본문에 답이 없는 실제 검색어 → 짧은 Q&A 블록(HTML). 본문 사실 범위 안에서만."""
    qs = "\n".join(f"- {q}" for q in queries[:3])
    prompt = (f"글 제목: {title}\n아래 본문 내용 범위 안에서만, 다음 실제 검색어에 각각 2~3문장으로 답하라. "
              "본문에 근거가 없으면 그 질문은 건너뛴다. 새 사실·수치 지어내기 금지.\n"
              f"검색어:\n{qs}\n\n본문(일부):\n{body_text[:3500]}\n\n"
              '형식: 순수 JSON 배열 [{"q":"검색어를 자연스러운 질문으로","a":"답"}]')
    raw = str(chat(prompt, llm, max_tokens=900, temperature=0.3))
    raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.M).strip()
    try:
        items = [x for x in json.loads(raw) if x.get("q") and x.get("a")]
    except Exception:
        return None
    if not items:
        return None
    h = '<h2 id="search-qa">검색으로 많이 찾는 질문</h2>\n'
    for x in items[:3]:
        h += f"<h3>{x['q']}</h3>\n<p>{x['a']}</p>\n"
    return h


def main():
    cfg = json.load(open("config.json", encoding="utf-8"))
    icfg = cfg.get("insights", {}) or {}
    creds = insights._creds(icfg)
    if not (creds and icfg.get("sc_site_url")):
        print("[serp] Search Console 미설정 — 종료")
        return
    llm = cfg.get("llm", {}) or {}
    base, H = wp_session(cfg)
    end = date.today() - timedelta(days=2)
    start = end - timedelta(days=27)

    rows = gsc_rows(icfg, creds, start, end, ["page", "query"])
    posts = live_posts(base, H)
    by_link = {p["link"].rstrip("/"): p for p in posts}
    pages = {}
    for r in rows:
        pg, q = r["keys"][0].rstrip("/"), r["keys"][1]
        d = pages.setdefault(pg, {"impr": 0, "clicks": 0, "pw": 0.0, "queries": []})
        d["impr"] += r.get("impressions", 0)
        d["clicks"] += r.get("clicks", 0)
        d["pw"] += r.get("position", 0) * r.get("impressions", 0)
        d["queries"].append((q, r.get("impressions", 0), round(r.get("position", 0), 1)))
    # 페이지 단위 합계(검색어가 익명화돼 빠진 노출까지 포함)
    for r in gsc_rows(icfg, creds, start, end, ["page"]):
        pg = r["keys"][0].rstrip("/")
        d = pages.setdefault(pg, {"impr": 0, "clicks": 0, "pw": 0.0, "queries": []})
        d["impr_total"], d["clicks_total"] = r.get("impressions", 0), r.get("clicks", 0)
        d["pos_total"] = round(r.get("position", 0), 1)

    exps = _load(EXP, [])
    recent = {e["post_id"] for e in exps
              if (date.today() - date.fromisoformat(e["at"][:10])).days < COOLDOWN}

    # ④ 검증: 14일 지난 실험 평가
    evaluated = 0
    for e in exps:
        if e.get("result") or (date.today() - date.fromisoformat(e["at"][:10])).days < EVAL_AFTER:
            continue
        ch = date.fromisoformat(e["at"][:10])
        span = min((end - ch).days, 28)
        if span < 7:
            continue
        aft = page_stats(icfg, creds, e["url"], ch + timedelta(days=1), ch + timedelta(days=span))
        bef = page_stats(icfg, creds, e["url"], ch - timedelta(days=span), ch - timedelta(days=1))
        e["eval"] = {"before": bef, "after": aft, "days": span, "at": date.today().isoformat()}
        if aft["impr"] < 20 and bef["impr"] < 20:
            e["result"] = "표본부족"
        elif aft["clicks"] > bef["clicks"] or (aft["ctr"] >= bef["ctr"] and (aft["pos"] or 99) <= (bef["pos"] or 99) + 1):
            e["result"] = "개선·유지"
        else:
            e["result"] = "악화·원복"
            if e.get("type") == "title" and e.get("old_title") and not DRY:
                requests.post(f"{base}/wp-json/wp/v2/posts/{e['post_id']}", headers=H, timeout=30,
                              json={"title": e["old_title"],
                                    "meta": {"rank_math_description": e.get("old_meta", "")}})
        evaluated += 1

    # ② 진단
    plan, quiet = [], []
    for link, p in by_link.items():
        d = pages.get(link)
        age = (datetime.now() - datetime.fromisoformat(p["date"])).days
        if not d:
            if age >= 21:
                quiet.append({"id": p["id"], "url": link, "title": p["title"]["raw"], "age": age})
            continue
        impr = d.get("impr_total", d["impr"])
        pos = d.get("pos_total") or (round(d["pw"] / d["impr"], 1) if d["impr"] else 0)
        clicks = d.get("clicks_total", d["clicks"])
        ctr = clicks / impr if impr else 0
        qs = sorted([(q, i) for q, i, _ in d["queries"]], key=lambda x: -x[1])
        content = _txt(p["content"].get("raw") or "")
        nc = _norm(content)
        # 본문에 그 검색어(공백 무시)도, 검색어의 단어 전부도 없으면 '답이 없는 검색어'
        missing = [(q, i) for q, i in qs if _norm(q) not in nc
                   and not all(_norm(w) in nc for w in str(q).split())]
        row = {"id": p["id"], "url": link, "title": p["title"]["raw"], "impr": impr,
               "clicks": clicks, "ctr": round(ctr, 4), "pos": pos, "top_queries": qs[:5]}
        if pos and pos <= 12 and impr >= 30 and ctr < _exp_ctr(pos) and qs:
            row["action"] = "title"
        elif pos and 8 <= pos <= 30 and impr >= 10 and missing:
            row["action"] = "qa"
            row["missing"] = missing[:3]
        plan.append(row)

    # ③ 검색어 갭 → 새 주제 씨앗
    titles = [_norm(p["title"]["raw"]) for p in posts]
    gaps = {}
    for pg, d in pages.items():
        for q, i, pos in d["queries"]:
            if i >= 3 and pos > 15 and not any(_norm(q) in t for t in titles):
                gaps[q] = max(gaps.get(q, 0), i)
    gap_list = [q for q, _ in sorted(gaps.items(), key=lambda x: -x[1])][:20]
    _save(GAPS, {"updated_at": date.today().isoformat(), "queries": gap_list})

    # 실행(상한 2편)
    acted = []
    for row in sorted([r for r in plan if r.get("action")], key=lambda r: -r["impr"]):
        if len(acted) >= MAX_ACT or row["id"] in recent:
            continue
        p = next(x for x in posts if x["id"] == row["id"])
        e = {"post_id": row["id"], "url": row["url"], "type": row["action"],
             "at": datetime.now().isoformat(timespec="minutes"),
             "before": {k: row[k] for k in ("impr", "clicks", "ctr", "pos")},
             "queries": row["top_queries"]}
        if row["action"] == "title":
            t = new_title(llm, row["title"], row["top_queries"])
            if not t or t == row["title"]:
                continue
            m = new_meta(llm, t, row["top_queries"]) or ""
            e.update({"old_title": row["title"], "new_title": t,
                      "old_meta": ((p.get("meta") or {}).get("rank_math_description") or ""), "new_meta": m})
            if not DRY:
                body = {"title": t}
                if m:
                    body["meta"] = {"rank_math_description": m}
                r = requests.post(f"{base}/wp-json/wp/v2/posts/{row['id']}", headers=H, json=body, timeout=30)
                if not r.ok:
                    continue
        else:
            import integrity
            html = p["content"].get("raw") or ""
            if 'id="search-qa"' in html:
                continue
            sec = qa_section(llm, row["title"], _txt(html), [q for q, _ in row["missing"]])
            if not sec:
                continue
            body, tail = integrity.split_tail(html)
            new = body + "\n" + sec + (integrity.TAIL_MARK + tail if tail else "")
            if len(integrity.critical(integrity.check(new))) > len(integrity.critical(integrity.check(html))):
                continue   # 보강이 새 결함을 만들면 포기
            e["added_qa"] = [q for q, _ in row["missing"]]
            if not DRY:
                r = requests.post(f"{base}/wp-json/wp/v2/posts/{row['id']}", headers=H,
                                  json={"content": new}, timeout=60)
                if not r.ok:
                    continue
        exps.append(e)
        acted.append(e)
        print(f"[serp] {row['action']} #{row['id']} 순위 {row['pos']} CTR {row['ctr']:.1%} 노출 {row['impr']}"
              + (f" → '{e.get('new_title')}'" if e.get("new_title") else ""))

    if not DRY:
        _save(EXP, exps)
    summary = {
        "updated_at": datetime.now().isoformat(timespec="minutes"),
        "window": [start.isoformat(), end.isoformat()],
        "pages_with_impr": len(pages), "queries": len(rows),
        "total_impr": sum(d.get("impr_total", d["impr"]) for d in pages.values()),
        "total_clicks": sum(d.get("clicks_total", d["clicks"]) for d in pages.values()),
        "plan": sorted(plan, key=lambda r: -r["impr"])[:30],
        "quiet": quiet[:40], "gaps": gap_list, "acted": acted, "evaluated": evaluated,
        "experiments": {"total": len(exps),
                        "improved": sum(1 for e in exps if e.get("result") == "개선·유지"),
                        "reverted": sum(1 for e in exps if e.get("result") == "악화·원복")},
    }
    _save(OUT, summary)
    print(f"[serp] 검색어×페이지 {len(rows)}행 · 노출 페이지 {len(pages)} · 총 노출 {summary['total_impr']} · "
          f"클릭 {summary['total_clicks']} · 실행 {len(acted)} · 평가 {evaluated} · 무반응 {len(quiet)} · 갭 {len(gap_list)}"
          + (" (DRY)" if DRY else ""))


if __name__ == "__main__":
    main()
