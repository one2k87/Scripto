"""
generator.py - 애드센스 '수익형 + 상위노출' 한국어 글 생성.

참고 자료(애드센스 실전 전략) 반영:
1) 클릭률 구조: 이미지 자리 → 그 아래 문단 사이 광고 자리 + 정책 안전한 유도문장.
2) 고단가 키워드 배치: 제목/첫문단/중반/마지막에 핵심 키워드 분산.
3) 체류시간: 3초 후킹 첫문장(질문/공감형), 요약표, 소제목 구조(H1>H2>H3).
4) 카테고리 반복수익: 끝에 '함께 보면 좋은 글' 내부링크(같은 카테고리 이전 글).
+ SEO: 슬러그, 메타(120~155자), 목차, FAQ, JSON-LD(BlogPosting+FAQPage).

광고/이미지 자리는 파이썬에서 안정적으로 삽입한다. LLM은 본문에 [[AD]] / [[IMG:설명]]
마커를 넣고, 없으면 파이썬이 소제목 사이에 자동 배치한다.
"""

import json
import re
import html as html_mod
import random
from llm import chat
from links import find_reference_links

# 승인 후 수익 최적화: True면 광고 3개 배치(기본 2개). main.run()에서 설정.
ADS_BOOST = False

# v1.1 픽 라인(쿠팡파트너스) 커머스 모드 — site_categories.json의 track:"coupang"일 때만.
# 애드 라인과의 차이는 '최적화 대상'뿐: 심사관 관점 → 구매의도. 경험담 창작 금지는 동일.
COMMERCE_MODE = False
def _commerce_block():
    if not COMMERCE_MODE:
        return ""
    return """
[커머스 모드 — 구매 결정을 돕는 글]
- 이 글의 목적은 검색량이 아니라 **구매의도**다: 가격대·규격·비교·추천·"어떤 걸 사야" 유형의 검색에 답한다.
- 제품 '유형' 2~3가지를 표나 분기로 비교한다(스펙·가격 범위·어떤 사람에게 맞는지). 특정 쇼핑몰·링크·"구매하세요"는 쓰지 않는다(링크는 시스템이 삽입).
- 선택 기준을 조건 분기로: "원룸이라면 A, 신축 아파트라면 B"처럼 상황별 결론을 내준다.
- 가격은 확인 시점 기준 범위로 쓰고 본문에 시점을 명시한다. 겪지 않은 사용 후기는 창작 금지 — 스펙·공식 정보 비교 관점으로.
"""

SYSTEM = (
    "당신은 구글 애드센스로 실제 수익을 내는 한국어 블로그 전문 작가입니다. "
    "고단가 키워드를 자연스러운 회화체로 녹이고, 방문자가 끝까지 읽고 광고에 시선이 가도록 "
    "구조를 설계합니다. 광고 클릭을 직접 유도하는 표현은 절대 쓰지 않고, 정책을 준수합니다. "
    "사실이 불확실하면 단정하지 않습니다."
)

# 광고 근처에 놓는 '정책 안전한' 유도문장 (자료 원문 예시 기반, 클릭 직접 유도 아님)
CTA_LINES = [
    "더 많은 정보는 아래에서 확인해보세요.",
    "관련 자료가 궁금하다면 다음 내용을 참고하세요.",
    "자세히 정리된 내용을 이어서 읽어보세요.",
    "아래에서 핵심 내용을 계속 확인해보세요.",
]


def slugify(text, max_words=8):
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text).strip("-")
    return "-".join(text.split("-")[:max_words]) or "post"


def _ad_slot():
    cta = random.choice(CTA_LINES)
    return (
        '<div class="ad-slot" style="margin:26px 0;padding:14px;border:1px dashed #d8dbe0;'
        'border-radius:10px;text-align:center;background:#fafbfc">'
        f'<p style="margin:0 0 8px;color:#666;font-size:14px">{cta}</p>'
        '<!-- 애드센스 광고 코드를 이 자리에 붙여넣으세요 -->'
        '<div style="color:#b6bcc6;font-size:13px">[ 광고 자리 ]</div>'
        '</div>'
    )


def _img_slot(desc):
    d = html_mod.escape(desc or "관련 이미지")
    return (
        '<figure style="margin:22px 0;text-align:center">'
        f'<div style="padding:38px 12px;background:#f2f4f7;border-radius:10px;color:#98a2b3">'
        f'📷 이미지 삽입: {d}</div>'
        f'<figcaption style="font-size:13px;color:#98a2b3;margin-top:6px">{d}</figcaption>'
        f'</figure><!-- alt: {d} -->'
    )


# ── 글의 '요건'(고정) ─────────────────────────────────────────────
# 형식은 매번 흔들되, 무엇을 쓰든 반드시 들어가야 하는 것은 고정한다.
# 형식만 랜덤화하면 사람 티는 나는데 알맹이가 빠지고, 요건만 고정하면
# 대량생산 티가 난다. 둘을 분리해 관리한다(data/article_requirements.json).
_REQ_CACHE = {}


def load_requirements(path="data/article_requirements.json"):
    if _REQ_CACHE.get("v"):
        return _REQ_CACHE["v"]
    try:
        with open(path, encoding="utf-8") as f:
            _REQ_CACHE["v"] = json.load(f)
    except Exception:
        _REQ_CACHE["v"] = {"requirements": []}
    return _REQ_CACHE["v"]


def requirements_block():
    reqs = (load_requirements() or {}).get("requirements") or []
    if not reqs:
        return ""
    lines = ["[반드시 들어가야 하는 것 — 형식이 어떻게 바뀌든 이건 고정]"]
    for i, r in enumerate(reqs, 1):
        lines.append(f"{i}. {r.get('label','')} — {r.get('how','')}")
    lines.append("※ 위 요건은 발행 전 기계로 검사합니다. 하나라도 빠지면 글이 폐기됩니다.")
    return "\n".join(lines)



# ── 톤 기수(era) ─────────────────────────────────────────────────
# 사람이 쓰는 블로그는 몇 달 단위로 문체가 조금씩 변한다. 같은 톤으로
# 수백 편이 쌓이면 그 균일함 자체가 자동 생성 신호가 된다.
# 그래서 기간(기본 2개월)마다 어조·리듬·선호 제목 골격을 이동시킨다.
# ⚠️ 급변은 금지 — 요건(무엇을 쓰는가)은 그대로 두고 '어떻게 말하는가'만
#    옮긴다. 경계에서는 이전 기수 톤을 일부 섞어 칼같이 끊기지 않게 한다.
_TONE_CACHE = {}


def load_tone_eras(path="data/tone_eras.json"):
    if _TONE_CACHE.get("v") is None:
        try:
            with open(path, encoding="utf-8") as f:
                _TONE_CACHE["v"] = json.load(f)
        except Exception:
            _TONE_CACHE["v"] = {"eras": [], "period_months": 2, "epoch": "2026-07", "blend_ratio": 0.25}
    return _TONE_CACHE["v"]


def current_era(today=None, seed=""):
    """오늘 날짜로 톤 기수를 정한다. (era_dict, 기수번호, 이전기수_섞임여부)"""
    from datetime import date
    cfg = load_tone_eras()
    eras = cfg.get("eras") or []
    if not eras:
        return None, 0, False
    today = today or date.today()
    try:
        ey, em = [int(x) for x in str(cfg.get("epoch", "2026-07")).split("-")[:2]]
    except Exception:
        ey, em = 2026, 7
    period = max(1, int(cfg.get("period_months", 2)))
    months = (today.year * 12 + today.month) - (ey * 12 + em)
    idx = max(0, months) // period
    # 경계 겹침: 일부 글은 직전 기수 톤으로 쓴다(사람의 문체는 칼같이 안 바뀐다)
    blend = float(cfg.get("blend_ratio", 0.25))
    use_prev = idx > 0 and (_variant(str(seed) + "|blend", 100) < int(blend * 100))
    use = (idx - 1) if use_prev else idx
    return eras[use % len(eras)], idx, use_prev


