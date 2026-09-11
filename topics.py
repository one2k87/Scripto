"""
topics.py - '카테고리 집중' 주제 엔진 (미니사이트 전략).

전략(참고 자료 기반):
- 고단가 카테고리 1개에 집중해 관련 글 다발(topic cluster)을 만든다.
- 두 갈래로 주제를 뽑는다:
    long   = 저경쟁 롱테일. 많은 사람이 다루지 않아 신생 블로그도 상위노출 쉬움 + 고단가.
    season = '이제 뜰' 시즌/이벤트 키워드를 2~4주 미리 선점(검색 반영에 1~2주 걸리므로).
- 이미 다룬 주제는 제외(중복 방지)하여 카테고리를 계속 채워 나간다.

LLM으로 주제를 생성하되, 히스토리(과거 발행 제목)를 프롬프트에 넣어 겹치지 않게 한다.
"""

import re
from datetime import date

# 시즌 선점 힌트: '지금 달'이 아니라 '1~2달 뒤 검색이 붙는' 주제를 노린다.
_SEASON_HINT = {
    1: "설 연휴 자금·연말정산 환급·새해 재테크 계획",
    2: "연말정산 추가납부·봄 이사 대출·전세자금",
    3: "종합소득세 준비·신학기 자녀 보험·봄 이사 자금",
    4: "5월 종합소득세 신고·근로장려금 신청·가정의 달 지출관리",
    5: "종합소득세 신고 마감·여름 휴가 적금·자동차세 연납",
    6: "여름 휴가 경비 마련·장마철 자동차보험·반기 결산 재테크",
    7: "휴가철 환전·해외여행 카드·하반기 재테크 점검",
    8: "추석 상여·명절 자금·연금저축 중간점검",
    9: "추석 연휴 자금·연말정산 미리보기·4분기 투자",
    10: "연말정산 세액공제 준비·김장/난방비 절약·연금 납입 한도",
    11: "연말정산 몰아넣기·연말 카드 실적·내년 재테크 계획",
    12: "연말정산 최종 점검·새해 예산·1월 만기 적금",
}


def season_focus(today=None):
    today = today or date.today()
    nxt = today.month % 12 + 1          # 다음 달(2~4주 뒤 검색 반영 타이밍)
    return nxt, _SEASON_HINT.get(nxt, "")


# 의도별 주제 지침 — strategy.py가 정한 그날의 비율에 따라 주입된다
INTENT_GUIDE = {
    "revenue": """
[이번 주제의 의도 = 수익형(결정 직전 검색)]
- 광고 단가가 높은 '돈이 오가기 직전' 검색만 잡는다.
- 반드시 다음 중 하나를 포함: 비용·가격·얼마·금리·한도·수수료·비교·추천·후기·순위·환급·혜택.
- 예) "OO 수수료 얼마", "OO vs OO 뭐가 싼가", "OO 한도 조건", "OO 실제 후기".
- 단순 정보 나열이 아니라 '선택을 도와주는' 각도로 잡는다.
""",
    "evergreen": """
[이번 주제의 의도 = 누적형(계속 찾는 검색)]
- 시즌을 타지 않고 1년 내내 일정하게 찾는 '방법·절차'형만 잡는다.
- 반드시 다음 중 하나를 포함: 방법·절차·신청·발급·조건·기준·확인·차이·준비물·서류.
- 예) "OO 발급 절차", "OO와 OO 차이", "OO 신청 준비물".
- 한 번 상위노출되면 오래가는 주제를 우선한다(뉴스성·일회성 금지).
""",
}


