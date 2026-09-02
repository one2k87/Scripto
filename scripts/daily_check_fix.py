# -*- coding: utf-8 -*-
"""매일 서버에서 점검하고, 옵트인 시 자동 수리까지 — '점검·수리의 서버 이전' v1 (2026-08-31).

왜: 종전엔 사용자가 대시보드를 열고 '전체 점검'과 '한 번에 고치기'를 눌러야 했다.
반복 작업은 자동화한다는 셀프서브 원칙에 따라, 대시보드의 본문 정밀 점검
(_dcQuickScore와 동일한 채점 스키마·임계값)을 파이썬으로 이식해 매일 실행에 넣었다.

- 결과는 dashboard/data/site_check.json → 앱의 '오늘 할 일' 인박스가 읽는다.
- data/site_categories.json 의 "auto_repair": true 면 60점 미만 글을
  Gemini로 재작성(하루 최대 5편 — 폭주 방지 캡)하고 검증 후 반영한다.
- 결과 요약을 텔레그램으로 보낸다(문제가 있거나 수리했을 때만).
"""
import json
import math
import os
import re
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests

cfg = json.load(open("config.json", encoding="utf-8"))
wp = cfg.get("wordpress", {}) or {}
site = (wp.get("site_url") or "").rstrip("/")
if not site or "your-blog" in site:
    print("[check] site_url 없음 — 건너뜀"); raise SystemExit(0)

try:
    site_file = json.load(open("data/site_categories.json", encoding="utf-8"))
except Exception:
    site_file = {}
AUTO_REPAIR = bool(site_file.get("auto_repair"))
REPAIR_CAP = int(site_file.get("auto_repair_cap", 5))

# ── 대시보드 _dcQuickScore 이식 (임계값은 실측 보정값 그대로) ─────────────
EXP = [r"실수", r"주의", r"조심", r"자주 (?:나|생기|발생)", r"흔히", r"잘못", r"실패",
       r"경고", r"이라면", r"라면 ", r"경우에 따라", r"에 따라 (?:다르|갈리)", r"장단", r"비교"]
CLICHE = [r"알아보겠습니다", r"살펴보겠습니다", r"이번 글에서는", r"도움이 되셨", r"마무리하겠습니다",
          r"함께 알아봐", r"참고하시기 바랍니다"]
FAKE = r"제가 (?:직접|경험|현장에서|작업할|시공|준비한)|겪었(?:습니다|기 때문|던)|겪으면서|경험 때문이었|현장을 경험|체감하게 된|느끼게 됐|(?:이해|정리)하게 된 건"


def strip_tags(h):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h or "")).strip()


def score_post(html):
    txt = strip_tags(html)
    sents = [s.strip() for s in re.split(r"(?<=[.!?다요죠])\s+", txt) if len(s.strip()) > 4]
    n = len(sents) or 1
    ends = {}
    for s in sents:
        m = re.search(r"(습니다|입니다|세요|해요|니다|있다|없다|한다|이다|까요|죠)\W*$", s)
        k = m.group(1) if m else "기타"
        ends[k] = ends.get(k, 0) + 1
    end_ratio = round(max(ends.values()) / n * 100) if ends else 0
    hedge = sum(1 for s in sents if re.search(r"(할 수 있습니다|일 수 있습니다|하는 것이 좋습니다|하시기 바랍니다)\W*$", s))
    hedge_ratio = round(hedge / n * 100)
    ordinal = len(re.findall(r"첫째[,.\s][\s\S]{0,120}?둘째[,.\s][\s\S]{0,120}?셋째", txt))
    comma3 = len(re.findall(r"[가-힣]+, [가-힣]+, [가-힣]+ 등", txt))
    triads = (ordinal + comma3) if (ordinal >= 2 or comma3 >= 4) else 0
    len_cv = 1.0
    if len(sents) >= 12:
        L = [len(s) for s in sents]
        mean = sum(L) / len(L)
        len_cv = math.sqrt(sum((x - mean) ** 2 for x in L) / len(L)) / mean if mean else 1
    fixed_end = bool(re.search(r"(결론적으로|요약하자면|지금까지 살펴본|이상으로)", txt[-260:]))
    exp = sum(1 for p in EXP if re.search(p, txt))
    cliche = sum(1 for p in CLICHE if re.search(p, txt))
    nums = len(re.findall(r"\d+(?:\.\d+)?\s*(?:mm|cm|m|만원|원|시간|분|kg|평|%|개|년|일)", txt))
    imgs = len(re.findall(r"<img", html or ""))
    fake_exp = len(re.findall(FAKE, txt))

    sc, issues = 100, []
    if exp == 0: sc -= 25; issues.append("실전 신호 0")
    elif exp <= 1: sc -= 10; issues.append("실전 신호 약함")
    if len(txt) < 800: sc -= 25; issues.append(f"본문 {len(txt)}자 — 너무 짧음")
    elif len(txt) < 1200: sc -= 12; issues.append(f"본문 {len(txt)}자 — 얇음")
    if nums < 3: sc -= 10; issues.append("구체 수치 부족")
    if end_ratio >= 80: sc -= 20; issues.append(f"어미 단조 {end_ratio}%")
    elif end_ratio >= 65: sc -= 10; issues.append(f"어미 단조 {end_ratio}%")
    if cliche >= 5: sc -= 20; issues.append(f"상투 표현 {cliche}종")
    elif cliche >= 3: sc -= 12; issues.append(f"상투 표현 {cliche}종")
    if imgs == 0: sc -= 8; issues.append("본문 이미지 없음")
    if hedge_ratio > 20: sc -= 12; issues.append(f"완충 표현 {hedge_ratio}%")
    if triads > 0: sc -= 8; issues.append(f"셋 묶음 {triads}회")
    if len_cv < 0.35: sc -= 10; issues.append(f"문장 길이 균일(CV {len_cv:.2f})")
    if fixed_end: sc -= 6; issues.append("고정 마무리")
    if fake_exp >= 3: sc -= 18; issues.append(f"1인칭 경험담 창작 의심 {fake_exp}건")
    elif fake_exp >= 1: sc -= 9; issues.append(f"1인칭 경험담 표현 {fake_exp}건")
    return max(0, sc), issues, len(txt)