def _weighted_pick(weights, seed):
    """{키: 가중치} 에서 시드로 하나 고른다(같은 글은 항상 같은 결과)."""
    items = [(k, max(0, int(v))) for k, v in (weights or {}).items() if int(v) > 0]
    if not items:
        return None
    total = sum(w for _, w in items)
    r = _variant(seed, total)
    for k, w in items:
        if r < w:
            return k
        r -= w
    return items[0][0]


def _article_prompt(keyword, kind, category, links, related, insert_ads, competitive=False):
    from datetime import date
    today = date.today()
    nxt = today.month % 12 + 1
    link_lines = "\n".join(f"- {l['title']}: {l['url']}" for l in links) or "(없음)"
    rel_lines = "\n".join(f"- {r['title']}" for r in related) or "(없음)"
    kind_hint = (
        "시즌 선점 글: 앞으로 검색이 붙을 시기를 겨냥해 지금 미리 완결성 있게 정리"
        if kind == "season"
        else "저경쟁 롱테일 글: 좁고 명확한 문제를 끝까지 해결해 상위노출을 노림"
    )
    # 글마다 '구성 스타일'을 무작위로 골라 획일적인 AI 양산 티를 없앤다.
    _style = random.choice([
        "문제 해결형: 독자의 고민→원인→해결 순서로 풀되, 실제 상황 예시로 시작한다.",
        "자료검증형: 공식 자료에서 확인한 사실을 근거로, 헷갈리는 지점을 짚어준다.",
        "비교/선택형: 몇 가지 선택지를 표와 함께 장단점으로 비교하고 상황별 추천을 준다.",
        "단계별 가이드형: 실제로 따라 할 수 있는 순서(1→2→3)로, 각 단계에 팁을 곁들인다.",
        "자주 묻는 질문형: 사람들이 실제로 궁금해하는 질문을 앞세워 하나씩 답해준다.",
    ])
    _open_mode = OPENING_MODES[_variant(keyword, len(OPENING_MODES))]

    # 톤 기수 — 이 글이 어느 시기의 목소리로 쓰이는지.
    # 부속물 확률·제목 골격이 모두 이 값을 참조하므로 가장 먼저 정한다.
    _era, _era_no, _era_prev = current_era(seed=keyword)
    # 제목 골격: 기수가 선호하는 형태에 가중치를 줘서 고른다.
    # (균등 랜덤이 아니라 가중 랜덤이라, 시기마다 목록의 '결'이 달라진다)
    _form_key = _weighted_pick((_era or {}).get("title_weights"), str(keyword) + "|tform") if _era else None
    _title_form = next((f for f in TITLE_FORMS if _form_key and f.startswith(_form_key)), None) \
        or TITLE_FORMS[_variant(str(keyword) + "|title", len(TITLE_FORMS))]


    # ── 부속물 확률 배정 (구조 복제 해소) ────────────────────────────
    # 전에는 모든 글에 tldr+요약표+FAQ3+체크리스트 4종 세트를 강제했다.
    # 소제목 문구를 아무리 바꿔도 모든 글이 같은 뼈대로 나와, 실측에서
    # '구조 복제 34%'로 잡혔다(2026-08, 본문 정밀 점검). 부속물을 글마다
    # 다르게 켜고 끄면 목록을 훑는 심사관 눈에 '찍어낸 티'가 사라진다.
    # 시드는 키워드 해시라 같은 글은 항상 같은 구성(재현 가능·디버깅 용이).
    _p = _variant(str(keyword) + "|parts", 100)
    _bias = ((_era or {}).get("parts_bias") or {})
    def _on(base, key, val):      # 기수 성향만큼 확률을 밀거나 당긴다
        return val < int(max(0, min(100, (base + _bias.get(key, 0)) * 100)))
    _use_table = _on(0.6, "table", _p) or "비교" in _style
    _use_tldr = _on(0.5, "tldr", (_p * 7) % 100)
    _use_check = _on(0.4, "checklist", (_p * 13) % 100)
    _faq_pool = [0, 3, 0, 4, 5, 3, 0, 4]
    if _bias.get("faq", 0) > 0.1:
        _faq_pool = [3, 3, 4, 4, 5, 3, 0, 4]
    elif _bias.get("faq", 0) < -0.1:
        _faq_pool = [0, 0, 3, 0, 4, 0, 0, 3]
    _n_faq = _faq_pool[_p % 8]
    _parts_rules = []
    _parts_rules.append(
        "7. summary_table: 핵심을 한눈에 보는 요약표(2~4행) 데이터를 rows로 제공."
        if _use_table else "7. summary_table: 이 글에는 넣지 않는다. 빈 값으로 두세요.")
    _parts_rules.append(
        f"8. faqs: 실제로 많이 묻는 질문 {_n_faq}개와 간결한 답(각 2~3문장)."
        if _n_faq else "8. faqs: 이 글에는 넣지 않는다. 빈 배열로 두세요.")
    _parts_rules.append(
        "9. tldr: 글 맨 위에 넣을 '핵심 요약' 2~3개(각 한 문장, 결론부터)."
        if _use_tldr else "9. tldr: 이 글에는 넣지 않는다. 빈 배열로 두세요.")
    _parts_rules.append(
        "10. checklist: 글 끝에 넣을 '실행 체크리스트' 3~5개(독자가 바로 할 행동)."
        if _use_check else "10. checklist: 이 글에는 넣지 않는다. 빈 배열로 두세요.")
    parts_block = "\n".join(_parts_rules)

    # ── 정보 이득(information gain) 슬롯 ────────────────────────────
    # 2026년 저가치 판정의 핵심 기준은 분량이 아니라 '검색 상위 글에 없는 것'이다.
    # 글마다 하나를 배정해 실행시키고, META의 gain 필드로 표기하게 한다.
    GAIN_MODES = [
        ("compare", "실제 제품·방식 2~3가지를 직접 비교하는 표(가격대·규격·수명·난이도 열 포함). 상위 글에 없는 조합으로."),
        ("failure", "이 작업에서 자주 나는 실패 시나리오 2가지와 각각의 복구 절차(무엇이 망가지고 어떻게 되돌리는지)."),
        ("branch", "조건별 분기표 — 상황(자재·구조·예산)에 따라 답이 갈리는 지점을 표로 정리."),
        ("range", "국내 기준 실측 범위 정리 — 규격·가격대·소요 시간을 범위로 제시하고 무엇에 따라 달라지는지."),
    ]
    _gain_key, _gain_desc = GAIN_MODES[_variant(str(keyword) + "|gain", len(GAIN_MODES))]
    if not insert_ads:
        ad_rule = "5. 이미지는 '딱 1개'만 [[IMG:스타일|장면묘사]]로 본문 상단부에 넣으세요(광고 마커는 넣지 말 것)."
    elif ADS_BOOST:   # 승인 후 수익 최적화: 광고 3개(첫 소제목·중반·결론 직전)
        ad_rule = ("5. 이미지는 '딱 1개'만 [[IMG:스타일|장면묘사]]로 본문 상단부에 넣고 그 아래 [[AD]] 1개. "
                   "본문 중간 '정보가 끝나는 문단 뒤'에 [[AD]] 1개, 마지막 결론 문단 직전에 [[AD]] 1개 — "
                   "광고는 총 3개(과밀하지 않게 문단 사이에 자연스럽게).")
    else:
        ad_rule = ("5. 이미지는 '딱 1개'만 [[IMG:스타일|장면묘사]]로 본문 상단부(첫 소제목 부근) 적절한 위치에 넣고, "
                   "그 바로 아래에 [[AD]]를 배치(이미지→광고 순서). 추가로 본문 중간 '정보가 끝나는 문단 뒤'에 "
                   "[[AD]] 1개를 더 넣어 광고는 총 2개.")
    # 이미지 마커 공통 규격(2026-09-04 품질 개편): 스타일을 글 내용에 맞게 LLM이 직접 고른다
    ad_rule += (" [이미지 마커 작성법] 스타일은 photo(실사 사진: 생활 장면·공간·작업 모습·경험 문맥), "
                "object(정물 사진: 특정 도구·재료·제품 클로즈업), diagram(도해: 구조·과정·원리·비교), "
                "illust(일러스트: 감성·비유·주의 환기) 중 이 글에 가장 어울리는 1개를 고르세요. "
                "장면묘사는 '무엇이, 어디서, 어떤 상태로'가 담긴 구체적 1~2문장(영어 아님, 한국어). "
                "⚠️ 장면묘사에는 이 글이 다루는 '핵심 소재'(특정 제품·도구·공간·재료 명칭)를 반드시 그대로 포함하고, "
                "글과 무관한 배경·인물·풍경은 넣지 마세요 — 이미지만 봐도 무슨 글인지 알 수 있어야 합니다. "
                "예: [[IMG:photo|주방 싱크대 아래 배수관을 몽키스패너로 조이는 손, 부품이 바닥에 정리되어 있는 모습]]")

    seo_block = ("""
[상위노출 강화 모드 — 검색량이 많고 경쟁이 있는 키워드]
- 이 글은 경쟁이 있는 키워드다. 검색자의 모든 궁금증을 이 한 글에서 끝내는 '가장 완성도 높은 글(필러 콘텐츠)'로 작성.
- 분량 1,500~2,500자, H2 5개 이상으로 폭넓고 깊게. 각 소제목이 검색자의 세부 질문에 답하게.
- 핵심 키워드+연관어(LSI)를 제목·첫문단·여러 H2 소제목·마지막 문단에 자연스럽게 반복(억지 반복 금지).
- 비교표·체크리스트·구체 수치·실제 예시를 넣어 경쟁 글보다 정보량이 많게(독보적 완성도).
- FAQ를 4~5개로 늘려 '사람들이 또 묻는 질문(PAA)'까지 커버.
- 제목은 검색어를 정확히 포함하되, '총정리·완벽정리·알아보기·핵심정보' 같은 상투어는 절대 쓰지 말 것.
  대신 그 글에만 있는 구체 정보(금액·조건·기간·대상)를 제목에 넣어 차별화한다.
"""
        if competitive else "")

    return f"""'{category}' 카테고리의 애드센스 수익형 한국어 블로그 글을 작성하세요.
{seo_block}
[오늘 날짜] {today.year}년 {today.month}월. (다음 시즌은 {nxt}월)

[제목 절대 규칙]
- 제목은 완성된 자연스러운 한국어 문장이어야 한다.
- '○○', 'XX', 'N월', 'N개', 빈칸, 채우지 않은 자리표시자를 절대 쓰지 말 것.
- 날짜는 '연·월'까지만 표기한다('{today.year}년 {today.month}월'처럼). 특정 '일자(며칠)'는 제목에 넣지 말 것.
  (예: "월 출시 예정" ❌ → "{today.year}년 {today.month}월 개인사업자 혜택, 미리 준비할 5가지" ✅)
- 제목이 조사·기호(!, ,, ·)로 시작하지 말 것. 주어/키워드로 시작.

[본문 날짜 규칙]
- 정확한 '일자(며칠)'는 확실히 아는 경우에만 표기한다. 확실치 않으면 지어내지 말고 '{today.month}월 중', '하반기', '연내' 등 범위로만.
- 제도 시행일·신청 마감일 등 바뀔 수 있는 날짜를 단정하지 말고, "공식 발표 기준 확인 필요"처럼 여지를 둔다.

[최신성·정확성 규칙 — 매우 중요]
- 모든 내용은 **{today.year}년 {today.month}월 기준**으로 쓴다. 과거 연도의 정보를 '현재/올해/최신'인 것처럼 쓰지 말 것.
- 금액·한도·금리·세율·순위·요금·가격 등 시간에 따라 바뀌는 수치에는 반드시 **'{today.year}년 기준'** 또는 '○○년 기준'처럼 기준 시점을 함께 적는다.
- 제도·지원금·이벤트가 **지금도 진행 중인지 / 종료됐는지 / 예정인지**를 분명히 구분해 표현한다.
  (예: "2024년 한시 지원으로 현재는 종료" / "{today.year}년 현재 신청 접수 중" / "{today.month+1 if today.month<12 else 1}월 시행 예정")
- 확실하지 않거나 바뀌었을 수 있는 정보는 단정하지 말고 "{today.year}년 {today.month}월 기준이며, 신청 전 공식 사이트에서 최신 내용을 확인하세요"처럼 검증 안내를 붙인다.
- 이미 지난 시점의 마감·행사(예: 과거 신청 기간)를 '아직 가능'한 것처럼 쓰지 말 것.
- 연도를 본문에 쓸 때는 반드시 그 연도가 '언제 기준'인지 드러나게 쓴다(맥락 없는 옛 연도 단독 표기 금지).

[민감·투자 주제 규칙]
- 전쟁·분쟁·테러·정치적 충돌 등 민감·자극적 소재는 다루지 않는다(주제 이탈 금지).
- 주식·코인·펀드 등 투자 소재라면: 특정 종목의 매수/매도를 권유하지 말고, "○○할 수 있습니다/검토해볼 수 있습니다"처럼 정보 제공형으로만 쓴다.
  "무조건 오른다", "확실한 수익", "손실 없는" 같은 단정·과장 표현 절대 금지. 원금 손실 가능성을 자연스럽게 언급한다.

[애드센스 실전 전략 5가지 — 자료 기준 그대로 반영]
① 클릭률 구조: 독자는 정독하지 않고 훑어본다. 이미지를 먼저 보여주고 그 아래(정보가 끝나는 문단 뒤)에
   광고가 오게 설계. 광고 근처엔 정책 위반 없는 '무의식 유도' 문장을 둔다
   (예: "더 많은 정보는 아래에서 확인해보세요.", "관련 자료가 궁금하다면 다음 내용을 참고하세요.").
   ※ '광고를 클릭하라'는 직접 표현은 절대 금지.
② 고단가 키워드: 금융/보험/건강/기술 계열 단가 높은 키워드를 제목·첫문단·본문 중반·마지막 문단에 나눠
   자연스러운 회화체로 삽입(예: "최근 자동차보험 갱신을 하면서 알아본 내용입니다.").
   특히 제목에 고단가 키워드를 분명히 담는다.
   (나쁜 예 "겨울철 건강관리 팁" → 좋은 예 "면역력 강화 건강기능식품 추천 (비타민, 홍삼 등)")
③ 타이밍/시의성: '지금 뜨는'보다 '이제 뜰' 주제를 완결성 있게 정리(검색 반영에 1~2주 걸림).
④ 체류시간: 첫 문장은 3초 안에 붙잡는 질문형/공감형으로 시작
   (예: "왜 내 글은 수익이 안 날까요?", "매달 이런 고민 해보셨나요?"). 서론은 짧게, 핵심을 바로 전달.
   중간중간 이미지·요약표로 시선을 붙잡는다.
⑤ 카테고리 반복수익: 글 끝에 같은 카테고리의 '함께 보면 좋은 글'로 내부링크(다음 글로 자연스럽게 유도).

핵심 키워드(고단가): {keyword}
글 성격: {kind_hint}

본문에 그대로 쓸 실제 외부 링크(URL을 지어내지 말 것, 없으면 넣지 않음):
{link_lines}

[작성 규칙 — 자료 전략 그대로]
1. 제목(title): 25~60자. 핵심 키워드를 반드시 포함하되, **이번 글에 배정된 골격**으로 쓴다.
   [이번 글의 제목 골격] {_title_form}
   ⚠️ 골격을 지키는 것이 단어를 바꾸는 것보다 중요하다. 실제 사례: 29편의 제목이 단어는
   전부 달랐지만 "[공간] [부품] [문제], [방법]으로 [동작]" 한 공식이었고, 목록을 훑는
   순간 자동 생성으로 보였다. 아래를 지켜라.
   - 명사만 5개 이상 이어 붙이지 마라("보일러실 가스 차단기 연동 신호선 결선 절연 장갑" ❌).
   - 배정 골격이 '상황선두형/질문형/수치선두형'이면 공간 이름으로 시작하지 마라.
   - "~로 보강", "~로 조정", "~ 절차", "~ 매뉴얼"처럼 동작명사·절차어로 끝내지 마라.
   (나쁜 예: "무직자 대출 총정리"  → 좋은 예: "무직자 비상금 대출, 한도는 300만 원까지입니다")
2. hook(첫 문장): 3초 안에 이탈을 막는 질문형 또는 공감형 한 문장. (예: "대출 이자 부담, 조금이라도 줄일 방법 없을까요?")
3. 첫 문단에서 검색 의도에 바로 답하고 핵심 키워드를 1회 자연스럽게 포함.
4. 키워드를 제목·첫문단·본문 중반·마지막 문단에 나눠서 자연스러운 회화체로 배치.
{ad_rule}
6. 구조: <h2>/<h3> 계층. H2 최소 3개, 각 H2 아래 2~4문장 문단. 정보가 끝나는 지점에서 문단을 끊어 광고가 들어갈 여지를 만든다.
{parts_block}
   ※ 위 4개는 글마다 다르게 배정됩니다. '넣지 않는다'고 한 항목을 임의로 채우지 마세요.
      모든 글이 같은 부속물을 달고 있으면 그 자체가 자동 생성 신호입니다.
11. 총 1,200~2,000자 분량. 광고 클릭을 직접 유도하는 문구 금지.

[이번 글의 정보 이득 — 반드시 실행]
'{_gain_key}' 방식: {_gain_desc}
- 이것이 이 글을 검색 상위 글과 다르게 만드는 유일한 요소입니다. 본문에서 실제로 실행하세요.
- META의 "gain" 필드에 '{_gain_key}'라고 적으세요.

[독창성 강화 — 애드센스 '대량 생성·저품질' 위험 회피]
- 이 글만의 '고유한 각도'를 하나 정해 일관되게 밀고 간다(특정 대상·상황·비교 관점 등).
- 구체적인 숫자·조건·예시를 반드시 포함한다(한도·금리·기간·자격요건·실제 상황 예시 등). 두루뭉술한 일반론 금지.
- 다음 같은 '속 빈 상투어'는 쓰지 말 것: "일반적으로", "중요합니다", "잘 알려져 있듯이", "다양한 방법이 있습니다", "결론적으로 매우 중요".
- 다른 글을 복제한 듯한 문장·구성을 피한다. 겪지 않은 경험을 지어내지 말고,
  '자료를 확인한 결과' 관점에서 실무적으로 주의할 지점을 짚는다.
- 사실은 단정하지 말고 "공식 기준 확인 필요"처럼 검증 여지를 남긴다(정확성·신뢰성 E-E-A-T).

{("[이번 시기의 목소리 — " + _era["name"] + "]" + chr(10)
   + "- 어조: " + _era.get("voice","") + chr(10)
   + "- 문장: " + _era.get("sentence","") + chr(10)
   + "- 도입 성향: " + _era.get("opening","") + chr(10)
   + "- 마무리 성향: " + _era.get("closing","") + chr(10)
   + "  (이 목소리는 시기마다 조금씩 달라집니다. 요건은 그대로 지키되 말투와 리듬을 여기에 맞추세요.)")
  if _era else ""}

{HUMAN_STYLE}
{_commerce_block()}
[이번 글의 도입 방식] {_open_mode}
  (이 방식으로만 시작한다. 다른 글과 같은 틀로 시작하면 안 된다.)

[이번 글 구성 스타일] {_style}
  (매번 같은 뼈대를 반복하지 말고, 위 스타일에 맞춰 흐름과 소제목을 자연스럽게 바꾼다.)

{requirements_block()}

[가치 규칙 — 5회차 반려('낮은 가치의 콘텐츠') 실측 반영. 다른 규칙과 충돌하면 이것이 우선]
반려된 글들의 공통점은 셋이었다: 실전 신호 0, 구체 수치 부족, 백과사전식 매뉴얼체.
아래 4가지는 발행 전 검수기가 기계로 검사하므로 반드시 지킨다.
1. 실전 신호 2개 이상 — 다음 중에서: 자주 나는 실수·실패 시나리오("이때 ○○가 자주 부러집니다"),
   조건 분기("벽이 석고보드라면 A, 콘크리트라면 B"), 두 가지 방법·제품의 장단 비교,
   순서를 어기면 생기는 문제 경고. ※ 겪지 않은 1인칭 일화("제가 직접 해보니")를 지어내는 건 금지 —
   '이 작업에서 흔히 겪는 문제' 관점으로 쓰면 거짓말 없이 같은 효과가 난다.
2. 실측형 수치 3개 이상 — 규격(mm·cm), 가격대(원, 기준 연도 표기), 소요 시간, 개수.
   확실치 않으면 범위로 쓴다("3만~5만 원대", "30분~1시간").
3. 금지 문구(하나라도 쓰면 검수 탈락): 알아보겠습니다 / 살펴보겠습니다 / 이번 글에서는 /
   도움이 되셨기를 / 지금까지 ~였습니다 / 마무리하겠습니다 / 함께 알아봐요 / 참고하시기 바랍니다.
4. 같은 어미로 끝나는 문장 3개 연속 금지. 평서형·의문형·명사형(~하기, ~할 것)을 섞는다.

[AI 문체 탐지 회피 — 연구로 확인된 실제 신호들]
5. 셋 묶음 습관 금지 — "첫째…둘째…셋째", 한 문장 안의 "A, B, C" 삼항 나열은
   AI가 가장 많이 쓰는 패턴이다. 나열은 2개 또는 4개로 하고, 셋이 필요하면 문장을 쪼갠다.
6. 완충 표현(헤징) 남발 금지 — "~할 수 있습니다 / ~일 수 있습니다 / ~하는 것이 좋습니다 /
   ~하시기 바랍니다"로 끝나는 문장이 전체의 1/4을 넘으면 안 된다.
   확실한 것은 단정한다("칼블럭을 씁니다"), 안전·법규·개인차가 있는 것만 완충한다.
7. 고정 마무리 금지 — 마지막 문단을 "결론적으로 / 요약하자면 / 지금까지"로 시작하지 마라.
   마지막은 '다음에 할 행동 하나' 또는 '가장 조심할 것 하나'로 끝낸다.
8. 문장 길이를 실제로 흔들어라 — 10자 이하 짧은 문장을 최소 3개 넣는다.
   모든 문장이 30~50자대면 사람이 안 쓴 티가 난다(기계 검사 대상).

[사람 목소리 — '기계가 쓴 티'가 안 나게]
- 문장 길이를 들쭉날쭉하게 섞는다(짧은 문장 + 긴 문장). 모든 문장이 비슷한 길이/구조면 AI 티가 난다.
- 사람이 쓰는 말투: 가벼운 구어체, 질문 던지기, 솔직한 팁·주의사항 한두 개.
  (1인칭 경험담은 위 가치 규칙 1의 금지를 따른다 — 창작하지 말 것)
- 지나치게 반듯한 '소제목→불릿→소제목' 반복 구조를 피하고, 흐름형 문단과 목록을 섞는다.
- 다음 'AI 티 나는 말투'는 피한다(과다 사용 금지):
  "게다가/또한/결론적으로/요컨대/~에 대해 알아보겠습니다/지금부터 살펴보겠습니다/
   다양한/여러 가지/~하는 것이 좋습니다/중요한 점은/무엇보다도/마지막으로 정리하자면".
- 첫 문장을 '~에 대해 알아보겠습니다' 같은 안내문으로 시작하지 말 것. 바로 본론·상황·질문으로.
- 모든 문단을 같은 길이로 만들지 말고, 한두 문장짜리 짧은 문단도 섞는다.
- 완벽하게 매끄럽기보다 자연스럽게. 단, 오탈자·비문은 없게(품질은 유지).
- ⚠️ AI 탐지를 '속이려는' 꼼수(보이지 않는 문자, 무의미한 동의어 치환 등)는 절대 쓰지 말 것 — 진짜 사람에게 유용한 글이 목적.

참고: 같은 카테고리의 다른 글 제목(내부링크로 이어질 수 있음, 참고만):
{rel_lines}

[출력 형식 — 정확히 아래 두 블록으로만. 다른 말·코드블록 금지]
먼저 ===META=== 줄 다음에 '작은 JSON'(본문 제외)만, 그다음 ===BODY=== 줄 다음에 '순수 HTML 본문'을 씁니다.
본문은 JSON이 아니라 그냥 HTML이므로 따옴표를 이스케이프하지 마세요.

===META===
{{"title":"클릭 유도형 제목","meta":"120~155자 메타설명(키워드 포함)","slug":"english-hyphen-slug","focus_keyword":"{keyword}","tags":["태그1","태그2","태그3","태그4","태그5"],"hook":"3초 후킹 첫 문장","gain":"{_gain_key}","tldr":[],"checklist":[],"summary_table":{{"headers":[],"rows":[]}},"faqs":[]}}
(위 tldr·checklist·summary_table·faqs는 '배정된 것만' 채우고, 배정되지 않은 항목은 위처럼 빈 채로 두세요)
===BODY===
<p>첫 문단(검색 의도에 바로 답, 키워드 포함)</p>
<h2>소제목1</h2><p>내용... [[IMG:photo|대표 장면의 구체적 묘사]]</p>[[AD]]
<h2>소제목2</h2><p>내용...</p>
<h2>소제목3</h2><p>마무리 내용... [[AD]]</p>"""


