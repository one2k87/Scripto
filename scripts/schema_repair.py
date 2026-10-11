"""schema_repair.py — 기발행 글의 구조화 데이터(JSON-LD)·FAQ 블록 자가치유 (2026-10-12).

GSC 메일 "파싱할 수 없는 구조화된 데이터 — 파싱 오류: ':' 누락"(#2618)에서 출발해 전수 실측한 결과:
  (a) FAQ JSON-LD가 중간에 잘린 채 </script> 없이 끝남 — accuracy.revise 출력이 max_tokens에 잘림 (#2618·#2737)
  (b) FAQ JSON-LD 파싱 오류 (#2580)
  (c) '자주 묻는 질문' 제목 아래 빈 h3/p 4쌍 + 질문·답이 ""인 FAQPage — 모델이 q/a 대신 다른 키로 돌려줌 (8편)
  (d) JSON-LD·기준일·고지 꼬리 블록이 통째로 없음 — 같은 잘림 (#2712·#2965 등 5편)

하는 일(멱등, 매일 daily-blog에서 DRY=0으로 돌려도 안전):
  1. 모든 <script type="application/ld+json"> 제거(닫히지 않은 것은 본문 끝까지 통째로).
  2. 빈 FAQ 블록 제거, 살아있는 FAQ(h3+p)는 그대로 두고 JSON-LD 재료로 씀.
  3. 기준일·AI 고지(제31조)가 없으면 '함께 보면 좋은 글' 앞에 넣는다.
  4. BlogPosting(+FAQPage) JSON-LD를 글 제목·발행일·수정일·대표이미지·페르소나로 다시 만들어 끝에 붙인다.
  5. 결과 JSON-LD를 json.loads로 자가검증한 뒤에만 저장.

DRY=1(기본): 바뀔 글 목록과 이유만 출력. DRY=0: 적용. ONLY=2618,2737 처럼 특정 글만도 가능.
"""
import base64
import html as html_mod
import json
import os
import re
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LD_RE = re.compile(r'<script type="application/ld\+json">[\s\S]*?(?:</script>|\Z)')
FAQ_H2_RE = re.compile(r"<h2[^>]*>자주 묻는 질문</h2>")   # _slugify_headings가 id를 붙이므로 속성 허용
TAIL_ANCHOR_RE = re.compile(r'<h2>함께 보면 좋은 글</h2>')
STRAY_RE = re.compile(r'<script type="application/ld\+json">\s*$')  # 잔재


def _auth():
    cfg = json.load(open("config.json", encoding="utf-8"))
    wp = cfg.get("wordpress", {}) or {}
    if not (wp.get("site_url") and wp.get("username") and wp.get("app_password")):
        print("WP 자격 부족"); sys.exit(1)
    base = wp["site_url"].rstrip("/")
    tok = base64.b64encode(f"{wp['username']}:{wp['app_password']}".encode()).decode()
    return cfg, base, {"User-Agent": "Mozilla/5.0 (ScriptoBot)", "Authorization": f"Basic {tok}",
                       "Content-Type": "application/json"}


def _persona(cfg):
    try:
        p = json.load(open("data/persona.json", encoding="utf-8"))
        pa = p.get(p.get("mode", "auto")) or p.get("auto") or {}
    except Exception:
        pa = {}
    return (pa.get("pen_name") or cfg.get("author") or "운영자"), (pa.get("bio") or pa.get("intro") or "")


def _text(s):
    return html_mod.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def extract_faqs(html):
    """'자주 묻는 질문' h2 뒤의 h3/p 쌍. 다음 h2 또는 꼬리 블록(class=verified/freshness/ai-notice)에서 멈춘다."""
    mh = FAQ_H2_RE.search(html)
    if not mh:
        return []
    seg = html[mh.end():]
    m = re.search(r'<h2[\s>]|<p class="(?:verified|freshness|ai-notice|disclaimer)"', seg)
    if m:
        seg = seg[:m.start()]
    out = []
    for q, a in re.findall(r"<h3[^>]*>(.*?)</h3>\s*<p[^>]*>(.*?)</p>", seg, re.S):
        q, a = _text(q), _text(a)
        if q and a:
            out.append({"q": q, "a": a})
    return out


