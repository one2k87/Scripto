"""
llm.py - 여러 LLM 제공자를 하나의 인터페이스로 호출.
config.json 의 "llm" 설정에 따라 OpenAI / Anthropic / Gemini 중 선택.

무료 등급 대응:
- Gemini 무료는 '모델당 하루 20회' 같은 일일 한도가 있음.
- 한 모델이 '일일 한도'에 걸리면 fallback_models 의 다음 모델로 자동 전환.
  (모델마다 한도가 따로라 여러 모델을 합치면 무료로 더 많이 생성 가능)
- 분당 제한(RPM) 등 '일시적' 오류는 백오프 후 같은 모델로 재시도.
설치: pip install openai  또는  anthropic  또는  google-generativeai
"""

import time

# '일시적' 오류(분당 제한 등) → 잠깐 쉬었다 같은 모델로 재시도
_RETRYABLE = ("rate limit", "429", "resource has been exhausted", "unavailable",
              "overloaded", "timeout", "deadline", "503", "500", "temporarily")
_exhausted = set()   # 오늘 한도 소진·모델 없음으로 판명된 (모델, 키)


def _keys(cfg, model):
    """키 순서(2026-11-09 키 분배): 모델 이름에 lite가 있으면 무료→유료, 아니면 유료→무료."""
    free = str(cfg.get("api_key") or "").strip()
    paid = str(cfg.get("api_key_paid") or "").strip()
    out = []
    for k in ([free, paid] if "lite" in str(model or "").lower() else [paid, free]):
        if k and k not in out:
            out.append(k)
    return out or [""]


def _who(cfg, key):
    return "유료" if key and key == str(cfg.get("api_key_paid") or "").strip() else "무료"
DEFAULT_MODEL = "gemini-3.8-flash"   # 2026-10-30 현행(ai.google.dev deprecations 실측)


def classify_error(msg):
    """LLM 오류 분류(대시보드 '결제·모델 상태' 경보용, 2026-10-30).
    billing = 선불 크레딧 소진·결제 문제(재시도 무의미) / model = 모델명 없음·종료 /
    quota = 무료 일일 한도 / other."""
    m = str(msg).lower()
    # 순서 중요(2026-11-02 정정): 무료 한도 429 문구에도 "check your plan and billing details"가
    # 들어 있어 'billing'으로 오분류 → 예비 모델로 안 넘어가고 10/31 생성 0편. 한도 판정을 먼저 한다.
    if _is_daily_quota(m) or "quota exceeded for metric" in m:
        return "quota"
    if "prepayment" in m or "credits are depleted" in m or m.startswith("402") or "billing account" in m:
        return "billing"
    if ("404" in m and "model" in m) or "is not found" in m or "not supported for generatecontent" in m:
        return "model"
    return "other"


def _is_daily_quota(msg):
    m = str(msg).lower()
    return ("perday" in m or "per day" in m or "requestsperday" in m
            or "free_tier_requests" in m or "generate_content_free_tier" in m)


def _models(cfg):
    seq = [cfg.get("model")] + list(cfg.get("fallback_models") or [])
    out, seen = [], set()
    for m in seq:
        if m and m not in seen:
            seen.add(m); out.append(m)
    return out or [DEFAULT_MODEL]


def chat(prompt, cfg, system=None, max_tokens=4000, temperature=0.7, retries=3):
    """모델마다 키를 순서대로 시도한다. 한도·모델 없음·결제·401/403·지속 429/503이면
    같은 모델을 다른 키로 먼저 재시도하고, 그래도 안 되면 다음 모델로 넘어간다."""
    provider = cfg.get("provider", "openai").lower()
    models = _models(cfg)
    last = None
    for model in models:
        keys = [k for k in _keys(cfg, model) if (model, k) not in _exhausted]
        for ki, key in enumerate(keys):
            more = ki < len(keys) - 1
            c = dict(cfg, api_key=key)
            who = _who(cfg, key)
            for attempt in range(retries):
                try:
                    out = _call(provider, prompt, c, model, system, max_tokens, temperature)
                    try:
                        import monitor
                        monitor.bump_llm()
                        monitor.mark(provider if provider != "google" else "gemini")
                    except Exception:
                        pass
                    if ki > 0:
                        print(f"[llm] '{model}' {who} 키로 성공")
                    return out
                except Exception as e:
                    last = e
                    msg = str(e)
                    low = msg.lower()
                    kind = classify_error(msg)
                    if kind == "billing":                     # 결제 문제 → 다른 키가 있으면 그 키로, 없으면 중단
                        if more:
                            print(f"[llm] '{model}' {who} 키 결제 문제 → 다른 키로 같은 요청 재시도")
                            break
                        raise
                    if kind == "model":                       # 없는/종료된 모델(키마다 다를 수 있음)
                        print(f"[llm] '{model}' {who} 키로 사용 불가(모델 없음/종료) → 다음 키/모델로 전환")
                        _exhausted.add((model, key))
                        break
                    if _is_daily_quota(msg):                  # 일일 한도 → 다음 키/모델로
                        print(f"[llm] '{model}' {who} 키 오늘 한도 소진 → 다음 키/모델로 전환")
                        _exhausted.add((model, key))
                        break
                    if low[:3] in ("401", "403"):             # 키 문제
                        if more:
                            print(f"[llm] {who} 키 인증 오류({low[:3]}) → 다른 키로 같은 요청 재시도")
                            break
                        raise
                    if any(k in low for k in _RETRYABLE):
                        if attempt < retries - 1:
                            wait = 2 * (attempt + 1)
                            print(f"[llm] 일시적 오류, {wait}s 후 재시도({attempt+1}): {msg[:80]}")
                            time.sleep(wait)
                            continue
                        print(f"[llm] '{model}' {who} 키 지속 오류 → 다음 키/모델로 전환: {msg[:80]}")
                        break
                    raise
    if last is None:                                      # 전부 소진 표시뿐이면 표시를 비우고 한 번 더
        _exhausted.clear()
        return chat(prompt, cfg, system, max_tokens, temperature, retries)
    raise last


