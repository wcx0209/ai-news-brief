const CACHE_NAME = "polyemergence-v3";
const DATA_CACHE_KEY = "/data/latest.json";
const APP_SHELL = [
  "/",
  "/en/",
  "/zh/",
  "/locale-redirect.js",
  "/styles.css",
  "/app.js",
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
    const response = await fetch(request);
    if (response.ok) cache.put(request, response.clone());
    return response;
  } catch {
    return (await cache.match(request, { ignoreSearch: true })) || cache.match(fallbackUrl, { ignoreSearch: true });
  }
}

async function freshDataFirst(request) {
  const cache = await caches.open(CACHE_NAME);
  try {
    // Bypass both the browser HTTP cache and the CDN's stale response path.
    const response = await fetch(new Request(request, { cache: "no-store" }));
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    await cache.put(DATA_CACHE_KEY, response.clone());
    return response;
  } catch {
    // The last successful payload remains available when the app is offline.
    return (await cache.match(DATA_CACHE_KEY)) || Response.error();
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

  if (["/app.js", "/styles.css", "/manifest.webmanifest"].includes(url.pathname)) {
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