def strip_empty_faq(html):
    """질문이 하나도 없는 FAQ 블록을 통째로 제거. 일부만 비었으면 빈 쌍만 제거."""
    mh = FAQ_H2_RE.search(html)
    if not mh:
        return html, False
    i, seg_start = mh.start(), mh.end()
    seg = html[seg_start:]
    m = re.search(r'<h2[\s>]|<p class="(?:verified|freshness|ai-notice|disclaimer)"|<script type="application/ld', seg)
    end = seg_start + (m.start() if m else len(seg))
    block = html[seg_start:end]
    cleaned = re.sub(r"<h3[^>]*>\s*</h3>\s*<p[^>]*>\s*</p>\s*", "", block)
    if not re.search(r"<h3[^>]*>\s*\S", cleaned):          # 살아있는 질문 없음 → 제목까지 제거
        return html[:i] + html[end:], True
    if cleaned != block:
        return html[:seg_start] + cleaned + html[end:], True
    return html, False


def build_jsonld(post, faqs, author, bio):
    title = _text((post.get("title") or {}).get("raw") or (post.get("title") or {}).get("rendered") or "")
    html = (post.get("content") or {}).get("raw") or ""
    desc = _text((post.get("excerpt") or {}).get("raw") or "")
    if not desc or len(desc) < 40:
        m = re.search(r'<p class="hook"[^>]*>(.*?)</p>', html, re.S) or re.search(r"<p(?![^>]*class)[^>]*>(.*?)</p>", html, re.S)
        desc = _text(m.group(1))[:155] if m else title
    img = re.search(r'<img[^>]+src="([^"]+)"', html)
    author_obj = {"@type": "Person", "name": author}
    if bio:
        author_obj["description"] = bio
    blog = {"@context": "https://schema.org", "@type": "BlogPosting",
            "headline": title, "description": desc, "inLanguage": "ko",
            "datePublished": post.get("date_gmt", "") + "Z" if post.get("date_gmt") else post.get("date", ""),
            "dateModified": post.get("modified_gmt", "") + "Z" if post.get("modified_gmt") else post.get("modified", ""),
            "author": author_obj, "mainEntityOfPage": {"@type": "WebPage", "@id": post.get("link", "")}}
    if img:
        blog["image"] = [img.group(1)]
    scripts = [json.dumps(blog, ensure_ascii=False)]
    if faqs:
        faq = {"@context": "https://schema.org", "@type": "FAQPage",
               "mainEntity": [{"@type": "Question", "name": f["q"],
                               "acceptedAnswer": {"@type": "Answer", "text": f["a"]}} for f in faqs]}
        scripts.append(json.dumps(faq, ensure_ascii=False))
    for s in scripts:                      # 자가검증 — 깨진 JSON은 절대 올리지 않는다
        json.loads(s)
    return "".join(f'<script type="application/ld+json">{s}</script>' for s in scripts)


TAIL_CUT_RE = re.compile(r'<p class="verified"|<p class="freshness"|<p class="ai-notice"|<p class="disclaimer"'
                         r'|<div class="disclaimer"|<h2[^>]*>함께 보면 좋은 글</h2>|<script type="application/ld\+json">')


