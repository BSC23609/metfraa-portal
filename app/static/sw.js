/* Metfraa Portal service worker — deliberately conservative.
   Network-first for everything (this app changes often and we've fought
   stale caches before); cache fallback only for static assets + an
   offline notice for pages. Bump VERSION to force-refresh all clients. */
const VERSION = "portal-v1";
const STATIC_CACHE = `static-${VERSION}`;

self.addEventListener("install", (e) => self.skipWaiting());
self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== STATIC_CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;

  if (url.pathname.startsWith("/static/")) {
    // static: network-first, fall back to cache when offline
    e.respondWith(
      fetch(e.request)
        .then((r) => {
          const copy = r.clone();
          caches.open(STATIC_CACHE).then((c) => c.put(e.request, copy));
          return r;
        })
        .catch(() => caches.match(e.request))
    );
    return;
  }

  if (e.request.mode === "navigate") {
    e.respondWith(
      fetch(e.request).catch(() =>
        new Response(
          "<!doctype html><meta name=viewport content='width=device-width'>" +
          "<body style='font-family:sans-serif;padding:40px;text-align:center;color:#334'>" +
          "<h2>You're offline</h2><p>Metfraa Portal needs an internet connection.<br>Reconnect and pull to refresh.</p></body>",
          { headers: { "Content-Type": "text/html" } }
        )
      )
    );
  }
});
