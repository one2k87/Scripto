"""keyword_intro.py — 제목 v2 글의 첫 3문장·H2에 포커스 키워드를 원형 그대로 1회 배치 (2026-11-09).

인계서 3-1. 대상은 data/retitle_queue.txt에서 '##' 뒤에 검색어가 붙은 글.
- 첫 3문장에 키워드가 없으면 첫 본문 문단만 LLM으로 다시 쓴다(사실·수치 추가 금지).
- 키워드를 가진 H2가 하나도 없으면 첫 H2 하나만 바꾼다.
- 적용 전 검증: 첫 3문장 포함, 키워드 추가 1회 이하(스터핑 방지), 길이 변화 ±30% 이내,
  무결성 치명 결함 증가 없음. 하나라도 어기면 그 글은 건너뛴다.
- AI 고지·바이라인(class=ai-notice/byline)과 짧은 문단은 본문으로 보지 않는다.

DRY=1(기본): 전/후 미리보기만. DRY=0: 원문을 data/keyword_intro_backup/에 저장한 뒤 적용.
ONLY=2555,2671 처럼 특정 글만 가능. LIMIT(기본 3)편까지만 처리한다.
"""
import base64
import json
import os
import re
import sys
from datetime import datetime

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import integrity  # noqa: E402

P_RE = re.compile(r"<p\b([^>]*)>(.*?)</p>", re.S)
H2_RE = re.compile(r"<h2\b([^>]*)>(.*?)</h2>", re.S)
SKIP_CLASS = ("ai-notice", "byline")


def _plain(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def load_queue():
    rows = []
    for line in open("data/retitle_queue.txt", encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line or "##" not in line:
            continue
        pid, rest = line.split("=", 1)
        _, kw = rest.split("##", 1)
        if pid.strip().isdigit() and kw.strip():
            rows.append((pid.strip(), kw.strip()))
    return rows


def first_body_p(html):
    """AI 고지·바이라인·짧은 문단을 건너뛰고 첫 본문 <p> 매치를 돌려준다."""
    for m in P_RE.finditer(html):
        if any(c in m.group(1) for c in SKIP_CLASS):
            continue
        if len(_plain(m.group(2))) >= 20:
            return m
    return None


def intro3(text):
    sents = re.split(r"(?<=[.!?。])\s+", text)
    return " ".join(sents[:3])


def rewrite(cfg, kind, inner, kw):
    from llm import chat
    if kind == "intro":
        rule = (f'검색어 "{kw}"를 띄어쓰기·어형 그대로 첫 3문장 안에 정확히 1회 넣는다. '
                "같은 단어를 반복하거나 나열하지 않는다. 어색하면 억지로 넣지 말고 원문을 그대로 낸다. "
                "새 사실·수치·경험을 추가하지 않는다. HTML 태그는 그대로 둔다. 문단 하나만 출력한다.")
        limit = "문단"
    else:
        rule = (f'검색어 "{kw}"를 포함한 소제목으로 바꾼다. 15~25자, 문장형이 아닌 명사형. '
                "HTML 태그 없이 소제목 한 줄만 출력한다.")
        limit = "소제목"
    prompt = f"아래 {limit}을 같은 내용으로 고쳐라. 조건: {rule}\n\n[원문]\n{inner}"
    return (chat(prompt, cfg["llm"], max_tokens=600, temperature=0.4) or "").strip()


def validate(old, new, kw):
    issues = []
    m = first_body_p(new)
    if not m or kw not in intro3(_plain(m.group(2))):
        issues.append("첫 3문장에 검색어 없음")
    if _plain(new).count(kw) - _plain(old).count(kw) > 1:
        issues.append("검색어 2회 이상 추가(스터핑 위험)")
    lo, ln = len(_plain(old)), len(_plain(new))
    if lo and abs(ln - lo) / lo > 0.3:
        issues.append("길이 변화 과다")
    b = len(integrity.critical(integrity.check(old)))
    a = len(integrity.critical(integrity.check(new)))
    if a > b:
        issues.append(f"무결성 치명 결함 증가({b}→{a})")
    return issues


def main():
    dry = os.getenv("DRY", "1") != "0"
    only = [x.strip() for x in os.getenv("ONLY", "").split(",") if x.strip()]
    limit = int(os.getenv("LIMIT", "3") or "3")

    cfg = json.load(open("config.json", encoding="utf-8"))
    wp = cfg["wordpress"]
    base = wp["site_url"].rstrip("/")
    tok = base64.b64encode(f"{wp['username']}:{wp['app_password']}".encode()).decode()
    H = {"Authorization": f"Basic {tok}", "User-Agent": "Mozilla/5.0 (ScriptoBot)"}

    rows = [r for r in load_queue() if not only or r[0] in only]
    handled = 0
    for pid, kw in rows:
        if handled >= limit:
            break
        g = requests.get(f"{base}/wp-json/wp/v2/posts/{pid}", headers=H, timeout=30,
                         params={"context": "edit", "_fields": "id,title,content,link"})
        if not g.ok:
            print(f"#{pid} 조회 실패 {g.status_code} — 건너뜀")
            continue
        p = g.json()
        html = p["content"]["raw"]
        pm = first_body_p(html)
        h2m = H2_RE.search(html)
        need_intro = bool(pm) and kw not in intro3(_plain(pm.group(2)))
        need_h2 = bool(h2m) and kw not in _plain(h2m.group(2))
        if not need_intro and not need_h2:
            print(f"#{pid} 이미 충족 — 건너뜀 ({kw})")
            continue
        handled += 1
        print(f"#{pid} {p['title']['raw']}\n  검색어: {kw}")

        new = html
        if need_intro:
            open_tag = pm.group(0)[: pm.start(2) - pm.start(0)]
            new_inner = rewrite(cfg, "intro", pm.group(2), kw)
            new = new.replace(pm.group(0), open_tag + new_inner + "</p>", 1)
            print("  [첫 문단] 전:", repr(pm.group(2)[:140]))
            print("            후:", repr(new_inner[:140]))
        if need_h2:
            h = H2_RE.search(new)
            new_h = rewrite(cfg, "h2", h.group(2), kw)
            new = new[: h.start()] + "<h2" + h.group(1) + ">" + new_h + "</h2>" + new[h.end():]
            print("  [소제목] 전:", h.group(2), " / 후:", new_h)

        issues = validate(html, new, kw)
        if issues:
            print("  ✗ 검증 실패 — 건너뜀:", ", ".join(issues))
            continue
        if dry:
            print("  (DRY — 적용 안 함)")
            continue

        os.makedirs("data/keyword_intro_backup", exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        open(f"data/keyword_intro_backup/{pid}-{stamp}.html", "w", encoding="utf-8").write(html)
        r = requests.post(f"{base}/wp-json/wp/v2/posts/{pid}",
                          headers={**H, "Content-Type": "application/json"},
                          json={"content": new}, timeout=60)
        print("  ✓ 적용" if r.ok else f"  ✗ 실패 {r.status_code} {r.text[:150]}")
        print(f"  {p['link']}")

    print(f"\n처리 {handled}편 ({'DRY' if dry else '적용'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