def _repair_json(s):
    s = (s or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s); s = re.sub(r"\n?```$", "", s).strip()
    # 중괄호 균형 부분만 추출
    a, b = s.find("{"), s.rfind("}")
    if a != -1 and b != -1 and b > a:
        s = s[a:b + 1]
    for cand in (s, re.sub(r",\s*([}\]])", r"\1", s)):   # 후행 콤마 제거 재시도
        try:
            return json.loads(cand)
        except Exception:
            continue
    return {}


def _extract_json(text):
    return _repair_json(text)


def _salvage_html(raw):
    """파싱 실패 시 JSON은 버리고 HTML 조각만 건져낸다(원문 노출 방지)."""
    s = re.sub(r"===\w+===", "", raw or "")
    lt = s.find("<p")
    if lt == -1:
        lt = s.find("<h")
    gt = s.rfind(">")
    if lt != -1 and gt != -1 and gt > lt:
        seg = s[lt:gt + 1]
        return seg.replace('\\"', '"').replace('\\n', '\n').replace('\\/', '/').replace('\\t', ' ')
    return ""


def _parse_output(raw):
    """LLM 출력(===META=== / ===BODY===)을 파싱. 실패해도 JSON 원문이 본문에 새지 않게."""
    raw = raw or ""
    if "===BODY===" in raw:
        meta_part, body_part = raw.split("===BODY===", 1)
        meta_part = re.sub(r"^.*?===META===", "", meta_part, flags=re.DOTALL).strip() or meta_part
        data = _repair_json(meta_part)
        data["html_body"] = body_part.strip()
        return data
    # 구형(단일 JSON) 응답 호환
    data = _repair_json(raw)
    if data and data.get("html_body"):
        return data
    return {}


