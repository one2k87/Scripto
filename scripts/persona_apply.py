"""persona_apply.py — 페르소나를 사이트 표면까지 적용(2026-09-14, 사용자 지시 '자동으로').

하는 일(전부 멱등):
  1) 워드프레스 발행 계정의 표시명 → 페르소나 필명(모든 글 바이라인 즉시 반영)
  2) 소개 페이지를 현재 주제+페르소나 기준으로 재작성(AI 활용·검증 원칙 고지 유지 — 심사 대비)
  3) 기발행 글 본문의 옛 서명(✍️ 편집부)을 필명으로 교체
자격은 시크릿에서 온 config.json을 쓰고, requests 외 의존성 없음(topic_pivot과 동일 원칙).
"""
import base64
import json
import os
import re
import sys
import time
from datetime import date

import requests


def load_persona():
    d = json.load(open("data/persona.json", encoding="utf-8"))
    p = d.get(d.get("mode", "auto")) or {}
    if not p.get("pen_name"):
        p = d.get("auto") or {}
    return p


def about_html(p, cat):
    today = date.today()
    name = p.get("pen_name", "이음")
    voice = "".join(f"<li>{v}</li>" for v in p.get("voice", []))
    habits = "".join(f"<li>{h}</li>" for h in p.get("signature_habits", []))
    return f"""
<p>원더랜드는 <strong>{cat}</strong>을 다루는 블로그입니다. 부모님 세대가 스마트폰과 디지털 세상 앞에서
막히는 순간들 — 글자가 작아서, 용어가 낯설어서, 사기가 무서워서 — 을 자녀의 마음으로 대신 알아보고,
전화 너머로도 따라 할 수 있는 순서로 정리합니다.</p>

<h2>글쓴이 — {name}</h2>
<p>{p.get("identity", "")}</p>
<ul>{voice}</ul>

<h2>정보를 확인하는 방법</h2>
<p>모든 글은 공식 앱 안내서, 통신사·기관의 공개 자료, 실제 이용자들의 후기를 대조해 작성합니다.
직접 확인하지 못한 것은 확인하지 못했다고 밝히고, 기기·통신사·앱 버전에 따라 화면이 다를 수 있는
부분은 그 사실을 명시합니다. 요금과 비용은 기준 시점과 범위로 적습니다.</p>

<h2>글을 쓰는 원칙</h2>
<ul>
<li>전문용어는 그 자리에서 부모님 말로 번역합니다.</li>
<li>단계는 3~5개, 한 단계에 한 동작 — 화면에 보이는 글자를 그대로 따옴표로 안내합니다.</li>
<li>돈·개인정보가 오가는 지점에서는 반드시 멈춰 세우고 확인 절차를 넣습니다(사기 예방 최우선).</li>
{habits}
</ul>

<h2>이런 분들께 도움이 됩니다</h2>
<p>부모님께 스마트폰 사용법을 알려드리고 싶은 자녀, 새 앱과 키오스크 앞에서 혼자 해결하고 싶은
시니어, 보이스피싱·스미싱이 걱정되는 모든 가족.</p>

<h2>운영과 도구에 대하여</h2>
<p>이 블로그는 자료 조사와 초안 작성에 생성형 AI 도구를 활용하며, 모든 글은 발행 전 구성·정확성
검증 절차를 거칩니다. 그래도 실제 적용 전에는 각 서비스의 공식 안내를 최종 확인하시길 권합니다.
문의는 문의하기 페이지를 이용해 주세요. ({today.year}년 {today.month}월 기준)</p>
""".strip()


def main():
    cfg = json.load(open("config.json", encoding="utf-8"))
    wp = cfg.get("wordpress", {}) or {}
    if not (wp.get("site_url") and wp.get("username") and wp.get("app_password")):
        print("WP 자격 부족"); return 1
    base = wp["site_url"].rstrip("/")
    tok = base64.b64encode(f"{wp['username']}:{wp['app_password']}".encode()).decode()
    H = {"User-Agent": "Mozilla/5.0 (ScriptoBot)", "Authorization": f"Basic {tok}"}

    site = json.load(open("data/site_categories.json", encoding="utf-8"))
    cat = (site.get("categories") or [{}])[0].get("name", "시니어 디지털")
    p = load_persona()
    pen = p.get("pen_name", "이음")
    steps = []

    # 1) 발행 계정 표시명 → 필명
    me = requests.get(f"{base}/wp-json/wp/v2/users/me", headers=H,
                      params={"context": "edit"}, timeout=30)
    if me.ok:
        uid = me.json()["id"]
        r = requests.post(f"{base}/wp-json/wp/v2/users/{uid}", headers=H,
                          json={"name": pen, "nickname": pen, "first_name": pen,
                                "description": (p.get("identity") or "")[:280]}, timeout=30)
        steps.append(f"표시명→{pen} {'✓' if r.ok else '✗'+str(r.status_code)}")
    else:
        steps.append(f"계정 조회 ✗{me.status_code}")

    # 2) 소개 페이지 재작성 (제목에 '소개' 또는 slug about)
    page_id = None
    for q in ({"search": "소개"}, {"slug": "about"}):
        r = requests.get(f"{base}/wp-json/wp/v2/pages", headers=H,
                         params={**q, "per_page": 10, "_fields": "id,title,slug"}, timeout=30)
        for it in (r.json() if r.ok else []):
            t = (it.get("title") or {}).get("rendered", "")
            if "소개" in t or it.get("slug") in ("about", "about-us"):
                page_id = it["id"]; break
        if page_id:
            break
    if page_id:
        r = requests.post(f"{base}/wp-json/wp/v2/pages/{page_id}", headers=H,
                          json={"content": about_html(p, cat)}, timeout=30)
        steps.append(f"소개 페이지 #{page_id} {'✓' if r.ok else '✗'+str(r.status_code)}")
    else:
        r = requests.post(f"{base}/wp-json/wp/v2/pages", headers=H,
                          json={"title": "소개", "slug": "about", "status": "publish",
                                "content": about_html(p, cat)}, timeout=30)
        steps.append(f"소개 페이지 신설 {'✓' if r.ok else '✗'+str(r.status_code)}")

    # 3) 기발행 글 본문의 옛 서명 교체(멱등)
    fixed = 0
    r = requests.get(f"{base}/wp-json/wp/v2/posts", headers=H,
                     params={"per_page": 50, "status": "publish", "context": "edit",
                             "_fields": "id,content"}, timeout=30)
    for it in (r.json() if r.ok else []):
        body = (it.get("content") or {}).get("raw") or ""
        neo = body.replace("✍️ 편집부", f"✍️ {pen}")
        if neo != body:
            u = requests.post(f"{base}/wp-json/wp/v2/posts/{it['id']}", headers=H,
                              json={"content": neo}, timeout=30)
            if u.ok:
                fixed += 1
            time.sleep(0.1)
    steps.append(f"본문 서명 교체 {fixed}편")

    msg = "✍️ 페르소나 적용 완료 — " + " · ".join(steps)
    print(msg)
    tokn, chat_id = os.getenv("TELEGRAM_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if tokn and chat_id:
        try:
            requests.post(f"https://api.telegram.org/bot{tokn}/sendMessage",
                          data={"chat_id": chat_id, "text": msg}, timeout=20)
        except Exception:
            pass
    return 0 if all("✗" not in s for s in steps) else 1


if __name__ == "__main__":
    sys.exit(main())
