/* Pages: network first, so a new month of data shows at once. Assets: cache first (they carry ?v=build). */
var V = "wmm-__BUILD__", BASE = "__BASE__";
var PRECACHE = [BASE + "/", BASE + "/thailand/", BASE + "/compare/", BASE + "/assets/app.css?v=__BUILD__", BASE + "/assets/app.js?v=__BUILD__", BASE + "/assets/icon.svg"];

self.addEventListener("install", function (e) {
  e.waitUntil(caches.open(V).then(function (c) { return c.addAll(PRECACHE); }).then(function () { return self.skipWaiting(); }));
});

self.addEventListener("activate", function (e) {
  e.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k !== V; }).map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});

self.addEventListener("fetch", function (e) {
  var req = e.request;
  if (req.method !== "GET" || new URL(req.url).origin !== location.origin) return;
  if (req.mode === "navigate") {
    e.respondWith(fetch(req).then(function (res) {
      var copy = res.clone();
      caches.open(V).then(function (c) { c.put(req, copy); });
      return res;
    }).catch(function () {
      return caches.match(req).then(function (r) { return r || caches.match(BASE + "/"); });
    }));
    return;
  }
  e.respondWith(caches.match(req).then(function (r) {
    return r || fetch(req).then(function (res) {
      var copy = res.clone();
      caches.open(V).then(function (c) { c.put(req, copy); });
      return res;
    });
  }));
});
