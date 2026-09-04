"""
images.py - 글에 들어갈 이미지를 '자동 생성'.

제공자(config.images.provider):
  - "free"     : (권장·무료) 무료 스톡 사진 시도 → 실패 시 코드 썸네일. 비용 0.
  - "stock"    : 무료 스톡 사진만(Pexels/Unsplash). 키 필요(무료 발급).
  - "thumbnail": 코드로 제목 썸네일 생성만. 키 불필요, 항상 성공, 완전 무료.
  - "openai"   : OpenAI 이미지(gpt-image-1). OPENAI 키 필요(유료).
  - "gemini"   : Google Imagen. Gemini 키(이미지 모델 권한) 필요(유료).
  - "none"     : 생성 안 함 → generator가 자리 표시(placeholder)로 대체.

생성된 PNG는 out_dir에 저장하고, 상황에 맞게:
  - WordPress 게시 시: 미디어로 업로드해 URL 사용(publisher.upload_media)
  - 그 외: base64 data URI로 본문에 인라인 삽입(복붙/미리보기에서 바로 보임)
실패해도 파이프라인이 멈추지 않도록 항상 안전하게 None을 반환한다.
"""

import os
import re
import time
import base64


# ── 스타일 프리셋 4종 (2026-09-04 품질 개편) ─────────────────────────
# 옛 방식(모든 이미지 = 납작한 도해 1종)이 저퀄 원인. 글 내용에 맞는 스타일을
# LLM([[IMG:스타일|묘사]] 마커) 또는 휴리스틱으로 고르고, 스타일별 고품질 프롬프트를 쓴다.
# 공통 원칙: 한글 렌더링 깨짐 방지를 위해 모든 스타일에서 글자 금지.
STYLE_PRESETS = {
    "photo": (   # 실사 사진 — 생활 장면·공간·작업 모습
        "Ultra-realistic editorial photograph for a Korean lifestyle blog. "
        "Full-frame camera look, 50mm lens at f/2.8, soft natural window light, "
        "shallow depth of field, true-to-life colors and material textures, and the small "
        "imperfections of a real, lived-in ordinary Korean home so it reads as a genuine photo. "
        "If hands appear they look natural; never show a person's face. "
        "Absolutely NO text, NO letters, NO logos, NO watermark."),
    "object": (  # 정물/제품 — 특정 도구·재료·제품 클로즈업
        "Minimal studio still-life photograph: one hero object centered on a clean neutral "
        "backdrop with a soft gradient, professional softbox lighting, crisp focus, fine detail, "
        "a gentle grounded shadow — premium magazine product-page quality. "
        "Absolutely NO text, NO letters, NO logos, NO watermark."),
    "diagram": ( # 도해 — 구조·과정·원리·비교
        "Premium isometric infographic-style 3D illustration that explains the concept at a "
        "glance: rounded friendly shapes, a cohesive 3-color palette, soft shadows, clear visual "
        "hierarchy and generous white space — modern tech-blog quality, not a flat clipart. "
        "Absolutely NO text, NO letters, NO numbers, NO watermark."),
    "illust": (  # 일러스트 — 감성·비유·주의 환기
        "Warm editorial illustration in a hand-drawn style with subtle paper grain, muted cozy "
        "color palette, charming friendly mood like a Korean lifestyle magazine spot illustration, "
        "thoughtful composition with breathing room. "
        "Absolutely NO text, NO letters, NO watermark."),
}
_STYLE_ALIASES = {
    "photo": "photo", "실사": "photo", "사진": "photo",
    "object": "object", "정물": "object", "제품": "object",
    "diagram": "diagram", "도해": "diagram", "인포": "diagram",
    "illust": "illust", "일러스트": "illust", "카툰": "illust", "cartoon": "illust",
}


def parse_marker(desc):
    """'스타일|묘사' 형식이면 (style, 묘사), 아니면 (None, 원문)."""
    d = str(desc or "").strip()
    if "|" in d:
        tag, rest = d.split("|", 1)
        s = _STYLE_ALIASES.get(tag.strip().lower())
        if s:
            return s, rest.strip()
    return None, d


