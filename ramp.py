"""
ramp.py — 승인 모드 → 수익 모드 점진 전환 엔진

Scripto가 파는 것의 핵심 로직이다.

  [승인 모드]  한 주제를 깊게, 광고 없이, 천천히  → 애드센스 심사 통과가 유일한 목표
  [전환 구간]  3~4주에 걸쳐 광고·제휴·발행량·주제 폭을 조금씩 올린다
  [수익 모드]  strategy.py의 주간 학습 루프가 인계받아 수익을 최적화한다

왜 '천천히' 인가 — 정직하게
  흔히 "승인 후 글을 바꾸면 구글이 승인을 취소한다"고들 하는데, 정확히는 그렇지 않다.
  실제 위험은 두 가지다.
    1) 광고를 한꺼번에 늘리면 페이지 경험(레이아웃 이동·본문 대비 광고 비율)이 나빠져
       정책 경고나 노출 축소로 이어진다.
    2) 주제를 급히 넓히면 얇은 글 비율이 다시 올라가 '가치 없는 콘텐츠' 상태로 되돌아간다.
  둘 다 '변화 그 자체'가 아니라 '변화 속도'의 문제다. 그래서 단계적으로 올린다.

각 단계는 config에 덮어쓸 값(overrides)을 돌려주고, main.py가 그대로 적용한다.
"""

import json
import os
from datetime import datetime, date

DATA = os.path.join("dashboard", "data")
STATE = os.path.join(DATA, "ramp.json")

# 단계 정의. days = 그 단계를 유지할 일수(승인일 기준 누적).
PHASES = [
    {
        "key": "approval", "label": "승인 준비", "days": None,   # 승인될 때까지 무기한
        "desc": "한 주제만 깊게. 광고·제휴 전부 끄고 심사 통과에만 집중합니다.",
        "overrides": {
            "posts_per_day": 2, "ad_slots": 0, "affiliate": False, "coupang": False,
            "topic_width": 1,            # 다루는 소주제 폭(1=핵심만)
            "min_chars": 1400,           # 깊이 우선
            "force_draft": False,        # 승인용 글은 실제 공개돼야 심사 대상이 됨
            "intent_bias": "evergreen",  # 정보성 위주가 심사에 유리
        },
    },
    {
        "key": "w1", "label": "전환 1주", "days": 7,
        "desc": "광고 1개만 조용히 올립니다. 주제는 그대로 유지합니다.",
        "overrides": {"posts_per_day": 2, "ad_slots": 1, "affiliate": False, "coupang": False,
                      "topic_width": 1, "min_chars": 1300, "force_draft": False,
                      "intent_bias": "evergreen"},
    },
    {
        "key": "w2", "label": "전환 2주", "days": 14,
        "desc": "광고 2개. 같은 주제 안에서 인접 소주제로 조금 넓힙니다.",
        "overrides": {"posts_per_day": 3, "ad_slots": 2, "affiliate": False, "coupang": True,
                      "topic_width": 2, "min_chars": 1200, "force_draft": False,
                      "intent_bias": "balanced"},
    },
    {
        "key": "w3", "label": "전환 3주", "days": 21,
        "desc": "광고 3개 + 제휴 도입. 수익형 키워드 비중을 올리기 시작합니다.",
        "overrides": {"posts_per_day": 4, "ad_slots": 3, "affiliate": True, "coupang": True,
                      "topic_width": 3, "min_chars": 1100, "force_draft": False,
                      "intent_bias": "revenue"},
    },
    {
        "key": "revenue", "label": "수익 운영", "days": 28,
        "desc": "전환 완료. 이제부터 주간 학습(strategy.py)이 비율을 스스로 조정합니다.",
        "overrides": {"posts_per_day": 5, "ad_slots": 3, "affiliate": True, "coupang": True,
                      "topic_width": 4, "min_chars": 1000, "force_draft": False,
                      "intent_bias": "auto"},   # auto = strategy.json에 맡김
    },
]


