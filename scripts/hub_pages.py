"""hub_pages.py — '죽지 않는 페이지' 3·4단계 (2026-10-19, 사용자 승인).

③ 도구 독립 페이지: 글 속에만 있던 자가점검 도구 5종을 각자 주소를 가진 페이지로 꺼낸다.
   "알뜰폰 요금제 진단", "보이스피싱 확인" 같은 검색어로 들어올 입구가 되고, 한 번 만들면 계속 쓰이는 자산.
④ 가이드 허브: 하위 주제 5개별로 공개 글 전부를 정리한 '전체 모음' 페이지. 새 글이 나오면 매일 자동 갱신.
   크롤러가 사이트 전체를 한 번에 따라가게 하고, 들어온 독자를 다음 글로 이어준다.

멱등: 슬러그로 페이지를 찾아 없으면 만들고, 내용이 바뀌었을 때만 갱신한다(수정일 낭비 없음).
메뉴: '전체 가이드'·'도구 모음' 두 항목이 메뉴에 없으면 페이지 항목으로 추가(기존 항목 불가침).
글 내용은 공개 글 제목·링크와 기존 도구 위젯만으로 조립한다 — 새로 지어내는 사실 없음.
DRY=1 이면 계획만 출력.
"""
import base64
import html as H
import json
import os
import re
import sys
from datetime import date

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import originality as O  # noqa: E402

NOTICE = ('<p class="ai-notice" style="margin:22px 0 8px;padding:8px 12px;border-left:3px solid #d0d5dd;'
          'background:#f9fafb;color:#667085;font-size:12px;line-height:1.6">ℹ️ 이 페이지의 도구와 안내문은 운영자가 '
          '공식 안내와 대조해 정리했으며, 작성에 생성형 AI 도구를 활용했습니다(AI 기본법 제31조에 따른 표시). '
          '자가 점검용이며 법률·금융·의료 판단을 대신하지 않습니다.</p>')

TOOLS = [
    # slug, 하위카테고리, 위젯, 제목, 도입, 쓰는 법
    ("mvno-plan-check", "senior-telecom", "plan_fit",
     "알뜰폰 요금제 진단 — 부모님 사용량에 맞는 요금 찾기",
     "부모님 휴대폰 요금이 사용량보다 비싸게 나가는 경우가 많습니다. 아래 다섯 가지 중 해당하는 것을 체크하면 "
     "어느 정도 데이터가 필요한지 바로 알려드리고, 정부 운영 비교 사이트(알뜰폰허브)의 시니어 요금제 실측 표를 함께 보여드립니다.",
     "부모님과 통화하면서 하나씩 여쭤보고 체크해 보세요. 결과가 나오면 표에서 '이후 요금'(할인 끝난 뒤 가격)을 기준으로 고르시면 됩니다."),
    ("scam-call-check", "senior-scam-prevention", "scam_check",
     "보이스피싱·스미싱 위험도 확인 — 방금 온 전화와 문자 점검",
     "검찰·은행·가족을 사칭하는 전화와 문자는 말투가 매번 바뀌지만, 요구하는 행동은 거의 같습니다. "
     "지금 받은 연락에서 해당하는 항목을 체크하면 위험도와 바로 해야 할 일을 알려드립니다.",
     "의심되는 연락을 받는 중이라면 먼저 전화를 끊고 체크하세요. 결과와 상관없이 돈·비밀번호·인증번호를 요구하면 응하지 않는 것이 원칙입니다."),
    ("phone-setup-checklist", "senior-smartphone-guide", "setup_list",
     "부모님 폰 기본 설정 체크리스트 — 이것만 해두면 편해집니다",
     "글씨 크기, 벨소리, 자녀 연락처 바로가기처럼 한 번만 해두면 부모님이 매일 덜 헤매는 설정 여섯 가지입니다. "
     "이미 된 것을 체크하면 남은 개수를 알려드립니다.",
     "부모님 폰을 직접 만질 수 있을 때 함께 확인해 보세요. 전화로 알려드릴 때는 '설정 앱 → 돋보기 → 이름 입력'이 가장 빠릅니다."),
    ("gov-app-ready", "senior-gov-apps", "gov_ready",
     "정부 앱·모바일 신분증 발급 전 준비물 체크",
     "정부24·모바일 신분증·PASS 같은 앱은 준비물 하나가 빠지면 중간에 막힙니다. "
     "발급을 시작하기 전에 다섯 가지를 체크해 보세요.",
     "특히 '본인 명의 휴대폰' 여부를 가장 먼저 확인하세요. 가족 명의 폰으로는 발급이 진행되지 않습니다."),
    ("kiosk-practice", "senior-kiosk", "kiosk_drill",
     "키오스크 주문 연습 — 실제 기계와 같은 순서로 3번 눌러보기",
     "카페·패스트푸드·병원 키오스크는 화면은 달라도 순서는 비슷합니다. "
     "아래 버튼을 세 번 눌러 보면서 '시작 → 담기 → 결제' 흐름을 미리 익혀 보세요.",
     "부모님과 함께 화면을 보며 눌러 보시면 실제 매장에서 덜 긴장하십니다."),
]
TOOLS_HUB = ("tools", "부모님 폰 도구 모음 — 체크하면 바로 답이 나오는 5가지")
GUIDE_HUB = ("guide", "부모님 스마트폰·디지털 생활 가이드 전체 모음")


