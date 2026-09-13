"""
quality.py - 발행 전 자동 품질 게이트 (애드센스 '대량 저품질' 위험 완화).
- 최소 분량, 소제목 구조, 키워드 과다반복(스터핑), 다른 글과의 유사도(중복) 검사.
- 템플릿성 검사(제목 어미 반복 / 도입부 상투 구문) — 애드센스 반려 1순위 원인.
- 기준 미달이면 발행 보류(초안 유지) 대상으로 표시한다.

운영 방침(2026-08): 게이트에 걸린 글은 사유를 불문하고 **즉시 폐기**하고,
워드프레스에 이미 올라간 초안은 휴지통으로 보낸다. REASON_META의 retry/discard
구분은 폐기 여부를 정하는 데 쓰지 않고, quality_log.json에 사유를 남겨
'생성 로직 어디를 고쳐야 하는가'를 파악하는 용도로만 쓴다.
"""

import re

# 보류 사유 코드 → (분류, 사람이 읽는 설명, 자동 조치 힌트)
REASON_META = {
    "분량부족":     ("retry",   "본문이 기준보다 짧습니다. 내용이 얇으면 '가치 없는 콘텐츠'로 반려됩니다.",
                     "목표 분량을 올려 재생성"),
    "소제목부족":   ("retry",   "H2 소제목이 부족해 글 구조가 잡히지 않았습니다.",
                     "소제목 최소 개수를 프롬프트에 명시해 재생성"),
    "키워드과다반복": ("retry", "같은 키워드가 과도하게 반복됐습니다(스터핑). 검색엔진이 조작으로 봅니다.",
                     "키워드 반복 상한을 프롬프트에 명시해 재생성"),
    "제목템플릿":   ("retry",   "최근 쓴 글과 제목이 같은 말로 끝납니다. 양산형 사이트 신호입니다.",
                     "최근 사용한 제목 어미를 금지 목록으로 넘겨 재생성"),
    "도입부템플릿": ("retry",   "도입부가 최근 글과 같은 틀입니다. 심사관이 세 편만 읽어도 드러납니다.",
                     "도입 방식을 다른 유형으로 지정해 재생성"),
    "기존글과유사": ("discard", "이미 쓴 글과 내용이 겹칩니다. 주제 자체가 중복이라 고쳐도 또 겹칩니다.",
                     "폐기하고 주제를 교체"),
}

# 도입부 상투 구문(경험담 흉내 템플릿). 2개 이상 동시 검출 시 템플릿으로 판정.
_OPEN_CLICHE = [
    r"처음\s*(접했|알아봤|이용했|들었|봤|겪었)", r"줄\s*알았", r"생각했(습니다|던|어요)",
    r"실제로\s*(확인|진행|해보|알아)", r"가장\s*(중요|먼저)", r"느끼게\s*되었",
    r"알게\s*되었", r"헷갈리는", r"궁금해하는",
]
# 상투적 제목 표현
_TITLE_CLICHE = ["알아야 할", "알아보기", "총정리", "완벽 정리", "완벽 분석", "하는 방법",
                 "핵심 정보", "핵심 사항", "한 번에", "제대로", "활용법"]


def classify(reason_str):
    """보류 사유 문자열 → {code: (분류, 설명, 조치)} 목록. main.py/앱이 함께 쓴다."""
    out = []
    for code, meta in REASON_META.items():
        if code in (reason_str or ""):
            out.append({"code": code, "kind": meta[0], "why": meta[1], "fix": meta[2]})
    return out


def is_discard(reason_str):
    """운영 방침(2026-08): 품질 게이트에 걸린 글은 사유를 불문하고 폐기한다.

    재생성 큐를 두면 같은 결함이 조금씩 다른 형태로 반복 유입되는 데다,
    사람이 큐를 비우지 못하면 그대로 쌓인다. 사유는 REASON_META 분류로
    quality_log.json에 남겨 '생성 로직을 고치는 근거'로만 쓴다.
    """
    return bool((reason_str or "").strip())


_END_STRIP = re.compile(r"(?:입니다|합니다|됩니다|줍니다|집니다|합니까|입니까|하세요|보세요|마세요|세요|해요|어요|네요|을까요|일까요|까요|나요|는가|은가|죠)$")