def _load():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(s):
    os.makedirs(DATA, exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


def state():
    """현재 램프 상태. 없으면 승인 모드로 시작한다."""
    s = _load()
    if not s:
        s = {"phase": "approval", "approved_at": None,
             "started_at": date.today().isoformat(), "manual_hold": False}
        _save(s)
    return s


def mark_approved(when=None):
    """애드센스 승인이 확인된 날. 이 날짜부터 전환 시계가 돈다."""
    s = state()
    s["approved_at"] = (when or date.today()).isoformat() if not isinstance(when, str) else when
    s["phase"] = "w1"
    _save(s)
    print(f"[램프] 승인 확인 → 전환 시작 ({s['approved_at']})")
    return s


def set_hold(on=True):
    """전환을 잠시 멈춘다(정책 경고를 받았거나 수동 점검이 필요할 때)."""
    s = state()
    s["manual_hold"] = bool(on)
    _save(s)
    return s


def days_since_approval(s=None):
    s = s or state()
    if not s.get("approved_at"):
        return None
    try:
        d0 = datetime.fromisoformat(s["approved_at"]).date()
    except Exception:
        return None
    return (date.today() - d0).days


def current(s=None):
    """오늘 적용할 단계를 반환한다."""
    s = s or state()
    if not s.get("approved_at"):
        return PHASES[0]
    if s.get("manual_hold"):
        # 멈춤 상태에서는 지금 단계를 그대로 유지(전진하지 않음)
        return next((p for p in PHASES if p["key"] == s.get("phase")), PHASES[0])
    d = days_since_approval(s) or 0
    cur = PHASES[1]
    for p in PHASES[1:]:
        if d >= (p["days"] or 0) - 7:      # days는 '그 단계가 끝나는 날' 기준
            cur = p
    # 진행 상태 저장(앱이 읽어 표시)
    if s.get("phase") != cur["key"]:
        s["phase"] = cur["key"]
        _save(s)
    return cur


def overrides(cfg=None):
    """main.py가 config에 덮어쓸 값. 단계에 맞춰 광고·발행량·깊이를 조절한다."""
    p = current()
    o = dict(p["overrides"])
    o["_phase"] = p["key"]
    o["_phase_label"] = p["label"]
    o["_phase_desc"] = p["desc"]
    return o


def apply_to_config(cfg):
    """config dict에 단계 설정을 반영한다(원본을 직접 수정)."""
    o = overrides(cfg)
    saf = cfg.setdefault("safety", {})
    saf["min_chars"] = o["min_chars"]
    saf["force_draft"] = o["force_draft"]
    rev = cfg.setdefault("revenue", {})
    rev["ad_slots"] = o["ad_slots"]
    aff, cp = o["affiliate"], o["coupang"]
    # 라인 격리(2026-09-09 순서 버그 수정): main의 격리 가드가 램프보다 '먼저' 돌아서,
    # 승인 2주차부터 램프가 쿠팡·제휴를 다시 켜며 가드를 덮어쓰고 있었다(승인되는 순간
    # 애드센스 라인에 커머스가 섞일 뻔). 픽담 b153 사고(램프가 쿠팡을 '끄던' 문제)의 대칭.
    # 애드센스 라인에서는 램프가 어떤 단계에서도 제휴·쿠팡을 켜지 않는다.
    try:
        _sc = json.load(open(os.path.join("data", "site_categories.json"), encoding="utf-8"))
        if _sc.get("line", "adsense") == "adsense" and cfg.get("track") != "coupang":
            if aff or cp:
                print("[램프] 애드센스 라인 — 단계상 제휴·쿠팡 on이지만 라인 격리로 유지 안 함")
            aff = cp = False
    except Exception:
        pass
    cfg.setdefault("affiliate", {})["enabled"] = aff
    cfg.setdefault("coupang", {})["enabled"] = cp
    cfg["_ramp"] = {k: v for k, v in o.items() if k.startswith("_")}
    cfg["_ramp_posts_per_day"] = o["posts_per_day"]
    cfg["_ramp_intent_bias"] = o["intent_bias"]
    cfg["_ramp_topic_width"] = o["topic_width"]
    print(f"[램프] {o['_phase_label']} — 하루 {o['posts_per_day']}편 · 광고 {o['ad_slots']}개 "
          f"· 제휴 {'on' if o['affiliate'] else 'off'} · 최소 {o['min_chars']}자")
    return cfg


def progress():
    """앱 표시용 요약."""
    s = state()
    p = current(s)
    idx = [x["key"] for x in PHASES].index(p["key"])
    d = days_since_approval(s)
    nxt = PHASES[idx + 1] if idx + 1 < len(PHASES) else None
    left = None
    if nxt and d is not None and nxt["days"]:
        left = max(0, nxt["days"] - 7 - d)
    return {
        "phase": p["key"], "label": p["label"], "desc": p["desc"],
        "step": idx + 1, "total": len(PHASES),
        "approved_at": s.get("approved_at"),
        "days_since_approval": d,
        "hold": bool(s.get("manual_hold")),
        "next_label": nxt["label"] if nxt else None,
        "days_to_next": left,
        "overrides": p["overrides"],
        "phases": [{"key": x["key"], "label": x["label"],
                    "done": [y["key"] for y in PHASES].index(x["key"]) < idx,
                    "current": x["key"] == p["key"]} for x in PHASES],
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "approved":
        mark_approved(sys.argv[2] if len(sys.argv) > 2 else None)
    print(json.dumps(progress(), ensure_ascii=False, indent=2))
