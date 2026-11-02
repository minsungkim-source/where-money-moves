// Render the site film (/film/) to an mp4: every frame from window.wmmFilmRender(t), the sound from
// window.wmmFilmSound(OfflineAudioContext), so the video is the same pure function of time as the page.
//
//   python build.py && node tools/film_mp4.mjs [out.mp4] [fps]
//
// No packages: Node's own http + WebSocket drive the installed Chrome over the DevTools protocol, and ffmpeg encodes.
// CHROME=/path/to/chrome overrides the browser; the built site is read from site/ (BASE_PATH is stripped if set).
import http from "node:http";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SITE = path.join(ROOT, "site");
const OUT = path.resolve(process.argv[2] || path.join(ROOT, "dist", "where-the-money-moved.mp4"));
const FPS = +(process.argv[3] || 30);
const W = 1920, H = 1080, SR = 48000;
const CHROME = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const BASE = (process.env.BASE_PATH || "").replace(/\/$/, "");

// ── a static server for site/
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json",
  ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2", ".webmanifest": "application/manifest+json", ".xml": "application/xml" };
const server = http.createServer((req, res) => {
  let p = decodeURIComponent(new URL(req.url, "http://x").pathname);
  if (BASE && p.startsWith(BASE)) p = p.slice(BASE.length) || "/";
  let f = path.join(SITE, path.normalize(p));
  if (!f.startsWith(SITE)) { res.writeHead(403).end(); return; }
  if (fs.existsSync(f) && fs.statSync(f).isDirectory()) f = path.join(f, "index.html");
  fs.readFile(f, (err, buf) => {
    if (err) { res.writeHead(404).end(); return; }
    res.writeHead(200, { "content-type": TYPES[path.extname(f)] || "application/octet-stream" }).end(buf);
  });
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const pageURL = `http://127.0.0.1:${server.address().port}${BASE}/film/`;

// ── headless Chrome with a throwaway profile; port 0 → it writes the chosen port to DevToolsActivePort
const profile = fs.mkdtempSync(path.join(os.tmpdir(), "wmm-film-"));
const chrome = spawn(CHROME, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "--hide-scrollbars",
  "--mute-audio", "--no-first-run", "--no-default-browser-check", `--window-size=${W},${H}`, "about:blank"], { stdio: "ignore" });
let port = null;
for (let i = 0; i < 100 && !port; i++) {
  await new Promise((r) => setTimeout(r, 100));
  try { port = fs.readFileSync(path.join(profile, "DevToolsActivePort"), "utf8").split("\n")[0]; } catch {}
}
if (!port) throw new Error("Chrome did not start: " + CHROME);
const target = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find((t) => t.type === "page");

const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
let seq = 0;
const pending = new Map(), waiters = [];
ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { const [r, j] = pending.get(m.id); pending.delete(m.id); m.error ? j(new Error(m.error.message)) : r(m.result); }
  else if (m.method) waiters.filter((w) => w.method === m.method).forEach((w) => { waiters.splice(waiters.indexOf(w), 1); w.r(m.params); });
};
const send = (method, params = {}) => new Promise((r, j) => { const id = ++seq; pending.set(id, [r, j]); ws.send(JSON.stringify({ id, method, params })); });
const once = (method) => new Promise((r) => waiters.push({ method, r }));
async function evaluate(expression) {
  const res = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (res.exceptionDetails) throw new Error(res.exceptionDetails.exception?.description || res.exceptionDetails.text);
  return res.result.value;
}

await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", { width: W, height: H, deviceScaleFactor: 1, mobile: false });
await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: "light" }, { name: "prefers-reduced-motion", value: "no-preference" }] });
const loaded = once("Page.loadEventFired");
await send("Page.navigate", { url: pageURL });
await loaded;

