"""diag_longtail.py — Actions에서 기종+증상 자동완성이 실제로 오는지 확인."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import topics
for q in ("갤럭시 A15 글씨 크게", "아이폰 15 소리"):
    print(q, "→", topics._suggest(q)[:6])
s = topics.longtail_seeds()
print("seeds", len(s)); [print(" -", x) for x in s]