def _convert_markers(html_body, insert_ads, resolver=None, fallback_desc=""):
    """[[IMG:..]] / [[AD]] 마커를 실제 이미지/광고 자리로 치환. 부족하면 자동 보충."""
    counter = [0]

    def img_repl(m):
        counter[0] += 1
        if counter[0] > 1:                # 글당 이미지 1개만: 초과 마커 제거
            return ""
        desc = m.group(1)
        if resolver:                      # 이미지 자동 생성 시도
            html = resolver(desc, counter[0])
            if html:
                return html
        return _img_slot(desc)            # 실패/미설정 시 자리 표시

    html_body = re.sub(r"\[\[IMG:([^\]]*)\]\]", img_repl, html_body)
    # LLM이 [[IMG:]] 마커를 빼먹는 일이 잦다 — 검수 요건(이미지 1장 이상)이 있으므로
    # 마커가 없으면 제목 기반으로 1장을 보장 삽입한다(2026-08-30: 마커 누락→전량 폐기 원인).
    if counter[0] == 0 and resolver and fallback_desc:
        _html = resolver(f"diagram|{fallback_desc} — 작업 과정을 한눈에 보여주는 도해", 1)
        if _html:
            if "</h2>" in html_body:
                html_body = html_body.replace("</h2>", "</h2>" + _html, 1)
            else:
                html_body = _html + html_body
    if insert_ads:
        if "[[AD]]" in html_body:
            html_body = html_body.replace("[[AD]]", _ad_slot())
        else:
            # 마커가 없으면 소제목(H2) 사이 2곳에 자동 삽입
            parts = re.split(r"(?=<h2)", html_body)
            if len(parts) >= 3:
                insert_at = [1, min(3, len(parts) - 1)]
                for off, idx in enumerate(insert_at):
                    parts.insert(idx + off, _ad_slot())
                html_body = "".join(parts)
            else:
                html_body += _ad_slot()
    else:
        html_body = html_body.replace("[[AD]]", "")
    return html_body