def pick_style(desc, category=""):
    """마커가 없을 때의 휴리스틱 — 설명 텍스트로 어울리는 스타일 추정."""
    t = f"{category} {desc}"
    if any(k in t for k in ("구조", "원리", "단계", "과정", "순서", "비교", "흐름", "배치도")):
        return "diagram"
    if any(k in t for k in ("도구", "제품", "재료", "기기", "공구", "클로즈업", "부품")):
        return "object"
    if any(k in t for k in ("느낌", "분위기", "비유", "캐릭터", "주의", "경고")):
        return "illust"
    return "photo"   # 기본은 실사 — 블로그 체감 퀄리티가 가장 높다


def build_prompt(desc, category, style=None):
    """스타일 프리셋 + 구체 묘사 결합. (구 config.images.style 문자열은 폐기 — 저퀄 원인)"""
    key = style if style in STYLE_PRESETS else pick_style(desc, category)
    subject = (f"Subject: {desc}. Context: an image for a Korean blog post "
               f"about {category or 'daily life and home'}; the subject matches the article.")
    return f"{STYLE_PRESETS[key]} {subject}"


def generate_image(desc, cfg_images, out_dir, idx=0, category=""):
    """desc(한국어 설명)로 이미지 1장 생성 → 저장 경로 반환(실패 시 None)."""
    cfg_images = cfg_images or {}
    provider = cfg_images.get("provider", "none")
    if provider in ("none", None, ""):
        return None
    size = cfg_images.get("size", "1024x1024")

    # 스타일 결정: [[IMG:스타일|묘사]] 마커 우선, 없으면 휴리스틱
    style, desc = parse_marker(desc)
    if not style:
        style = pick_style(desc, category)
    globals()["LAST_STYLE"] = style
    globals()["LAST_DESC"] = desc

    data = None
    global LAST_KIND
    LAST_KIND = "photo"
    if provider == "free":
        # 무료 우선: ①Gemini 무료 생성(키 있을 때) ②스톡 ③코드 썸네일. 항상 무언가는 나옴.
        # (2026-08-30: 옛 순서는 스톡→썸네일뿐이라 CI에 스톡 키·Pillow가 없으면 전부 None
        #  → '이미지 1장' 요건에서 글이 통째로 폐기되던 원인)
        if cfg_images.get("api_key"):
            data = _gemini(build_prompt(desc, category, style), cfg_images)
            if data: LAST_KIND = "ai"
        if not data:
            data = _stock(desc, category, cfg_images, size) or _thumbnail(desc, category, size)
    elif provider in ("stock", "pexels", "unsplash"):
        data = _stock(desc, category, cfg_images, size)
    elif provider in ("thumbnail", "thumb", "code"):
        data = _thumbnail(desc, category, size)
    elif provider == "openai":
        data = _openai(build_prompt(desc, category, style), cfg_images, size)
    elif provider in ("gemini", "imagen", "google"):
        data = _gemini(build_prompt(desc, category, style), cfg_images)
        if data: LAST_KIND = "ai"
    if not data:
        globals()["LAST_ERR"] = globals().get("LAST_ERR") or f"provider '{provider}' 결과 없음(스톡 키·Pillow 확인)"
        return None

    # 사용량/비용 집계(유료 provider만 비용 발생)
    try:
        import monitor
        monitor.bump_image(paid=provider in ("openai", "gemini", "imagen", "google"))
    except Exception:
        pass

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"img_{int(time.time()*1000)}_{idx}.png")
    with open(path, "wb") as f:
        f.write(data)
    return path


# ── 무료 스톡 사진 (Pexels / Unsplash) ─────────────────────────────
_STOCK_KW = {
    "금융": "finance money savings", "재테크": "finance investment savings",
    "건강": "health wellness lifestyle", "생활": "daily life home",
    "경제": "economy business chart", "IT": "technology laptop office",
    "부동산": "real estate house", "대출": "money loan finance",
    "보험": "insurance protection", "투자": "investment stock market",
    "다이어트": "diet healthy food", "여행": "travel trip",
    "인테리어": "home interior renovation", "수리": "home repair tools",
    "시공": "home improvement work", "집": "house interior",
    "요리": "cooking kitchen", "육아": "parenting baby", "반려": "pet dog cat",
}