// the stage fills the viewport at 1920×1080; the caption is set for a 1080p frame, not for a page column
const DUR = await evaluate(`(async () => {
  document.documentElement.dataset.theme = "light";
  const st = document.createElement("style");
  st.textContent = \`.film-stage { position: fixed !important; inset: 0 !important; width: ${W}px !important; height: ${H}px !important;
      margin: 0 !important; border: 0 !important; border-radius: 0 !important; z-index: 2147483647; opacity: 1 !important; transform: none !important; }
    .film-cap { font-size: 36px !important; padding-top: 16px !important; }\`;
  document.head.append(st);
  await document.fonts.ready;
  dispatchEvent(new Event("resize"));
  await new Promise((r) => setTimeout(r, 1200));
  return JSON.parse(document.getElementById("film-data").textContent).duration;
})()`);
const N = Math.round(DUR * FPS);

// ── sound: the page's own score through an OfflineAudioContext, back as 16-bit PCM WAV
const wavB64 = await evaluate(`(async () => {
  const ac = new OfflineAudioContext(2, Math.ceil(${SR} * ${DUR}), ${SR});
  wmmFilmSound(ac);
  const buf = await ac.startRendering(), n = buf.length, L = buf.getChannelData(0), R = buf.getChannelData(1);
  const dv = new DataView(new ArrayBuffer(44 + n * 4)), s = (o, t) => [...t].forEach((c, i) => dv.setUint8(o + i, c.charCodeAt(0)));
  s(0, "RIFF"); dv.setUint32(4, 36 + n * 4, true); s(8, "WAVEfmt "); dv.setUint32(16, 16, true); dv.setUint16(20, 1, true);
  dv.setUint16(22, 2, true); dv.setUint32(24, ${SR}, true); dv.setUint32(28, ${SR} * 4, true); dv.setUint16(32, 4, true);
  dv.setUint16(34, 16, true); s(36, "data"); dv.setUint32(40, n * 4, true);
  for (let i = 0, o = 44; i < n; i++, o += 4) {
    dv.setInt16(o, Math.max(-1, Math.min(1, L[i])) * 32767, true); dv.setInt16(o + 2, Math.max(-1, Math.min(1, R[i])) * 32767, true);
  }
  const u8 = new Uint8Array(dv.buffer); let bin = "";
  for (let i = 0; i < u8.length; i += 0x8000) bin += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  return btoa(bin);
})()`);
fs.mkdirSync(path.dirname(OUT), { recursive: true });
const wav = path.join(profile, "sound.wav");
fs.writeFileSync(wav, Buffer.from(wavB64, "base64"));

// ── frames → ffmpeg (the score is mixed for a page; loudnorm lifts it to video loudness)
const ff = spawn("ffmpeg", ["-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", String(FPS), "-i", "-", "-i", wav,
  "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p", "-tune", "animation",
  "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", String(SR), "-c:a", "aac", "-b:a", "192k",
  "-movflags", "+faststart", "-shortest", OUT], { stdio: ["pipe", "inherit", "inherit"] });
const done = new Promise((r, j) => ff.on("close", (c) => (c ? j(new Error("ffmpeg exited " + c)) : r())));
const t0 = Date.now();
for (let i = 0; i < N; i++) {
  await evaluate(`wmmFilmRender(${Math.min(i / FPS, DUR - 0.001) || 0.0001})`);
  const { data } = await send("Page.captureScreenshot", { format: "png", clip: { x: 0, y: 0, width: W, height: H, scale: 1 } });
  if (!ff.stdin.write(Buffer.from(data, "base64"))) await new Promise((r) => ff.stdin.once("drain", r));
  if (i % FPS === 0) process.stdout.write(`\r  frame ${i}/${N}  (${((Date.now() - t0) / 1000).toFixed(0)}s)`);
}
ff.stdin.end();
await done;
process.stdout.write(`\r  ${N} frames, ${DUR}s at ${FPS} fps → ${OUT}\n`);

ws.close(); server.close();
const exited = new Promise((r) => chrome.once("exit", r));
chrome.kill();
await exited;                                                     // Chrome writes to its profile until it has gone
fs.rmSync(profile, { recursive: true, force: true, maxRetries: 5 });
