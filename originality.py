"""originality.py — '이 사이트에만 있는 것'을 글마다 자동으로 심는 층 (2026-10-10 신설).

7회차 반려 뒤 결론: 글의 구조·문체를 아무리 고쳐도 심사관이 보는 "고유 가치"는 안 생겼다.
사진을 사람이 찍는 대신, 자동으로 만들 수 있으면서 **지어낸 것이 아닌** 세 가지를 넣는다.
  ① 실측 데이터 표 — 공개 출처(공공·정부 운영 사이트)의 오늘 기준 실제 숫자 + 확인일 + 출처 링크
  ② 인터랙티브 도구 — 하위 영역별 작은 HTML 위젯(진단·체크리스트·연습). 애드센스가 말하는 '도구'
  ③ 공공 사이트 실제 화면 — Playwright로 찍은 진짜 캡처(AI 이미지 아님). 공공 사이트만(저작권)
정직 규칙과의 관계: 셋 다 사실이다. 표는 출처가 있고, 도구는 계산이고, 화면은 실제 캡처다.

데이터는 scripts/originality_refresh.py가 매일 갱신해 dashboard/data/originality/*.json에 둔다.
enrich_html()은 그 JSON만 읽어 글에 끼운다(생성 시점에 네트워크를 타지 않아 생성이 느려지지 않는다).
"""
import html as _h
import json
import os
import re
from datetime import date

DATA_DIR = os.path.join("dashboard", "data", "originality")
MARK = "<!--orig:v2-->"


# ── 하위 영역 slug → 어떤 블록을 쓰는가 ───────────────────────────────────
PLAN = {
    "senior-telecom":         {"table": "mvnohub_senior", "widget": "plan_fit",   "shot": "mvnohub"},
    "senior-scam-prevention": {"table": None,             "widget": "scam_check", "shot": None},   # counterscam112 캡처 실패(10/10)
    "senior-smartphone-guide":{"table": None,             "widget": "setup_list", "shot": None},
    "senior-gov-apps":        {"table": None,             "widget": "gov_ready",  "shot": None},   # 정부24는 해외 IP 헤드리스 차단(10/10 실측)
    "senior-kiosk":           {"table": None,             "widget": "kiosk_drill","shot": None},
}

# 공개 출처(갱신 스크립트가 읽는다). 전부 정부·공공 운영 사이트.
SOURCES = {
    "mvnohub_senior": {
        "label": "알뜰폰허브 '65세 이상 시니어 요금제'",
        "url": "https://www.mvnohub.kr/product/products.do?themeTagIds=270",
        "owner": "과학기술정보통신부·한국정보통신진흥협회 운영",
    },
}
SHOTS = {
    "mvnohub":     {"url": "https://www.mvnohub.kr/product/products.do?themeTagIds=270", "label": "알뜰폰허브 시니어 요금제 목록"},

}


def _load(name):
    try:
        return json.load(open(os.path.join(DATA_DIR, name + ".json"), encoding="utf-8"))
    except Exception:
        return None


# ── ① 실측 데이터 표 ──────────────────────────────────────────────────────
def table_html(table_key):
    d = _load(table_key)
    if not d or not d.get("rows"):
        return ""
    src = SOURCES.get(table_key, {})
    rows = d["rows"][:10]
    th = "".join(f"<th style='text-align:left;padding:7px 8px;border-bottom:2px solid #e5e7eb;font-size:13px'>{_h.escape(c)}</th>"
                 for c in d["columns"])
    trs = ""
    for r in rows:
        tds = "".join(f"<td style='padding:7px 8px;border-bottom:1px solid #eef0f3;font-size:13px'>{_h.escape(str(c))}</td>" for c in r)
        trs += f"<tr>{tds}</tr>"
    return (f'<div class="orig-table" style="margin:22px 0;padding:14px;border:1px solid #e5e7eb;border-radius:10px;background:#fafbfc">'
            f'<p style="margin:0 0 8px;font-weight:600">📊 {_h.escape(d.get("title") or src.get("label",""))} — {_h.escape(d.get("checked") or "")} 기준 실제 가격</p>'
            f'<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse">'
            f'<thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></div>'
            f'<p style="margin:8px 0 0;font-size:12px;color:#667085">출처: <a href="{_h.escape(src.get("url","#"))}" rel="nofollow noopener" target="_blank">{_h.escape(src.get("label",""))}</a>'
            f'({_h.escape(src.get("owner",""))}) · {_h.escape(d.get("checked") or "")} 확인 · 프로모션 가격은 기간이 끝나면 오르니 "이후 요금"을 꼭 보세요.</p></div>')


