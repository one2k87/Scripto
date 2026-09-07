"""sibling.py — 형제 사이트(픽담) 제목 중복 회피 (2026-09-08, P 권고의 대칭 적용)

배경: 2026-09-01 픽담과 원더랜드가 완전히 동일한 제목을 생성(둘 다 품질 게이트에서
폐기)한 실측 사고. 같은 파이프라인·같은 LLM에 니치가 겹치면 재발한다.
픽토는 원더랜드 제목을 공개 REST로 받아 회피 중 — 스크립토도 반대 방향을 막는다.

원칙(공유_경계 준수): 공개 정보(제목)만 읽는다. **중복 회피 전용** — 내부링크·통계 등
다른 용도로는 절대 쓰지 않는다(라인 격리). 조회 실패는 무해(회피만 못 할 뿐).
형제 목록은 data/site_categories.json의 sibling_sites(단일 소스).
"""
import json
import re

import requests

_CACHE = None


def _norm(s):
    return re.sub(r"[\s\W]+", "", str(s or "")).lower()


def norms():
    """형제 사이트들의 발행 글 제목(정규화) 집합. 프로세스당 1회 조회."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    out = set()
    try:
        sc = json.load(open("data/site_categories.json", encoding="utf-8"))
        sites = sc.get("sibling_sites") or []
    except Exception:
        sites = []
    for base in sites:
        base = str(base).rstrip("/")
        pg = 0
        try:
            while True:
                pg += 1
                r = requests.get(f"{base}/wp-json/wp/v2/posts",
                                 params={"per_page": 100, "page": pg, "_fields": "title"},
                                 timeout=20)
                if not r.ok:
                    break
                b = r.json()
                for it in b:
                    t = re.sub(r"<[^>]+>", "", (it.get("title") or {}).get("rendered") or "")
                    if t:
                        out.add(_norm(t))
                if len(b) < 100:
                    break
        except Exception as e:
            print(f"[형제] {base} 제목 조회 실패(회피 생략): {e}")
    if out:
        print(f"[형제] 중복 회피 제목 {len(out)}개 로드")
    _CACHE = out
    return out


def is_dup(keyword):
    return _norm(keyword) in norms()
