"""post_patch.py — 발행 글 본문의 '문장 단위' 정확 치환 (2026-11-02, 로컬 세션 요청).

용도: 사용자 승인된 한 문장 수정(모순 문장·오탈자·사실 정정)을 워드프레스 관리 화면 없이 처리.
입력(환경변수, workflow_dispatch로 전달):
  PATCH_ID       글 ID (예: 2555)
  PATCH_FIND     본문에서 찾을 정확한 문자열 (HTML 원문 기준, content.raw)
  PATCH_REPLACE  바꿀 문자열 (빈 값이면 삭제)
  PATCH_COUNT    기대 일치 횟수(기본 1). 실제 횟수가 다르면 아무것도 안 바꾸고 실패 — 엉뚱한 곳 치환 방지
  PATCH_DRY      "true"면 전후 미리보기만
안전장치: 무결성 검사(integrity.check)의 치명 결함이 늘면 중단 / 수정 전 원문을 data/patch_backup/에 커밋해 되돌릴 수 있게.
"""
import base64
import json
import os
import sys
from datetime import datetime

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import integrity  # noqa: E402


def main():
    pid = os.getenv("PATCH_ID", "").strip()
    find = os.getenv("PATCH_FIND", "")
    repl = os.getenv("PATCH_REPLACE", "")
    want = int(os.getenv("PATCH_COUNT", "1") or "1")
    dry = os.getenv("PATCH_DRY", "").lower() == "true"
    if not (pid.isdigit() and find.strip()):
        print("입력 오류: PATCH_ID(숫자)와 PATCH_FIND가 필요"); return 1

    wp = json.load(open("config.json", encoding="utf-8"))["wordpress"]
    base = wp["site_url"].rstrip("/")
    tok = base64.b64encode(f"{wp['username']}:{wp['app_password']}".encode()).decode()
    H = {"Authorization": f"Basic {tok}", "User-Agent": "Mozilla/5.0 (ScriptoBot)"}

    g = requests.get(f"{base}/wp-json/wp/v2/posts/{pid}", headers=H, timeout=30,
                     params={"context": "edit", "_fields": "id,title,content,link"})
    g.raise_for_status()
    p = g.json()
    html = p["content"]["raw"]
    n = html.count(find)
    print(f"#{pid} {p['title']['raw']}\n  일치 {n}회 (기대 {want}회)")
    if n != want:
        # 렌더링 텍스트엔 보이는데 원문엔 없는 경우(따옴표·공백 차이)를 돕기 위해 근처 후보를 보여준다
        key = find.strip()[:12]
        i = html.find(key)
        if i >= 0:
            print("  원문 근처:", repr(html[max(0, i - 40): i + len(find) + 40]))
        print("  ✗ 일치 횟수가 달라 중단(아무것도 바꾸지 않음)"); return 1
    new = html.replace(find, repl)
    before = len(integrity.critical(integrity.check(html)))
    after = len(integrity.critical(integrity.check(new)))
    i = html.find(find)
    print("  전:", repr(html[max(0, i - 60): i + len(find) + 60]))
    j = new.find(repl) if repl else i
    print("  후:", repr(new[max(0, j - 60): j + len(repl) + 60]))
    if after > before:
        print(f"  ✗ 무결성 치명 결함 증가({before}→{after}) — 중단"); return 1
    if dry:
        print("  (DRY — 적용 안 함)"); return 0

    os.makedirs("data/patch_backup", exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    open(f"data/patch_backup/{pid}-{stamp}.html", "w", encoding="utf-8").write(html)
    r = requests.post(f"{base}/wp-json/wp/v2/posts/{pid}", headers={**H, "Content-Type": "application/json"},
                      json={"content": new}, timeout=60)
    print("  ✓ 적용" if r.ok else f"  ✗ 실패 {r.status_code} {r.text[:150]}")
    msg = f"✏️ 본문 수정 #{pid} {'완료' if r.ok else '실패'}\n전: {find[:120]}\n후: {repl[:160]}\n{p['link']}"
    t, c = os.getenv("TELEGRAM_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if t and c:
        try:
            requests.post(f"https://api.telegram.org/bot{t}/sendMessage", data={"chat_id": c, "text": msg}, timeout=20)
        except Exception:
            pass
    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(main())