# ── ② 인터랙티브 도구(자급자족 HTML — 외부 스크립트 없음) ──────────────────
# ⚠️ 워드프레스 함정(10/10 실측): 본문의 onclick="…'…'…" 안 따옴표를 wptexturize가 둥근따옴표로 바꿔
#    JS가 깨진다. 그래서 속성 안에 JS를 두지 않는다. 메시지는 숨은 <span data-min> 요소로, 동작은
#    글당 1회 붙는 <script> 한 줄(스크립트 안은 texturize 대상 아님, 줄바꿈 없이 써서 wpautop도 피함)
TOOL_SCRIPT = ('<script>(function(){if(window.__origTool)return;window.__origTool=1;'
               'document.addEventListener("click",function(e){var b=e.target.closest("[data-act]");if(!b)return;'
               'var r=b.closest(".orig-tool");if(!r)return;var act=b.getAttribute("data-act");'
               'if(act==="check"){var s=0,n=0,t=0;r.querySelectorAll("input[type=checkbox]").forEach(function(i){t++;if(i.checked){s+=parseInt(i.getAttribute("data-w")||"1",10);n++;}});'
               'var mode=r.getAttribute("data-mode")||"score";var best=null,bv=-1;r.querySelectorAll(".m").forEach(function(m){var mn=m.getAttribute("data-min");'
               'if(mode==="count"){if(mn==="all"&&n===t){best=m;bv=999;}else if(mn==="rest"&&n<t&&bv<1){best=m;bv=1;}}'
               'else{var v=parseInt(mn,10);if(s>=v&&v>bv){best=m;bv=v;}}});'
               'var o=r.querySelector(".out");if(o){o.innerHTML=best?best.innerHTML.replace("{rest}",String(t-n)):"";}}'
               'if(act==="step"){var st=parseInt(r.getAttribute("data-step")||"0",10);var steps=r.querySelectorAll(".st");var q=r.querySelector(".q");'
               'if(st>=steps.length){r.setAttribute("data-step","0");q.innerHTML=r.getAttribute("data-q0");b.textContent=r.getAttribute("data-b0");return;}'
               'q.innerHTML=steps[st].innerHTML;b.textContent=steps[st].getAttribute("data-b");r.setAttribute("data-step",String(st+1));}});})();</script>')

_BTN = '<button type="button" data-act="{act}" style="margin-top:10px;padding:8px 14px;border-radius:8px;border:0;background:#4f46e5;color:#fff;font-weight:600;cursor:pointer">{label}</button>'

def _tool(title, items, msgs, mode="score", btn="결과 보기"):
    boxes = "".join(f'<label style="display:block;margin:6px 0;font-size:14px"><input type="checkbox" data-w="{w}" style="margin-right:8px">{_h.escape(t)}</label>' for t, w in items)
    hidden = "".join(f'<span class="m" data-min="{k}" style="display:none">{v}</span>' for k, v in msgs)
    return (f'<div class="orig-tool" data-mode="{mode}" style="margin:22px 0;padding:16px;border:2px solid #c7d2fe;border-radius:12px;background:#f5f7ff">'
            f'<p style="margin:0 0 10px;font-weight:700">🧰 {_h.escape(title)} <span style="font-weight:400;font-size:12px;color:#667085">— 체크하면 바로 답이 나옵니다</span></p>'
            f'{boxes}{_BTN.format(act="check", label=btn)}<p class="out" style="margin:10px 0 0;font-size:14px;line-height:1.6;min-height:1.4em"></p>{hidden}</div>')

