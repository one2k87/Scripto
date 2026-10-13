"""integrity.py — 발행물 HTML 무결성 게이트 (2026-10-12).

왜 생겼나: GSC "파싱할 수 없는 구조화된 데이터" 메일로 전수 실측해 보니, 글을 통째로 LLM에 다시 쓰게 하는
경로(accuracy.revise·폐기 구제·daily_check_fix 자동 수리)가 세 군데였고 셋 다 (a)출력이 토큰 한도에 잘려도
'길이 절반 이상'이면 받아들였고 (b)꼬리 블록(FAQ·기준일·고지·JSON-LD)까지 LLM에 보내 잘리거나 변형됐다.
daily_check_fix는 심지어 rendered(플러그인 목차·wpautop 포함)를 raw로 다시 써넣었다.

이 모듈이 유일한 관문이다:
  split_tail(html)            본문/꼬리 분리 — LLM에는 본문만 보낸다
  rewrite_guard(orig, new)    LLM 출력 채택 여부 판정 + 꼬리 복원 (None이면 폐기)
  check(html)                 발행 직전·일일 점검 공통 규칙 → [(level, msg)]
  fix(html)                   기계적으로 고칠 수 있는 것만 고친다(빈 제목·빈 문단·깨진 JSON-LD·안 닫힌 태그)
"""
import json
import re

TAIL_MARK = "<!--tail-->"
TAIL_START_RE = re.compile(
    r'(<h2[^>]*>실행 체크리스트</h2>|<h2[^>]*>자주 묻는 질문</h2>|<p class="verified"|<p class="freshness"'
    r'|<p class="ai-notice"|<p class="disclaimer"|<div class="disclaimer"|<h2[^>]*>함께 보면 좋은 글</h2>'
    r'|<script type="application/ld\+json">)')
LD_RE = re.compile(r'<script type="application/ld\+json">([\s\S]*?)(?:</script>|\Z)')
BLOCK_TAGS = ("p", "h2", "h3", "ul", "ol", "li", "table", "thead", "tbody", "tr", "figure", "div", "script", "a", "strong", "em", "b")
PLACEHOLDER_RE = re.compile(r"\[IMAGE[^\]]*\]|\[\[[^\]]*\]\]|```|\{\{[^}]*\}\}|<!--\s*IMAGE|\[광고\]|\[표\]")


# ── 본문/꼬리 ────────────────────────────────────────────────────────
def split_tail(html):
    """(본문, 꼬리). 꼬리는 TAIL_MARK부터, 없으면 첫 꼬리 블록부터."""
    html = html or ""
    if TAIL_MARK in html:
        body, tail = html.split(TAIL_MARK, 1)
        return body, TAIL_MARK + tail
    m = TAIL_START_RE.search(html)
    if m:
        return html[:m.start()], html[m.start():]
    return html, ""


def tag_balance(html):
    """{태그: (열림, 닫힘)} — 짝이 안 맞는 것만."""
    out = {}
    for t in BLOCK_TAGS:
        o = len(re.findall(rf"<{t}(?=[\s>])", html))
        c = len(re.findall(rf"</{t}\s*>", html))
        if o != c:
            out[t] = (o, c)
    return out


def is_truncated(html):
    """LLM 출력이 토큰 한도에 잘렸는지: 닫는 태그로 안 끝나거나 블록 짝이 안 맞으면 True."""
    s = (html or "").rstrip()
    if not s or not s.endswith(">"):
        return True
    bal = tag_balance(s)
    # 인라인 <a>/<b>류 1개 차이는 본문 안 잘림일 수 있어 역시 잘림으로 본다 — 보수적으로.
    return bool(bal)


def rewrite_guard(orig_html, new_html, min_ratio=0.5):
    """LLM이 다시 쓴 본문(new_html)을 채택할지. 채택 시 '새 본문 + 원문 꼬리'를 돌려주고, 아니면 None.
    new_html에 꼬리가 섞여 돌아왔으면 떼어내고 원문 꼬리로 바꾼다(LLM이 꼬리를 변형해도 안전)."""
    body0, tail0 = split_tail(orig_html or "")
    new = (new_html or "").strip()
    new = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", new).strip()
    if not new.startswith("<"):
        return None
    new_body, _ = split_tail(new)
    new_body = new_body.rstrip()
    if is_truncated(new_body):
        return None
    if len(new_body) < max(300, int(len(body0) * min_ratio)):
        return None
    if PLACEHOLDER_RE.search(new_body):
        return None
    return new_body + tail0


# ── 점검 ────────────────────────────────────────────────────────────
def _strip_toc(html):
    return re.sub(r'<span class="ez-toc-section[^"]*"[^>]*></span>|<span class="ez-toc-section-end"></span>', "", html or "")