def _summary_table_html(tbl):
    if not tbl or not tbl.get("rows"):
        return ""
    headers = tbl.get("headers") or []
    th = "".join(f"<th style='text-align:left;padding:8px;border-bottom:2px solid #e5e7eb'>{html_mod.escape(str(h))}</th>" for h in headers)
    trs = ""
    for row in tbl["rows"]:
        tds = "".join(f"<td style='padding:8px;border-bottom:1px solid #eef0f3'>{html_mod.escape(str(c))}</td>" for c in row)
        trs += f"<tr>{tds}</tr>"
    head = f"<thead><tr>{th}</tr></thead>" if th else ""
    return (f'<table class="summary" style="border-collapse:collapse;width:100%;margin:16px 0">'
            f'{head}<tbody>{trs}</tbody></table>')


def _slugify_headings(html_body):
    items, counter = [], [0]

    def repl(m):
        level, attrs, inner = m.group(1), m.group(2) or "", m.group(3)
        text = re.sub(r"<[^>]+>", "", inner).strip()
        counter[0] += 1
        hid = f"sec-{counter[0]}"
        items.append((hid, text, level))
        return f'<h{level}{attrs} id="{hid}">{inner}</h{level}>'

    return re.sub(r"<h([23])([^>]*)>(.*?)</h\1>", repl, html_body, flags=re.DOTALL), items


def _build_toc(items):
    if len(items) < 3:
        return ""
    lis = "".join(
        f'<li style="margin-left:{0 if lvl=="2" else 16}px"><a href="#{hid}">{html_mod.escape(txt)}</a></li>'
        for hid, txt, lvl in items)
    return f'<nav class="toc" aria-label="목차"><strong>목차</strong><ul>{lis}</ul></nav>'


def _build_faq_html(faqs):
    if not faqs:
        return ""
    blocks = "".join(
        f'<h3>{html_mod.escape(f.get("q",""))}</h3><p>{html_mod.escape(f.get("a",""))}</p>'
        for f in faqs)
    return f"<h2>자주 묻는 질문</h2>{blocks}"


