"""네이버 검색 HUB 첫 호출 실측 + 핵심 30편 검색어의 블로그·웹문서 총 문서 수·상위 5개(2026-11-17)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import naver_search as ns
import metrics

Q = json.load(open("data/core30_queries.json", encoding="utf-8"))
out = []
for i, q in enumerate(Q):
    row = {"id": q["id"], "query": q["query"]}
    for kind in ("blog", "webkr"):
        st, total, items = ns.search(q["query"], kind, display=5)
        row[kind] = {"status": st, "total": total, "top": items}
        if i == 0:
            print(f"[첫 호출] {kind}: {st} · total={total}")
    out.append(row)
# 월간 검색량(검색광고 키워드도구, 5개씩)
ncfg = {k: os.environ.get(e, "").strip() for k, e in (("api_key", "NAVER_API_KEY"), ("secret_key", "NAVER_SECRET_KEY"), ("customer_id", "NAVER_CUSTOMER_ID"))}
if ncfg["api_key"]:
    for i in range(0, len(out), 5):
        vol = metrics.naver_volumes([r["query"] for r in out[i:i + 5]], ncfg) or {}
        for r in out[i:i + 5]:
            m = vol.get(metrics._norm(r["query"]))
            r["volume"] = m["volume"] if m else None
for r in out:
    print(f"vol {r['id']} {r['query']} = {r.get('volume')}")
    print(f"{q['id']} {q['query']} | blog {row['blog']['total']} | web {row['webkr']['total']}")
os.makedirs("dashboard/data", exist_ok=True)
json.dump(out, open("dashboard/data/serp_naver_core30.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for row in out[:3]:
    print(f"\n== {row['query']}")
    for it in row["blog"]["top"]:
        print("  ·", it["title"][:50], it["link"])
