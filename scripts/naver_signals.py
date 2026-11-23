# -*- coding: utf-8 -*-
"""네이버 신호 수집 (2026-11-23 신설) — 키워드마다 '추이 판정'과 (선택)'내 사이트 순위'를 붙인다.

무엇을 자동화하나
  서치어드바이저의 노출·클릭은 API 가 없어 사람이 옮겨 적어야 한다. 그 빈자리를 두 가지로 메운다.
    · 추이 판정  데이터랩 검색어 트렌드 2년치 → 에버그린 / 급상승 / 시즌진입 / 시즌형 / 하락
    · 순위       웹문서 검색에서 내 사이트가 몇 위인지(RANK_CHECK=true 일 때만)
  결과는 글감 배분(강화·에버그린·핫이슈·실험)의 근거로 쓴다.

키워드를 어디서 가져오나 (있는 것만 쓴다 — 다른 레포에 복사해도 그대로 돈다)
  1) data/naver_seed_keywords.json        서치어드바이저에서 유입이 확인된 말(사람이 갱신)
  2) dashboard/data/keyword_volume_audit.json  글마다 잡은 대표 키워드
  3) data/retitle_queue.txt                    제목 교체 대기열의 포커스 키워드
  4) 위가 다 없으면 워드프레스 공개 REST 의 최근 글 제목 앞 세 낱말

환경변수
  NAVER_HUB_KEY_ID / NAVER_HUB_KEY   필수(없으면 아무것도 쓰지 않고 끝낸다)
  SITE_DOMAIN                        순위를 볼 도메인. 없으면 BLOG_URL·WP_SITE 에서 뽑는다
  RANK_CHECK                         true 면 순위도 본다(기본 false — naver_hub.py 머리말의 약관 주의 참조)
  SIGNALS_MAX                        한 번에 볼 키워드 수(기본 80)
"""
import datetime as dt
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests

import naver_hub as nh

OUT_JSON = os.path.join("dashboard", "data", "naver_signals.json")
OUT_MD = os.path.join("data", "naver_signals.md")
LANE = {"에버그린": "B 에버그린", "급상승": "C 핫이슈", "시즌진입": "C 핫이슈(시즌 선점)",
        "시즌형": "철 1~2달 전에", "하락": "쓰지 않는다", "자료부족": "D 실험(수요 미확인)", "조회실패": "-"}


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


def gather(domain, limit):
    rows, seen = [], set()

    def add(kw, **extra):
        k = nh.clean_keyword(kw)
        if len(k) >= 2 and k not in seen:
            seen.add(k)
            rows.append({"keyword": k, **extra})

    seed = _load(os.path.join("data", "naver_seed_keywords.json")) or {}
    for it in sorted(seed.get("keywords") or [], key=lambda x: -(x.get("impr") or 0)):
        add(it.get("keyword"), source="서치어드바이저", post_id=it.get("post_id"),
            sa_impr=it.get("impr"), sa_clicks=it.get("clicks"))
    audit = _load(os.path.join("dashboard", "data", "keyword_volume_audit.json")) or {}
    for r in sorted(audit.get("rows") or [], key=lambda x: -(x.get("volume") or 0)):
        add(r.get("keyword"), source="글 대표 키워드", post_id=r.get("id"), volume=r.get("volume"))
    # 제목 교체 대기열에 적힌 포커스 키워드('글ID=새 제목##포커스 키워드'). 그 파일을 쓰는 레포에서만 잡힌다.
    try:
        for line in open(os.path.join("data", "retitle_queue.txt"), encoding="utf-8"):
            if "##" in line and "=" in line and not line.lstrip().startswith("#"):
                pid, focus = line.split("=", 1)[0].strip(), line.rsplit("##", 1)[1].strip()
                add(focus, source="포커스 키워드", post_id=int(pid) if pid.isdigit() else None)
    except Exception:
        pass
    if not rows and domain:
        try:
            j = requests.get(f"https://{domain}/wp-json/wp/v2/posts",
                             params={"per_page": 50, "_fields": "id,title"}, timeout=30).json()
            for p in j if isinstance(j, list) else []:
                # 제목은 문장이라 그대로 넣으면 추이가 안 잡힌다. 쉼표 앞 구절의 첫 세 낱말만 쓴다.
                t = nh.clean_keyword((p.get("title") or {}).get("rendered"))
                add(" ".join(t.split()[:3]), source="글 제목", post_id=p.get("id"))
        except Exception as e:
            print(f"::warning::글 제목 조회 실패 {type(e).__name__}")
    return rows[:limit]


