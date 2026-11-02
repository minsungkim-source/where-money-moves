/* Where Money Moves — "Where the money moved", a 42-second film drawn in code.

   Directed with the Lemo-Opuscar method (github.com/lemomo-ai/lemo-opuscar, MIT) in its Data Storytelling grammar,
   made our own: the site's paper, ink and current-teal instead of cream and pencil.
     · the chart is the film: every mark is a real number from data/processed, baked into the page by build.py
     · transitions are chart operations (bars grow, a bar opens into a map, the map falls into a ranking), no fades
     · one signature move: 77 provinces lift off the map and settle into a momentum ranking
     · sound is sonification: each mark is a pitch from its value; real silences before the turn and the reveal
   render(t) is a pure function of time, so the same code can be stepped frame by frame for a video export. */
(function () {
  "use strict";
  var root = document.getElementById("film");
  if (!root) return;
  var F = JSON.parse(document.getElementById("film-data").textContent);
  var canvas = root.querySelector("canvas"), ctx = canvas.getContext("2d");
  var capEl = root.querySelector(".film-cap"), playBtn = root.querySelector(".film-play"), bar = root.querySelector(".film-bar i");
  var reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  var W = 1920, H = 1080, DUR = F.duration;

  // ── palette from the site's tokens, re-read when the theme changes
  var C = {};
  function readColors() {
    var cs = getComputedStyle(document.documentElement);
    ["paper", "ink", "muted", "line", "current", "ebb", "sea", "land", "s1", "s2", "s3", "s4", "s5", "s6", "s7"].forEach(function (k) {
      C[k] = cs.getPropertyValue("--" + k).trim();
    });
  }
  readColors();
  new MutationObserver(function () { readColors(); draw(); }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  // ── easing and timing helpers
  var clamp = function (x, a, b) { return Math.max(a, Math.min(b, x)); };
  var ease = function (x) { x = clamp(x, 0, 1); return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; };
  var out3 = function (x) { x = clamp(x, 0, 1); return 1 - Math.pow(1 - x, 3); };
  var span = function (t, a, b) { return clamp((t - a) / (b - a), 0, 1); };
  var lerp = function (a, b, k) { return a + (b - a) * k; };
  function ramp(p) { return C["s" + Math.min(7, Math.floor((p || 0) / (100 / 7)) + 1)]; }

  // ── the cue sheet: when each beat happens (seconds). Captions hold ≥ 1.8 s and ≥ letters/15 + 1.5 s.
  var T = { hook: 0, bars: 3.2, thai: 8.6, turn: 12.2, dive: 13.4, bkk: 16.8, east: 21.6, lift: 26.8, rank: 28.6, close: 33.4, end: 38.6 };
  var CAPS = F.captions;           // [[start, end, text], …] written by build.py from the data

  // ── scenes ──────────────────────────────────────────────────────────────
  function paper() {
    ctx.fillStyle = C.paper; ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = C.line;
    for (var x = 60; x < W; x += 60) for (var y = 60; y < H - 160; y += 60) ctx.fillRect(x, y, 2, 2);
  }

  function title(t) {
    var a = span(t, 0.2, 1.4) * (1 - span(t, T.bars - 0.4, T.bars + 0.3));
    if (a <= 0) return;
    ctx.globalAlpha = a;
    ctx.fillStyle = C.ink;
    ctx.font = "700 92px 'Bricolage Grotesque', Inter, sans-serif";
    ctx.textBaseline = "alphabetic";
    var words = F.question.split(" "), shown = Math.ceil(words.length * out3(span(t, 0.2, 2.2)));
    var line1 = words.slice(0, 5).join(" "), line2 = words.slice(5).join(" ");
    var s = words.slice(0, shown).join(" ");
    ctx.fillText(s.length > line1.length ? line1 : s, 140, 420);
    if (s.length > line1.length) ctx.fillText(s.slice(line1.length + 1), 140, 530);
    ctx.globalAlpha = 1;
  }

  // 11 countries: a ranked bar chart, longest first; the home country lands last after a held silence
  var BX = 520, BY = 150, BW = 1180, BH = 52, GAP = 22;
  function bars(t) {
    var a = span(t, T.bars, T.bars + 0.6) * (1 - span(t, T.dive + 0.6, T.dive + 1.4));
    if (a <= 0) return;
    ctx.globalAlpha = a;
    F.countries.forEach(function (c, i) {
      var land = T.bars + 0.35 + i * 0.42 + (c.home ? 1.0 : 0);              // the home bar waits out a silence
      var k = out3(span(t, land, land + 0.55));
      var y = BY + i * (BH + GAP);
      ctx.fillStyle = C.muted; ctx.font = "500 30px Inter, sans-serif"; ctx.textAlign = "right"; ctx.textBaseline = "middle";
      ctx.fillText(c.n, BX - 28, y + BH / 2);
      ctx.fillStyle = c.home ? C.ebb : ramp(c.s);
      var w = BW * (c.s / 100) * k;
      ctx.fillRect(BX, y, w, BH);
      if (k > 0.98) {
        ctx.fillStyle = C.ink; ctx.textAlign = "left"; ctx.font = "600 28px Inter, sans-serif";
        ctx.fillText(Math.round(c.s), BX + w + 14, y + BH / 2);
      }
      if (c.home && t > land + 0.6) {                                          // ring the home bar
        ctx.strokeStyle = C.ebb; ctx.lineWidth = 4;
        var r = out3(span(t, land + 0.6, land + 1.2));
        ctx.globalAlpha = a * r;
        ctx.strokeRect(BX - 14, y - 12, w + 120, BH + 24);
        ctx.globalAlpha = a;
      }
    });
    ctx.textAlign = "left";
    ctx.globalAlpha = 1;
  }

  // Thailand's provinces: map space (TH map units) → screen, with a camera that dives in
  var vb = F.thai.viewBox, paths = F.thai.provinces.map(function (p) { return new Path2D(p.d); });
  var focus = (function () {                       // the camera pushes in on the Bangkok → east corridor
    var b = F.thai.provinces.find(function (p) { return p.role === "bkk"; }),
        e = F.thai.provinces.find(function (p) { return p.role === "east"; }) || b;
    return [(b.cx + e.cx) / 2, (b.cy + e.cy) / 2];
  })();
  function mapXform(t) {
    var s = Math.min((H - 240) / vb[1], 900 / vb[0]);
    var x0 = W * 0.30 - (vb[0] * s) / 2, y0 = 80;
    var k = ease(span(t, T.dive, T.dive + 2.2));                               // from the home bar, outwards
    var homeY = BY + F.countries.findIndex(function (c) { return c.home; }) * (BH + GAP);
    var base = { s: lerp(0.18, 1, k) * s, x: lerp(BX, x0, k), y: lerp(homeY, y0, k) };
    // push in for the two beats, pull back out before the provinces lift off
    var z = 1 + 1.25 * ease(span(t, T.bkk - 0.6, T.bkk + 1.6)) * (1 - ease(span(t, T.lift - 1.6, T.lift - 0.1)));
    if (z === 1) return { s: base.s, x: base.x, y: base.y, k: k };
    var fx = base.x + focus[0] * base.s, fy = base.y + focus[1] * base.s;   // focus point on screen before zoom
    var tx = lerp(fx, W * 0.36, (z - 1) / 1.25), ty = lerp(fy, H * 0.40, (z - 1) / 1.25);
    var sz = base.s * z;
    return { s: sz, x: tx - focus[0] * sz, y: ty - focus[1] * sz, k: k };
  }
  function province(i, fill, alpha) {
    ctx.globalAlpha = alpha; ctx.fillStyle = fill; ctx.fill(paths[i]);
    ctx.lineWidth = 0.6; ctx.strokeStyle = C.paper; ctx.stroke(paths[i]);
  }
  function thaiMap(t) {
    if (t < T.dive || t > T.rank + 1.2) return;
    var m = mapXform(t), fade = 1 - span(t, T.lift, T.rank);
    ctx.save(); ctx.translate(m.x, m.y); ctx.scale(m.s, m.s);
    ctx.lineJoin = "round";
    F.thai.provinces.forEach(function (p, i) {
      var col = C.land;                                                        // everyone else waits in land colour
      if (t > T.bkk && p.role === "bkk") col = C.ebb;
      if (t > T.east && p.role === "east") col = C.current;
      ctx.lineWidth = 0.6 / (m.s / 1.4);
      province(i, col, m.k * fade);
    });
    ctx.restore(); ctx.globalAlpha = 1;
    notes(t, m);
  }

  // pinned notes: a leader from the province to a label in the open sea to the right
  function notes(t, m) {
    [["bkk", T.bkk + 0.5, C.ebb, 0], ["east", T.east + 0.5, C.current, 1]].forEach(function (n) {
      var p = F.thai.provinces.find(function (q) { return q.role === n[0]; });
      if (!p) return;
      var a = out3(span(t, n[1], n[1] + 0.6)) * (1 - span(t, T.lift - 1.4, T.lift - 0.4));
      if (a <= 0) return;
      var px = m.x + p.cx * m.s, py = m.y + p.cy * m.s;
      var lx = W * 0.62, ly = 300 + n[3] * 190;
      var grow = out3(span(t, n[1], n[1] + 0.5));
      ctx.globalAlpha = a; ctx.strokeStyle = n[2]; ctx.lineWidth = 3;
      ctx.beginPath(); ctx.moveTo(px, py);
      ctx.quadraticCurveTo((px + lx) / 2, ly - 60, lerp(px, lx - 20, grow), lerp(py, ly - 12, grow)); ctx.stroke();
      ctx.beginPath(); ctx.arc(px, py, 9, 0, Math.PI * 1.7); ctx.stroke();      // an unclosed ring on the mark
      ctx.fillStyle = C.ink; ctx.font = "700 46px 'Bricolage Grotesque', Inter, sans-serif";
      ctx.fillText(F.notes[n[0]][0], lx, ly);
      ctx.fillStyle = n[2]; ctx.font = "600 34px Inter, sans-serif";
      ctx.fillText(F.notes[n[0]][1], lx, ly + 48);
      ctx.globalAlpha = 1;
    });
  }

  // the signature move: each province leaves its place on the map and settles into a ranked strip
  function lift(t) {
    if (t < T.lift) return;
    var m = mapXform(t), n = F.thai.provinces.length;
    var x0 = 140, x1 = W - 140, yb = 760;
    F.thai.provinces.forEach(function (p, i) {
      var start = T.lift + (p.rank / n) * 1.6;                                  // leaders go first
      var k = ease(span(t, start, start + 1.4));
      var sx = m.x + p.cx * m.s, sy = m.y + p.cy * m.s;
      var tx = lerp(x0, x1, (p.rank - 1) / (n - 1)), h = 30 + (p.s / 100) * 420;
      var x = lerp(sx, tx, k), y = lerp(sy, yb, k);
      var w = lerp(8, (x1 - x0) / n - 3, k), hh = lerp(8, h, k);
      var out = 1 - span(t, T.close - 0.2, T.close + 0.8);
      ctx.globalAlpha = out;
      ctx.fillStyle = p.role === "bkk" ? C.ebb : p.role === "east" ? C.current : ramp(p.s);
      ctx.fillRect(x - w / 2, y - hh, w, hh);
      if (k > 0.97 && (p.role === "bkk" || p.role === "east")) {
        ctx.fillStyle = C.ink; ctx.font = "600 26px Inter, sans-serif"; ctx.textAlign = "center";
        ctx.fillText(p.n + "  #" + p.rank, x, y - hh - 18);
        ctx.textAlign = "left";
      }
    });
    if (t > T.rank) {                                                           // the axis arrives with the unit
      var a = span(t, T.rank, T.rank + 0.6) * (1 - span(t, T.close - 0.2, T.close + 0.6));
      ctx.globalAlpha = a; ctx.fillStyle = C.muted; ctx.font = "500 24px Inter, sans-serif";
      ctx.fillText("Momentum, 77 provinces: fastest", x0, yb + 40);
      ctx.textAlign = "right"; ctx.fillText("slowest", x1, yb + 40); ctx.textAlign = "left";
      ctx.fillRect(x0, yb + 6, x1 - x0, 2);
    }
    ctx.globalAlpha = 1;
  }

  // ending: one mark, close
  function closeUp(t) {
    if (t < T.close) return;
    var a = span(t, T.close, T.close + 0.7);
    var d = F.district, cx = W * 0.5, cy = 470;
    var r = lerp(4, 130, out3(span(t, T.close, T.close + 1.2)));
    ctx.globalAlpha = a;
    ctx.fillStyle = C.current; ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fill();
    var ring = span(t, T.close + 0.4, T.close + 2.4);                           // one ripple as it lands
    ctx.strokeStyle = C.current; ctx.lineWidth = 3; ctx.globalAlpha = a * (1 - ring);
    ctx.beginPath(); ctx.arc(cx, cy, r + 40 + ring * 120, 0, Math.PI * 2); ctx.stroke();
    ctx.globalAlpha = a;
    ctx.fillStyle = C.paper; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.font = "700 64px 'Bricolage Grotesque', Inter, sans-serif"; ctx.fillText(d.dep, cx, cy - 6);
    ctx.font = "500 24px Inter, sans-serif"; ctx.fillText("deposits, a year", cx, cy + 44);
    ctx.fillStyle = C.ink; ctx.font = "700 54px 'Bricolage Grotesque', Inter, sans-serif";
    ctx.fillText(d.n, cx, cy + 210);
    ctx.fillStyle = C.muted; ctx.font = "500 28px Inter, sans-serif";
    ctx.fillText(d.prov + ", Thailand", cx, cy + 262);
    ctx.textAlign = "left"; ctx.textBaseline = "alphabetic"; ctx.globalAlpha = 1;
  }

  function endCard(t) {
    if (t < T.end) return;
    var a = span(t, T.end, T.end + 0.8);
    ctx.globalAlpha = a; ctx.fillStyle = C.paper; ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = C.ink; ctx.textAlign = "center";
    ctx.font = "700 96px 'Bricolage Grotesque', Inter, sans-serif"; ctx.fillText("Where Money Moves", W / 2, 470);
    ctx.fillStyle = C.muted; ctx.font = "500 34px Inter, sans-serif";
    ctx.fillText(F.endline, W / 2, 550);
    ctx.textAlign = "left"; ctx.globalAlpha = 1;
  }

  function caption(t) {
    var c = CAPS.find(function (c) { return t >= c[0] && t < c[1]; });
    var text = c ? c[2] : "";
    if (capEl.textContent !== text) capEl.textContent = text;
  }

  function render(t) {
    ctx.setTransform(canvas.width / W, 0, 0, canvas.height / H, 0, 0);
    paper(); title(t); bars(t); thaiMap(t); lift(t); closeUp(t); endCard(t);
    caption(t);
    bar.style.width = (100 * t / DUR) + "%";
  }

  // ── sound: sonification on WebAudio. Each landing mark is a pitch from its value (pentatonic), a soft pad
  // underneath, and two real silences (before the home bar, before the ranking).
  var audio = null, scheduled = false;
  // Takes an optional context: the video export passes an OfflineAudioContext and gets the same score, sample-exact.
  function sound(given) {
    var AC = window.AudioContext || window.webkitAudioContext;
    if (!given && !AC) return null;
    var ac = given || new AC(), master = ac.createGain();
    master.gain.value = 0.55; master.connect(ac.destination);
    var t0 = ac.currentTime + (given ? 0 : 0.05);
    var penta = [0, 2, 4, 7, 9];
    function note(at, value, len, vol) {
      var step = Math.round((value / 100) * 12), semi = 12 * Math.floor(step / 5) + penta[step % 5];
      var f = 220 * Math.pow(2, semi / 12);
      var o = ac.createOscillator(), m = ac.createOscillator(), mg = ac.createGain(), g = ac.createGain();
      o.type = "sine"; o.frequency.value = f; m.frequency.value = f * 2; mg.gain.value = f * (0.3 + value / 120);
      m.connect(mg); mg.connect(o.frequency);
      g.gain.setValueAtTime(0, t0 + at); g.gain.linearRampToValueAtTime(vol, t0 + at + 0.01);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + at + len);
      o.connect(g); g.connect(master); o.start(t0 + at); m.start(t0 + at); o.stop(t0 + at + len + 0.05); m.stop(t0 + at + len + 0.05);
    }
    function pad(from, to, freq) {
      [0, 4, -5].forEach(function (cents, i) {
        var o = ac.createOscillator(), lp = ac.createBiquadFilter(), g = ac.createGain();
        o.type = "sawtooth"; o.frequency.value = freq * (i === 2 ? 1.5 : 1); o.detune.value = cents * 3;
        lp.type = "lowpass"; lp.frequency.value = 520;
        g.gain.setValueAtTime(0, t0 + from); g.gain.linearRampToValueAtTime(0.03, t0 + from + 1.5);
        g.gain.setValueAtTime(0.03, t0 + to - 1.2); g.gain.linearRampToValueAtTime(0, t0 + to);
        o.connect(lp); lp.connect(g); g.connect(master); o.start(t0 + from); o.stop(t0 + to + 0.1);
      });
    }
    pad(0.2, T.bars + 3.8, 110);                                   // silence at the home bar
    pad(T.dive, T.lift - 0.4, 98);                                  // silence before the ranking falls
    pad(T.rank + 0.6, DUR, 130.8);
    F.countries.forEach(function (c, i) {
      note(T.bars + 0.35 + i * 0.42 + (c.home ? 1.0 : 0), c.s, c.home ? 1.6 : 0.6, c.home ? 0.32 : 0.18);
    });
    F.thai.provinces.forEach(function (p) { note(T.lift + (p.rank / F.thai.provinces.length) * 1.6 + 0.9, p.s, 0.35, 0.06); });
    note(T.close + 0.4, 100, 2.4, 0.3);
    return ac;
  }

  // ── playback
  var start = null, raf = 0, playing = false;
  function size() {
    var dpr = Math.min(devicePixelRatio || 1, 2), w = canvas.clientWidth;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(w * dpr * H / W);
  }
  function draw(t) { render(t === undefined ? (playing ? (performance.now() - start) / 1000 : (root.dataset.t ? +root.dataset.t : 0)) : t); }
  function loop() {
    var t = (performance.now() - start) / 1000;
    if (t >= DUR) { render(DUR - 0.001); stop(true); return; }
    render(t); root.dataset.t = t.toFixed(2);
    raf = requestAnimationFrame(loop);
  }
  function stop(done) {
    playing = false; cancelAnimationFrame(raf);
    if (audio) { audio.close(); audio = null; }
    root.classList.remove("playing");
    playBtn.textContent = done ? "Play again" : "Play";
  }
  playBtn.addEventListener("click", function () {
    if (playing) { stop(false); return; }
    playing = true; root.classList.add("playing"); playBtn.textContent = "Stop";
    start = performance.now();
    if (!root.querySelector("[data-mute]").checked) audio = sound();
    loop();
  });
  addEventListener("resize", function () { size(); draw(); });
  size();
  if (document.fonts) document.fonts.ready.then(function () { draw(reduced ? T.lift + 4 : 0.0001); });
  render(reduced ? T.lift + 4 : 0.0001);
  window.wmmFilmRender = render;                                   // frame-by-frame export hooks (tools/film_mp4.mjs)
  window.wmmFilmSound = sound;
})();
