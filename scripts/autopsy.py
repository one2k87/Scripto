"""autopsy.py — 반려 부검 봇 (자가적응 루프 P0, 2026-09-14)

'가치가 별로 없는 콘텐츠'류 반려의 프록시 지표를 현재 사이트에서 기계로 채점한다.
반려 원탭(❌)이 자동 발동하고, 평시에도 돌려 '신청 게이트 v2'의 근거 데이터가 된다.
구글 내부 기준은 관측 불가 — 이 지표들은 6회차까지의 실측에서 확인된 반려 원인의
프록시이며, 회차 결과가 쌓일수록 adsense_rules.json의 규칙 신뢰도를 갱신한다.

지표(전부 공개 데이터·repo 데이터만 사용, 시크릿 불필요):
  ①기계 제목: 조사 없는 명사 연쇄(5+)·절차어 종결 — 6회차 확정 원인
  ②니치 이탈: is_offniche + 카테고리 밖 글
  ③정보이득 보유율: 표/분기표/체크리스트/실패·복구 섹션 존재 비율
  ④실전 신호: quality.practical 패턴 보유 비율
  ⑤페르소나 일관성: 필명 서명 보유 비율
  ⑥실수요: insights.json GSC 클릭(28일)
  ⑦색인: index_status.json 신호등
출력: dashboard/data/autopsy.json + attempts.json 최신 회차에 진단 요약 append + 텔레그램
"""
import json
import os
import re
import sys
from datetime import datetime

import requests

DATA = os.path.join("dashboard", "data")


def _get_posts(base):
    posts, pg = [], 1
    while True:
        r = requests.get(f"{base}/wp-json/wp/v2/posts", timeout=30,
                         params={"per_page": 50, "page": pg, "status": "publish",
                                 "_fields": "id,title,content,link"},
                         headers={"User-Agent": "Mozilla/5.0 (ScriptoBot)"})
        if not r.ok:
            break
        b = r.json()
        posts += b
        if len(b) < 50:
            break
        pg += 1
    return posts


def mechanical_title(t):
    """키워드 뭉치 제목 검출 — 6회차 확정 원인의 프록시."""
    t = re.sub(r"[\"'?,!·…]", " ", t)
    words = [w for w in t.split() if w]
    # 조사·어미 흔적이 있는 어절 비율이 낮고 명사 연쇄가 길면 기계 제목
    josa = re.compile(r"(은|는|이|가|을|를|의|에|로|와|과|도|만|요|까|다|죠|냐|니|면|서|고|한|할|던|나요|세요|해요|합니다|입니다|할까|보다|처럼|부터|까지)$")
    natural = sum(1 for w in words if josa.search(w))
    run, best = 0, 0
    for w in words:
        run = 0 if josa.search(w) else run + 1
        best = max(best, run)
    ends_proc = bool(re.search(r"(절차|매뉴얼|프로토콜|보강|결선|체결|시공법)\s*$", t))
    return (best >= 6 and natural == 0) or ends_proc   # 보수적 검출(오검출이 더 해롭다)