WIDGETS = {
    "plan_fit": lambda: _tool("우리 부모님 요금제, 이 정도면 충분할까?", [
        ("전화는 받는 쪽이 많고 거는 건 하루 몇 통", 1), ("카카오톡·사진은 집 와이파이에서 주로", 1), ("유튜브를 밖에서도 자주 본다", 4),
        ("지도·내비를 밖에서 쓴다", 2), ("한 달 요금이 2만 원 넘으면 부담", 1)],
        [(0, "아주 적게 쓰는 편 — 월 1~3GB·통화 위주 요금제로 1만 원 미만도 가능합니다."),
         (2, "중간입니다 — 월 3~7GB면 충분합니다. 표의 중간 가격대를 보세요."),
         (5, "데이터가 꽤 필요합니다 — 월 10GB 이상, 아래 표에서 <b>이후 요금</b> 2만 원대 안쪽을 고르세요.")]),
    "scam_check": lambda: _tool("방금 온 전화·문자, 위험한가요?", [
        ("검찰·경찰·금감원이라며 전화로 계좌를 물었다", 5), ("지금 당장, 오늘 안에처럼 시간을 재촉한다", 3), ("링크를 눌러 앱을 설치하라고 한다", 5),
        ("가족이 다쳤다·사고 났다며 돈을 보내라고 한다", 5), ("택배·카드 승인 문자인데 모르는 번호다", 2), ("상품권·기프트카드 번호를 알려달라고 한다", 5)],
        [(0, "<b style=\"color:#15803d\">특별한 위험 신호는 없습니다.</b> 그래도 돈·비밀번호를 묻는 순간 끊는 게 원칙입니다."),
         (2, "<b style=\"color:#b45309\">⚠️ 의심.</b> 상대가 말한 기관의 대표번호를 직접 찾아 다시 걸어 확인하세요. 문자 속 번호로는 걸지 마세요."),
         (5, "<b style=\"color:#b91c1c\">🚨 사기 가능성 매우 높음.</b> 지금 전화를 끊고 아무것도 누르지 마세요. 자녀에게 먼저 전화 → 그다음 112(경찰) 또는 1332(금감원).")]),
    "setup_list": lambda: _tool("부모님 폰, 이것만 해두면 편해집니다", [
        ("글씨 크기를 키웠다", 1), ("벨소리·알림 소리를 크게 했다", 1), ("홈 화면에 자녀 연락처 바로가기를 뒀다", 1),
        ("모르는 번호 차단을 켰다", 1), ("긴급 연락처(의료정보)를 등록했다", 1), ("자동 업데이트를 와이파이에서만으로 했다", 1)],
        [("all", "✅ 전부 되어 있습니다. 한 달에 한 번만 다시 확인하면 됩니다."),
         ("rest", "아직 <b>{rest}가지</b>가 남았습니다. 이 글의 순서대로 하나씩 해보세요 — 전화로 알려드릴 때는 <b>설정 앱 → 돋보기(검색) → 그 이름 입력</b>이 가장 빠릅니다.")],
        mode="count", btn="확인"),
    "gov_ready": lambda: _tool("정부 앱 발급 전 준비물 체크", [
        ("본인 명의 휴대폰이다(가족 명의면 안 됨)", 1), ("주민등록증 또는 운전면허증이 손에 있다", 1), ("휴대폰에 PASS 또는 은행 앱이 설치돼 있다", 1),
        ("문자 인증번호를 받을 수 있다(수신 차단 아님)", 1), ("저장공간이 500MB 이상 남아 있다", 1)],
        [("all", "✅ 준비 완료 — 보통 5~10분이면 끝납니다."),
         ("rest", "빠진 <b>{rest}가지</b>부터 챙기세요. 특히 <b>본인 명의</b>가 아니면 발급 자체가 안 되니 가장 먼저 확인하세요.")],
        mode="count", btn="확인"),
    "kiosk_drill": lambda: ('<div class="orig-tool" data-step="0" data-q0="1단계. 화면 어디를 눌러야 시작될까요?" data-b0="화면 아무 곳이나 터치" style="margin:22px 0;padding:16px;border:2px solid #c7d2fe;border-radius:12px;background:#f5f7ff;text-align:center">'
        '<p style="margin:0 0 10px;font-weight:700;text-align:left">🧰 키오스크 연습 — 3번만 눌러보세요</p>'
        '<p class="q" style="font-size:15px;margin:6px 0 12px">1단계. 화면 어디를 눌러야 시작될까요?</p>'
        '<button type="button" data-act="step" style="padding:14px 22px;font-size:16px;border-radius:12px;border:0;background:#4f46e5;color:#fff;font-weight:700;cursor:pointer">화면 아무 곳이나 터치</button>'
        '<span class="st" data-b="담기" style="display:none">2단계. 메뉴를 골랐습니다. 이제 <b>담기</b>를 누르세요.</span>'
        '<span class="st" data-b="카드 결제" style="display:none">3단계. 결제 수단을 고르세요. 현금은 안 되는 곳이 많아 <b>카드</b>가 안전합니다.</span>'
        '<span class="st" data-b="처음부터 다시" style="display:none">✅ 끝! 영수증 번호를 기억했다가 음식이 나오면 받으면 됩니다. 실제 기계도 이 순서입니다.</span></div>'),
}

