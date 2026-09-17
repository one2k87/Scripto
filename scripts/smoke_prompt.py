"""smoke_prompt.py — 생성 직전 '프롬프트 조립' 무연기 시험(2026-09-17 신설).

왜 필요한가: 9/17 실측 — `_article_prompt`가 category를 dict로 가정해 터졌는데
main은 category=문자열을 넘긴다. 글 생성 루프가 예외를 삼키고 다음 글로 넘어가는
구조라 **워크플로는 success, 그날 생산은 0편**이 됐고 아무도 실패를 못 봤다.
LLM·이미지·네트워크 없이 프롬프트 조립만 돌려, 이런 크래시를 생성 전에 죽인다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import generator  # noqa: E402

CASES = [
    # (keyword, kind, category)  — category는 main이 실제로 넘기는 '문자열'을 우선 검증
    ("부모님 스마트폰 글씨 크게 하는 법", "long_single", "시니어 디지털"),
    ("보이스피싱 전화 구별하는 법", "long_single", ""),
    ("정부24 등본 발급", "single", None),
    ("키오스크 주문 순서", "long_single", {"name": "시니어 디지털", "desc": "설명"}),
]


def main():
    fails = []
    for kw, kind, cat in CASES:
        try:
            p = generator._article_prompt(kw, kind, cat, [], [], True)
            assert "정확히 2개" in p, "이미지 2장 규칙 누락"
            assert "배정된 플롯" in p, "대표이미지 플롯 배정 누락"
        except Exception as e:
            fails.append(f"{kw} / category={cat!r} → {type(e).__name__}: {e}")
    # 마커 변환도 함께(이미지 2장 보장 로직)
    try:
        body = generator._convert_markers(
            "<p>d</p><h2>A</h2><p>[[IMG:photo|장면]]</p><h2>B</h2><p>x</p><h2>C</h2>",
            False, lambda d, i: f"<figure>{i}</figure>", fallback_desc="주제",
            fallback_hero=generator._hero_fallback_desc("주제", "시니어 디지털"))
        assert body.count("<figure>") == 2, f"이미지 2장이 아님({body.count('<figure>')})"
    except Exception as e:
        fails.append(f"_convert_markers → {type(e).__name__}: {e}")

    if fails:
        print("❌ 프롬프트 조립 시험 실패 — 생성을 중단합니다")
        for f in fails:
            print("  ·", f)
        return 1
    print(f"✅ 프롬프트 조립 시험 통과({len(CASES)}개 경로)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