def main():
    site_cfg = json.load(open("data/site_categories.json", encoding="utf-8"))
    base = "https://wontheland.com"
    cat = (site_cfg.get("categories") or [{}])[0]
    try:
        persona = json.load(open("data/persona.json", encoding="utf-8"))
        pen = (persona.get(persona.get("mode", "auto")) or persona.get("auto") or {}).get("pen_name", "")
    except Exception:
        pen = ""

    import topics as topics_mod
    posts = _get_posts(base)
    n = len(posts)
    mech, offn, gain, practical, signed = [], [], 0, 0, 0
    PRACT = [r"흔한\s*실수", r"잘못\s*(?:누르|입력|보내|지우|고르)", r"이럴\s*때", r"안\s*될\s*때",
             r"주의할\s*점", r"만약\s", r"반대로", r"라면\s", r"인\s*경우", r"차이가", r"멈추고"]
    for p in posts:
        t = re.sub(r"<[^>]+>", "", (p.get("title") or {}).get("rendered", ""))
        body = (p.get("content") or {}).get("rendered", "")
        if mechanical_title(t):
            mech.append(t[:40])
        if topics_mod.is_offniche(t):
            offn.append(t[:40])
        if ("<table" in body) or ("체크리스트" in body) or ("실패" in body and "복구" in body) or ("분기" in body):
            gain += 1
        if sum(1 for pt in PRACT if re.search(pt, body)) >= 1:
            practical += 1
        if pen and pen in body:
            signed += 1

    def _load(name, default):
        try:
            return json.load(open(os.path.join(DATA, name), encoding="utf-8"))
        except Exception:
            return default
    ins = _load("insights.json", {})
    scp = ((ins.get("search_console") or {}).get("pages")) or []
    clicks = sum(int(p.get("clicks") or 0) for p in scp)
    idx = _load("index_status.json", {})
    idx_pass = sum(1 for v in (idx.get("results") or {}).values()
                   if isinstance(v, dict) and "indexed" in str(v.get("verdict", "")).lower()) \
        if isinstance(idx.get("results"), dict) else idx.get("passed", "?")

    report = {
        "at": datetime.now().isoformat()[:19],
        "rules_version": _load("adsense_rules.json", {}).get("version", "?"),
        "posts": n,
        "mechanical_titles": {"n": len(mech), "samples": mech[:5]},
        "offniche": {"n": len(offn), "samples": offn[:5]},
        "gain_coverage": round(gain / n, 2) if n else 0,
        "practical_coverage": round(practical / n, 2) if n else 0,
        "persona_signed": round(signed / n, 2) if n else 0,
        "gsc_clicks_28d": clicks,
        "indexed_hint": idx_pass,
        "verdicts": [],
    }
    # 판정(가설 초안) — 6회차 확정 원인 순서대로
    if report["mechanical_titles"]["n"]:
        report["verdicts"].append(f"기계 제목 {len(mech)}편 — 재작성 필요")
    if report["offniche"]["n"]:
        report["verdicts"].append(f"니치 이탈 {len(offn)}편 — 비공개/재분류 필요")
    if n and report["gain_coverage"] < 0.9:
        report["verdicts"].append(f"정보이득 보유율 {report['gain_coverage']:.0%} < 90%")
    if n and report["practical_coverage"] < 0.9:
        report["verdicts"].append(f"실전 신호 보유율 {report['practical_coverage']:.0%} < 90%")
    if clicks < 3:
        report["verdicts"].append(f"실수요 부족(GSC 클릭 {clicks}) — 유입 라인·대기 필요")
    if not report["verdicts"]:
        report["verdicts"].append("전 지표 통과 — 성격 지표상 신청 가능 상태(게이트 v2 기준)")

    json.dump(report, open(os.path.join(DATA, "autopsy.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    # 회차 대장에 진단 스냅샷 부착(최신 미결 회차)
    try:
        ap = os.path.join(DATA, "attempts.json")
        a = json.load(open(ap, encoding="utf-8"))
        cur = next((x for x in reversed(a["attempts"]) if not x.get("result")), None)
        if cur is not None:
            cur.setdefault("autopsies", []).append(
                {"at": report["at"], "verdicts": report["verdicts"],
                 "posts": n, "clicks": clicks, "gain": report["gain_coverage"]})
            cur["autopsies"] = cur["autopsies"][-10:]
            json.dump(a, open(ap, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception as e:
        print("대장 기록 실패:", e)

    msg = ("🔬 스크립토 부검 리포트 — 글 " + str(n) + "편 (rules " + str(report["rules_version"]) + ")\n"
           + "\n".join("· " + v for v in report["verdicts"]))
    print(msg)
    tok, chat_id = os.getenv("TELEGRAM_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if tok and chat_id:
        try:
            requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                          data={"chat_id": chat_id, "text": msg}, timeout=20)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
