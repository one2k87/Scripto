"""diag_sa_email.py — Search Console·GA4용 서비스계정 이메일만 출력(권한 부여 시 필요). 키는 출력하지 않는다."""
import json, os
raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
try:
    print("service account:", json.loads(raw).get("client_email", "(없음)"))
except Exception:
    cfg = json.load(open("config.json", encoding="utf-8"))
    sa = (cfg.get("insights") or {}).get("service_account_json") or ""
    try:
        print("service account:", json.loads(sa).get("client_email", "(없음)"))
    except Exception:
        print("service account: (config에 없음)")
