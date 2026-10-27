/* Where Money Moves — progressive enhancement only. Every page is complete without this file. */
(function () {
  "use strict";
  var doc = document, root = doc.documentElement, BASE = root.dataset.base || "";
  var $ = function (s, r) { return (r || doc).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || doc).querySelectorAll(s)); };
  var reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  var store = {
    get: function (k, d) { try { var v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set: function (k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }
  };
  root.classList.add("js");

  // ── toasts
  var toasts = $(".toasts");
  function toast(msg, action, ms) {
    if (!toasts) return;
    var t = doc.createElement("div");
    t.className = "toast";
    var span = doc.createElement("span");
    span.textContent = msg;
    t.appendChild(span);
    if (action) {
      var b = doc.createElement("button");
      b.type = "button";
      b.textContent = action.label;
      b.addEventListener("click", function () { action.run(); close(); });
      t.appendChild(b);
    }
    toasts.appendChild(t);
    while (toasts.children.length > 3) toasts.firstElementChild.remove();
    var timer = setTimeout(close, ms || 4200);
    t.addEventListener("pointerenter", function () { clearTimeout(timer); });
    t.addEventListener("pointerleave", function () { timer = setTimeout(close, 1800); });
    function close() { clearTimeout(timer); t.classList.add("out"); setTimeout(function () { t.remove(); }, 230); }
  }
  window.wmmToast = toast;

  // ── theme: system → dark → light → system
  var themeBtn = $("[data-theme-toggle]");
  if (themeBtn) themeBtn.addEventListener("click", function () {
    var cur = root.dataset.theme || "system";
    var next = { system: "dark", dark: "light", light: "system" }[cur];
    if (next === "system") { delete root.dataset.theme; try { localStorage.removeItem("wmm-theme"); } catch (e) {} }
    else { root.dataset.theme = next; try { localStorage.setItem("wmm-theme", next); } catch (e) {} }
    toast(next === "system" ? "Theme follows your device" : (next === "dark" ? "Dark theme" : "Light theme"));
  });

  // ── header border + reading progress
  var top = $(".top"), bar = $(".progress"), ticking = false;
  function onScroll() {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(function () {
      var y = scrollY, h = doc.documentElement.scrollHeight - innerHeight;
      if (top) top.classList.toggle("scrolled", y > 8);
      if (bar) bar.style.setProperty("--p", h > 0 ? Math.min(1, y / h) : 0);
      ticking = false;
    });
  }
  addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  // ── nav: mark the current section
  $$(".nav a").forEach(function (a) {
    var href = a.getAttribute("href");
    if (href !== BASE + "/" && location.pathname.indexOf(href) === 0) a.setAttribute("aria-current", "page");
  });

  // ── count-up: animates the number already printed in the HTML
  function countUp(el) {
    var text = el.dataset.count || el.textContent;
    var m = text.match(/^([^\d−+-]*)([−+-]?)([\d,]*\.?\d+)(.*)$/);
    if (!m || reduced) return;
    var pre = m[1], sign = m[2], numStr = m[3], post = m[4];
    var target = parseFloat(numStr.replace(/,/g, ""));
    var dec = (numStr.split(".")[1] || "").length, comma = numStr.indexOf(",") >= 0;
    var t0 = null, dur = 900;
    function fmt(v) {
      var s = v.toFixed(dec);
      if (comma) s = Number(s).toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec });
      return pre + sign + s + post;
    }
    function step(ts) {
      if (t0 === null) t0 = ts;
      var k = Math.min(1, (ts - t0) / dur), e = 1 - Math.pow(1 - k, 3);
      el.textContent = fmt(target * e);
      if (k < 1) requestAnimationFrame(step); else el.textContent = text;
    }
    requestAnimationFrame(step);
  }

  // ── reveal (one entrance per section) + count-up + chart line draw.
  // Web Animations with no fill: if an animation never runs, the element simply stays as authored.
  var EASE = "cubic-bezier(.2,.7,.2,1)";
  var revealEls = $$(".reveal, .kpi");
  if ("IntersectionObserver" in window && !reduced && Element.prototype.animate) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        var el = en.target;
        io.unobserve(el);
        if (en.boundingClientRect.top < innerHeight * 0.9 && performance.now() < 600) return;   // already on screen at load
        el.animate([{ opacity: 0, transform: "translateY(14px)" }, { opacity: 1, transform: "none" }], { duration: 650, easing: EASE });
        $$("[data-count]", el).forEach(countUp);
        if (el.matches("[data-count]")) countUp(el);
        $$(".chart .ln", el).forEach(function (p) {
          p.animate([{ strokeDashoffset: 1 }, { strokeDashoffset: 0 }], { duration: 1300, easing: EASE });
        });
      });
    }, { rootMargin: "0px 0px -6% 0px", threshold: 0.06 });
    revealEls.forEach(function (el) { io.observe(el); });
  }

  // ── the SEA map's one orchestrated moment: countries arrive in momentum order
  $$(".atlas .map.sea").forEach(function (m) {
    if (reduced || !Element.prototype.animate) return;
    var as = $$(".units > a", m);
    as.sort(function (a, b) { return (JSON.parse(b.dataset.tip).s || 0) - (JSON.parse(a.dataset.tip).s || 0); });
    as.forEach(function (a, i) {
      a.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 600, delay: 120 + i * 70, easing: EASE, fill: "backwards" });
    });
  });

  // ── lenses: map colour, ranked list order (FLIP), sub-headings
  var LENS_NAME = { score: "Momentum", people: "People", jobs: "Jobs", biz: "Businesses", money: "Money" };
  function placeInk(tabs) {
    var sel = $('[aria-selected="true"]', tabs), ink = $(".lens-ink", tabs);
    if (!sel || !ink) return;
    ink.style.width = sel.offsetWidth + "px";
    ink.style.transform = "translateX(" + sel.offsetLeft + "px)";
  }
  // dataset keys: data-r-people → dataset.rPeople
  function key(prefix, lens) { return prefix + lens.charAt(0).toUpperCase() + lens.slice(1); }
  function flip(list, lens) {
    var items = $$("li", list);
    var first = new Map(items.map(function (li) { return [li, li.getBoundingClientRect().top]; }));
    items.sort(function (a, b) { return (+a.dataset[key("r", lens)] || 999) - (+b.dataset[key("r", lens)] || 999); });
    items.forEach(function (li, i) {
      list.appendChild(li);
      var v = li.dataset[key("v", lens)], r = +li.dataset[key("r", lens)] || 999;
      $(".val", li).textContent = v;
      $(".pos", li).textContent = r > 900 ? "–" : (i + 1);
      $(".bar", li).style.setProperty("--w", r > 900 ? "0%" : Math.round(100 * (items.length - r + 1) / items.length) + "%");
    });
    if (reduced) return;
    items.forEach(function (li) {
      var dy = first.get(li) - li.getBoundingClientRect().top;
      if (dy) li.animate([{ transform: "translateY(" + dy + "px)" }, { transform: "none" }], { duration: 420, easing: "cubic-bezier(.2,.7,.2,1)" });
    });
  }

  $$(".lenses").forEach(function (tabs) {
    var scope = tabs.closest(".atlas, .split, section") || doc;
    var map = $(".map", scope);
    tabs.classList.add("ready");
    placeInk(tabs);
    addEventListener("resize", function () { placeInk(tabs); });
    // the web font can land after fonts.ready resolves; re-measure whenever a tab changes size
    if ("ResizeObserver" in window) {
      var ro = new ResizeObserver(function () { placeInk(tabs); });
      $$("button", tabs).forEach(function (b) { ro.observe(b); });
    }
    function set(lens, quiet) {
      $$("button", tabs).forEach(function (b) { b.setAttribute("aria-selected", String(b.dataset.lens === lens)); });
      placeInk(tabs);
      if (map) map.dataset.lens = lens;
      var list = $(".sea-list", scope);
      if (list) flip(list, lens);
      $$(".tlist", scope).forEach(function (t) { t.hidden = t.dataset.for !== lens; });
      $$("[data-sub-score],[data-sub-people],[data-sub-jobs],[data-sub-biz],[data-sub-money]", scope).forEach(function (p) {
        p.hidden = !p.hasAttribute("data-sub-" + lens);
      });
      if (!quiet) history.replaceState(null, "", "#" + (scope.id || "map") + "=" + lens);
    }
    $$("button", tabs).forEach(function (b) {
      b.addEventListener("click", function () { set(b.dataset.lens); });
    });
    tabs.addEventListener("keydown", function (e) {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      var bs = $$("button", tabs), i = bs.findIndex(function (b) { return b.getAttribute("aria-selected") === "true"; });
      var n = bs[(i + (e.key === "ArrowRight" ? 1 : bs.length - 1)) % bs.length];
      n.focus(); set(n.dataset.lens);
    });
    var h = location.hash.match(/^#([\w-]+)=(\w+)$/);
    if (h && h[1] === (scope.id || "map") && LENS_NAME[h[2]]) set(h[2], true);
  });

  // ── map tooltip (pointer) and tap sheet (touch)
  var tip = $(".tip"), canHover = matchMedia("(hover: hover)").matches;
  function tipHTML(d, lens) {
    var rows = [["Momentum", d.s == null ? "–" : d.s, "score"], ["People", d.people, "people"], ["Jobs", d.jobs, "jobs"],
                ["Businesses", d.biz, "biz"], ["Money", d.money, "money"]];
    var el = doc.createElement("div");
    var b = doc.createElement("b"); b.textContent = d.n; el.appendChild(b);
    if (d.a) { var s = doc.createElement("span"); s.className = "native"; s.textContent = d.a; el.appendChild(s); }
    var dl = doc.createElement("dl");
    rows.forEach(function (r) {
      var dt = doc.createElement("dt"), dd = doc.createElement("dd");
      dt.textContent = r[0]; dd.textContent = r[1] == null ? "–" : r[1];
      if (r[2] === lens) { dt.className = dd.className = "on"; }
      dl.appendChild(dt); dl.appendChild(dd);
    });
    el.appendChild(dl);
    return el;
  }
  $$(".map .units").forEach(function (units) {
    var map = units.closest(".map");
    var frame = map.closest(".mapframe");
    var sheet = null;
    if (!canHover && frame) {
      sheet = doc.createElement("a");
      sheet.className = "sheet"; sheet.hidden = true;
      frame.insertAdjacentElement("afterend", sheet);
    }
    units.addEventListener("pointermove", function (e) {
      if (!canHover || !tip) return;
      var a = e.target.closest("a[data-tip]");
      if (!a) { tip.hidden = true; return; }
      tip.replaceChildren(tipHTML(JSON.parse(a.dataset.tip), map.dataset.lens));
      tip.hidden = false;
      var x = Math.min(innerWidth - 110, Math.max(110, e.clientX));
      tip.style.left = x + "px"; tip.style.top = e.clientY + "px";
    });
    units.addEventListener("pointerleave", function () { if (tip) tip.hidden = true; });
    units.addEventListener("click", function (e) {
      var a = e.target.closest("a[data-tip]");
      if (!a || canHover || !sheet) return;
      if (sheet.dataset.cur === a.getAttribute("href")) return;      // second tap opens the page
      e.preventDefault();
      var d = JSON.parse(a.dataset.tip);
      sheet.replaceChildren(tipHTML(d, map.dataset.lens));
      var go = doc.createElement("span"); go.className = "go"; go.textContent = "Open " + d.n; sheet.appendChild(go);
      sheet.href = a.getAttribute("href"); sheet.dataset.cur = a.getAttribute("href");
      sheet.hidden = false;
      $$("a.cur", units).forEach(function (x) { x.classList.remove("cur"); });
      a.classList.add("cur");
    });
  });

  // ── command palette
  var dlg = $("#cmdk"), idx = null, sel = 0;
  function norm(s) { return (s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[\s\-.,']/g, ""); }
  function loadIdx() {
    if (idx) return Promise.resolve(idx);
    return fetch(BASE + "/assets/search.json").then(function (r) { return r.json(); }).then(function (j) {
      idx = j.map(function (x) { x._n = norm(x.n); x._a = norm(x.a); return x; });
      return idx;
    });
  }
  function renderCmdk() {
    var q = norm($("input", dlg).value), ul = $("ul", dlg);
    var hits = (q ? idx.filter(function (x) { return x._n.indexOf(q) >= 0 || x._a.indexOf(q) >= 0; }) : idx.filter(function (x) { return x.k === "Country"; }))
      .map(function (x) {
        var pre = x._n.indexOf(q) === 0 ? 0 : 2, kind = { Country: 0, Province: 1, Ranking: 2, District: 3 }[x.k];
        return [pre * 10 + kind, x];
      }).sort(function (a, b) { return a[0] - b[0]; }).slice(0, 9).map(function (p) { return p[1]; });
    sel = 0;
    if (!hits.length) {
      var li = doc.createElement("li"); li.className = "empty"; li.textContent = "No place matches. Try an English or Thai name.";
      ul.replaceChildren(li); return;
    }
    ul.replaceChildren.apply(ul, hits.map(function (x, i) {
      var li = doc.createElement("li"), a = doc.createElement("a"), b = doc.createElement("span"), s = doc.createElement("small"), k = doc.createElement("span");
      a.href = x.u; a.setAttribute("role", "option"); a.setAttribute("aria-selected", String(i === 0));
      b.textContent = x.n; s.textContent = x.a; k.className = "kind"; k.textContent = x.k;
      a.appendChild(b); a.appendChild(k); a.appendChild(s); li.appendChild(a); return li;
    }));
  }
  function openCmdk() {
    if (!dlg || dlg.open) return;
    dlg.showModal();
    var inp = $("input", dlg); inp.value = ""; inp.focus();
    loadIdx().then(renderCmdk).catch(function () { toast("Search is unavailable offline"); });
  }
  if (dlg) {
    $$("[data-cmdk]").forEach(function (b) { b.addEventListener("click", openCmdk); });
    $("input", dlg).addEventListener("input", function () { if (idx) renderCmdk(); });
    $("input", dlg).addEventListener("keydown", function (e) {
      var links = $$("a", dlg);
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        sel = Math.max(0, Math.min(links.length - 1, sel + (e.key === "ArrowDown" ? 1 : -1)));
        links.forEach(function (l, i) { l.setAttribute("aria-selected", String(i === sel)); if (i === sel) l.scrollIntoView({ block: "nearest" }); });
      } else if (e.key === "Enter" && links[sel]) { e.preventDefault(); location.href = links[sel].href; }
    });
    dlg.addEventListener("click", function (e) { if (e.target === dlg) dlg.close(); });
    doc.addEventListener("keydown", function (e) {
      var typing = /INPUT|TEXTAREA|SELECT/.test((doc.activeElement || {}).tagName || "");
      if ((e.key === "/" && !typing) || (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey))) { e.preventDefault(); openCmdk(); }
    });
  }

  // ── watchlist → compare
  function watch() { return store.get("wmm-watch", []); }
  function setWatch(list) { store.set("wmm-watch", list); badge(); }
  function badge() {
    var n = watch().length;
    $$(".cmp .count").forEach(function (c) { c.hidden = !n; c.textContent = n; });
  }
  badge();
  $$("[data-watch]").forEach(function (b) {
    var item = JSON.parse(b.dataset.watch);
    function sync() {
      var on = watch().some(function (w) { return w.id === item.id; });
      b.setAttribute("aria-pressed", String(on));
      $("span", b).textContent = on ? "Watching" : "Watch";
    }
    sync();
    b.addEventListener("click", function () {
      var list = watch(), on = list.some(function (w) { return w.id === item.id; });
      if (on) {
        setWatch(list.filter(function (w) { return w.id !== item.id; }));
        sync();
        toast("Removed " + item.name + " from Compare", { label: "Undo", run: function () { setWatch(watch().concat([item])); sync(); } });
      } else {
        if (list.length >= 6) { toast("Compare holds six places. Remove one first.", { label: "Open Compare", run: function () { location.href = BASE + "/compare/"; } }); return; }
        setWatch(list.concat([item]));
        sync();
        toast("Added " + item.name + " to Compare", { label: "Open Compare", run: function () { location.href = BASE + "/compare/"; } });
      }
    });
  });

  // ── share
  $$("[data-share]").forEach(function (b) {
    b.addEventListener("click", function () {
      var data = { title: doc.title, url: location.href.split("#")[0] };
      if (navigator.share && !canHover) { navigator.share(data).catch(function () {}); return; }
      (navigator.clipboard ? navigator.clipboard.writeText(data.url) : Promise.reject())
        .then(function () { toast("Link copied"); })
        .catch(function () { toast("Copy this link from the address bar"); });
    });
  });

  // ── compare page
  var cmpEl = $("#compare");
  if (cmpEl) {
    var lenses = JSON.parse(cmpEl.dataset.lenses);
    var fromUrl = new URLSearchParams(location.search).get("ids");
    fetch(BASE + "/assets/compare.json").then(function (r) { return r.json(); }).then(function (all) {
      function ids() { return fromUrl ? fromUrl.split(",") : watch().map(function (w) { return w.id; }); }
      function render() {
        var list = ids().filter(function (id) { return all[id]; });
        if (!list.length) return;
        var wrap = doc.createElement("div"); wrap.className = "cmp-grid";
        var head = doc.createElement("div"); head.className = "cmp-head";
        list.forEach(function (id) {
          var c = doc.createElement("span"), a = doc.createElement("a"), x = doc.createElement("button");
          c.className = "chip"; a.href = all[id].u; a.textContent = all[id].n;
          x.type = "button"; x.setAttribute("aria-label", "Remove " + all[id].n); x.textContent = "×";
          x.addEventListener("click", function () {
            if (fromUrl) { fromUrl = list.filter(function (i) { return i !== id; }).join(",") || null; }
            else setWatch(watch().filter(function (w) { return w.id !== id; }));
            toast("Removed " + all[id].n);
            cmpEl.replaceChildren(); if (!ids().length) location.reload(); else render();
          });
          c.appendChild(a); c.appendChild(x); head.appendChild(c);
        });
        var copy = doc.createElement("button"); copy.className = "btn ghost"; copy.type = "button"; copy.textContent = "Copy link to this comparison";
        copy.addEventListener("click", function () {
          var url = location.origin + BASE + "/compare/?ids=" + list.join(",");
          (navigator.clipboard ? navigator.clipboard.writeText(url) : Promise.reject()).then(function () { toast("Link copied"); }).catch(function () { toast(url); });
        });
        head.appendChild(copy);
        wrap.appendChild(head);
        var rows = [["score", "Momentum score"]].concat(lenses);
        rows.forEach(function (lr) {
          var k = lr[0], vals = list.map(function (id) { return all[id][k === "score" ? "s" : k]; });
          if (vals.every(function (v) { return v == null; })) return;
          var max = Math.max.apply(null, vals.map(function (v) { return Math.abs(v || 0); })) || 1;
          var row = doc.createElement("section"); row.className = "cmp-row" + (k === "score" ? " score" : "");
          var h = doc.createElement("h3"); h.textContent = lr[1]; row.appendChild(h);
          list.forEach(function (id, i) {
            var v = vals[i], it = all[id];
            var line = doc.createElement("div"); line.className = "cmp-bar";
            var nm = doc.createElement("span"); nm.textContent = it.n;
            var sm = doc.createElement("small"); sm.textContent = k === "score" ? " " + it.k : (it[k + "y"] ? " " + it[k + "y"] : ""); nm.appendChild(sm);
            var tr = doc.createElement("span"); tr.className = "track";
            var f = doc.createElement("span"); f.className = "fill" + (v < 0 ? " neg" : "");
            var num = doc.createElement("span"); num.className = "num";
            if (v == null) { num.textContent = "–"; }
            else if (k === "score") { f.style.left = "0"; f.style.width = v + "%"; num.textContent = Math.round(v); }
            else {
              var w = Math.abs(v) / max * 50;
              f.style.left = (v < 0 ? 50 - w : 50) + "%"; f.style.width = w + "%";
              num.textContent = (v >= 0 ? "+" : "−") + Math.abs(v * 100).toFixed(1) + "%";
            }
            tr.appendChild(f); line.appendChild(nm); line.appendChild(tr); line.appendChild(num); row.appendChild(line);
          });
          wrap.appendChild(row);
        });
        cmpEl.replaceChildren(wrap);
      }
      render();
    }).catch(function () { toast("Compare needs a connection the first time"); });
  }

  // ── sortable tables
  $$("table[data-sortable]").forEach(function (t) {
    $$("thead button", t).forEach(function (b) {
      b.addEventListener("click", function () {
        var k = +b.dataset.k, desc = b.dataset.dir !== "desc";
        $$("thead button", t).forEach(function (x) { delete x.dataset.dir; });
        b.dataset.dir = desc ? "desc" : "asc";
        var body = t.tBodies[0], rows = $$("tr", body);
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

  // ── PWA: service worker, install, offline, new data
  if ("serviceWorker" in navigator && location.protocol === "https:") {
    navigator.serviceWorker.register(BASE + "/sw.js", { scope: BASE + "/" }).catch(function () {});
  }
  addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();
    if (store.get("wmm-install-dismissed", false)) return;
    setTimeout(function () {
      toast("Install Where Money Moves on this device", { label: "Install", run: function () { e.prompt(); } }, 8000);
      store.set("wmm-install-dismissed", true);
    }, 20000);
  });
  addEventListener("appinstalled", function () { toast("Installed"); });
  addEventListener("offline", function () { toast("You're offline. Pages you've opened still work."); });
  addEventListener("online", function () { toast("Back online"); });
  var build = root.dataset.build, seen = store.get("wmm-build", null);
  if (seen && seen !== build) setTimeout(function () { toast("Updated with the latest data"); }, 1200);
  store.set("wmm-build", build);
})();