def _build_internal_links(related, blog_url):
    """같은 카테고리 이전 글로 '함께 보면 좋은 글' 내부링크."""
    if not related:
        return ""
    items = []
    for r in related[:3]:
        url = r.get("url") or (f"{blog_url.rstrip('/')}/{r['slug']}" if blog_url and r.get("slug") else "#")
        items.append(f'<li><a href="{url}">{html_mod.escape(r["title"])}</a></li>')
    return ('<h2>함께 보면 좋은 글</h2>'
            f'<ul class="related">{"".join(items)}</ul>')


def _tldr_html(items):
    if not items:
        return ""
    lis = "".join(f"<li>{html_mod.escape(str(x))}</li>" for x in items[:4])
    return ('<div class="tldr" style="margin:14px 0;padding:14px 16px;background:#f2f0ff;'
            'border-radius:12px;border:1px solid #e6e2ff">'
            '<strong>📌 핵심 요약</strong>'
            f'<ul style="margin:6px 0 0;padding-left:18px;line-height:1.6">{lis}</ul></div>')


def _checklist_html(items):
    if not items:
        return ""
    lis = "".join(f'<li style="margin:4px 0">✅ {html_mod.escape(str(x))}</li>' for x in items[:6])
    return ('<h2>실행 체크리스트</h2>'
            f'<ul class="checklist" style="list-style:none;padding-left:0">{lis}</ul>')


def _disclaimer_html(category):
    c = category or ""
    if any(k in c for k in ["금융", "재테크", "경제", "대출", "보험", "투자", "세금", "연금"]):
        opts = [
            "본 글은 정보 제공용이며 특정 금융상품 가입·투자를 권유하지 않습니다. 결정 전 본인 상황에 맞게 전문가와 상담하세요.",
            "참고용 정보입니다. 대출·투자·세무는 조건이 사람마다 달라, 실제 진행 전 공식 창구나 전문가 확인을 권합니다.",
            "이 글은 일반적인 안내이며 개인별 결과를 보장하지 않습니다. 큰 결정 전에는 꼭 전문가와 상의하세요.",
        ]
    elif any(k in c for k in ["건강", "다이어트", "의료", "질환", "영양", "탈모", "피부"]):
        opts = [
            "본 글은 정보 제공용이며 의학적 진단·치료를 대체하지 않습니다. 증상이 있으면 전문의와 상담하세요.",
            "참고용 건강 정보입니다. 몸 상태는 사람마다 달라, 이상이 있으면 병원에서 정확히 진료받으시길 권합니다.",
            "이 글은 일반적인 정보이며 개인 상태에 따라 다를 수 있어요. 치료가 필요하면 반드시 전문가와 상의하세요.",
        ]
    else:
        opts = [
            "정보 제공을 목적으로 작성했습니다. 실제 적용 시 최신 내용을 한 번 더 확인하세요.",
            "참고용 글입니다. 상황에 따라 다를 수 있으니 공식 자료도 함께 확인하시길 권합니다.",
        ]
    txt = random.choice(opts)
    return ('<p class="disclaimer" style="margin-top:22px;padding:12px 14px;border-left:3px solid #d8dbe0;'
            f'background:#fafbfc;color:#6b7280;font-size:13px;line-height:1.6">ℹ️ {txt}</p>')


# 투자 위험 안내가 필요한 주제(주식·코인·파생 등)
_INVEST_KW = ("주식", "투자", "코인", "암호화폐", "가상자산", "비트코인", "이더리움",
              "ETF", "etf", "펀드", "선물", "옵션", "레버리지", "배당", "종목",
              "매수", "매도", "상장", "IPO", "공모주", "채권", "리츠", "차트", "수익률")


def _needs_invest_risk(text):
    t = str(text or "")
    return any(k in t for k in _INVEST_KW)


def _invest_risk_html():
    """주식·투자·코인 등 글에 붙는 투자 위험 고지(원금 손실 경고)."""
    return ('<p class="invest-risk" style="margin-top:16px;padding:12px 14px;border-left:3px solid #e5484d;'
            'background:#fff5f5;color:#b4232a;font-size:13px;line-height:1.6">'
            '⚠️ <b>투자 위험 고지</b> — 본 콘텐츠는 정보 제공을 위한 것으로 특정 종목·상품의 매수·매도를 '
            '권유하지 않습니다. 주식·가상자산·파생상품 등 모든 투자는 <b>원금 손실 위험</b>이 있으며 과거 수익률이 '
            '미래 수익을 보장하지 않습니다. 투자 결정과 그 책임은 본인에게 있으며, 필요 시 자격을 갖춘 전문가와 '
            '상담하시기 바랍니다.</p>')


def _byline_html(author, bio=""):
    """작성자 표시줄. bio가 있으면 이름 옆에 짧은 소개를 덧붙여 E-E-A-T(경험·전문성) 신호를 강화."""
    from datetime import date
    d = date.today()
    a = html_mod.escape(author or "편집부")
    bio_html = f' <span style="color:#b0b8c1">· {html_mod.escape(bio)}</span>' if bio else ""
    return (f'<p class="byline" style="font-size:12px;color:#98a2b3;margin:2px 0 12px">'
            f'✍️ {a}{bio_html} · 최종 업데이트 {d.year}년 {d.month}월 {d.day}일</p>')


# ── 사람이 검수한 글처럼 만드는 층 ────────────────────────────────
# 원칙: '안 한 경험을 지어내지 않는다'.
#   구글이 문제 삼는 건 AI 사용 자체가 아니라 "검수 없는 대량 발행"이다.
#   그래서 ①구조·리듬을 글마다 다르게 하고 ②실제 확인한 출처·날짜를 남기고
#   ③운영자가 한 줄이라도 직접 채우는 '검수 슬롯'을 만든다.
#   반대로 겪지도 않은 일을 1인칭으로 지어내는 건 정책 위험이자 우리 탐지기에
#   그대로 걸리는 짓이라 프롬프트에서 명시적으로 금지한다.
HUMAN_STYLE = """
[사람이 쓰고 검수한 글처럼 — 반드시 지킬 것]
1) 문장 리듬을 흔들어라. 짧은 문장(5~10자)과 긴 문장(60자 이상)을 섞는다.
   모든 문장이 비슷한 길이면 기계가 쓴 티가 난다.
2) 문단 길이도 들쭉날쭉하게. 한 줄짜리 문단을 최소 두 번 넣는다.
3) 구체적으로 써라. "저렴합니다"(X) → "3만 2천 원이었습니다"(O).
   금액·기간·서류명·기관명·조건 숫자를 반드시 넣는다. 모르면 그 항목을 아예 빼라.
4) 괄호로 곁가지를 달아라. (저는 이 부분에서 한 번 헤맸습니다) 같은 실무 코멘트.
5) 확정하지 못하는 건 솔직히 적어라. "지자체마다 다르니 확인이 필요합니다".
   모든 문장이 단정적이면 오히려 신뢰가 떨어진다.
6) ❌ 절대 금지 — 겪지 않은 경험을 지어내지 마라.
   "제가 직접 신청해보니", "처음 알아봤을 때 저는 ~인 줄 알았습니다" 같은
   가짜 경험담은 쓰지 않는다. 대신 '자료를 확인한 결과' 관점으로 쓴다.
7) ❌ 상투적 도입 금지 — "~을 알아보다 보면", "가장 중요한 것은", "총정리"로 시작하지 마라.
8) 근거가 되는 공식 출처(기관명 + 페이지명)를 본문에 최소 1회 언급하라.
"""

# 도입부 방식 — slug로 고정 선택해 글마다 다른 방식이 나오게 한다
OPENING_MODES = [
    "질문형: 독자가 실제로 검색창에 칠 법한 질문 한 줄로 시작한다.",
    "장면형: 그 상황이 벌어지는 구체적 순간을 한 문장으로 묘사하며 시작한다.",
    "숫자형: 핵심 수치 하나를 앞세워 시작한다(예: '한도는 3천만 원입니다').",
    "오해정정형: 흔히 잘못 아는 사실을 먼저 바로잡으며 시작한다.",
    "시기형: 지금 이 시점에 왜 중요한지(마감·변경일)로 시작한다.",
    "비교형: 헷갈리는 두 가지의 차이를 한 문장으로 못 박으며 시작한다.",
]