def _auth():
    cfg = json.load(open("config.json", encoding="utf-8"))
    wp = cfg.get("wordpress", {}) or {}
    base = wp["site_url"].rstrip("/")
    tok = base64.b64encode(f"{wp['username']}:{wp['app_password']}".encode()).decode()
    return base, {"User-Agent": "Mozilla/5.0 (ScriptoBot)", "Authorization": f"Basic {tok}",
                  "Content-Type": "application/json"}


def _posts_by_sub(base, h):
    cats = requests.get(f"{base}/wp-json/wp/v2/categories", headers=h, timeout=30,
                        params={"per_page": 100, "_fields": "id,slug,name"}).json()
    cid = {c["slug"]: c["id"] for c in cats}
    out = {}
    for _, sub, *_ in TOOLS:
        if sub not in cid:
            out[sub] = []
            continue
        r = requests.get(f"{base}/wp-json/wp/v2/posts", headers=h, timeout=30,
                         params={"categories": cid[sub], "per_page": 100, "status": "publish",
                                 "_fields": "id,link,title,date"})
        out[sub] = [p for p in (r.json() if r.ok else []) if not re.search(r"/post-[0-9a-f]{8}/?$", p["link"])]
    names = {c["slug"]: c["name"] for c in cats}
    return out, names


def _li(posts, n=None):
    ps = posts[:n] if n else posts
    return "".join(f'<li><a href="{H.escape(p["link"])}">{H.escape(H.unescape(re.sub("<[^>]+>", "", p["title"]["rendered"])))}</a></li>' for p in ps)


def _tool_page(t, posts, base):
    slug, sub, wkey, title, intro, how = t
    extra = ""
    plan = O.PLAN.get(sub, {})
    if plan.get("table"):
        extra += O.table_html(plan["table"])
    if plan.get("shot"):
        extra += O.shot_html(plan["shot"])
    rel = f'<h2>이 주제의 가이드</h2><ul>{_li(posts, 8)}</ul>' if posts else ""
    return (f'<p>{H.escape(intro)}</p>{O.widget_html(wkey)}<h2>이렇게 쓰세요</h2><p>{H.escape(how)}</p>'
            f'{extra}{rel}<p>👉 <a href="{base}/{TOOLS_HUB[0]}/">다른 도구 보기</a> · '
            f'<a href="{base}/{GUIDE_HUB[0]}/">전체 가이드 모음</a></p>{NOTICE}')


def _tools_hub(base):
    items = "".join(f'<li><a href="{base}/{TOOLS_HUB[0]}/{t[0]}/"><b>{H.escape(t[3].split(" — ")[0])}</b></a> — '
                    f'{H.escape(t[3].split(" — ")[1] if " — " in t[3] else "")}</li>' for t in TOOLS)
    return (f'<p>부모님께 휴대폰을 알려드리다 보면 "그래서 우리 부모님은 뭘 하면 되지?"에서 막힙니다. '
            f'아래 도구들은 몇 가지만 체크하면 바로 답을 보여주도록 만든 자가 점검표입니다. 로그인·설치 없이 이 페이지에서 바로 쓸 수 있습니다.</p>'
            f'<ul style="line-height:2">{items}</ul><p>👉 <a href="{base}/{GUIDE_HUB[0]}/">주제별 전체 가이드 모음</a></p>{NOTICE}')


