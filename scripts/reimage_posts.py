"""reimage_posts.py — 기발행 글 이미지를 4스타일 시스템(2026-09-04)으로 전량 교체.

동작: 발행 글을 wp-json으로 순회 → LLM이 글에 어울리는 스타일(photo/object/diagram/illust)과
장면 묘사를 선택 → 새 이미지를 생성·미디어 업로드 → 본문 첫 이미지(figure/자리표시)를 교체.
이미 교체된 글은 <!--imgv2--> 마커로 건너뛴다(재실행 안전).

환경: GitHub Actions에서 build_config.py로 config.json 생성 후 실행.
  REIMAGE_LIMIT: 이번 실행에서 처리할 최대 글 수(기본 100)
  REIMAGE_DRY:   "true"면 실제 게시 수정 없이 계획만 출력
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests

import images
from publisher import _auth_header, upload_media

MARK = "<!--imgv2-->"
NOTES = {"diagram": "이해를 돕기 위한 도해입니다",
         "illust": "내용을 표현한 일러스트입니다",
         "photo": "AI로 연출한 참고 이미지입니다",
         "object": "AI로 연출한 참고 이미지입니다"}
# 본문에서 교체할 기존 이미지: 우리가 심은 figure(스타일 인라인) 또는 이미지 자리표시 div
RE_FIGURE = re.compile(r'<figure style="margin:22px 0;[^>]*>.*?</figure>', re.S)
RE_SLOT = re.compile(r'<div[^>]*>\s*📷 이미지 삽입:.*?</div>', re.S)


def strip_html(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def llm_pick(title, text, key, model):
    """글 내용 → (스타일, 장면 묘사). 실패 시 휴리스틱 폴백.
    v2(9/5): 글의 '핵심 소재'를 먼저 찾게 하고 묘사에 강제 포함 — 무관 이미지 재발 방지."""
    prompt = (
        "당신은 블로그 대표 이미지 기획자다. 이미지만 봐도 무슨 글인지 알 수 있어야 한다.\n"
        f"제목: {title}\n본문 일부: {text[:900]}\n"
        "1) 이 글이 다루는 '구체적 핵심 소재'(특정 제품·도구·작업·공간·재료의 명칭)를 본문에서 찾아라.\n"
        "2) 스타일 1개 선택 — photo(실사: 그 소재를 다루는 생활 장면·작업 모습), object(정물: 그 소재 클로즈업), "
        "diagram(도해: 그 소재의 구조·과정·비교), illust(일러스트: 감성·비유).\n"
        "3) 장면 묘사 규칙: 반드시 핵심 소재 명칭을 그대로 포함하고, '무엇이·어디서·어떤 상태로'를 담아 "
        "한국어 1~2문장. 글과 무관한 배경·인물·풍경 금지.\n"
        '순수 JSON만 출력: {"style":"photo","desc":"...","subject":"핵심 소재 명사"}')
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        r = requests.post(url, headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                          json={"contents": [{"parts": [{"text": prompt}]}],
                                "generationConfig": {"maxOutputTokens": 300, "temperature": 0.6}},
                          timeout=60)
        t = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        t = re.sub(r"^```(json)?\s*|\s*```$", "", t, flags=re.M).strip()
        # 정규식 추출 우선 — LLM이 JSON 규격(이스케이프·줄바꿈)을 자주 어겨 json.loads가 깨진다(9/4 실측)
        ms = re.search(r'"style"\s*:\s*"(\w+)"', t)
        md = re.search(r'"desc"\s*:\s*"([^"\n]{5,300})', t)
        mj = re.search(r'"subject"\s*:\s*"([^"\n]{1,60})', t)
        style = ms.group(1) if (ms and ms.group(1) in images.STYLE_PRESETS) else None
        desc = md.group(1).strip() if md else ""
        subj = mj.group(1).strip() if mj else ""
        if style and desc:
            if subj and subj not in desc:      # 핵심 소재가 빠졌으면 앞에 박는다
                desc = f"{subj} — {desc}"
            return style, desc
    except Exception as e:
        print(f"  [llm] 스타일 선택 실패(폴백): {e}")
    return images.pick_style(title), title


def main():
    cfg = json.load(open("config.json", encoding="utf-8"))
    wp = cfg.get("wordpress", {})
    if not (wp.get("enabled") and wp.get("site_url")):
        print("WP 설정 없음 — 종료"); return
    llm_key = (cfg.get("llm") or {}).get("api_key", "")
    llm_model = (cfg.get("llm") or {}).get("model") or "gemini-2.5-flash"
    img_key = (cfg.get("images") or {}).get("api_key") or llm_key
    limit = int(os.getenv("REIMAGE_LIMIT") or "100")
    dry = (os.getenv("REIMAGE_DRY") or "").lower() == "true"
    force = (os.getenv("REIMAGE_FORCE") or "").lower() == "true"   # imgv2 마커 무시하고 재교체

    base = wp["site_url"].rstrip("/")
    headers = _auth_header(wp["username"], wp["app_password"])

    posts, page = [], 1
    while True:
        r = requests.get(f"{base}/wp-json/wp/v2/posts",
                         headers=headers, params={"per_page": 50, "page": page,
                                                  "status": "publish", "context": "edit"},
                         timeout=30)
        if r.status_code != 200:
            break
        batch = r.json()
        posts += batch
        if len(batch) < 50:
            break
        page += 1
    print(f"발행 글 {len(posts)}개 발견 (limit={limit}, dry={dry})")

    done = skipped = failed = 0
    for p in posts:
        if done >= limit:
            break
        pid = p["id"]
        title = strip_html(p["title"].get("rendered") or p["title"].get("raw", ""))
        content = p["content"].get("raw") or p["content"].get("rendered", "")
        if MARK in content:
            if not force:
                skipped += 1
                continue
            content = content.replace(MARK, "")   # 강제 모드: 마커 제거 후 기존 v2 figure를 다시 교체
        print(f"\n[{pid}] {title[:40]}")
        style, desc = llm_pick(title, strip_html(content), llm_key, llm_model)
        print(f"  스타일={style} / 묘사={desc[:60]}")
        if dry:
            done += 1
            continue
        path = images.generate_image(f"{style}|{desc}",
                                     {"provider": "gemini", "api_key": img_key},
                                     "output/reimg", pid, category="")
        if not path:
            print(f"  ✗ 생성 실패: {images.LAST_ERR[:100]}"); failed += 1
            time.sleep(8); continue
        url = upload_media(path, wp, alt=desc)
        if not url:
            print("  ✗ 업로드 실패"); failed += 1
            time.sleep(8); continue
        note = NOTES.get(style)
        fig = images.figure_html(url, desc, note) + MARK
        new = RE_FIGURE.sub(fig, content, count=1)
        if new == content:
            new = RE_SLOT.sub(fig, content, count=1)
        if new == content:                      # 일반 figure/단독 img도 교체 대상(중복 삽입 방지)
            new = re.sub(r"<figure\b.*?</figure>", fig, content, count=1, flags=re.S)
        if new == content:
            new = re.sub(r"<img\b[^>]*>", fig, content, count=1)
        if new == content:                      # 이미지가 아예 없던 글: 첫 소제목 뒤 삽입
            if "</h2>" in content:
                new = content.replace("</h2>", "</h2>" + fig, 1)
            else:
                new = fig + content
        r = requests.post(f"{base}/wp-json/wp/v2/posts/{pid}",
                          headers={**headers, "Content-Type": "application/json"},
                          json={"content": new}, timeout=60)
        if r.status_code in (200, 201):
            print("  ✓ 교체 완료"); done += 1
        else:
            print(f"  ✗ 글 수정 실패 {r.status_code}: {r.text[:120]}"); failed += 1
        time.sleep(8)   # 무료 등급 이미지 모델 분당 한도 보호

    summary = f"이미지 재생성: 성공 {done} · 스킵(기교체) {skipped} · 실패 {failed} / 전체 {len(posts)}"
    print("\n" + summary)
    tok, chat = os.getenv("TELEGRAM_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if tok and chat:
        try:
            requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                          data={"chat_id": chat, "text": f"🖼 {wp['site_url']} {summary}"}, timeout=20)
        except Exception:
            pass


if __name__ == "__main__":
    main()
