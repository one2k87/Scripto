"""humanize.py — 기발행 글에 '사람이 앞에 서는' 고지·바이라인 적용 + 페르소나 결 다듬기 (2026-10-10).

7회차 반려 뒤 사용자 지시: "AI로 전부 썼다고 하지 말고, 페르소나가 쓴 것처럼 다듬어 발행".
선을 하나 긋는다 — 고지는 AI 기본법 제31조 의무 표기라 없애거나 '일부'로 축소하지 않는다.
대신 ①글 맨 위의 "생성형 AI로 작성" 상자를 빼고 ②글 끝에 '운영자가 주제 선정·검수·출처 대조,
초안·이미지는 AI 도구'라는 사실 그대로의 고지를 넣고 ③바이라인을 '확인·정리'로 바꾼다.
④VOICE=1이면 첫 문단(후킹)과 마지막 본문 문단을 페르소나 목소리로 다시 쓴다 — 단 persona.json의
honesty_rules를 그대로 지킨다(안 한 경험을 '해봤다'고 쓰지 않는다).

DRY=1(기본): 첫 글 1편의 전/후만 출력. DRY=0: 전수 적용. ONLY=2604 처럼 특정 글만도 가능.
"""
import base64
import json
import os
import re
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

NOTICE_RE = re.compile(r'<p class="ai-notice"[^>]*>.*?</p>', re.S)
BYLINE_RE = re.compile(r'(<p class="byline"[^>]*>)(.*?)(</p>)', re.S)


def _auth():
    cfg = json.load(open("config.json", encoding="utf-8"))
    wp = cfg.get("wordpress", {}) or {}
    if not (wp.get("site_url") and wp.get("username") and wp.get("app_password")):
        print("WP 자격 부족"); sys.exit(1)
    base = wp["site_url"].rstrip("/")
    tok = base64.b64encode(f"{wp['username']}:{wp['app_password']}".encode()).decode()
    return cfg, base, {"User-Agent": "Mozilla/5.0 (ScriptoBot)", "Authorization": f"Basic {tok}",
                       "Content-Type": "application/json"}


def _persona():
    try:
        p = json.load(open("data/persona.json", encoding="utf-8"))
        return p.get(p.get("mode", "auto")) or p.get("auto") or {}
    except Exception:
        return {}


def _new_notice(author):
    import generator
    return generator._ai_notice_html(author)


def _voice_pass(html, cfg, pa):
    """첫 문단·마지막 본문 문단만 페르소나 결로. 사실·숫자·단계는 바꾸지 않는다."""
    from llm import chat
    paras = list(re.finditer(r"<p(?![^>]*class=\"(?:byline|ai-notice)\")[^>]*>(.*?)</p>", html, re.S))
    if len(paras) < 3:
        return html, False
    first = paras[0]
    # 마지막 '본문' 문단 = FAQ/체크리스트 블록 앞의 마지막 <p>
    cut = html.find("자주 묻는 질문")
    body_paras = [m for m in paras if cut < 0 or m.start() < cut]
    last = body_paras[-1] if len(body_paras) > 1 and body_paras[-1] is not first else None
    rules = "\n".join("- " + r for r in pa.get("honesty_rules", []))
    voice = "\n".join("- " + v for v in pa.get("voice", []))
    def rewrite(txt):
        prompt = (f"당신은 '{pa.get('pen_name','이음')}'입니다. {pa.get('identity','')}\n"
                  f"[목소리]\n{voice}\n[절대 규칙]\n{rules}\n"
                  "- 사실·숫자·단계·고유명사는 한 글자도 바꾸지 않는다. 새 정보를 더하지 않는다.\n"
                  "- '제가 해봤더니' 같은 경험 주장 금지. 조사·확인형 1인칭만.\n"
                  "- 길이는 원문의 ±20%. HTML 태그는 그대로. 출력은 문단 하나(<p> 없이 본문만).\n\n"
                  f"아래 문단을 위 목소리로 자연스럽게 다시 쓰세요.\n\n{txt}")
        out = chat(prompt, cfg["llm"], max_tokens=600, temperature=0.5) or ""
        out = re.sub(r"^\s*<p[^>]*>|</p>\s*$", "", out.strip())
        return out if 20 < len(out) < len(txt) * 1.6 else None
    changed = False
    new_html = html
    for m in ([last] if last else []) + [first]:   # 뒤에서부터 바꿔야 앞 인덱스가 안 밀린다
        if not m: continue
        r = rewrite(m.group(1))
        if r and r != m.group(1):
            new_html = new_html[:m.start(1)] + r + new_html[m.end(1):]
            changed = True
        time.sleep(0.5)
    return new_html, changed


