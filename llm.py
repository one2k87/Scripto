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
_exhausted = set()   # 오늘 일일 한도 소진된 모델
DEFAULT_MODEL = "gemini-3.8-flash"   # 2026-10-30 현행(ai.google.dev deprecations 실측)


def classify_error(msg):
    """LLM 오류 분류(대시보드 '결제·모델 상태' 경보용, 2026-10-30).
    billing = 선불 크레딧 소진·결제 문제(재시도 무의미) / model = 모델명 없음·종료 /
    quota = 무료 일일 한도 / other."""
    m = str(msg).lower()
    if ("prepayment" in m or "credits are depleted" in m or "billing" in m
            or "402" in m or "payment" in m):
        return "billing"
    if ("404" in m and "model" in m) or "is not found" in m or "not supported for generatecontent" in m:
        return "model"
    if _is_daily_quota(m) or "quota" in m:
        return "quota"
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
    provider = cfg.get("provider", "openai").lower()
    models = _models(cfg)
    avail = [m for m in models if m not in _exhausted] or models
    last = None
    for model in avail:
        for attempt in range(retries):
            try:
                out = _call(provider, prompt, cfg, model, system, max_tokens, temperature)
                try:
                    import monitor
                    monitor.bump_llm()
                    monitor.mark(provider if provider != "google" else "gemini")
                except Exception:
                    pass
                return out
            except Exception as e:
                last = e
                msg = str(e)
                kind = classify_error(msg)
                if kind == "billing":                         # 결제 문제 → 모델을 바꿔도 같음, 즉시 중단
                    raise
                if kind == "model":                           # 없는/종료된 모델 → 다음 모델로
                    print(f"[llm] '{model}' 사용 불가(모델 없음/종료) → 다른 모델로 전환")
                    _exhausted.add(model)
                    break
                if _is_daily_quota(msg):                      # 일일 한도 → 다음 모델로
                    if model not in _exhausted:
                        print(f"[llm] '{model}' 오늘 무료 한도 소진 → 다른 모델로 전환")
                    _exhausted.add(model)
                    break
                if attempt < retries - 1 and any(k in msg.lower() for k in _RETRYABLE):
                    wait = 2 * (attempt + 1)
                    print(f"[llm] 일시적 오류, {wait}s 후 재시도({attempt+1}): {msg[:80]}")
                    time.sleep(wait)
                    continue
                raise
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


def _anthropic(prompt, cfg, model, system, max_tokens, temperature):
    import anthropic
    client = anthropic.Anthropic(api_key=cfg["api_key"])
    resp = client.messages.create(
        model=model or "claude-3-5-sonnet-20241022", max_tokens=max_tokens,
        temperature=temperature, system=system or "",
        messages=[{"role": "user", "content": prompt}])
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


def _gemini(prompt, cfg, model, system, max_tokens, temperature):
    import google.generativeai as genai
    genai.configure(api_key=cfg["api_key"])
    gm = genai.GenerativeModel(model or DEFAULT_MODEL, system_instruction=system or None)
    resp = gm.generate_content(
        prompt, generation_config={"max_output_tokens": max_tokens, "temperature": temperature})
    return resp.text
