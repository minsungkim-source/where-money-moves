/* Where Money Moves TH — 페이지는 JS 없이도 읽힌다. 여기는 지도 탭·검색·정렬·설치만. */
(function () {
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var lang = document.documentElement.lang || "th";

  // ── 지도: 지표 전환 + 탭하면 카드, 같은 주를 다시 탭하면 이동
  var wrap = $(".mapwrap");
  if (wrap) {
    $$(".seg button").forEach(function (b) {
      b.addEventListener("click", function () {
        $$(".seg button").forEach(function (x) { x.setAttribute("aria-checked", String(x === b)); });
        wrap.dataset.metric = b.dataset.m;
        $$(".legend").forEach(function (l) { l.hidden = l.dataset.for.split(" ").indexOf(b.dataset.m) < 0; });
      });
    });
    var pick = $("#pick"), tpl = $("#pick-tpl");
    var show = function (a) {
      var card = tpl.content.firstElementChild.cloneNode(true);
      card.setAttribute("href", a.getAttribute("href"));
      $(".nm", card).textContent = a.dataset.name;
      $(".sc", card).textContent = a.dataset.score ? a.dataset.score + "/100 · #" + a.dataset.rank : "–";
      $(".dep", card).textContent = a.dataset.dep;
      $(".cr", card).textContent = a.dataset.cr;
      pick.replaceChildren(card);
      pick.dataset.cur = a.dataset.id;
      $$(".map a.cur").forEach(function (x) { x.classList.remove("cur"); });
      a.classList.add("cur");
    };
    wrap.addEventListener("click", function (e) {
      var a = e.target.closest("a[data-id]");
      if (!a || pick.dataset.cur === a.dataset.id) return;
      e.preventDefault();
      show(a);
    });
    wrap.addEventListener("mouseover", function (e) {
      var a = e.target.closest("a[data-id]");
      if (a && matchMedia("(hover: hover)").matches) show(a);
    });
    wrap.addEventListener("focusin", function (e) {
      var a = e.target.closest("a[data-id]");
      if (a) show(a);
    });
  }

  // ── 검색: 처음 포커스할 때 색인을 받는다
  var q = $("#q"), qr = $("#qr"), idx = null, sel = -1;
  var norm = function (s) { return (s || "").toLowerCase().replace(/[\s\-]/g, ""); };
  var load = function () {
    if (idx) return Promise.resolve(idx);
    return fetch("/assets/search-" + lang + ".json").then(function (r) { return r.json(); })
      .then(function (j) { idx = j.map(function (x) { x._k = norm(x.n + x.a); return x; }); return idx; });
  };
  var render = function () {
    var v = norm(q.value);
    if (!v) { qr.hidden = true; return; }
    // 이름 앞부분이 맞는 것 → 주 → 나머지 순
    var rank = function (x) {
      var pre = norm(x.n).indexOf(v) === 0 || norm(x.a).indexOf(v) === 0;
      return (pre ? 0 : 2) + (x.k === "p" ? 0 : 1);
    };
    var hits = idx.filter(function (x) { return x._k.indexOf(v) >= 0; })
      .sort(function (a, b) { return rank(a) - rank(b); }).slice(0, 8);
    sel = -1;
    qr.replaceChildren.apply(qr, hits.length ? hits.map(function (x) {
      var li = document.createElement("li"), a = document.createElement("a"), s = document.createElement("small");
      a.href = x.u; a.textContent = x.n; s.textContent = x.a; a.appendChild(s); li.appendChild(a); return li;
    }) : [Object.assign(document.createElement("li"), { textContent: q.dataset.none, className: "note" })]);
    qr.hidden = false;
  };
  if (q) {
    q.addEventListener("focus", load);
    q.addEventListener("input", function () { load().then(render); });
    q.addEventListener("keydown", function (e) {
      var links = $$("a", qr);
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        sel = Math.max(0, Math.min(links.length - 1, sel + (e.key === "ArrowDown" ? 1 : -1)));
        links.forEach(function (l, i) { l.setAttribute("aria-selected", String(i === sel)); });
      } else if (e.key === "Enter" && links.length) {
        location.href = links[Math.max(sel, 0)].getAttribute("href");
      } else if (e.key === "Escape") { qr.hidden = true; }
    });
    document.addEventListener("click", function (e) { if (!e.target.closest(".search")) qr.hidden = true; });
  }

  // ── 표 정렬
  $$("table[data-sortable]").forEach(function (t) {
    $$("thead button", t).forEach(function (b) {
      b.addEventListener("click", function () {
        var k = +b.dataset.k, desc = b.dataset.dir !== "desc";      // 첫 클릭은 큰 값부터
        $$("thead button", t).forEach(function (x) { delete x.dataset.dir; });
        b.dataset.dir = desc ? "desc" : "asc";
        var body = t.tBodies[0];
        var rows = $$("tr", body);
        rows.sort(function (r1, r2) {
          var a = r1.children[k].dataset.v, c = r2.children[k].dataset.v;
          if (a === "" && c === "") return 0;
          if (a === "") return 1;
          if (c === "") return -1;
          return desc ? parseFloat(c) - parseFloat(a) : parseFloat(a) - parseFloat(c);
        });
        rows.forEach(function (r) { body.appendChild(r); });
      });
    });
  });

  // ── PWA
  if ("serviceWorker" in navigator && location.protocol === "https:") {
    navigator.serviceWorker.register("/sw.js").catch(function () {});
  }
  var deferred = null, btn = $("#install");
  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault(); deferred = e; if (btn) btn.hidden = false;
  });
  if (btn) btn.addEventListener("click", function () {
    if (!deferred) return;
    deferred.prompt(); deferred = null; btn.hidden = true;
  });
})();
