/* 少年仔、安啦會客室 Service Worker（由 /sw.js 提供，scope 為 /）
 * 離線安心逃生艙：預先快取外殼資源與離線頁面。
 * 隱私原則：
 *   - 絕不快取 /api/*（對話、摘要、狀態等皆不落地）。
 *   - 不快取任何 HTML 頁面本身（頁面內含 CSRF token 與當次會談狀態）；斷網時改顯示離線頁。
 */
"use strict";

const CACHE_PREFIX = "anla-shell-";
const CACHE_NAME = CACHE_PREFIX + "v2026-10-23.6";
const OFFLINE_URLS = ["/offline", "/static/offline.html"];
const SHELL = [
  ...OFFLINE_URLS,
  "/static/css/style.css",
  "/static/css/themes.css",
  "/static/js/app.js",
  "/static/js/referral.js",
  "/static/js/checkin.js",
  "/static/js/theme.js",
  "/static/js/pwa.js",
  "/manifest.json",
  "/static/manifest.json",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/icons/icon-maskable-192.png",
  "/static/icons/icon-maskable-512.png",
  "/static/icons/apple-touch-icon.png"
];

self.addEventListener("install", event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    // 逐一快取：任何一項暫時取不到（例如路由尚未上線）都不影響其他項目。
    await Promise.all(SHELL.map(url =>
      fetch(new Request(url, { cache: "reload", credentials: "same-origin" }))
        .then(response => (response.ok ? cache.put(url, response) : null))
        .catch(() => null)
    ));
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys
      .filter(key => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME)
      .map(key => caches.delete(key)));
    await self.clients.claim();
  })());
});

async function offlineFallback() {
  const cache = await caches.open(CACHE_NAME);
  for (const url of OFFLINE_URLS) {
    const hit = await cache.match(url);
    if (hit) return hit;
  }
  return new Response(
    "<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>" +
    "<title>離線中</title><body style='font-family:sans-serif;padding:1.5rem;line-height:1.8'>" +
    "<h1>目前沒有網路</h1><p>若有立即危險請撥 <a href='tel:119'>119</a>／<a href='tel:110'>110</a>；" +
    "想找人聊聊可撥 <a href='tel:1925'>1925 安心專線</a> 或 <a href='tel:1995'>1995 生命線</a>。</p></body>",
    { status: 503, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } }
  );
}

// 頁面：網路優先；失敗時顯示離線安心逃生艙。頁面本身不寫入快取。
async function handleNavigation(request, url) {
  try {
    const response = await fetch(request);
    if (!response.ok && OFFLINE_URLS.includes(url.pathname)) {
      const hit = await (await caches.open(CACHE_NAME)).match("/static/offline.html");
      if (hit) return hit;
    }
    return response;
  } catch (_) {
    if (OFFLINE_URLS.includes(url.pathname)) {
      const cache = await caches.open(CACHE_NAME);
      const hit = await cache.match(url.pathname);
      if (hit) return hit;
    }
    return offlineFallback();
  }
}

// 靜態資源：網路優先（更新後立刻生效，不會卡在舊版程式），只有離線時才用快取；
// 離線時忽略 ?v= 版本參數找最近一次的副本。
async function handleStatic(request) {
  const cache = await caches.open(CACHE_NAME);
  try {
    const response = await fetch(request);
    if (response.ok && response.type === "basic") cache.put(request, response.clone());
    return response;
  } catch (error) {
    const hit = await cache.match(request) || await cache.match(request, { ignoreSearch: true });
    if (hit) return hit;
    throw error;
  }
}

self.addEventListener("fetch", event => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // API（含對話資料）一律直接走網路，不經過任何快取。
  if (url.pathname.startsWith("/api/")) return;

  if (request.mode === "navigate") {
    event.respondWith(handleNavigation(request, url));
    return;
  }
  if (url.pathname.startsWith("/static/") || url.pathname === "/manifest.json") {
    event.respondWith(handleStatic(request));
  }
});
