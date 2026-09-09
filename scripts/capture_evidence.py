"""capture_evidence.py — 승인 여정 증빙 자동 캡처 (2026-09-09)

docs/승인_여정_기록.md 4절의 캡처 목록 중 '로그인이 필요 없는 것' 전부를
Playwright로 찍어 docs/증빙/<날짜>/ 에 저장한다. 승인 당일 원탭 절차(approveDayFlow)가
이 워크플로를 자동 발동하고, 심사 중에도 수동 실행해 '이전' 상태를 기준선으로 남긴다.

자동 캡처 대상:
  ① 원더랜드 홈(데스크톱)  ② ads.txt  ③ 앱 홈(데모 모드, 모드 카드·D+n 뱃지)
  ④ 앱 승인 탭(여정 스테퍼·준비도)  ⑤ 앱 글 탭
수동으로 남는 것(구글 로그인 필요 — 자동화 금지 영역):
  · 애드센스 승인 화면/메일  · GSC 색인 그래프
"""
import os
import sys
from datetime import datetime

from playwright.sync_api import sync_playwright

OUT = os.path.join("docs", "증빙", datetime.now().strftime("%Y-%m-%d"))
APP = "https://one2k87.github.io/Scripto/dashboard/"


def shot(page, path, **kw):
    page.screenshot(path=os.path.join(OUT, path), full_page=kw.pop("full", False), **kw)
    print("  ✓", path)


def main():
    os.makedirs(OUT, exist_ok=True)
    ok, fail = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()

        # ── 사이트(데스크톱 뷰) ──
        d = browser.new_page(viewport={"width": 1280, "height": 800})
        for name, url, full in (
            ("01_원더랜드_홈.png", "https://wontheland.com/", False),
            ("02_ads_txt.png", "https://wontheland.com/ads.txt", False),
        ):
            try:
                d.goto(url, timeout=45000, wait_until="domcontentloaded")
                d.wait_for_timeout(2500)
                shot(d, name, full=full)
                ok.append(name)
            except Exception as e:
                print("  ✗", name, e); fail.append(name)

        # ── 앱(모바일 뷰, 데모 모드 = 실측 데이터 읽기 전용) ──
        m = browser.new_page(viewport={"width": 390, "height": 844})
        try:
            m.goto(APP, timeout=45000)
            m.wait_for_timeout(2500)
            m.get_by_text("데모로 둘러보기").click(timeout=10000)
            m.wait_for_timeout(4000)              # 데모 진입은 reload를 동반한다
            views = [("home", "03_앱_홈_모드카드.png"),
                     ("ads", "04_앱_승인탭_여정.png"),
                     ("list", "05_앱_글탭.png")]
            for k, name in views:
                try:
                    m.evaluate(f"gotoTab('{k}')")
                    m.wait_for_timeout(2500)
                    shot(m, name, full=True)
                    ok.append(name)
                except Exception as e:
                    print("  ✗", name, e); fail.append(name)
        except Exception as e:
            print("  ✗ 앱 데모 진입 실패:", e); fail.append("앱 전체")
        browser.close()

    print(f"[증빙] 저장 {len(ok)}장 → {OUT} (실패 {len(fail)})")
    # 실패가 있어도 성공분은 커밋되도록 정상 종료. 전부 실패면 에러로 알린다.
    if ok:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