def _stock_query(desc, category):
    """한국어 desc/카테고리 → 스톡 검색용 영어 키워드.
    매칭이 없으면 None — 주제와 무관한 사진(옛 'business abstract')은 심사관에게
    '내용과 이미지 불일치' 신호라, 차라리 중립 썸네일로 폴백한다(2026-09-01)."""
    text = f"{category} {desc}"
    for k, v in _STOCK_KW.items():
        if k in text:
            return v
    return None


def _http_get(url, headers=None, params=None, timeout=15):
    import requests
    return requests.get(url, headers=headers or {}, params=params or {}, timeout=timeout)


def _stock(desc, category, cfg, size):
    """무료 스톡 사진 1장의 바이트를 반환(실패 시 None)."""
    query = _stock_query(desc, category)
    if not query:          # 주제 매칭 실패 → 무관한 사진 대신 썸네일 폴백에 맡긴다
        return None
    pexels = cfg.get("pexels_key") or os.getenv("PEXELS_API_KEY")
    unsplash = cfg.get("unsplash_key") or os.getenv("UNSPLASH_ACCESS_KEY")
    try:
        if pexels:
            r = _http_get("https://api.pexels.com/v1/search",
                          headers={"Authorization": pexels},
                          params={"query": query, "per_page": 1, "orientation": "landscape"})
            if r.status_code == 200:
                photos = r.json().get("photos", [])
                if photos:
                    src = photos[0]["src"].get("large") or photos[0]["src"].get("original")
                    img = _http_get(src)
                    if img.status_code == 200:
                        print(f"[images] 무료 스톡(Pexels) 사용: {query}")
                        return img.content
            else:
                print(f"[images] Pexels 응답 {r.status_code}")
        if unsplash:
            r = _http_get("https://api.unsplash.com/search/photos",
                          headers={"Authorization": f"Client-ID {unsplash}"},
                          params={"query": query, "per_page": 1, "orientation": "landscape"})
            if r.status_code == 200:
                res = r.json().get("results", [])
                if res:
                    src = res[0]["urls"].get("regular")
                    img = _http_get(src)
                    if img.status_code == 200:
                        print(f"[images] 무료 스톡(Unsplash) 사용: {query}")
                        return img.content
    except Exception as e:
        print(f"[images] 스톡 사진 실패(무시): {e}")
    return None


# ── 코드 썸네일 (Pillow, 완전 무료·키 불필요) ────────────────────────
_CAT_COLOR = {
    "금융": (124, 92, 255), "재테크": (124, 92, 255),
    "건강": (46, 179, 127), "생활": (46, 179, 127),
    "경제": (255, 138, 76), "IT": (74, 144, 226),
}


def _find_kr_font():
    """시스템에서 한글 지원 폰트 경로를 찾는다(없으면 None)."""
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/Library/Fonts/AppleSDGothicNeo.ttc",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "C:\\Windows\\Fonts\\malgunbd.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def _short_title(desc):
    t = re.sub(r"\s+", " ", str(desc or "")).strip()
    t = re.sub(r"[\"'“”‘’]", "", t)
    return t[:40] if len(t) > 40 else t