# ── 글 수집·채점 ───────────────────────────────────────────────
posts = []
for pg in (1, 2):
    try:
        r = requests.get(f"{site}/wp-json/wp/v2/posts",
                         params={"per_page": 50, "page": pg, "_fields": "id,title,content,link"},
                         headers={"User-Agent": "Mozilla/5.0 (ScriptoBot)"}, timeout=30)
        if not r.ok: break
        chunk = r.json(); posts += chunk
        if len(chunk) < 50: break
    except Exception as e:
        print(f"[check] 목록 실패: {e}"); break

scored = []
for p in posts:
    sc, issues, ln = score_post(p.get("content", {}).get("rendered", ""))
    scored.append({"id": p["id"], "title": strip_tags(p["title"]["rendered"])[:60],
                   "link": p.get("link", ""), "score": sc, "len": ln, "issues": issues})
fails = [x for x in scored if x["score"] < 60]
avg = round(sum(x["score"] for x in scored) / len(scored)) if scored else 0
print(f"[check] {len(scored)}편 채점 — 평균 {avg}점 · 미달 {len(fails)}편")

# ── 자동 수리 (옵트인, 하루 캡) ─────────────────────────────────
repaired, repair_fail = [], []
if AUTO_REPAIR and fails:
    from llm import chat
    from publisher import update_post_content

    RULES = """[반드시 지킬 것 — 기계로 검사합니다]
1. 실전 신호 3개 이상: 자주 나는 실수·실패 시나리오, 조건 분기("벽이 석고보드라면 A, 콘크리트라면 B"),
   순서를 어기면 생기는 문제, 방법·부품 2가지 장단 비교.
   ⚠️ 겪지 않은 1인칭 경험담을 창작하지 말고, 원문에 있는 것("제가 경험했던"류)은 관찰형으로 바꾸세요.
2. 실측형 수치 4개 이상(규격·가격대·시간·개수). 원문에 없는 수치는 범위로.
3. 금지 문구: 알아보겠습니다/살펴보겠습니다/이번 글에서는/도움이 되셨기를/마무리하겠습니다.
4. 같은 어미 3문장 연속 금지, 10자 이하 짧은 문장 3개 이상.
5. 완충 표현 마무리 문장은 전체의 1/4 이하.
6. 셋 묶음 나열 금지(2개나 4개로).
7. 마지막 문단을 "결론적으로/요약하자면"으로 시작하지 말 것.
8. 이 글만의 정보 이득 1가지(비교표/실패 시나리오/분기표/실측 범위 중 택1).
9. 분량은 원문 이상(최소 1,300자). 소제목(h2/h3) 구조 유지.
10. 광고 자리(<div class="ad-slot">…</div>)와 기존 이미지·링크는 그대로 둘 것.
[출력] 순수 HTML 본문만. 코드블록 금지. <p>로 시작."""

    for f in fails[:REPAIR_CAP]:
        try:
            r = requests.get(f"{site}/wp-json/wp/v2/posts/{f['id']}?_fields=content", timeout=30)
            orig = r.json().get("content", {}).get("rendered", "")
            prompt = (f"아래 한국어 블로그 글 HTML을 '가치 있는 실전 글'로 다시 쓰세요. "
                      f"현재 감점 사유: {', '.join(f['issues'][:5])}\n\n{RULES}\n\n[원문]\n{orig}")
            neo = chat(prompt, cfg["llm"], max_tokens=16000, temperature=0.7)
            neo = re.sub(r"^```html?\s*|\s*```$", "", (neo or "").strip())
            nsc, nis, nlen = score_post(neo)
            if nsc >= 70 and nlen >= max(1100, int(f["len"] * 0.85)) and neo.lstrip().startswith("<"):
                if update_post_content(wp, f["id"], neo):
                    repaired.append(f"{f['title'][:24]} {f['score']}→{nsc}점")
                else:
                    repair_fail.append(f"{f['title'][:20]}(업로드)")
            else:
                repair_fail.append(f"{f['title'][:20]}(검증 {nsc}점)")
        except Exception as e:
            repair_fail.append(f"{f['title'][:20]}({str(e)[:30]})")
    print(f"[repair] 수리 {len(repaired)}편 · 실패 {len(repair_fail)}편")