def build_topic_prompt(category, category_desc, kind, count, exclude=None, today=None,
                       winners=None, intent=None):
    exclude = exclude or []
    ex_text = "\n".join(f"- {t}" for t in exclude[:60]) or "(없음)"
    winners = winners or []
    intent_text = INTENT_GUIDE.get(intent or "", "")
    win_text = ""
    if winners:
        win_text = ("\n[성과 피드백 — 최근 실제 유입이 많았던 검색어]\n"
                    + "\n".join(f"- {w}" for w in winners[:8])
                    + "\n→ 위와 '비슷한 각도/의도'의 주제를 우대하되, 똑같이 베끼지는 말고 새로운 세부 주제로 확장한다.\n")

    common = f"""당신은 '{category}' 카테고리에 집중하는 애드센스 수익형 블로그의 주제 기획자입니다.
이 블로그는 '{category}' 미니사이트로 운영되며, 아래 세부 분야를 다룹니다:
{category_desc}

[독자 = 일반 개인(가장 중요)]
- 이 블로그의 독자는 '평범한 일반인'이다. 회사 실무자·투자 전문가·기업 담당자가 아니다.
- 그래서 **일반인이 실제로 검색하고 클릭할 '내 생활·내 돈·내 문제'와 직결된 주제**만 뽑는다.
- 다음처럼 '기업·전문가·B2B용' 주제는 절대 금지(일반인이 클릭 안 함):
  기업 실적/재무제표 분석, 시장 점유율·산업 리포트, 법인 대상 상품, ERP·SaaS 도입,
  기업 데이터·통계 자료, 거시경제 이론, 업계 동향 분석, 규제 정책 해설(전문가용) 등.
- '개인이 직접 하는 행동'으로 바꿔서 잡는다.
  (나쁜 예: "국내 클라우드 시장 규모 분석" → 좋은 예: "구글 포토 용량 꽉 찼을 때 무료로 늘리는 법")
  (나쁜 예: "삼성전자 3분기 실적 분석" → 좋은 예: "삼성전자 배당금 언제 얼마 들어오나 (개인 주주 기준)")
  (나쁜 예: "기업 대출 금리 동향" → 좋은 예: "무직자·프리랜서도 되는 비상금 대출 조건")
- 판단 기준: "우리 엄마·친구가 검색창에 칠 만한 말인가?" 아니면 버린다.

[반드시 지킬 원칙]
- 모두 '{category}' 카테고리 안의 주제여야 한다(카테고리 이탈 금지).
- 수익성은 '카테고리 안의 돈이 걸린 결정'으로 잡는다(2026-09-11 개정 — 옛 CPC 목록이
  대출·보험·지원금 같은 니치 밖 주제를 끌어들여 6회차 반려의 한 원인이 됐다):
  시공 비용·업체 견적 비교(도배/장판/욕실/주방/철거), 셀프 vs 업체 손익 분기,
  자재·공구 구매 선택(가격대별 차이), 하자·누수 보수 비용, 폐기물 처리 비용,
  이사 전후 수리 우선순위 등 — 독자가 '지출 직전'에 검색하는 순간을 노린다.
- ❌ 카테고리 밖 '돈 주제'로 절대 새지 마라: 대출·보험·세금·연말정산·청약·연금·
  지원금·보조금·정부 정책·신청 조건류는 이 블로그의 주제가 아니다(니치 이탈=심사 감점 실측).
- 아래 '이미 다룬 주제'와 겹치거나 매우 비슷하면 안 된다(새로운 각도로):
{ex_text}
- 각 주제는 검색 의도가 분명한 정보형(방법/비교/조건/신청/추천/후기 형태), 그리고 '개인 관점'.
"""

    if kind == "season":
        today = today or date.today()
        m1 = today.month % 12 + 1          # 1개월 뒤
        m2 = (today.month + 1) % 12 + 1     # 2개월 뒤
        hint = _SEASON_HINT.get(m1, "")
        extra = f"""[이번 배치 = 시즌 선점 · 1~2개월 뒤 겨냥]
- 지금은 {today.year}년 {today.month}월. **{m1}월~{m2}월(=지금부터 1~2개월 뒤)에 검색이 오를 주제만** 고른다.
- 검색엔진 색인·상위노출에 몇 주 걸리므로, 딱 이 시점(1~2개월 뒤)을 노려 지금 미리 쓴다.
- ⚠️ 3개월 이상 먼 주제는 금지. (예: 지금 {today.month}월인데 11월 수능, 12월 연말정산처럼 먼 이벤트 ❌)
- 참고 시즌 맥락({m1}월경): {hint}
- 계절/제도 일정/연례 이벤트와 '{category}'를 결합하되, 시점이 {m1}~{m2}월인 것만.
"""
    else:
        extra = """[이번 배치 = 수익형 저경쟁(스위트스팟)]
- 핵심: '수익이 날 만큼 검색량은 있으면서(월 대략 1,000~30,000회 수준)', 대형 매체가 도배하지 않아 신생 블로그도 노려볼 만한 키워드.
- 검색이 거의 없는 초극소 키워드(월 수십~수백 회)는 피한다 → 트래픽·수익이 안 나옴.
- 반대로 너무 광범위한 대형 키워드(예: 그냥 "대출", "다이어트")도 피한다 → 상위노출 불가.
- 그 중간: 특정 대상/조건/상황을 담되 '실제로 찾는 사람이 꽤 있는' 롱테일.
  (좋은 예: "무직자 비상금 대출 조건", "연말정산 월세 세액공제 조건", "직장인 점심 다이어트 도시락")
  (나쁜 예: 너무 좁아 아무도 안 찾는 "○○동 △△은행 무직자 소액대출 후기" 류)
"""

    return common + intent_text + win_text + extra + f"""
출력은 줄바꿈으로 구분된 한국어 주제 문장 정확히 {count}개만. 번호/설명/따옴표 없이.
각 주제는 그대로 블로그 제목 키워드로 쓸 수 있게 구체적으로."""