def widget_html(key):
    f = WIDGETS.get(key)
    return (f() + TOOL_SCRIPT) if f else ""


# ── ③ 공공 사이트 실제 화면 ────────────────────────────────────────────────
def shot_html(shot_key):
    d = _load("shots") or {}
    s = d.get(shot_key)
    if not s or not s.get("url"):
        return ""
    meta = SHOTS.get(shot_key, {})
    return (f'<figure style="margin:22px 0;text-align:center"><img src="{_h.escape(s["url"])}" alt="{_h.escape(meta.get("label",""))} 실제 화면" loading="lazy" style="max-width:100%;border:1px solid #e5e7eb;border-radius:10px">'
            f'<figcaption style="font-size:12px;color:#667085;margin-top:6px">{_h.escape(meta.get("label",""))} — {_h.escape(s.get("taken",""))} 실제 캡처(공공 사이트)</figcaption></figure>')


# ── 글에 끼우기 ─────────────────────────────────────────────────────────────
def enrich_html(html, subtopic_slug):
    """하위 영역에 맞는 표·도구·화면을 본문에 넣는다. 이미 들어간 글(MARK)은 건드리지 않는다."""
    if not html or MARK in html:
        return html, False
    # v1(onclick 방식, WP texturize로 깨짐) 잔재는 걷어내고 다시 넣는다
    if "<!--orig:v1-->" in html:
        html = re.sub(r"<!--orig:v1-->", "", html)
        html = re.sub(r'<div class="orig-tool".*?</div>\s*</div>', "", html, count=1, flags=re.S)
        html = re.sub(r'<div class="orig-table".*?</table></div>.*?</div>', "", html, count=1, flags=re.S)
        html = re.sub(r'<figure[^>]*>\s*<img src="[^"]*shot_[a-z0-9]+\.png".*?</figure>', "", html, count=1, flags=re.S)
    plan = PLAN.get(subtopic_slug or "")
    if not plan:
        return html, False
    blocks = []
    if plan.get("widget"):
        blocks.append(widget_html(plan["widget"]))
    if plan.get("table"):
        blocks.append(table_html(plan["table"]))
    if plan.get("shot"):
        blocks.append(shot_html(plan["shot"]))
    blocks = [b for b in blocks if b]
    if not blocks:
        return html, False
    ins = MARK + "".join(blocks)
    # 위치: 두 번째 H2 앞(도입 뒤, 본문 중간) — 없으면 FAQ 앞, 그것도 없으면 끝
    hs = [m.start() for m in re.finditer(r"<h2[\s>]", html)]
    if len(hs) >= 2:
        at = hs[1]
    else:
        m = re.search(r"<h2[^>]*>\s*자주 묻는 질문", html)
        at = m.start() if m else len(html)
    return html[:at] + ins + html[at:], True