# ── 결과 저장 + 텔레그램 ───────────────────────────────────────
out = {"at": datetime.datetime.now().isoformat()[:19], "n": len(scored), "avg": avg,
       "fails": [{k: x[k] for k in ("id", "title", "score", "issues")} for x in fails],
       "auto_repair": AUTO_REPAIR, "repaired": repaired, "repair_fail": repair_fail}
os.makedirs("dashboard/data", exist_ok=True)
json.dump(out, open("dashboard/data/site_check.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

try:
    import notify
    idx_line, ghost_line = "", ""
    try:
        idx = json.load(open("dashboard/data/index_status.json", encoding="utf-8"))
        pn = len([r for r in idx["results"] if r["url"] != idx["site"] + "/"])
        pp = len([r for r in idx["results"] if r["verdict"] == "PASS" and r["url"] != idx["site"] + "/"])
        idx_line = f"\n🚦 구글 색인 {pp}/{pn}편"
        ghosts = idx.get("ghosts") or []
        if ghosts:
            # 이미 SC 삭제 요청을 넣었으면 며칠간 색인 상태에 남는 게 정상 — 잔소리 대신 대기 안내.
            # 14일이 지나도 남아 있으면 그때 다시 행동 경고로 승격한다(2026-09-02 중복 알림 실측).
            req = ""
            try:
                req = (json.load(open("data/removed_urls.json", encoding="utf-8")) or {}).get("sc_removal_requested", "")
            except Exception:
                pass
            days = 99
            if req:
                import datetime as _dt
                days = (_dt.date.today() - _dt.date.fromisoformat(req)).days
            if req and days <= 14:
                ghost_line = f"\n👻 삭제 잔재 {len(ghosts)}건 — 삭제 요청 처리 대기 중({req} 요청, 보통 며칠 내 반영)"
            else:
                ghost_line = (f"\n👻 삭제 글 검색 잔재 {len(ghosts)}건 — SC 삭제 도구에서 제거하세요\n"
                              "https://search.google.com/search-console/removals")
    except Exception:
        pass
    # 2026-09-01부터 '무소식 = 정상'도 매일 한 줄로 알린다 — 앱을 안 열어도 아는 상태가 제품의 약속.
    msg = (f"📋 <b>스크립토 아침 점검</b>\n"
           f"글 {len(scored)}편 · 평균 {avg}점 · 미달 {len(fails)}편{idx_line}{ghost_line}")
    if repaired: msg += "\n🔧 자동 수리: " + " / ".join(repaired[:3])
    if repair_fail: msg += "\n⚠️ 수리 실패: " + " / ".join(repair_fail[:3])
    if fails and not AUTO_REPAIR: msg += "\n앱에서 '한 번에 고치기'를 실행하세요 (또는 자동 수리를 켜세요)"
    if not (fails or repaired or repair_fail): msg += "\n✅ 이상 없음"
    notify.send(cfg, msg)
except Exception as e:
    print(f"[notify] 건너뜀: {e}")
