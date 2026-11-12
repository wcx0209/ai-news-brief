const CACHE_NAME = "polyemergence-v13";
const APP_SHELL = [
  "/",
  "/en/",
  "/zh/",
  "/locale-redirect.js",
  "/styles.css",
  "/app.js",
  "/share.js",
  "/manifest.webmanifest",
  "/favicon.svg",
  "/assets/app-icon.svg",
  "/assets/app-icon-192.png",
  "/assets/app-icon-512.png",
  "/assets/apple-touch-icon.png"
];

self.addEventListener("install", event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(APP_SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

async function networkFirst(request, fallbackUrl) {
  const cache = await caches.open(CACHE_NAME);
  try {
    const response = await fetch(new Request(request, { cache: "no-cache" }));
    if (response.ok) cache.put(request, response.clone());
    return response;
  } catch {
    return (await cache.match(request, { ignoreSearch: true })) || cache.match(fallbackUrl, { ignoreSearch: true });
  }
}

async function freshDataFirst(request) {
  const cache = await caches.open(CACHE_NAME);
  // Each JSON resource needs its own offline entry. Taxonomy/observations must
  // never overwrite the latest-news cache, and refresh query strings should
  // still resolve to the same last successful document when offline.
  const dataCacheKey = new URL(request.url).pathname;
  try {
    // Bypass both the browser HTTP cache and the CDN's stale response path.
    const response = await fetch(new Request(request, { cache: "no-store" }));
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    await cache.put(dataCacheKey, response.clone());
    return response;
  } catch {
    // The last successful payload remains available when the app is offline.
    return (await cache.match(dataCacheKey)) || Response.error();
  }
}

self.addEventListener("fetch", event => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    const fallback = url.pathname.startsWith("/zh") ? "/zh/" : "/en/";
    event.respondWith(networkFirst(request, fallback));
    return;
  }

  if (url.pathname.startsWith("/data/")) {
    event.respondWith(freshDataFirst(request));
    return;
  }

  if (url.pathname.startsWith("/api/")) {
    event.respondWith(fetch(new Request(request, { cache: "no-store" })));
    return;
  }

  if (["/app.js", "/share.js", "/styles.css", "/manifest.webmanifest"].includes(url.pathname)) {
    event.respondWith(networkFirst(request, url.pathname));
    return;
  }

  event.respondWith(
    caches.match(request, { ignoreSearch: true }).then(cached => cached || fetch(request).then(response => {
      if (response.ok) caches.open(CACHE_NAME).then(cache => cache.put(request, response.clone()));
      return response;
    }))
  );
});
