"""
accuracy.py - 글의 '최신성·정확성'을 발행 전에 세부 검증.

두 단계로 확인한다:
1) 휴리스틱(무비용): 본문 속 연도 표기를 스캔해
   - 말이 안 되는 미래 연도(현재+2 이상) → 지어낸 정보 의심
   - '올해/현재/최신'이라면서 현재 연도와 다른 옛 연도를 씀 → 최신화 안 됨 의심
   - 제목의 연도가 현재/내년과 다름 → 옛 글 의심
2) (선택) LLM 검증: 값싼 모델로 초안을 읽고
   - 지금도 진행 중인지(진행중/종료/예정/불명)
   - 오래됐거나 불확실해 확인이 필요한 주장
   - 최신성 평가(ok/warn/stale)와 보완 힌트
를 받아 기록한다.

config.safety.verify_accuracy:
   "off"   = LLM 검증 안 함(휴리스틱만)
   "flag"  = LLM 검증해 메모만 남김(발행은 함)         ← 기본 권장
   "strict"= 최신성 'stale' 또는 심각 이슈면 발행 보류
"""

import re
import json as _json
from datetime import date

_YEAR = re.compile(r"(19|20)\d{2}")
_NOW_WORDS = ("올해", "금년", "현재", "지금", "최신")


def heuristic(article, today=None):
    """(issues: list[str], stale: bool) — 무비용 연도 검사."""
    today = today or date.today()
    cy = today.year
    text = re.sub(r"<[^>]+>", " ", article.get("html", "") or "")
    title = article.get("title", "") or ""
    issues = []
    stale = False

    years = sorted({int(m.group(0)) for m in _YEAR.finditer(text)})
    # 1) 비현실적 미래 연도(지어낸 정보 의심)
    for y in years:
        if y > cy + 1:
            issues.append(f"미래 연도 {y} 표기(사실 확인 필요)")
    # 2) '올해/현재'라면서 옛 연도를 함께 씀
    if any(w in text for w in _NOW_WORDS):
        old = [y for y in years if y < cy]
        # 옛 연도가 '기준/당시/까지' 없이 등장하면 최신화 의심
        for y in old:
            for m in re.finditer(str(y), text):
                ctx = text[max(0, m.start() - 12):m.end() + 12]
                if not any(k in ctx for k in ("기준", "당시", "까지", "부터", "년도", "이전", "말")):
                    issues.append(f"'{y}'년 정보를 최신처럼 서술(현재 {cy}년) — 최신화 확인")
                    stale = True
                    break
    # 3) 제목 연도가 현재/내년과 다름
    tyears = [int(m.group(0)) for m in _YEAR.finditer(title)]
    for y in tyears:
        if y < cy:
            issues.append(f"제목의 연도 {y}가 과거(현재 {cy}년) — 제목 갱신 권장")
            stale = True

    # 중복 제거
    seen, uniq = set(), []
    for i in issues:
        if i not in seen:
            seen.add(i); uniq.append(i)
    return uniq, stale


def llm_review(article, chat, llm_cfg, today=None):
    """값싼 모델로 최신성·정확성 검토. dict 반환(실패 시 {})."""
    today = today or date.today()
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", article.get("html", "") or "")).strip()
    if not text:
        return {}
    prompt = f"""오늘은 {today.year}년 {today.month}월입니다. 아래 블로그 글 초안을 '최신성·정확성' 관점에서만 검토하세요.
- 이 글이 다루는 제도/지원금/이벤트가 지금도 진행 중인지 판단: 진행중 / 종료 / 예정 / 불명 중 하나.
- 오래됐거나 사실이 바뀌었을 수 있어 '확인이 필요한 주장'을 짧게 나열(없으면 빈 배열).
- 최신성 등급: ok(문제 없음) / warn(일부 확인 필요) / stale(옛 정보를 현재처럼 서술).
- 어떻게 고치면 좋은지 한 문장.

글 초안(일부):
\"\"\"{text[:2500]}\"\"\"

아래 JSON만 출력(설명 없이):
{{"fresh":"ok|warn|stale","ongoing":"진행중|종료|예정|불명","issues":["..."],"fix":"한 문장"}}"""
    try:
        # 비용 절감: 저가 모델 우선
        cfg = dict(llm_cfg)
        fb = cfg.get("fallback_models") or []
        if fb:
            cfg = dict(cfg, model=fb[0])
        raw = chat(prompt, cfg, max_tokens=500, temperature=0.1)
        raw = re.sub(r"^```[a-zA-Z]*|```$", "", (raw or "").strip()).strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        return _json.loads(m.group(0)) if m else {}
    except Exception as e:
        print(f"[accuracy] LLM 검증 실패(무시): {e}")
        return {}


