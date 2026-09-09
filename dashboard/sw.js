// 서비스워커 - 아이폰 홈화면 설치(PWA)
// v3: 앱 화면(HTML/JS)과 데이터(JSON)는 '항상 최신 우선'으로 받아,
//     업데이트가 즉시 반영되도록 함(예전엔 캐시가 옛 화면을 붙잡던 문제 수정).
const CACHE = "scripto-v95";

// 앱에서 '즉시 업데이트' 요청 시 대기 없이 새 버전으로 전환
self.addEventListener("message", (e) => {
  if (e.data === "SKIP_WAITING") self.skipWaiting();
});
const ASSETS = [
  "./manifest.json",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
  "./icons/apple-touch-icon.png"
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(// 같은 오리진에 4개 앱이 살므로 "내 접두사" 캐시만 지운다(남의 앱 캐시 삭제 금지 — 2026-09-09 실측: 두 앱이 같은 이름을 쓰며 서로 지우던 포크 잔재 수정)
      keys.filter((k) => k.startsWith("scripto-") && k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  const isDoc = e.request.mode === "navigate" ||
                url.pathname.endsWith("/") || url.pathname.endsWith(".html");
  const isJson = url.pathname.endsWith(".json");

  // 화면(HTML)과 데이터(JSON)는 네트워크 우선 → 새로 올린 버전/글이 바로 보임
  if (isDoc || isJson) {
    e.respondWith(
      fetch(e.request).then((r) => {
        const copy = r.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return r;
      }).catch(() => caches.match(e.request))
    );
    return;
  }
  // 아이콘 등 정적 자원만 캐시 우선(오프라인에서도 아이콘 표시)
  e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request)));
});