def rebuild_tail(html, author):
    """꼬리(기준일·고지·면책·관련 글)를 결정적으로 다시 만든다. (새 HTML, 바뀜 여부)
    실측(#2596): 옛 잘림이 '함께 보면 좋은 글' 목록 중간에서 끊겨 <a>·<ul>이 안 닫힌 채 남고, 그 뒤에
    보강 블록이 또 붙어 제목이 2개가 됐다. 꼬리는 생성 규칙이 고정돼 있으니 부분 수선보다 재조립이 안전하다."""
    import generator, integrity
    m = TAIL_CUT_RE.search(html)
    if not m:
        return html, False
    head, seg = html[:m.start()], html[m.start():]
    seg_wo_ld = LD_RE.sub("", seg)
    dup_related = len(re.findall(r"함께 보면 좋은 글", seg_wo_ld)) > 1
    broken = bool(integrity.tag_balance(seg_wo_ld))
    missing = any(k not in seg_wo_ld for k in ('class="verified"', 'class="freshness"', 'class="ai-notice"'))
    if not (dup_related or broken or missing):
        return html, False
    print(f"  [tail] dup={dup_related} broken={integrity.tag_balance(seg_wo_ld) if broken else ''} missing={missing} seg={seg_wo_ld[:160]!r}")
    # 관련 글 링크 회수(사이트 내부 링크만, 중복 제거, 3개)
    links, seen = [], set()
    for href, txt in re.findall(r'<a href="([^"]+)"[^>]*>([^<]{1,150})</a>', seg_wo_ld):
        if "wontheland.com" in href and href not in seen and _text(txt):
            seen.add(href); links.append((href, _text(txt)))
    related = ""
    if links:
        lis = "".join(f'<li><a href="{h}">{html_mod.escape(t)}</a></li>' for h, t in links[:3])
        related = f'<h2>함께 보면 좋은 글</h2><ul class="related">{lis}</ul>'
    # 면책 문단은 온전히 닫힌 것만 재사용
    dm = re.search(r'<p class="disclaimer"[^>]*>.*?</p>', seg_wo_ld, re.S)
    disclaimer = dm.group(0) if dm else ""
    tail = (generator._verified_html() + generator._freshness_html() + generator._ai_notice_html(author)
            + disclaimer + related)
    return head.rstrip() + tail, True


def repair(post, author, bio):
    """(새 HTML, 변경 사유 목록). 변경 없으면 사유 []."""
    raw = (post.get("content") or {}).get("raw") or ""
    html, why = raw, []

    import integrity
    has_img = bool(re.search(r"<img\s", html))
    lds = LD_RE.findall(html)
    bad = 0
    for s in lds:
        body = re.sub(r"^<script[^>]*>|</script>$", "", s)
        try:
            o = json.loads(body)
            if o.get("@type") == "FAQPage" and any(not q.get("name") or not (q.get("acceptedAnswer") or {}).get("text")
                                                   for q in o.get("mainEntity", [])):
                bad += 1
            if o.get("@type") == "BlogPosting" and has_img and not o.get("image"):
                bad += 1
        except Exception:
            bad += 1
    if not lds:
        why.append("JSON-LD 없음")
    elif bad:
        why.append(f"JSON-LD 깨짐/빈 FAQ/이미지 누락 {bad}건")

    # 꼬리 재조립은 tidy(html5lib) 전에 — 안 닫힌 <a>를 파서가 뒤 블록까지 감싸 버리기 전에 원문에서 링크를 회수
    html, tail_rebuilt = rebuild_tail(html, author)
    if tail_rebuilt:
        why.append("꼬리 재조립(깨진 관련글/중복/누락)")

    # 기계 수리(빈 제목·빈 문단·안 닫힌 태그) — integrity.fix가 단일 기준
    _bal_before = integrity.tag_balance(LD_RE.sub("", html))
    html, done = integrity.fix(html)
    done = [d for d in done if "JSON-LD" not in d and "FAQ" not in d]   # JSON-LD·FAQ는 아래서 다시 만든다
    if done:
        why.append("/".join(sorted(set(done))) + (f" {_bal_before}" if _bal_before else ""))

    html, faq_changed = strip_empty_faq(html)
    if faq_changed:
        why.append("빈 FAQ 블록 제거")

    html = LD_RE.sub("", html).rstrip()

    import generator
    added = []
    if 'class="verified"' not in html:
        added.append(generator._verified_html())
    if 'class="freshness"' not in html:
        added.append(generator._freshness_html())
    if 'class="ai-notice"' not in html:
        added.append(generator._ai_notice_html(author))
    if added:
        why.append("기준일/고지 보강")
        ins = "".join(added)
        m = TAIL_ANCHOR_RE.search(html)
        html = (html[:m.start()] + ins + html[m.start():]) if m else html + ins

    faqs = extract_faqs(html)
    html = html + build_jsonld(post, faqs, author, bio)

    if not why:
        # JSON-LD가 멀쩡했고 구조 변화도 없으면 재작성하지 않는다(수정일 보존).
        return raw, []
    crit = integrity.critical(integrity.check(html))
    if crit:
        raise RuntimeError(f"수리 후에도 치명 문제 {crit}")
    return html, why


