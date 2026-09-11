"""persona_gen.py — 주제 맞춤 'AI 추천 페르소나' 재생성(2026-09-11 이원화 시스템).

data/site_categories.json의 현재 주제를 읽어 LLM으로 페르소나를 새로 설계해
data/persona.json의 auto 슬롯에 넣는다(mode와 custom 슬롯은 건드리지 않는다).
주제를 바꿀 때마다 이 워크플로 한 번이면 페르소나가 따라온다.
"""
import json
import sys
from datetime import date

from llm import chat

P = "data/persona.json"


def main():
    cfg = json.load(open("config.json", encoding="utf-8"))
    site = json.load(open("data/site_categories.json", encoding="utf-8"))
    cats = site.get("categories") or []
    if not cats:
        print("카테고리 없음 — 종료"); return 1
    name = cats[0]["name"]; desc = cats[0]["desc"]

    prompt = f"""블로그 주제에 딱 맞는 '글쓴이 페르소나'를 설계하라. 주제: {name}
세부: {desc}

요구사항:
- pen_name: 한글 2~3자 필명(사람 이름 느낌보다 따뜻한 별칭)
- identity: 이 주제를 다룰 자격이 '조사·검증·정리 습관'에서 나오는 인물 한 문단.
  ⚠️ 특정 직업·자격증·경력을 사칭하지 말 것(예: '현직 ○○사 15년' 금지).
  '~를 대조해 정리하는 사람' 같은 검증 가능한 정체성으로.
- voice: 말투·관점 원칙 4개(독자 눈높이·안전·비용 표현 방식 포함)
- honesty_rules: 3개 고정 — ①하지 않은 일을 했다고 쓰지 않는다 ②1인칭은 조사·확인형만
  ③기기·조건에 따라 다른 것은 다르다고 밝힌다 (주제에 맞게 어휘만 조정)
- signature_habits: 독자가 '이 블로그 글이네'라고 알아볼 반복 장치 3개(이 주제 특화)

JSON만 출력: {{"pen_name":"","identity":"","voice":[],"honesty_rules":[],"signature_habits":[]}}"""
    raw = chat(prompt, cfg["llm"], max_tokens=1200, temperature=0.8)
    m = raw[raw.find("{"):raw.rfind("}") + 1]
    auto = json.loads(m)
    assert auto.get("pen_name") and auto.get("identity") and len(auto.get("voice", [])) >= 3

    d = json.load(open(P, encoding="utf-8"))
    auto["_생성"] = f"{date.today().isoformat()}, 주제 '{name}' 기준 AI 추천"
    d["auto"] = auto
    json.dump(d, open(P, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"AI 추천 페르소나 재생성 완료: '{auto['pen_name']}' (주제: {name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