def main():
    if not nh.available():
        print("::warning::NAVER_HUB_KEY_ID / NAVER_HUB_KEY 가 없어 건너뜁니다. "
              "금고에서 이 레포로 배포하세요(keys/requests.txt → keys.sh apply).")
        return 0
    domain = site_domain()
    do_rank = (os.getenv("RANK_CHECK") or "").strip().lower() in ("1", "true", "yes") and bool(domain)
    rows = gather(domain, int(os.getenv("SIGNALS_MAX") or 80))
    if not rows:
        print("::warning::볼 키워드가 없습니다.")
        return 0
    prev = {r.get("keyword"): r for r in ((_load(OUT_JSON) or {}).get("rows") or [])}
    print(f"키워드 {len(rows)}개 · 도메인 {domain or '(없음)'} · 순위 확인 {'켬' if do_rank else '끔'}")

    fails = 0
    for i, r in enumerate(rows):
        r.update(nh.trend_profile(r["keyword"]))
        if r["label"] == "조회실패":
            fails += 1
            if fails == 1:
                print(f"::warning::추이 조회 실패 — {r.get('err')}")
            if fails >= 5 and fails == i + 1:      # 처음부터 연달아 실패 = 키·경로 문제. 한도만 태우지 않는다
                print("::error::처음 5건이 전부 실패했습니다. 키 배포 상태와 HUB 앱에 '검색어 트렌드'가 "
                      "등록됐는지 확인하세요.")
                return 1
        if do_rank:
            got = nh.site_rank(r["keyword"], domain)
            if got is not None:
                r["rank"], r["total"], r["url"] = got["rank"], got["total"], got["url"]
                p = prev.get(r["keyword"]) or {}
                if "rank" in p:
                    r["rank_prev"] = p.get("rank")
        r["lane"] = LANE.get(r["label"], "-")
        time.sleep(0.15)

    count = {}
    for r in rows:
        count[r["label"]] = count.get(r["label"], 0) + 1
    out = {"at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "site": domain,
           "rank_check": do_rank, "count": count, "rows": rows}
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    json.dump(out, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    def rk(r):
        if "rank" not in r:
            return "-"
        cur = "100위 밖" if r["rank"] is None else f"{r['rank']}위"
        pv = r.get("rank_prev", "x")
        if pv == "x" or pv == r["rank"]:
            return cur
        return f"{cur} (이전 {'100위 밖' if pv is None else str(pv) + '위'})"

    L = [f"# 네이버 신호 — {out['at']}", "",
         f"도메인 `{domain}` · 키워드 {len(rows)}개 · 순위 확인 {'켬' if do_rank else '끔'}", "",
         "판정 분포: " + " · ".join(f"{k} {v}" for k, v in sorted(count.items(), key=lambda kv: -kv[1])), "",
         "| 키워드 | 판정 | 배분 | 최근/직전 | 작년 대비 | 봉우리 달 | 순위 | 출처 |",
         "|---|---|---|---:|---:|---:|---|---|"]
    order = {"급상승": 0, "시즌진입": 1, "에버그린": 2, "시즌형": 3, "자료부족": 4, "하락": 5, "조회실패": 6}
    for r in sorted(rows, key=lambda x: (order.get(x["label"], 9), -(x.get("sa_impr") or x.get("volume") or 0))):
        L.append(f"| {r['keyword']} | {r['label']} | {r.get('lane', '-')} | {r.get('rise', '-')} | "
                 f"{r.get('yoy') if r.get('yoy') is not None else '-'} | {r.get('peak_month') or '-'} | "
                 f"{rk(r)} | {r.get('source', '')} |")
    os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
    open(OUT_MD, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("판정 분포:", count)
    print(f"저장: {OUT_JSON} · {OUT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