def title_ending(title):
    """제목 마무리의 '동사 어간'을 돌려준다.
    종결어미(합니다/하세요/까요…)는 한국어의 닫힌 어휘라 문장형 제목끼리 겹치는 게
    정상이다. 어미를 그대로 비교하던 옛 방식은 문장형 제목(우리가 권장한 방향)을
    전부 템플릿으로 오판해 재생성을 반복시켰다(2026-08-31 실측 후 개편).
    어미를 벗긴 어간끼리 비교하면 같은 동사 남발(진짜 반복)만 잡힌다."""
    w = re.findall(r"[가-힣A-Za-z0-9]+", title or "")
    for i in range(len(w) - 1, max(len(w) - 4, -1), -1):
        stem = _END_STRIP.sub("", w[i])
        if len(stem) >= 2:
            return stem
    return w[-1] if w else ""


def _first_sentence(text):
    m = re.match(r"^.{10,200}?[.!?。]", text or "", re.S)
    return (m.group(0) if m else (text or "")[:120]).strip()


def _bigrams(s):
    t = re.sub(r"[^가-힣A-Za-z0-9]", "", s or "")
    return set(t[i:i + 2] for i in range(len(t) - 1))


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def _words(t):
    return re.findall(r"[가-힣A-Za-z0-9]+", t or "")


def _shingles(words, n=3):
    return set(tuple(words[i:i + n]) for i in range(max(0, len(words) - n + 1)))


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)



# ── 글의 '요건' 검사 (data/article_requirements.json) ────────────────
# 형식은 매번 흔들되 요건은 고정한다. 생성 프롬프트와 '같은 파일'을 읽어
# 검사하므로, 요건을 늘리면 생성과 검수가 함께 움직인다(둘이 어긋나는 사고 방지).
_REQ = {}


def load_requirements(path="data/article_requirements.json"):
    if _REQ.get("v") is None:
        try:
            import json
            with open(path, encoding="utf-8") as f:
                _REQ["v"] = json.load(f)
        except Exception:
            _REQ["v"] = {"requirements": []}
    return _REQ["v"]


def check_requirements(html, text=None):
    """(미충족 요건 라벨 목록, 충족 수, 전체 수) 반환. 기계 검사 가능한 항목만."""
    t = text if text is not None else _text(html)
    reqs = (load_requirements() or {}).get("requirements") or []
    missing, checked = [], 0
    for r in reqs:
        v = r.get("verify")
        if not v:
            continue
        checked += 1
        ok = True
        kind = v.get("type")
        if kind == "regex_count":
            n = sum(len(re.findall(p, t)) for p in v.get("patterns", []))
            ok = n >= int(v.get("min", 1))
        elif kind == "regex_absent":
            ok = not any(re.search(p, t[-300:]) for p in v.get("patterns", []))
        elif kind == "tag_min":
            ok = (html or "").count("<" + v.get("tag", "h2")) >= int(v.get("min", 1))
        elif kind == "min_chars":
            ok = len(t) >= int(v.get("min", 1000))
        if not ok:
            missing.append(r.get("label", r.get("id", "?")))
    return missing, checked - len(missing), checked


