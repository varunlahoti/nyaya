// Minimal offline-capable service worker for the Nyaya PWA.
// Caches the app shell; API calls always go to the network.
const CACHE = "nyaya-v1";
const SHELL = ["/", "/manifest.json", "/icon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Never cache API responses (case facts + fresh results).
  if (url.pathname.startsWith("/api/")) return;

  // App shell: cache-first, fall back to network.
  if (request.method === "GET") {
    event.respondWith(
      caches.match(request).then((cached) => cached || fetch(request))
    );
  }
});
