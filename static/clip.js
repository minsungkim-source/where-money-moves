/* Where Money Moves — "This month in fifteen seconds", a 9:16 clip drawn in code for sharing.

   The same grammar as the film (static/film.js): the chart is the clip, every mark is a real number baked in by
   build.py, and render(t) is a pure function of time, so tools/clip_mp4.mjs can step it frame by frame.
     · one count-down: the five fastest provinces land from 5th to 1st, each lighting up on the map as its bar grows
     · then the yardstick (Thailand as a whole) and the one shrinking or slowest, in ebb-red only if it declined
   Text stays out of the top 180 px and the bottom 360 px, where story apps put their own buttons. */
(function () {
  "use strict";
  var root = document.getElementById("clip");
  if (!root) return;
  var F = JSON.parse(document.getElementById("clip-data").textContent);
  var canvas = root.querySelector("canvas"), ctx = canvas.getContext("2d");
  var playBtn = root.querySelector(".clip-play"), bar = root.querySelector(".film-bar i");
  var W = 1080, H = 1920, DUR = F.duration;
  var DISPLAY = "'Bricolage Grotesque', 'Atkinson Hyperlegible Next', sans-serif", BODY = "'Atkinson Hyperlegible Next', sans-serif";

  var C = {};
  function readColors() {
    var cs = getComputedStyle(document.documentElement);
    ["paper", "ink", "muted", "line", "current", "ebb"].forEach(function (k) { C[k] = cs.getPropertyValue("--" + k).trim(); });
  }
  readColors();
  new MutationObserver(function () { readColors(); draw(); }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  var clamp = function (x, a, b) { return Math.max(a, Math.min(b, x)); };
  var out3 = function (x) { x = clamp(x, 0, 1); return 1 - Math.pow(1 - x, 3); };
  var span = function (t, a, b) { return clamp((t - a) / (b - a), 0, 1); };
  var lerp = function (a, b, k) { return a + (b - a) * k; };

  // ── the cue sheet (seconds)
  var T = { title: 0.2, map: 1.0, first: 2.6, step: 1.35, nat: 9.6, low: 11.0, out: 12.9, end: 13.4 };
  function landOf(r) { return T.first + (5 - r) * T.step; }              // r = 1…5: the 5th lands first

  // ── layout: title left, the country right, the ranking under both
  var vb = F.thai.viewBox, paths = F.thai.provinces.map(function (d) { return new Path2D(d); });
  var MS = Math.min(500 / vb[1], 300 / vb[0]), MX = 1000 - vb[0] * MS, MY = 190;
  var RX = 80, RW = 920, RY = 790, RH = 122;
  var top = F.top, max = Math.max.apply(null, top.map(function (c) { return c.v; }).concat([(F.nat && F.nat.v) || 0]));
  var lit = {};                                                           // province index → rank among the five
  top.forEach(function (c, i) { lit[c.i] = i + 1; });

  function paper() {
    ctx.fillStyle = C.paper; ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = C.line;
    for (var x = 60; x < W; x += 60) for (var y = 60; y < H; y += 60) ctx.fillRect(x, y, 2, 2);
  }

  function heading(t, a) {
    ctx.globalAlpha = a;
    ctx.textBaseline = "alphabetic"; ctx.textAlign = "left";
    ctx.fillStyle = C.ink; ctx.font = "700 32px " + DISPLAY;
    ctx.fillText("Where Money Moves", RX, 150);
    ctx.font = "700 78px " + DISPLAY;
    F.title.forEach(function (line, i) {                                  // each line wipes in from the left
      var k = out3(span(t, T.title + i * 0.22, T.title + i * 0.22 + 0.7));
      if (k <= 0) return;
      ctx.save();
      ctx.beginPath(); ctx.rect(RX - 10, 230 + i * 90, 640 * k + 10, 110); ctx.clip();
      ctx.fillText(line, RX, 310 + i * 90);
      ctx.restore();
    });
    var ks = out3(span(t, T.title + 0.9, T.title + 1.5));
    ctx.globalAlpha = a * ks; ctx.fillStyle = C.muted; ctx.font = "500 36px " + BODY;
    F.sub.forEach(function (line, i) { ctx.fillText(line, RX, 600 + i * 48); });
    ctx.globalAlpha = 1;
  }

  function country(t, a) {
    ctx.save();
    ctx.setTransform(canvas.width / W * MS, 0, 0, canvas.height / H * MS, canvas.width / W * MX, canvas.height / H * MY);
    paths.forEach(function (p, i) {
      var k = out3(span(t, T.map + (i / paths.length) * 0.9, T.map + (i / paths.length) * 0.9 + 0.5));
      if (k <= 0) return;
      var r = lit[i], on = r && t >= landOf(r), low = i === F.low.i && t >= T.low;
      ctx.globalAlpha = a * k;
      if (on) ctx.fillStyle = C.current;
      else if (low) ctx.fillStyle = F.low.v < 0 ? C.ebb : C.muted;
      else { ctx.fillStyle = C.ink; ctx.globalAlpha = a * k * 0.16; }
      ctx.fill(p);
      ctx.globalAlpha = a * k; ctx.lineWidth = 0.7; ctx.strokeStyle = C.paper; ctx.stroke(p);
    });
    // the province that just landed gets a ring for as long as it is the newest
    top.forEach(function (c, i) {
      var r = i + 1, l = landOf(r), k = span(t, l, l + 0.3) * (1 - span(t, l + T.step - 0.2, l + T.step));
      if (r === 1) k = span(t, l, l + 0.3) * (1 - span(t, T.nat - 0.2, T.nat));
      if (k <= 0) return;
      ctx.globalAlpha = a * k; ctx.lineWidth = 3 / MS; ctx.strokeStyle = C.ink; ctx.stroke(paths[c.i]);
    });
    ctx.restore();
    ctx.globalAlpha = 1;
  }

  function rows(t, a) {
    top.forEach(function (c, i) {
      var r = i + 1, l = landOf(r), k = out3(span(t, l, l + 0.45)), g = out3(span(t, l + 0.15, l + 0.9));
      if (k <= 0) return;
      var y = RY + i * RH, dx = (1 - k) * 60;
      ctx.globalAlpha = a * k; ctx.textBaseline = "alphabetic";
      ctx.textAlign = "left"; ctx.fillStyle = C.muted; ctx.font = "600 34px " + BODY;
      ctx.fillText(String(r), RX + dx, y + 44);
      ctx.fillStyle = C.ink; ctx.font = "600 44px " + BODY;
      ctx.fillText(c.n, RX + 56 + dx, y + 44);
      ctx.textAlign = "right"; ctx.fillStyle = C.current; ctx.font = "700 56px " + DISPLAY;
      ctx.fillText(g < 1 ? fmt(c.v * g) : c.l, RX + RW + dx, y + 48);
      var bx = RX + 56, bw = (RW - 56) * Math.max(0, c.v) / max;
      ctx.fillStyle = C.line; round(bx, y + 66, RW - 56, 14);
      ctx.fillStyle = C.current; round(bx, y + 66, Math.max(14, bw * g), 14);
    });
    ctx.textAlign = "left"; ctx.globalAlpha = 1;
  }
  function round(x, y, w, h) {
    ctx.beginPath(); if (ctx.roundRect) ctx.roundRect(x, y, w, h, h / 2); else ctx.rect(x, y, w, h); ctx.fill();
  }
  function fmt(v) { return (v < 0 ? "−" : "+") + Math.abs(v * 100).toFixed(1) + "%"; }

  function yardstick(t, a) {
    if (!F.nat) return;
    var k = out3(span(t, T.nat, T.nat + 0.6));
    if (k <= 0) return;
    var y1 = RY + 4 * RH + 96, x = RX + 56 + (RW - 56) * Math.max(0, F.nat.v) / max;
    ctx.globalAlpha = a * k;
    if (F.nat.v > 0) {                                                    // a tick across each bar, clear of the names
      ctx.fillStyle = C.ink;
      for (var i = 0; i < top.length; i++) {
        var ty = RY + i * RH + 58, kk = out3(span(t, T.nat + i * 0.06, T.nat + i * 0.06 + 0.4));
        ctx.globalAlpha = a * kk; ctx.fillRect(x - 2, ty, 4, 30 * kk);
      }
      ctx.globalAlpha = a * k;
    }
    ctx.fillStyle = C.ink; ctx.font = "600 38px " + BODY; ctx.textBaseline = "alphabetic";
    var label = "Thailand as a whole " + F.nat.l;
    ctx.textAlign = F.nat.v > 0 && x > RX + RW / 2 ? "right" : "left";
    ctx.fillText(label, F.nat.v > 0 ? x : RX + 56, y1 + 52);
    ctx.textAlign = "left"; ctx.globalAlpha = 1;
  }

  function slowest(t, a) {
    var k = out3(span(t, T.low, T.low + 0.6));
    if (k <= 0) return;
    var y = RY + 5 * RH + 112;
    ctx.globalAlpha = a * k; ctx.textBaseline = "alphabetic"; ctx.textAlign = "left";
    ctx.fillStyle = C.muted; ctx.font = "500 36px " + BODY;
    ctx.fillText("Slowest of " + F.n + " provinces", RX, y);
    ctx.fillStyle = C.ink; ctx.font = "600 44px " + BODY;
    ctx.fillText(F.low.n, RX, y + 58);
    ctx.textAlign = "right"; ctx.fillStyle = F.low.v < 0 ? C.ebb : C.ink; ctx.font = "700 56px " + DISPLAY;
    ctx.fillText(F.low.l, RX + RW, y + 60);
    ctx.textAlign = "left"; ctx.globalAlpha = 1;
  }

  function endCard(t) {
    var k = out3(span(t, T.end, T.end + 0.7));
    if (k <= 0) return;
    ctx.globalAlpha = k; ctx.textAlign = "center"; ctx.textBaseline = "alphabetic";
    ctx.fillStyle = C.ink; ctx.font = "700 84px " + DISPLAY;
    ctx.fillText("Every province,", W / 2, 820 + (1 - k) * 30);
    ctx.fillText("every month", W / 2, 920 + (1 - k) * 30);
    ctx.fillStyle = C.current; ctx.font = "600 38px " + BODY;
    ctx.fillText(F.site, W / 2, 1020 + (1 - k) * 30);
    ctx.fillStyle = C.muted; ctx.font = "500 32px " + BODY;
    ctx.fillText("Bank of Thailand, " + F.month, W / 2, 1080 + (1 - k) * 30);
    ctx.textAlign = "left"; ctx.globalAlpha = 1;
  }

  function render(t) {
    ctx.setTransform(canvas.width / W, 0, 0, canvas.height / H, 0, 0);
    paper();
    var a = 1 - out3(span(t, T.out, T.end));                              // the chart clears for the end card
    if (a > 0) { heading(t, a); country(t, a); rows(t, a); yardstick(t, a); slowest(t, a); }
    endCard(t);
    if (bar) bar.style.width = playing ? (100 * t / DUR) + "%" : "0%";
  }

  // ── playback on the page
  var start = null, raf = 0, playing = false, still = T.out - 0.1;         // at rest the page shows the finished chart
  function size() {
    var dpr = Math.min(devicePixelRatio || 1, 2), w = canvas.clientWidth || 360;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(w * dpr * H / W);
  }
  function draw() { render(playing ? (performance.now() - start) / 1000 : still); }
  function loop() {
    var t = (performance.now() - start) / 1000;
    if (t >= DUR) { render(DUR - 0.001); stop(true); return; }
    render(t); raf = requestAnimationFrame(loop);
  }
  function stop(done) {
    playing = false; cancelAnimationFrame(raf);
    playBtn.textContent = done ? "Play again" : "Play";
    if (done) still = T.out - 0.1;
  }
  playBtn.addEventListener("click", function () {
    if (playing) { stop(false); return; }
    playing = true; playBtn.textContent = "Stop"; start = performance.now(); loop();
  });
  addEventListener("resize", function () { size(); draw(); });
  size();
  if (document.fonts) document.fonts.ready.then(draw);
  render(still);
  // the mp4 exists only once a deploy has rendered it: offer the download when it is really there
  var dl = root.querySelector(".clip-dl");
  if (dl && location.protocol.indexOf("http") === 0) {
    fetch(dl.href, { method: "HEAD" }).then(function (r) { if (r.ok) dl.hidden = false; }).catch(function () {});
  }
  window.wmmClipRender = render;                                   // frame-by-frame export hook (tools/clip_mp4.mjs)
})();