def main():
    dry = os.getenv("DRY", "1") != "0"
    voice = os.getenv("VOICE", "0") == "1"
    only = {int(x) for x in os.getenv("ONLY", "").replace(" ", ",").split(",") if x.strip().isdigit()}
    cfg, base, H = _auth()
    pa = _persona(); author = pa.get("pen_name") or cfg.get("author") or "운영자"
    notice = _new_notice(author)

    posts, pg = [], 1
    while True:
        r = requests.get(f"{base}/wp-json/wp/v2/posts", headers=H, timeout=60,
                         params={"per_page": 50, "page": pg, "status": "publish", "context": "edit",
                                 "_fields": "id,title,content"})
        if not r.ok: break
        b = r.json(); posts += b
        if len(b) < 50: break
        pg += 1
    if only: posts = [p for p in posts if p["id"] in only]
    print(f"대상 {len(posts)}편 {'(드라이런: 첫 1편만 표시)' if dry else ''} voice={'on' if voice else 'off'}")

    done, skip, fail = 0, 0, []
    for p in posts:
        pid = p["id"]; raw = (p.get("content") or {}).get("raw") or ""
        html = raw
        had_top = bool(NOTICE_RE.search(html))
        html = NOTICE_RE.sub("", html, count=1)
        # 바이라인 문구
        html = BYLINE_RE.sub(lambda m: m.group(1) + re.sub(r"최종 업데이트\s*(\d{4}년 \d{1,2}월 \d{1,2}일)", r"\1 확인·정리", m.group(2)) + m.group(3), html, count=1)
        # 새 고지는 '정보 기준일(freshness)' 블록 뒤, 없으면 면책/마지막에
        anchor = None
        for pat in (r'<p class="freshness"[^>]*>.*?</p>', r'<div class="freshness"[^>]*>.*?</div>', r'<p class="disclaimer"[^>]*>', r'<div class="disclaimer"[^>]*>'):
            m = re.search(pat, html, re.S)
            if m: anchor = m; break
        if "ai-notice" not in html:
            if anchor and anchor.group(0).startswith("<p class=\"freshness\"") or (anchor and anchor.group(0).startswith("<div class=\"freshness\"")):
                html = html[:anchor.end()] + notice + html[anchor.end():]
            elif anchor:
                html = html[:anchor.start()] + notice + html[anchor.start():]
            else:
                html = html + notice
        vchanged = False
        if voice:
            try:
                html, vchanged = _voice_pass(html, cfg, pa)
            except Exception as e:
                print(f"  ⚠️ #{pid} 목소리 패스 실패(고지만 적용): {e}")
        if html == raw:
            skip += 1; continue
        if dry:
            t = re.sub(r"<[^>]+>", "", p["title"]["raw"])[:40]
            print(f"\n── #{pid} {t}\n  상단 AI 고지 제거: {had_top} · 하단 새 고지 삽입: {'ai-notice' in html} · 목소리 변경: {vchanged}")
            m = re.search(r"<p(?![^>]*class)[^>]*>(.*?)</p>", html, re.S)
            print("  첫 문단(후):", re.sub(r"<[^>]+>", "", m.group(1))[:160] if m else "-")
            print("  새 고지:", re.sub(r"<[^>]+>", "", notice)[:140])
            return 0
        u = requests.post(f"{base}/wp-json/wp/v2/posts/{pid}", headers=H, timeout=60, json={"content": html})
        if u.ok: done += 1; print(f"  ✓ #{pid}{' 🗣' if vchanged else ''}")
        else: fail.append(f"#{pid} {u.status_code}")
        time.sleep(0.4)

    msg = (f"🧑‍💻 사람 앞세우기 적용 — {done}편 (변경 없음 {skip}" + (f", 실패 {len(fail)}" if fail else "") + ")\n"
           "· 상단 'AI로 작성' 상자 → 글 끝 '운영자 검수 + AI 도구 활용' 고지(법정 표시 유지)\n"
           "· 바이라인 '확인·정리'" + ("\n· 첫·끝 문단 페르소나 결 다듬기(정직 규칙 준수)" if voice else ""))
    print(msg)
    t, c = os.getenv("TELEGRAM_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if t and c:
        try: requests.post(f"https://api.telegram.org/bot{t}/sendMessage", data={"chat_id": c, "text": msg}, timeout=20)
        except Exception: pass
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
