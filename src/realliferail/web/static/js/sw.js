// Service worker: keeps the app shell so it opens instantly from the home screen. Train data is never cached here,
// because a stale time shown as current would be worse than an offline message.
"use strict";

const SHELL = "rlr-shell-v2";
const ASSETS = [
  "/offline",
  "/static/css/app.css?v=1",
  "/static/css/themes/platform.css",
  "/static/css/base/elements.css",
  "/static/css/composition/layout.css",
  "/static/css/block/chrome.css",
  "/static/css/block/forms.css",
  "/static/css/block/board.css",
  "/static/css/block/route.css",
  "/static/css/utility/text.css",
  "/static/js/app.js?v=1",
  "/static/js/live.js?v=1",
  "/static/fonts/barlow-latin-400-normal.woff2",
  "/static/fonts/barlow-latin-500-normal.woff2",
  "/static/fonts/barlow-semi-condensed-latin-700-normal.woff2",
  "/static/icons/icon-192.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== SHELL).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.startsWith("/static/")) {
    e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request)));
    return;
  }
  if (e.request.mode === "navigate") {
    e.respondWith(fetch(e.request).catch(() => caches.match("/offline")));
  }
});