def classify_topics(items, category, chat, llm_cfg, today=None):
    """
    각 후보 주제를 '저경쟁(long)' vs '시즌(season)'으로 지속 판별한다.
    - 시즌: 특정 시기/계절/연례 일정과 결합돼 앞으로 검색이 몰릴 주제.
    - 저경쟁: 시기와 무관하게 1년 내내 꾸준하고 경쟁이 약한 롱테일.
    각 item에 lane_ai, lane_reason, season_month 를 채운다.
    """
    import json as _json
    import re as _re
    if not items:
        return items
    lst = "\n".join(f"{i+1}. {it['keyword']}" for i, it in enumerate(items))
    today = today or date.today()
    prompt = f"""'{category}' 블로그 주제들을 두 부류로 분류하세요. 오늘은 {today.year}년 {today.month}월입니다.

- season: 특정 시기/계절/연례 일정(연말정산, 종소세, 명절, 청약 일정 등)과 묶여 곧 검색이 몰릴 주제.
- long: 시기와 무관하게 1년 내내 꾸준하고 경쟁이 약한 롱테일 주제.

주제 목록:
{lst}

각 주제를 아래 JSON 배열로만 출력(설명 없이):
[{{"n":1,"lane":"long|season","month":0,"reason":"짧은 근거"}}, ...]
month는 season일 때 검색이 붙을 달(1~12), long이면 0."""
    try:
        raw = chat(prompt, llm_cfg, max_tokens=700, temperature=0.2)
        raw = _re.sub(r"^```[a-zA-Z]*|```$", "", (raw or "").strip()).strip()
        m = _re.search(r"\[.*\]", raw, _re.DOTALL)
        arr = _json.loads(m.group(0)) if m else []
        by_n = {int(x.get("n", 0)): x for x in arr}
        for i, it in enumerate(items):
            x = by_n.get(i + 1, {})
            it["lane_ai"] = x.get("lane", "")
            it["lane_reason"] = x.get("reason", "")
            it["season_month"] = x.get("month", 0)
    except Exception as e:
        print(f"[classify] 판별 실패(무시): {e}")
    return items


def split_by_lane(items, want, other_pool=None):
    """판별 결과(lane_ai)가 want('long'/'season')인 것 우선, 부족하면 나머지로 채움."""
    match = [x for x in items if x.get("lane_ai") == want]
    rest = [x for x in items if x.get("lane_ai") != want]
    return match, rest


# 애드센스 정책 위반 소지가 큰 주제(자동 제외). 필요시 config로 확장 가능.
BLOCKLIST = [
    "성인", "야동", "포르노", "19금", "성인용품",
    "도박", "카지노", "토토", "베팅", "슬롯머신", "바카라", "사설",
    "마약", "대마", "총기", "무기", "폭탄", "해킹", "불법",
    "미성년", "청소년 유해",
    "확실히 낫는", "100% 완치", "즉효", "부작용 없이", "무조건 살빠지는",  # 과장 의료/효과
    "토렌트", "불법 다운로드", "크랙", "무료 스트리밍", "다시보기 링크",     # 저작권
    # 전쟁·분쟁·정치적 민감 이슈(애드센스 '충격적/민감한 콘텐츠' 위험 → 제외)
    "전쟁", "내전", "분쟁", "교전", "침공", "침략", "테러", "테러리스트",
    "무장", "군사충돌", "학살", "대량학살", "쿠데타", "폭동", "시위 진압",
    "인질", "포로", "난민", "핵전쟁", "미사일 발사", "공습", "휴전", "정전협정",
]


# 니치 이탈 감시(2026-09-11, 6회차 반려 대응): 셀프 인테리어 블로그에 정책·금융 글이
# 섞이면 "무슨 사이트인지 모호"해져 심사 감점. 주제 생성·백로그 재고 양쪽에 적용된다.
OFFNICHE = ["지원금", "보조금", "정부 정책", "정책 신청", "환급", "연말정산", "청약",
            "대출", "보험", "세금", "연금", "재테크", "감면", "청년 주거", "전세보증금",
            "바우처", "복지", "공제"]


def is_offniche(keyword):
    k = str(keyword or "")
    return any(w in k for w in OFFNICHE)


def is_blocked(keyword, extra=None):
    kw = str(keyword or "")
    words = BLOCKLIST + list(extra or [])
    return any(b and b in kw for b in words)


# 일반인이 클릭 안 하는 '기업·전문가·B2B' 주제(안전망 필터). 프롬프트로 1차 차단하고 이걸로 2차 제거.
CORPORATE_HINTS = [
    "기업 데이터", "기업데이터", "재무제표", "실적 분석", "실적분석", "시장 규모", "시장규모",
    "시장 점유율", "점유율", "산업 동향", "업계 동향", "산업 리포트", "시장 전망 보고서",
    "B2B", "b2b", "법인", "엔터프라이즈", "ERP", "erp", "SaaS 도입", "saas 도입",
    "공급망", "밸류체인", "IR 자료", "ir자료", "거시경제 분석", "매크로", "컨센서스",
    "애널리스트", "산업분석", "섹터 분석", "기관투자", "수출입 통계", "생산자물가지수",
]


def is_corporate(keyword):
    kw = str(keyword or "")
    return any(h and h in kw for h in CORPORATE_HINTS)


def parse_topics(text, count):
    out = []
    seen = set()
    for line in (text or "").splitlines():
        line = re.sub(r"^[\-\*\d\.\)\s\"'·•]+", "", line.strip()).strip().strip('"').strip()
        key = re.sub(r"\s+", "", line)
        if line and key not in seen:
            seen.add(key)
            out.append({"keyword": line, "news": []})
        if len(out) >= count:
            break
    return out