def check(html, require_tail=True, min_chars=1800, min_images=1):
    """[(level, msg)] — level은 'crit'(발행 막음) 또는 'warn'."""
    html = html or ""
    h = _strip_toc(html)
    out = []
    text = re.sub(r"<script[\s\S]*?</script>", " ", h)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < min_chars:
        out.append(("warn", f"본문 {len(text)}자 < {min_chars}"))
    if is_truncated(h):
        out.append(("crit", f"잘림/태그 짝 불일치 {tag_balance(h)}"))
    if PLACEHOLDER_RE.search(h):
        out.append(("crit", "플레이스홀더/코드펜스 잔존"))
    if re.search(r"<h[23][^>]*>\s*</h[23]>", h):
        out.append(("crit", "빈 소제목"))
    if re.search(r"<p(?:\s[^>]*)?>\s*</p>", h):
        out.append(("warn", "빈 문단"))
    imgs = len(re.findall(r"<img\s", h))
    if imgs < min_images:
        out.append(("warn", f"이미지 {imgs}장 < {min_images}"))
    if re.search(r"<img(?![^>]*\salt=)[^>]*>", h):
        out.append(("warn", "alt 없는 이미지"))
    # 구조화 데이터
    lds = LD_RE.findall(h)
    unclosed = len(re.findall(r'<script type="application/ld\+json">', h)) - len(
        re.findall(r'<script type="application/ld\+json">[\s\S]*?</script>', h))
    if unclosed:
        out.append(("crit", "닫히지 않은 JSON-LD"))
    has_blog = False
    for s in lds:
        try:
            o = json.loads(s)
        except Exception as e:
            out.append(("crit", f"JSON-LD 파싱 오류: {str(e)[:40]}"))
            continue
        if o.get("@type") == "BlogPosting":
            has_blog = True
            for k in ("headline", "description", "author", "datePublished"):
                if not o.get(k):
                    out.append(("warn", f"BlogPosting {k} 없음"))
            if imgs and not o.get("image"):
                out.append(("warn", "BlogPosting image 없음"))
        if o.get("@type") == "FAQPage":
            qs = o.get("mainEntity") or []
            if not qs or any(not q.get("name") or not (q.get("acceptedAnswer") or {}).get("text") for q in qs):
                out.append(("crit", "FAQPage 빈 질문/답"))
    if require_tail:
        if not has_blog:
            out.append(("crit", "BlogPosting JSON-LD 없음"))
        for cls, label in (("freshness", "기준일"), ("ai-notice", "AI 고지(제31조)"), ("byline", "바이라인")):
            if f'class="{cls}"' not in h:
                out.append(("crit" if cls == "ai-notice" else "warn", f"{label} 블록 없음"))
    # 빈 FAQ 블록(제목만 있고 질문 없음)
    m = re.search(r"<h2[^>]*>자주 묻는 질문</h2>([\s\S]*?)(?=<h2|<p class=\"|<script|\Z)", h)
    if m and not re.search(r"<h3[^>]*>\s*\S", m.group(1)):
        out.append(("crit", "FAQ 제목만 있고 질문 없음"))
    # 인라인 스크립트가 WP 필터에 망가졌는지(originality 위젯)
    for s in re.findall(r"<script>([\s\S]*?)</script>", h):
        if "<" in s or "&#8217;" in s or "&#8221;" in s or "&#038;" in s:
            out.append(("crit", "인라인 스크립트 변형(WP 필터)"))
            break
    if re.search(r'<a\s+href="(?!https?://|/|#|mailto:)[^"]*"', h):
        out.append(("warn", "가짜/깨진 링크 href"))
    if len(re.findall(r"<!--orig:v\d+-->", h)) > 1:
        out.append(("warn", "독창성 블록 중복"))
    # 본문 잘림 의심: 꼬리 직전의 마지막 글자가 문장부호/닫힘이 아니면(LLM 출력이 중간에 끊긴 흔적)
    body, _ = split_tail(h)
    btxt = re.sub(r"<script[\s\S]*?</script>|<[^>]+>", " ", body)
    btxt = re.sub(r"\s+", " ", btxt).strip()
    if btxt and btxt[-1] not in ".!?。)）]」』*\"'…:;" and not re.search(r"(다|요|죠|까|니다|세요|습니다)$", btxt[-4:]):
        out.append(("warn", f"본문 잘림 의심(끝: …{btxt[-20:]})"))
    if re.search(r"<p[^>]*>\s*본 콘텐츠는 생성형", h):
        out.append(("warn", "옛 상단 AI 고지 잔존"))
    return out


def critical(issues):
    return [m for lv, m in issues if lv == "crit"]


