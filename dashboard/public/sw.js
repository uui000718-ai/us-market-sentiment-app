const CACHE = "market-pulse-v5";
const APP_SHELL = ["./", "./manifest.webmanifest", "./favicon.svg"].map(path => new URL(path, self.location.href).href);

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(APP_SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key.startsWith("market-pulse") && key !== CACHE).map((key) => caches.delete(key)))));
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/report") || url.pathname.includes("/data/")) {
    // Let the page explicitly mark localStorage fallbacks as cached.
    // An API cache would incorrectly preserve delivery_mode: live offline.
    event.respondWith(fetch(event.request));
    return;
  }
  event.respondWith(fetch(event.request).catch(() => caches.match(event.request)));
});