def main():
    dry = os.getenv("DRY", "1") != "0"
    only = {int(x) for x in os.getenv("ONLY", "").replace(" ", ",").split(",") if x.strip().isdigit()}
    cfg, base, H = _auth()
    author, bio = _persona(cfg)

    posts, pg = [], 1
    while True:
        r = requests.get(f"{base}/wp-json/wp/v2/posts", headers=H, timeout=60,
                         params={"per_page": 50, "page": pg, "status": "publish", "context": "edit",
                                 "_fields": "id,title,content,excerpt,date,date_gmt,modified,modified_gmt,link"})
        if not r.ok:
            break
        b = r.json(); posts += b
        if len(b) < 50:
            break
        pg += 1
    if only:
        posts = [p for p in posts if p["id"] in only]

    done, fail, touched, warns = 0, [], [], {}
    import integrity
    for p in posts:
        pid = p["id"]
        try:
            new, why = repair(p, author, bio)
        except Exception as e:
            fail.append(f"#{pid} repair {e}"); continue
        if os.getenv("DUMP_RAW") and str(pid) in os.getenv("DUMP_RAW", "").split(","):
            os.makedirs("dashboard/data/tmp", exist_ok=True)
            open(f"dashboard/data/tmp/raw_{pid}.html", "w", encoding="utf-8").write((p.get("content") or {}).get("raw") or "")
            open(f"dashboard/data/tmp/new_{pid}.html", "w", encoding="utf-8").write(new)
        w = [m for lv, m in integrity.check(new) if lv == "warn"]
        if w:
            warns[pid] = w
        if not why:
            continue
        touched.append(f"#{pid} {', '.join(why)}")
        if dry:
            continue
        u = requests.post(f"{base}/wp-json/wp/v2/posts/{pid}", headers=H, timeout=60, json={"content": new})
        if u.ok:
            done += 1
        else:
            fail.append(f"#{pid} {u.status_code}")
        time.sleep(0.4)

    head = f"🧬 구조화 데이터 자가치유 — 대상 {len(posts)}편, 수리 {len(touched)}편" + (" (드라이런)" if dry else f", 적용 {done}편")
    try:   # 대시보드·기록용 일일 무결성 감사 결과
        from datetime import datetime
        os.makedirs("dashboard/data", exist_ok=True)
        json.dump({"at": datetime.now().strftime("%Y-%m-%d %H:%M"), "total": len(posts), "dry": dry,
                   "repaired": touched, "failed": fail, "warnings": {str(k): v for k, v in warns.items()}},
                  open("dashboard/data/integrity_audit.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception as e:
        print("감사 기록 실패:", e)
    print(head)
    for t in touched:
        print("  ", t)
    if fail:
        print("  실패:", fail)
    if touched and not dry:
        msg = head + "\n" + "\n".join(touched[:12]) + ("\n…" if len(touched) > 12 else "") + \
              ("\n⚠️ 실패 " + ", ".join(fail) if fail else "")
        t, c = os.getenv("TELEGRAM_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
        if t and c:
            try:
                requests.post(f"https://api.telegram.org/bot{t}/sendMessage", data={"chat_id": c, "text": msg}, timeout=20)
            except Exception:
                pass
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