def _guide_hub(subs, names, base):
    secs = []
    total = 0
    for slug, sub, _w, title, *_ in TOOLS:
        ps = subs.get(sub) or []
        if not ps:
            continue
        total += len(ps)
        secs.append(f'<h2>{H.escape(names.get(sub, sub))} <span style="font-size:14px;color:#667085;font-weight:400">({len(ps)}편)</span></h2>'
                    f'<p>🧰 먼저 해보기: <a href="{base}/{TOOLS_HUB[0]}/{slug}/">{H.escape(title.split(" — ")[0])}</a></p>'
                    f'<ul>{_li(ps)}</ul>')
    head = (f'<p>부모님 스마트폰과 디지털 생활에 관한 원더랜드의 모든 가이드를 주제별로 모았습니다. '
            f'현재 {total}편이며, 새 글이 올라오면 이 목록도 자동으로 갱신됩니다(마지막 갱신 {date.today():%Y년 %m월 %d일}).</p>')
    return head + "".join(secs) + f'<p>👉 <a href="{base}/{TOOLS_HUB[0]}/">체크 도구 모음</a></p>'


def _upsert(base, h, slug, title, content, parent=0, dry=False):
    r = requests.get(f"{base}/wp-json/wp/v2/pages", headers=h, timeout=30,
                     params={"slug": slug, "status": "publish,draft,private", "context": "edit",
                             "_fields": "id,content,title,parent"})
    found = [p for p in (r.json() if r.ok else []) if p.get("parent", 0) == parent] if r.ok else []
    payload = {"title": title, "content": content, "slug": slug, "status": "publish", "parent": parent}
    if found:
        p = found[0]
        same = (p["content"]["raw"].strip() == content.strip()) and (p["title"]["raw"] == title)
        if same:
            print(f"  = /{slug}/ 변경 없음 (#{p['id']})")
            return p["id"]
        if dry:
            print(f"  ~ /{slug}/ 갱신 예정 (#{p['id']})"); return p["id"]
        u = requests.post(f"{base}/wp-json/wp/v2/pages/{p['id']}", headers=h, json=payload, timeout=60)
        print(f"  ~ /{slug}/ 갱신 {u.status_code}")
        return p["id"]
    if dry:
        print(f"  + /{slug}/ 생성 예정"); return 0
    c = requests.post(f"{base}/wp-json/wp/v2/pages", headers=h, json=payload, timeout=60)
    print(f"  + /{slug}/ 생성 {c.status_code}")
    return c.json().get("id", 0) if c.ok else 0


def _menu(base, h, items, dry=False):
    menus = requests.get(f"{base}/wp-json/wp/v2/menus", headers=h, timeout=30)
    if not menus.ok:
        print("  메뉴 조회 실패", menus.status_code); return
    for m in menus.json():
        cur = requests.get(f"{base}/wp-json/wp/v2/menu-items", headers=h, timeout=30,
                           params={"menus": m["id"], "per_page": 100, "_fields": "id,object_id,type,title"}).json()
        have = {it.get("object_id") for it in cur if it.get("type") == "post_type"}
        for pid, label in items:
            if not pid or pid in have:
                continue
            if dry:
                print(f"  + 메뉴 '{label}' 추가 예정"); continue
            r = requests.post(f"{base}/wp-json/wp/v2/menu-items", headers=h, timeout=30,
                              json={"title": label, "object": "page", "object_id": pid, "type": "post_type",
                                    "menus": m["id"], "status": "publish"})
            print(f"  + 메뉴 '{label}' {r.status_code}")


def main():
    dry = os.getenv("DRY", "0") == "1"
    base, h = _auth()
    subs, names = _posts_by_sub(base, h)
    hub_id = _upsert(base, h, TOOLS_HUB[0], TOOLS_HUB[1], _tools_hub(base), dry=dry)
    for t in TOOLS:
        _upsert(base, h, t[0], t[3], _tool_page(t, subs.get(t[1]) or [], base), parent=hub_id or 0, dry=dry)
    guide_id = _upsert(base, h, GUIDE_HUB[0], GUIDE_HUB[1], _guide_hub(subs, names, base), dry=dry)
    _menu(base, h, [(guide_id, "전체 가이드"), (hub_id, "도구 모음")], dry=dry)
    print("[hub_pages] 완료")


if __name__ == "__main__":
    main()