# ── 기계적 수리 ─────────────────────────────────────────────────────
def _tidy(html):
    """html5lib가 있으면 안 닫힌 태그를 표준대로 닫는다(브라우저와 같은 결과). 없으면 원문."""
    try:
        import html5lib  # noqa
        from bs4 import BeautifulSoup
    except Exception:
        return html, False
    # 스크립트·JSON-LD는 파서가 건드리지 않도록 잠시 빼둔다
    keep = []
    def _hold(m):
        keep.append(m.group(0)); return f"\x00K{len(keep)-1}\x00"
    tmp = re.sub(r"<script[\s\S]*?</script>|<!--[\s\S]*?-->", _hold, html)
    soup = BeautifulSoup(tmp, "html5lib")
    body = soup.body
    out = "".join(str(x) for x in body.contents) if body else str(soup)
    out = re.sub(r"\x00K(\d+)\x00", lambda m: keep[int(m.group(1))], out)
    return out, out != html


def fix(html):
    """고칠 수 있는 것만 고친다. (새 HTML, 적용한 수리 목록)"""
    html = html or ""
    done = []
    # 깨진·닫히지 않은 JSON-LD 제거(재생성은 호출자가 generator/schema_repair로)
    def _ld(m):
        s = m.group(0)
        if not s.endswith("</script>"):
            done.append("닫히지 않은 JSON-LD 제거"); return ""
        try:
            o = json.loads(m.group(1))
            if o.get("@type") == "FAQPage" and (not o.get("mainEntity") or any(
                    not q.get("name") or not (q.get("acceptedAnswer") or {}).get("text") for q in o["mainEntity"])):
                done.append("빈 FAQPage 제거"); return ""
            return s
        except Exception:
            done.append("깨진 JSON-LD 제거"); return ""
    html = LD_RE.sub(_ld, html)
    # 빈 FAQ 쌍·빈 제목·빈 문단
    n0 = len(html)
    html = re.sub(r"<h3[^>]*>\s*</h3>\s*<p(?:\s[^>]*)?>\s*</p>\s*", "", html)
    html = re.sub(r"<h[23][^>]*>\s*</h[23]>\s*", "", html)
    html = re.sub(r"<p(?:\s[^>]*)?>\s*</p>\s*", "", html)
    if len(html) != n0:
        done.append("빈 제목/문단 제거")
    # 질문 없는 FAQ 제목
    m = re.search(r"<h2[^>]*>자주 묻는 질문</h2>(?=\s*(?:<h2|<p class=\"|<script|$))", html)
    if m:
        html = html[:m.start()] + html[m.end():]
        done.append("빈 FAQ 제목 제거")
    # 모델이 본문 끝에 직접 쓴 '함께 보면 좋은 글' 블록(지어낸 외부 주소·우리 제목) 제거 — 시스템 블록이 꼬리에 따로 있다
    body0, tail0 = split_tail(html)
    n2 = len(body0)
    body0 = re.sub(r"<h[23][^>]*>\s*함께 보면 좋은 글\s*</h[23]>\s*<ul[^>]*>[\s\S]*?</ul>\s*", "", body0)
    body0 = re.sub(r"<h[23][^>]*>\s*함께 보면 좋은 글\s*</h[23]>\s*(?=<h2|$)", "", body0)
    if len(body0) != n2:
        html = body0 + tail0; done.append("본문 속 가짜 관련글 블록 제거")
    # 모델이 지어낸 가짜 내부 링크(href가 한글 슬러그·상대경로 아님) → 링크만 벗기고 글자는 남긴다(404 링크 방지)
    n1 = len(html)
    html = re.sub(r'<a\s+href="(?!https?://|/|#|mailto:)[^"]*"[^>]*>(.*?)</a>', r"\1", html, flags=re.S)
    if len(html) != n1:
        done.append("가짜 링크 제거")
    # 옛 잘림 때 본문 목록 안으로 끌려 들어간 '🔎 …기준으로 내용을 확인했습니다' 조각 제거
    html, k = re.subn(r"<li[^>]*>\s*🔎[^<]*</li>\s*", "", html)
    if k:
        done.append("끌려 들어간 확인 문구 제거")
    # 안 닫힌 태그
    if tag_balance(html):
        html2, changed = _tidy(html)
        if changed and not tag_balance(html2):
            html = html2; done.append("안 닫힌 태그 정리")
            # 태그를 닫고 나서야 드러나는 조각(열린 <li> 안의 🔎 문구)을 한 번 더 정리
            html, k = re.subn(r"<li[^>]*>\s*🔎[^<]*</li>\s*", "", html)
            if k and "끌려 들어간 확인 문구 제거" not in done:
                done.append("끌려 들어간 확인 문구 제거")
    return html, done