def _call(provider, prompt, cfg, model, system, max_tokens, temperature):
    if provider == "openai":
        return _openai(prompt, cfg, model, system, max_tokens, temperature)
    if provider == "anthropic":
        return _anthropic(prompt, cfg, model, system, max_tokens, temperature)
    if provider in ("gemini", "google"):
        return _gemini(prompt, cfg, model, system, max_tokens, temperature)
    raise ValueError(f"알 수 없는 LLM provider: {provider}")


def _openai(prompt, cfg, model, system, max_tokens, temperature):
    from openai import OpenAI
    client = OpenAI(api_key=cfg["api_key"])
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    resp = client.chat.completions.create(
        model=model or "gpt-4o-mini", messages=messages,
        max_tokens=max_tokens, temperature=temperature)
    return resp.choices[0].message.content


def _claude_model(model):
    """2026-11-13: 2024년 기본값 교체. Gemini 모델명이 넘어오면 Claude로 대응(lite→Haiku, 그 외→Sonnet)."""
    m = (model or "").strip()
    if m.startswith("claude"):
        return m
    return "claude-haiku-5-5" if "lite" in m else "claude-sonnet-5-5"


def _anthropic(prompt, cfg, model, system, max_tokens, temperature):
    import anthropic
    client = anthropic.Anthropic(api_key=cfg["api_key"])
    resp = client.messages.create(
        model=_claude_model(model), max_tokens=max_tokens,
        temperature=temperature, system=system or "",
        messages=[{"role": "user", "content": prompt}])
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


def _gemini(prompt, cfg, model, system, max_tokens, temperature):
    """Gemini REST 직접 호출(2026-10-30). 옛 google.generativeai SDK는 지원 종료 + 3.x 사고(thinking)
    토큰이 max_output_tokens 를 먹어 빈 응답(finish_reason=MAX_TOKENS)이 났다(10/30 #229 실측).
    → thinkingLevel=low + 사고 여유분 4096 토큰 가산, 타임아웃 180초."""
    import requests
    model = model or DEFAULT_MODEL
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    gen = {"maxOutputTokens": min(int(max_tokens) + 4096, 65536), "temperature": temperature}
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": gen}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if not model.startswith("gemini-2."):
        gen["thinkingConfig"] = {"thinkingLevel": "low"}
    h = {"x-goog-api-key": cfg["api_key"], "Content-Type": "application/json"}
    r = requests.post(url, json=body, headers=h, timeout=180)
    if r.status_code == 400 and "thinkingConfig" in gen:   # 사고 설정 거부는 문구 없이 'invalid argument'로도 온다(11/4 캐스토 실측)
        gen.pop("thinkingConfig")                     # 사고 설정을 모르는 모델이면 빼고 재시도
        r = requests.post(url, json=body, headers=h, timeout=180)
    if r.status_code != 200:
        try:
            m = r.json().get("error", {}).get("message", "")
        except Exception:
            m = r.text[:300]
        raise RuntimeError(f"{r.status_code} {m} (model {model})")
    j = r.json()
    cands = j.get("candidates") or []
    if not cands:
        raise RuntimeError(f"빈 응답(차단?) promptFeedback={j.get('promptFeedback')}")
    parts = (cands[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if not text:
        raise RuntimeError(f"503 temporarily empty text, finishReason={cands[0].get('finishReason')}")
    return text
