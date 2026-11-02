// Shared by the tools that photograph the built site (film_mp4.mjs, og_images.mjs): a static server for site/ and a
// headless Chrome driven over the DevTools protocol with Node's own http + WebSocket, so no packages are needed.
// CHROME=/path/to/chrome overrides the browser; BASE_PATH (as in build.py) is stripped from requests if set.
import http from "node:http";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const SITE = path.join(ROOT, "site");
export const BASE = (process.env.BASE_PATH || "").replace(/\/$/, "");
const CHROME = process.env.CHROME || (process.platform === "darwin"
  ? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" : "google-chrome");

const TYPES = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json",
  ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2", ".webmanifest": "application/manifest+json", ".xml": "application/xml" };

/** A static server for site/ on a free port → { origin, close } */
export async function serve() {
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
  return { origin: `http://127.0.0.1:${server.address().port}${BASE}`, close: () => server.close() };
}

/** Headless Chrome with a throwaway profile, one page, sized W×H → { send, once, evaluate, open, close } */
export async function chrome(W, H) {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "wmm-chrome-"));
  const args = ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "--hide-scrollbars",
    "--mute-audio", "--no-first-run", "--no-default-browser-check", `--window-size=${W},${H}`];
  if (process.env.CI) args.push("--no-sandbox");             // GitHub's Ubuntu runners refuse Chrome's sandbox
  const proc = spawn(CHROME, [...args, "about:blank"], { stdio: "ignore" });
  let port = null;                                            // port 0 → Chrome writes the one it chose to DevToolsActivePort
  for (let i = 0; i < 150 && !port; i++) {
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
  async function open(url) {
    const loaded = once("Page.loadEventFired");
    await send("Page.navigate", { url });
    await loaded;
  }
  async function close() {
    ws.close();
    const exited = new Promise((r) => proc.once("exit", r));
    proc.kill();
    await exited;                                             // Chrome writes to its profile until it has gone
    try {                                                     // its helpers can outlive it by a moment (seen on CI): tidy, never fail
      fs.rmSync(profile, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
    } catch (e) {
      console.warn(`  left ${profile}: ${e.code}`);
    }
  }
  return { send, once, evaluate, open, close };
}
