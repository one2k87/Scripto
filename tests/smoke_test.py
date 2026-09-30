"""
smoke_test.py - 배포 전 '핵심 함수가 안 깨졌는지' 빠르게 확인(무료·오프라인).
네트워크·API 키 없이 순수 로직만 검증한다. 실패하면 종료코드 1.
"""
import os
import sys
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

fails = []


def check(name, cond):
    print(("  OK  " if cond else " FAIL ") + name)
    if not cond:
        fails.append(name)


# 1) config.json 이 유효한 JSON 이고 키가 자리표시자인지(실키 유출 방지)
with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
    cfg = json.load(f)
check("config.json 유효", isinstance(cfg, dict))
api = str(cfg.get("llm", {}).get("api_key", ""))
check("config.json 에 실제 키 없음(자리표시자)", ("여기에" in api) or api == "")

# 2) 금지·기업 주제 필터
import topics
check("전쟁 주제 차단", topics.is_blocked("우크라이나 전쟁 근황"))
check("도박 주제 차단", topics.is_blocked("카지노 후기"))
check("일반 주제 통과", not topics.is_blocked("무직자 대출 조건"))
check("기업 주제 차단", topics.is_corporate("국내 클라우드 시장 규모 분석"))
check("개인 주제 통과", not topics.is_corporate("구글 포토 용량 늘리는 법"))

# 3) 품질 게이트
import quality
good = {"html": "<p>2026년 9월 확인 기준으로 정리했습니다. 흔히 하는 실수는 순서를 건너뛰는 것입니다.</p><h2>준비</h2><p>실리콘 10mm 노즐과 마스킹 테이프 2개를 준비합니다. 비용은 8,000원에서 15,000원 사이입니다. 벽이 석고보드라면 앙카를 쓰고, 콘크리트라면 해머드릴이 필요합니다. 두 방법은 비용과 강도에서 장단이 갈립니다.</p><figure><img src='x.png' alt='작업하는 손'><figcaption>작업 장면</figcaption></figure><h2>시공</h2><p>작업 시간은 30분 정도 걸립니다. 실패 사례로는 건조 시간 1시간을 지키지 않아 다시 뜯는 경우가 많습니다. 먼저 표면의 먼지를 마른 걸레로 닦아내세요. 짧게 끊지 마세요. 중간에 멈추면 경계면에 이음선이 남고 물이 스며들 틈이 생겨 결국 처음부터 다시 뜯어내야 하는 상황이 오기 때문에 한 번에 끝까지 이어서 마감하는 것이 무엇보다 중요합니다. 노즐 각도는 45도입니다. 압력은 일정하게. 손이 흔들리면 폭이 달라져 보기 싫은 자국이 남게 됩니다. 초보자라면 마스킹 테이프를 먼저 붙이고 시작하는 편이 마감 품질에서 차이가 큽니다. 테이프는 실리콘이 마르기 전에 떼야 깔끔합니다. 겨울철에는 실내 온도를 5도 이상으로 맞춰야 경화가 정상적으로 진행되고, 여름에는 반대로 너무 빨리 굳어 수정할 시간이 없는 것을 조심해야 합니다. 작은 구간부터 연습해 보세요. 익숙해지면 속도가 붙습니다.</p><figure><img src='y.png' alt='단계 도해'><figcaption>작업 순서 도해</figcaption></figure><h2>마감 점검</h2><p>제조사 시방서를 근거로 24시간 양생을 권합니다. 모서리 4곳을 눌러 들뜸을 확인합니다. 들뜸이 있으면 해당 구간만 잘라냅니다. 칼날은 새것으로. 그 다음 프라이머를 얇게 바르고 완전히 마른 뒤에 같은 제품으로 다시 채워 넣어야 기존 구간과 색 차이가 나지 않고 경계선도 티가 나지 않습니다. 마르는 시간은 계절마다 다릅니다. 겉마름과 속마름은 다르니 하루는 기다리는 편이 안전합니다. 점검은 밝은 낮에 하세요. 어두운 조명 아래에서는 미세한 들뜸이 잘 보이지 않아 놓치기 쉽고, 놓친 들뜸은 장마철에 하자로 돌아옵니다.</p><h2>비용 비교</h2><p>직접 하면 재료비 15,000원 안팎으로 끝나지만 업체를 부르면 출장비 포함 60,000원에서 100,000원 사이가 일반적입니다. 다만 곰팡이가 이미 안쪽까지 번진 상태라면 이야기가 다릅니다. 겉만 덮으면 두 달 안에 재발합니다. 이럴 때는 기존 실리콘을 전부 제거하고 곰팡이 제거제를 뿌린 뒤 하루를 말리고 나서 새로 쏘는 것이 정석이고, 여기까지 하면 반나절 작업이 됩니다. 자신이 없다면 욕실 한 곳만 업체에 맡겨 과정을 본 뒤 나머지를 직접 하는 절충안도 있습니다. 공구는 한 번 사두면 5년은 씁니다.</p>", "focus_keyword": "실리콘"}
# ↑ 2026-09-01: 게이트 강화(수치·실전신호·이미지·1,200자) 이후 옛 픽스처(가나다라×200)가 항상 실패 — 현행 요건을 충족하는 픽스처로 교체
# ↑ 2026-10-01: 이미지 요건이 1→2장(대표+설명)으로 바뀐 9/17 이후 이 픽스처가 2주간 계속 실패하고 있었다.
#    data/article_requirements.json 을 고치면 이 픽스처도 같이 고쳐야 한다.
bad = {"html": "<p>짧다</p>", "focus_keyword": "대출"}
check("좋은 글 통과", quality.check(good, [], cfg.get("safety", {}))[0])
check("나쁜 글 보류", not quality.check(bad, [], cfg.get("safety", {}))[0])

# 4) 최신성 휴리스틱
import accuracy
iss, stale = accuracy.heuristic({"title": "2019년 최신 대출", "html": "<p>올해 기준입니다.</p>"})
check("옛 연도 감지", stale)

# 5) 무료 코드 썸네일 생성(Pillow)
import images
data = images._thumbnail("무직자 비상금 대출 조건 총정리", "금융", "600x600")
check("코드 썸네일 생성", bool(data) and len(data) > 500)

print()
if fails:
    print(f"❌ 스모크 테스트 실패 {len(fails)}건: {fails}")
    sys.exit(1)
print("✅ 스모크 테스트 전체 통과")