def _thumbnail(desc, category, size):
    """제목을 얹은 브랜드 썸네일 이미지 바이트 생성(완전 무료)."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception as e:
        print(f"[images] Pillow 없음(썸네일 건너뜀): {e}")
        return None
    try:
        w, h = (int(x) for x in str(size).lower().split("x"))
    except Exception:
        w, h = 1024, 1024
    base = next((c for k, c in _CAT_COLOR.items() if k in f"{category}"), (124, 92, 255))
    # 세로 그라데이션 배경
    img = Image.new("RGB", (w, h), base)
    top = tuple(min(255, int(v * 0.55)) for v in base)   # 위는 진하게
    for y in range(h):
        t = y / max(1, h - 1)
        row = tuple(int(top[i] + (base[i] - top[i]) * t) for i in range(3))
        for x in range(0, w, w):  # 한 줄씩
            pass
        img.paste(Image.new("RGB", (w, 1), row), (0, y))
    draw = ImageDraw.Draw(img)

    font_path = _find_kr_font()
    title = _short_title(desc)
    if font_path:
        # 제목 폰트 크기: 이미지 폭에 맞춰 조정
        fsize = max(28, int(w / 12))
        try:
            font = ImageFont.truetype(font_path, fsize)
            small = ImageFont.truetype(font_path, max(16, int(w / 34)))
        except Exception:
            font = ImageFont.load_default(); small = font
        # 제목 줄바꿈(폭 기준)
        lines, cur = [], ""
        for ch in title:
            test = cur + ch
            if draw.textlength(test, font=font) > w * 0.82 and cur:
                lines.append(cur); cur = ch
            else:
                cur = test
        if cur:
            lines.append(cur)
        lines = lines[:4]
        line_h = fsize + int(fsize * 0.35)
        total_h = line_h * len(lines)
        y = (h - total_h) // 2
        for ln in lines:
            tw = draw.textlength(ln, font=font)
            x = (w - tw) // 2
            draw.text((x + 2, y + 2), ln, font=font, fill=(0, 0, 0))       # 그림자
            draw.text((x, y), ln, font=font, fill=(255, 255, 255))
            y += line_h
        # 상단 카테고리 태그
        tag = f"{category}".strip() or "Scripto"
        draw.text((int(w * 0.06), int(h * 0.06)), tag, font=small, fill=(255, 255, 255))
        # 하단 브랜드
        draw.text((int(w * 0.06), int(h * 0.90)), "Scripto", font=small, fill=(255, 255, 255))
    else:
        print("[images] 한글 폰트 없음 → 글자 없는 배경 썸네일 생성")

    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    print(f"[images] 코드 썸네일 생성: {title[:20]}")
    return buf.getvalue()


def to_data_uri(path):
    with open(path, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()


LAST_KIND = "photo"   # generate_image가 갱신: "ai"(생성) / "photo"(스톡·썸네일)
LAST_STYLE = "photo"  # generate_image가 갱신: photo/object/diagram/illust
LAST_DESC = ""        # 마커 태그를 뗀 순수 묘사(alt/캡션용)
LAST_ERR = ""         # 마지막 실패 사유(관측용) — status.json에 실린다

def figure_html(src, alt, note=None):
    a = (alt or "").replace('"', "'")
    return (f'<figure style="margin:22px 0;text-align:center">'
            f'<img src="{src}" alt="{a}" loading="lazy" '
            f'style="max-width:100%;height:auto;border-radius:10px">'
            f'<figcaption style="font-size:13px;color:#98a2b3;margin-top:6px">{a}{(" — "+note) if note else ""}</figcaption>'
            f'</figure>')


def _openai(prompt, cfg, size):
    try:
        from openai import OpenAI
        client = OpenAI(api_key=cfg.get("api_key") or os.getenv("OPENAI_API_KEY"))
        r = client.images.generate(model=cfg.get("model", "gpt-image-1"),
                                    prompt=prompt, size=size, n=1)
        return base64.b64decode(r.data[0].b64_json)
    except Exception as e:
        print(f"[images] openai 생성 실패: {e}")
        return None


def _gemini(prompt, cfg):
    """Gemini 이미지 생성 — REST 직접 호출.
    옛 코드는 google-generativeai SDK의 ImageGenerationModel을 썼는데 그런 API가 없어
    항상 예외로 죽었다(대시보드에서 잘 도는 REST 방식으로 교체, 2026-08-30).
    무료 등급 키로 동작(gemini-*-flash-image 계열)."""
    try:
        import requests as _rq
        model = cfg.get("model") or "gemini-3.1-flash-image"
        if model.startswith("imagen"):          # 옛 기본값이 시크릿에 남아 있어도 동작하게
            model = "gemini-3.1-flash-image"
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:generateContent?key={cfg.get('api_key','')}")
        r = _rq.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=90)
        j = r.json()
        if r.status_code != 200:
            global LAST_ERR
            LAST_ERR = f"gemini HTTP {r.status_code}: {str(j.get('error',{}).get('message',''))[:150]}"
            print(f"[images] {LAST_ERR}")
            return None
        for part in (j.get("candidates") or [{}])[0].get("content", {}).get("parts", []):
            blob = part.get("inlineData") or part.get("inline_data") or {}
            if blob.get("data"):
                return base64.b64decode(blob["data"])
        print("[images] gemini 응답에 이미지 없음")
    except Exception as e:
        globals()["LAST_ERR"] = f"gemini 예외: {str(e)[:150]}"
        print(f"[images] gemini 생성 실패: {e}")
    return None