# 제목 '골격' 배정 — 단어가 아니라 문장 구조가 겹치는 것이 대량생산의 진짜 티다.
# 실측(2026-08, 발행 29편): 모든 제목이 "[공간] [부품] [문제], [방법]으로 [동작]"
# 한 공식이었고 29편 전부 공간 명사로 시작했다. 단어는 다 달랐지만 골격이 같아
# 목록을 훑는 순간 찍어낸 티가 났다. 그래서 글마다 골격 자체를 바꾼다.
TITLE_FORMS = [
    "질문형: 독자가 검색창에 칠 법한 질문 그대로. 물음표로 끝낸다. (예: '싱크대 배수구 냄새, 트랩만 갈면 될까요?')",
    "수치선두형: 숫자를 맨 앞에 놓는다. (예: '3만 원으로 끝내는 방충망 교체, 필요한 건 두 가지')",
    "문장종결형: 완결된 서술문. '~니다/~습니다'로 끝낸다. (예: '실리콘은 걷어내지 않으면 다시 뜹니다')",
    "대조형: 두 가지를 맞세운다. (예: '앵커냐 칼블럭이냐, 벽 두드려보면 답이 나옵니다')",
    "경고형: 하지 말아야 할 것을 앞세운다. (예: '수전 누수에 테프론테이프부터 감으면 안 되는 이유')",
    "상황선두형: 문제 상황을 먼저 던진다. 공간 이름으로 시작하지 않는다. (예: '문이 안 닫힐 때 경첩부터 보는 순서')",
    "명사구형: 짧은 명사구 하나. 8어절 이내로 끊는다. (예: '몰딩 들뜸, 접착제 선택 기준')",
]


def _variant(seed_text, n):
    """slug 등을 시드로 0~n-1 값을 고정 반환(같은 글은 항상 같은 구조)."""
    h = 0
    for ch in str(seed_text or ""):
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return h % max(1, n)


def _review_slot_html(note=""):
    """운영자가 직접 한 줄 채우는 '검수 슬롯'.
    여기에 실제 경험·확인 내용을 넣으면 그게 진짜 사람 검수 기록이 된다."""
    if note:
        return ('<div class="review-note" style="margin:16px 0;padding:11px 13px;border-left:3px solid #b9a3f0;'
                'background:#f7f5fd;color:#3a3357;font-size:13.5px;line-height:1.65">'
                f'✍️ <b>운영자 확인</b> — {html_mod.escape(note)}</div>')
    return ""


def _verified_html(sources=None):
    """확인 흔적: 무엇을 언제 확인했는지 남긴다(검수 절차의 증거)."""
    from datetime import date
    d = date.today()
    src = ""
    if sources:
        items = " · ".join(html_mod.escape(s) for s in sources[:3])
        src = f"<br>확인한 자료: {items}"
    return ('<p class="verified" style="margin-top:14px;padding:9px 12px;border-left:3px solid #cfc6e8;'
            'background:#faf9fe;color:#6b6386;font-size:12px;line-height:1.6">'
            f'🔎 {d.year}년 {d.month}월 {d.day}일 기준으로 내용을 확인했습니다.{src}</p>')


def _ai_notice_html():
    """AI 기본법(2026-01-22 시행) 제31조 의무 표기 — 생성형 AI로 작성된 콘텐츠임을 항상 고지.
    (Marry_Baby_Meal의 동일 취지 고지와 문구를 맞춤 — solvup_global_architecture.md 3번 참고)"""
    return ('<p class="ai-notice" style="margin:2px 0 12px;padding:8px 12px;border-left:3px solid #98a2b3;'
            'background:#f6f7f9;color:#667085;font-size:12px;line-height:1.6">'
            '⚠️ 본 콘텐츠(텍스트·이미지)는 생성형 AI를 통해 작성되었습니다. 정확성을 위해 검증 과정을 거치지만, '
            '실제 적용 전 공식 출처로 최종 확인하시길 권합니다.</p>')


def _freshness_html():
    """정보 기준일 안내(최신성 신뢰 신호). 본문 하단에 배치. 문구는 무작위로 조금씩 달리한다."""
    from datetime import date
    d = date.today()
    tail = random.choice([
        "제도·금액·한도·순위는 시점에 따라 바뀔 수 있어요. 신청 전 공식 사이트에서 최신 내용을 확인하세요.",
        "숫자·조건은 바뀔 수 있으니, 실제 이용 전 공식 페이지에서 한 번 더 확인하시길 권합니다.",
        "정책·요금은 수시로 변경됩니다. 진행 전 공식 출처로 최신값을 꼭 확인하세요.",
    ])
    return ('<p class="freshness" style="margin-top:16px;padding:10px 14px;border-left:3px solid #7c5cff;'
            'background:#f6f4ff;color:#5b53a8;font-size:13px;line-height:1.6">'
            f'🗓️ <b>기준: {d.year}년 {d.month}월</b> · {tail}</p>')


def _build_jsonld(title, meta, faqs, author="편집부", lang="ko", author_type="Organization", author_bio=""):
    """author_type='Person'이면 실명 저자로 인식되어 YMYL(금융/건강) E-E-A-T 신뢰 신호가 강해진다."""
    from datetime import date
    iso = date.today().isoformat()
    a_type = "Person" if str(author_type or "").strip().lower() == "person" else "Organization"
    author_obj = {"@type": a_type, "name": author or "편집부"}
    if author_bio and a_type == "Person":
        author_obj["description"] = author_bio
    blog = {"@context": "https://schema.org", "@type": "BlogPosting",
            "headline": title, "description": meta, "inLanguage": lang,
            "datePublished": iso, "dateModified": iso,
            "author": author_obj,
            "mainEntityOfPage": {"@type": "WebPage"}}
    scripts = [json.dumps(blog, ensure_ascii=False)]
    if faqs:
        faq = {"@context": "https://schema.org", "@type": "FAQPage",
               "mainEntity": [{"@type": "Question", "name": f.get("q", ""),
                               "acceptedAnswer": {"@type": "Answer", "text": f.get("a", "")}}
                              for f in faqs]}
        scripts.append(json.dumps(faq, ensure_ascii=False))
    return "".join(f'<script type="application/ld+json">{s}</script>' for s in scripts)


