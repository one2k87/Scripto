"""diag_cfimage.py — Cloudflare FLUX 무료 이미지 1장 시험 생성(2026-11-02). LLM 한도 소모 0."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import images

print("CF_ACCOUNT_ID 있음:", bool(os.getenv("CF_ACCOUNT_ID")), "/ CF_API_TOKEN 있음:", bool(os.getenv("CF_API_TOKEN")))
p = images.build_prompt("70대 어머니가 거실에서 스마트폰 화면을 보며 미소 짓는 모습", "시니어 디지털", "photo")
data = images._cloudflare(p, {}, "1200x675")
if not data:
    print("실패:", images.LAST_ERR if hasattr(images, "LAST_ERR") else "")
    sys.exit(1)
from PIL import Image
import io
im = Image.open(io.BytesIO(data))
print(f"성공: {im.width}x{im.height}, {len(data)//1024}KB")
