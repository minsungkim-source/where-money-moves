/* 페이지는 네트워크 우선(새 달 데이터가 바로 보이게), 정적 자산은 캐시 우선. */
var V = "wmm-__BUILD__";
var PRECACHE = ["/th/", "/en/", "/assets/app.css?v=__BUILD__", "/assets/app.js?v=__BUILD__", "/assets/icon.svg"];

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
      return caches.match(req).then(function (r) { return r || caches.match("/th/"); });
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
