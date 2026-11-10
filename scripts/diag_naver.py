"""네이버 검색광고 키워드도구 인증 점검(값은 출력하지 않는다)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import metrics

ncfg = {k: os.environ.get(e, "").strip() for k, e in
        (("api_key", "NAVER_API_KEY"), ("secret_key", "NAVER_SECRET_KEY"), ("customer_id", "NAVER_CUSTOMER_ID"))}
print("키 길이:", {k: len(v) for k, v in ncfg.items()})
probe = ["갤럭시 국제전화 차단", "카톡 글씨 크기", "에너지바우처 잔액조회", "핸드폰 화면 어두워짐", "부모님 갤럭시 a15 업데이트 알림 떴을 때 데이터 요금"]
vol = metrics.naver_volumes(probe, ncfg)
if vol is None:
    print("결과: 실패(위 오류 참고)"); sys.exit(1)
print(f"결과: 성공 · 응답 키워드 {len(vol)}개")
for q in probe:
    m = vol.get(metrics._norm(q))
    print(f"  {q} → {m['volume'] if m else '응답에 없음'}{' / 경쟁 ' + m['comp'] if m else ''}")