def check(article, other_texts, safety, recent=None):
    """(ok: bool, reason: str) 반환.

    recent: 최근 발행/생성된 글 목록 [{title, html|opening}] — 템플릿성 비교용(선택).
    """
    safety = safety or {}
    html = article.get("html", "")
    t = _text(html)
    words = _words(t)
    reasons = []

    min_chars = int(safety.get("min_chars", 1000))
    if len(t) < min_chars:
        reasons.append(f"분량부족({len(t)}자<{min_chars})")

    if html.count("<h2") < int(safety.get("min_h2", 3)):
        reasons.append("소제목부족(H2<3)")

    # 키워드 스터핑
    fk = (article.get("focus_keyword") or "").strip()
    if fk and words:
        cnt = t.count(fk)
        density = cnt / max(1, len(words))
        if cnt >= int(safety.get("stuffing_count", 8)) and density > float(safety.get("max_keyword_density", 0.03)):
            reasons.append(f"키워드과다반복({cnt}회)")

    # 다른 글과 유사도(중복)
    sh = _shingles(words)
    thr = float(safety.get("max_similarity", 0.5))
    for ot in other_texts or []:
        if jaccard(sh, _shingles(_words(_text(ot)))) > thr:
            reasons.append("기존글과유사(중복위험)")
            break

    # ── 템플릿성 검사 (애드센스 반려 1순위 원인) ──────────────────────
    if safety.get("check_template", True):
        title = article.get("title") or ""

        # 1) 상투적 제목 표현
        if sum(1 for c in _TITLE_CLICHE if c in title) >= 1 and safety.get("block_title_cliche", True):
            reasons.append("제목템플릿(상투표현)")

        # 2) 최근 글과 제목 어미 중복
        recent = recent or []
        end = title_ending(title)
        if end and len(end) > 1:
            dup = sum(1 for r in recent if title_ending(r.get("title", "")) == end)
            if dup >= int(safety.get("max_same_title_ending", 3)):  # 어간 기준이라 2는 과민(실측)
                reasons.append(f"제목템플릿(어미'{end}' 최근 {dup}건)")

        # 3) 도입부 상투 구문
        opening = _first_sentence(_text(html))
        hits = sum(1 for p in _OPEN_CLICHE if re.search(p, opening))
        if hits >= 2:
            reasons.append("도입부템플릿(상투구문)")

        # 4) 최근 글과 도입부 서술부(문장 끝) 유사
        tail = re.sub(r"[.!?。]\s*$", "", opening)[-15:]
        if len(tail) >= 8:
            tg = _bigrams(tail)
            for r in recent:
                rt = r.get("opening") or _first_sentence(_text(r.get("html", "")))
                rt = re.sub(r"[.!?。]\s*$", "", rt)[-15:]
                if len(rt) >= 8:
                    og = _bigrams(rt)
                    inter = len(tg & og)
                    if inter and inter / max(1, len(tg | og)) >= 0.40:
                        reasons.append("도입부템플릿(최근글과 어미 유사)")
                        break

    # ── 가치 검사 (5회차 반려 '낮은 가치의 콘텐츠' 실측 반영) ──────────
    # 대시보드 본문 정밀 점검(contentDeepCheck)과 같은 기준. 프롬프트의
    # [가치 규칙]이 지켜졌는지 기계로 재확인한다 — 프롬프트만 믿으면
    # 모델이 슬그머니 백과사전체로 후퇴해도 아무도 모른다(실제로 그랬다).
    if safety.get("check_value", True):
        # 1) 실측형 수치 3개 이상
        nums = re.findall(r"\d+(?:\.\d+)?\s*(?:mm|cm|m|만\s*원|원|시간|분|kg|평|%|개|년|일)", t)
        if len(nums) < int(safety.get("min_value_numbers", 3)):
            reasons.append(f"수치부족({len(nums)}개<3)")
        # 2) 실전 신호(실수·조건분기·비교·경고) 최소 1개
        # 2026-09-13: 주제 중립화 — 옛 패턴이 인테리어 어휘(부러지/새/막히)에 치우쳐
        # 시니어 디지털 글의 같은 취지 표현(잘못 누르면/화면이 다르면)을 못 잡아 이틀 연속
        # 오탐 보류(생성↔검수 불일치의 재발). 신호의 '종류'는 유지하고 어휘만 넓힌다.
        practical = [r"자주\s*(?:부러|틀어지|새|막히|풀리|끊|놓치|헷갈|틀리)", r"흔한\s*실수", r"라면\s", r"인\s*경우(?:에는|엔)?",
                     r"반대로", r"주의할\s*점", r"순서를\s*바꾸면", r"하다\s*보면", r"장단점", r"비교하(?:면|자면)",
                     r"잘못\s*(?:누르|입력|보내|지우|고르)", r"이럴\s*때", r"안\s*될\s*때", r"다를\s*수\s*있",
                     r"만약\s", r"멈추고", r"하지\s*마세요", r"차이가"]
        if sum(1 for p in practical if re.search(p, t)) < int(safety.get("min_practical_signals", 1)):
            reasons.append("실전신호없음(실수·조건분기·비교 부재)")
        # 3) 본문 상투 표현
        cliche = ["알아보겠습니다", "살펴보겠습니다", "이번 글에서는", "도움이 되셨기를",
                  "마무리하겠습니다", "함께 알아봐요", "참고하시기 바랍니다"]
        hits = [c for c in cliche if c in t]
        if hits:
            reasons.append(f"본문상투표현({hits[0]} 외 {len(hits)-1}종)" if len(hits) > 1 else f"본문상투표현({hits[0]})")
        # 4) 어미 단조: 문장 마지막 어절 최빈값이 80% 이상
        sents = [s for s in re.split(r"(?<=[.!?…])\s+", t) if len(s) > 8]
        if len(sents) >= 8:
            ends = {}
            for s in sents:
                w = re.sub(r"[.!?…\"']+$", "", s).split(" ")[-1][-4:]
                if w:
                    ends[w] = ends.get(w, 0) + 1
            top = max(ends.values()) if ends else 0
            ratio = round(top / len(sents) * 100)
            if ratio >= int(safety.get("max_ending_monotony", 80)):
                reasons.append(f"어미단조({ratio}%)")

    # ── 요건 검사(형식과 무관하게 반드시 들어가야 하는 것) ───────────
    if safety.get("check_requirements", True):
        miss, _okn, _tot = check_requirements(html, t)
        # 이미 위에서 같은 사유로 잡힌 것은 중복 표기하지 않는다
        dup = ("수치부족", "실전신호없음", "소제목부족", "분량부족", "고정마무리문구")
        miss = [m for m in miss if not any(d[:4] in "".join(reasons) and d[:2] in m[:6] for d in dup)]
        if miss:
            reasons.append("요건미충족(" + ", ".join(miss[:3]) + (f" 외 {len(miss)-3}" if len(miss) > 3 else "") + ")")

    # ── AI 문체 신호 검사 ────────────────────────────────────────────
    # 근거: AI 탐지 연구가 공통으로 꼽는 신호 — 문장 길이 균일, 셋 묶음 남용,
    # 과도한 헤징, 고정된 결론 문구. 단일 신호가 아니라 동시 출현이 판정 기준이므로
    # 각각을 개별 사유로 쌓아 올린다.
    if safety.get("check_ai_tells", True):
        sents = [s for s in re.split(r"(?<=[.!?…])\s+", t) if len(s) > 8]
        # 1) 헤징 밀도 — 완충 어미로 끝나는 문장 비율
        if len(sents) >= 8:
            hedge = sum(1 for s in sents if re.search(
                r"(?:할 수 있습니다|일 수 있습니다|있을 수 있습니다|하는 것이 좋습니다|"
                r"하시기 바랍니다|필요가 있습니다|좋을 것 같습니다)[.!?…\"']*$", s))
            hr = round(hedge / len(sents) * 100)
            # 실측: 현행 발행 글 29편은 0~8%(중앙값 3%). 20%면 정상 글을 건드리지
            # 않으면서 헤징으로 도배된 글만 걸러낸다.
            if hr > int(safety.get("max_hedge_ratio", 20)):
                reasons.append(f"완충표현과다({hr}%)")
        # 2) 셋 묶음(rule of three) 남용
        #    명시적 "첫째…둘째…셋째"는 2회만 나와도 습관이다. 쉼표 삼항 나열은
        #    한국어에서 자연스러울 때가 있어 더 관대하게 본다.
        ordinal = len(re.findall(r"첫째[,.\s].{0,120}?둘째[,.\s].{0,120}?셋째", t))
        comma3 = len(re.findall(r"[가-힣]{2,10},\s*[가-힣]{2,10},\s*[가-힣]{2,10}\s*(?:등|을|를|이|가)\s", t))
        if ordinal >= int(safety.get("max_ordinal_triads", 2)) or comma3 >= int(safety.get("max_triads", 4)):
            reasons.append(f"셋묶음나열과다(순서형{ordinal}·나열{comma3})")
        # 3) 문장 길이 균일(기계 리듬) — 변동계수
        #    ⚠️ 임계값은 추측이 아니라 실측으로 잡았다. 실제 발행 글 29편의 CV는
        #    0.78~1.05(중앙값 0.82)였다. 0.45는 오탐만 만들고 절대 걸리지 않는
        #    죽은 검사였다. 0.35 아래면 확실히 기계 리듬이다.
        if len(sents) >= 12:
            L = [len(s) for s in sents]
            mean = sum(L) / len(L)
            cv = (sum((x - mean) ** 2 for x in L) / len(L)) ** 0.5 / mean if mean else 1
            if cv < float(safety.get("min_length_cv", 0.35)):
                reasons.append(f"문장길이균일(CV {cv:.2f})")
        # 4) 고정 마무리
        tail = t[-260:]
        if re.search(r"(?:결론적으로|요약하자면|지금까지 살펴본|이상으로)", tail):
            reasons.append("고정마무리문구")

    return (len(reasons) == 0, "; ".join(reasons))