def check(article, chat, llm_cfg, safety, today=None):
    """
    종합 검증. article에 accuracy 관련 필드를 채우고 (hold: bool, summary: str) 반환.
    hold=True 면 최신성 문제로 발행 보류 대상(strict 모드).
    """
    safety = safety or {}
    mode = str(safety.get("verify_accuracy", "flag")).lower()
    today = today or date.today()

    issues, stale = heuristic(article, today)
    ongoing = ""
    fresh = "stale" if stale else "ok"
    fix = ""

    if mode in ("flag", "strict"):
        r = llm_review(article, chat, llm_cfg, today)
        if r:
            fresh = r.get("fresh", fresh) or fresh
            ongoing = r.get("ongoing", "") or ""
            fix = r.get("fix", "") or ""
            for it in (r.get("issues") or []):
                if it and it not in issues:
                    issues.append(it)
            if r.get("fresh") == "stale":
                stale = True

    article["accuracy"] = fresh                 # ok / warn / stale
    article["ongoing"] = ongoing                # 진행중 / 종료 / 예정 / 불명
    article["accuracy_issues"] = issues
    article["accuracy_fix"] = fix

    hold = (mode == "strict" and (fresh == "stale" or stale))
    summary = fresh + (f"·{ongoing}" if ongoing else "") + (f" ({'; '.join(issues[:3])})" if issues else "")
    return hold, summary


def revise(article, chat, llm_cfg, today=None):
    """
    최신성 점검에서 나온 문제(issues/fix)를 반영해 '본문 HTML을 실제로 다시 쓴다'.
    구조·태그는 유지하고 오래됐거나 불확실한 서술만 최신 기준으로 고침.
    성공 시 article['html'] 교체하고 True 반환, 실패/불필요 시 False.
    """
    today = today or date.today()
    issues = article.get("accuracy_issues") or []
    fix = article.get("accuracy_fix") or ""
    html = article.get("html", "") or ""
    if not html or (not issues and article.get("accuracy") == "ok"):
        return False

    # 꼬리(체크리스트·FAQ·기준일·고지·JSON-LD)는 LLM에 보내지 않고 그대로 붙인다.
    # 2026-10-12 실측: 전체 HTML을 보내면 출력이 max_tokens(6000)에 잘려 JSON-LD가 중간에 끊기거나
    # 꼬리 블록이 통째로 사라진 채 '절반 이상 길이' 안전장치를 통과해 발행됐다.
    tail = ""
    try:
        from generator import TAIL_MARK
    except Exception:
        TAIL_MARK = "<!--tail-->"
    if TAIL_MARK in html:
        html, tail = html.split(TAIL_MARK, 1)
        tail = TAIL_MARK + tail
    else:
        m = re.search(r'(<h2>실행 체크리스트</h2>|<h2>자주 묻는 질문</h2>|<p class="verified"|<p class="freshness"'
                      r'|<p class="ai-notice"|<script type="application/ld\+json">)', html)
        if m:
            html, tail = html[:m.start()], html[m.start():]

    issue_txt = "\n".join(f"- {i}" for i in issues) or "- 최신성/정확성 표현 보완"
    prompt = f"""오늘은 {today.year}년 {today.month}월입니다. 아래 블로그 글(HTML)을 '최신성·정확성'만 고쳐서 다시 쓰세요.

[고칠 점]
{issue_txt}
{("[개선 방향] " + fix) if fix else ""}

[반드시 지킬 규칙]
- HTML 구조·태그(<h2>,<p>,<ul>,<table>,<figure>,<script>,광고/이미지 자리 등)는 그대로 유지. 새 섹션을 통째로 추가/삭제하지 말 것.
- 오래된 연도·수치를 {today.year}년 기준으로 바로잡거나, '○○년 기준'처럼 기준 시점을 명시.
- 제도/지원금/이벤트는 지금도 진행 중인지(진행중/종료/예정)를 분명히.
- 확실치 않으면 단정하지 말고 "공식 사이트에서 최신 정보 확인" 식으로 표현.
- 이미 들어있는 '정보 기준일/면책/투자위험' 안내 문단, <script type="application/ld+json"> 는 그대로 둔다.
- 사실을 지어내지 말 것. 모르면 범위/여지를 남긴다.

원문 HTML:
\"\"\"{html}\"\"\"

수정된 '완성 HTML 본문'만 출력하세요(설명·코드블록 표시 없이, <로 시작)."""
    try:
        out = chat(prompt, llm_cfg, max_tokens=10000, temperature=0.3)
        out = (out or "").strip()
        out = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", out).strip()
        # 안전장치: HTML 형태이고, 원문의 절반 이상 길이일 때만 채택(붕괴 방지)
        # 잘림 감지: 닫는 태그로 끝나지 않거나(출력이 토큰 한도에 걸림) 블록 태그 짝이 안 맞으면 폐기.
        truncated = (not out.endswith(">")) or any(
            len(re.findall(rf"<{t}\b", out)) != len(re.findall(rf"</{t}>", out))
            for t in ("p", "h2", "h3", "ul", "ol", "table", "figure", "div", "script"))
        if out.startswith("<") and not truncated and len(out) >= max(300, int(len(html) * 0.5)):
            article["html"] = out + tail
            article["revised"] = True
            return True
        print(f"[accuracy] 재작성 결과가 부실해 원문 유지(truncated={truncated}, len={len(out)}/{len(html)})")
    except Exception as e:
        print(f"[accuracy] 재작성 실패(원문 유지): {e}")
    return False