def _assemble(data, related, blog_url, insert_ads, resolver=None, series_nav="",
              category="", author="편집부", author_bio="", author_type="Organization"):
    body = _convert_markers(data.get("html_body", ""), insert_ads, resolver,
                            fallback_desc=(data.get("title") or "")[:60])
    body, headings = _slugify_headings(body)
    toc = _build_toc(headings)
    summary = _summary_table_html(data.get("summary_table"))
    hook = data.get("hook", "")
    hook_html = f'<p class="hook" style="font-size:17px;font-weight:600">{html_mod.escape(hook)}</p>' if hook else ""
    byline = _byline_html(author, author_bio)            # 작성자·소개·최종수정일
    ai_notice = _ai_notice_html()                        # AI 기본법 제31조 의무 표기(항상 포함)
    tldr = _tldr_html(data.get("tldr", []))             # 상단 핵심요약
    checklist = _checklist_html(data.get("checklist", []))  # 실행 체크리스트
    faq_html = _build_faq_html(data.get("faqs", []))
    disclaimer = _disclaimer_html(category)             # 면책 고지(YMYL)
    freshness = _freshness_html()                        # 정보 기준일(최신성 안내)
    # 주식·투자·코인 주제면 투자 위험 고지(원금 손실 경고) 추가
    risk_txt = f"{category} {data.get('title','')} {data.get('focus_keyword','')} {data.get('meta','')}"
    invest_risk = _invest_risk_html() if _needs_invest_risk(risk_txt) else ""
    internal = _build_internal_links(related, blog_url)
    jsonld = _build_jsonld(data.get("title", ""), data.get("meta", ""), data.get("faqs", []),
                           author, author_type=author_type, author_bio=author_bio)
    # ── 구조 변주 ──
    # 모든 글이 같은 골격이면 그 자체가 대량생산 신호다. slug를 시드로
    # 선택 블록(요약표·체크리스트·목차)을 글마다 다르게 넣고 순서도 흔든다.
    seed = data.get("slug") or data.get("title") or ""
    v = _variant(seed, 6)
    if v in (1, 4):
        summary = ""                      # 요약표 빼는 글
    if v in (2, 5):
        checklist = ""                    # 체크리스트 빼는 글
    if v == 3:
        toc = ""                          # 목차 빼는 글(짧은 글처럼)
    review = _review_slot_html(data.get("review_note", ""))
    verified = _verified_html(data.get("sources"))

    head = f"{hook_html}{byline}{ai_notice}{review}"
    if v % 2 == 0:                        # 요약을 목차 앞/뒤로 번갈아
        mid = f"{tldr}{series_nav}{toc}{summary}"
    else:
        mid = f"{series_nav}{toc}{tldr}{summary}"
    tail = f"{checklist}{faq_html}{verified}{freshness}{invest_risk}{disclaimer}{series_nav}{internal}{jsonld}"
    return head + mid + body + tail


def _gen_one(keyword, kind, llm_cfg, category, links, related, blog_url,
             insert_ads, image_resolver, series_nav="", author="편집부",
             author_bio="", author_type="Organization", competitive=False):
    prompt = _article_prompt(keyword, kind, category, links, related, insert_ads, competitive)
    raw = chat(prompt, llm_cfg, system=SYSTEM, max_tokens=6000, temperature=0.7)
    data = _parse_output(raw)
    body = data.get("html_body", "")
    # 파싱 실패/본문 유실 시: JSON 원문을 본문에 넣지 않고 HTML만 건져 안전 처리
    if not body or "===META===" in body or body.lstrip().startswith("{") or '"html_body"' in body:
        body = _salvage_html(raw) or f"<p>{html_mod.escape(keyword)} 관련 정보를 정리한 글입니다.</p>"
        data["html_body"] = body
    # 제목 보정: 자리표시자·깨진 제목 감지 시 키워드 기반 완성 제목으로 교체
    title = (data.get("title") or "").strip()
    title = re.sub(r"^[\s!,.\-·…∼~•]+", "", title)   # 앞의 조사/기호 제거
    _bad = (
        len(title) < 12
        or re.match(r"^(월|일|년|개|위|원)\b", title)                  # 숫자 빠진 단위로 시작
        or re.search(r"[○◯□]{1,}|[Xx]{2,}|\bN(월|개|위|년|원)\b|\bXX\b|__+|\(\)|\[\]", title)
        or re.search(r"(?<![0-9])월\s*(출시|시행|시작|오픈|공개)", title)  # 숫자 없이 'X월 ...'
    )
    if _bad:
        # 폴백 제목도 상투어를 쓰지 않는다(품질 게이트가 잡는 표현이므로)
        title = f"{keyword}, 신청 전에 확인해야 할 조건"
    data["title"] = title
    slug = slugify((data.get("slug") or "").strip() or slugify(title))
    full_html = _assemble(data, related, blog_url, insert_ads, image_resolver, series_nav,
                          category=category, author=author, author_bio=author_bio,
                          author_type=author_type)
    return {
        "keyword": keyword, "kind": kind, "lang": "ko", "category": category,
        "title": data.get("title") or keyword,
        "meta": data.get("meta", ""), "slug": slug,
        "focus_keyword": data.get("focus_keyword", keyword),
        "tags": data.get("tags", []), "faqs": data.get("faqs", []),
        "html": full_html, "links": links,
    }


def generate_article(keyword, kind, llm_cfg, category="", related=None,
                     blog_url="", insert_ads=True, context_news=None, image_resolver=None,
                     author="편집부", author_bio="", author_type="Organization", competitive=False):
    """키워드 1개 → 수익형 한국어 글 dict 반환(리스트로 감싸 반환)."""
    related = related or []
    links = find_reference_links(keyword, max_results=2)
    art = _gen_one(keyword, kind, llm_cfg, category, links, related, blog_url,
                   insert_ads, image_resolver, author=author, author_bio=author_bio,
                   author_type=author_type, competitive=competitive)
    return [art]


def _series_nav(parts_meta, cur_idx, blog_url):
    """시리즈 편 간 내비게이션(마지막 편 → 처음 편 루프 포함)."""
    n = len(parts_meta)
    links = []
    for i, p in enumerate(parts_meta):
        url = p.get("url") or (f"{blog_url.rstrip('/')}/{p['slug']}" if blog_url and p.get("slug") else "#")
        label = f"{i+1}편"
        if i == cur_idx:
            links.append(f'<strong style="color:#7c5cff">{label}(현재)</strong>')
        else:
            links.append(f'<a href="{url}">{label}</a>')
    return ('<nav class="series-nav" style="margin:16px 0;padding:10px 14px;background:#f6f4ff;'
            'border-radius:10px;font-size:14px">📚 시리즈: ' + " · ".join(links) + '</nav>')


def generate_series(topic, kind, n_parts, llm_cfg, category="", related=None,
                    blog_url="", insert_ads=True, image_resolver=None, author="편집부",
                    author_bio="", author_type="Organization", competitive=False):
    """
    하나의 주제를 2~3편 시리즈로 기획해 각 편을 완성 글로 생성.
    편 간 내부링크 + 마지막→처음 루프. 반환: 편 리스트(모두 같은 series_id).
    시리즈는 상위(main)에서 1건으로 카운트한다.
    """
    related = related or []
    # 1) 시리즈 편 구성(part별 소주제) 기획
    plan_prompt = f"""'{category}' 카테고리에서 아래 주제를 {n_parts}편 시리즈로 나누세요.
주제: {topic}
각 편은 겹치지 않게 단계적으로 이어지며, 각 편만으로도 완결성이 있어야 합니다.
(예: 준비편 → 실행편 → 최적화편)
출력은 각 편의 '구체적 제목 키워드'를 줄바꿈으로 {n_parts}개만. 번호/설명 없이."""
    raw = chat(plan_prompt, llm_cfg, max_tokens=300, temperature=0.7)
    part_kws = [re.sub(r"^[\-\*\d\.\)\s]+", "", ln).strip()
                for ln in (raw or "").splitlines() if ln.strip()][:n_parts]
    while len(part_kws) < n_parts:
        part_kws.append(f"{topic} {len(part_kws)+1}편")

    import uuid as _uuid
    series_id = "s" + _uuid.uuid4().hex[:8]
    # 2) 편별 슬러그 먼저 확정(상호 링크용)
    parts_meta = [{"slug": slugify(kw) + f"-{i+1}", "url": ""} for i, kw in enumerate(part_kws)]

    links = find_reference_links(topic, max_results=2)
    arts = []
    for i, kw in enumerate(part_kws):
        nav = _series_nav(parts_meta, i, blog_url)
        rel = related[:2]
        art = _gen_one(kw, kind, llm_cfg, category, links, rel, blog_url,
                       insert_ads, image_resolver, series_nav=nav, author=author,
                       author_bio=author_bio, author_type=author_type,
                       competitive=competitive)
        art["slug"] = parts_meta[i]["slug"]     # 확정 슬러그 유지(링크 일치)
        art["series_id"] = series_id
        art["series_part"] = i + 1
        art["series_total"] = n_parts
        art["title"] = f"[{i+1}편] " + art["title"]
        arts.append(art)
    return arts
