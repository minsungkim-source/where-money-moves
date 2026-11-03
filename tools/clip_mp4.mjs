// Render the monthly clip (/clip/) to a 1080×1920 mp4 next to its page, as site/clip/<file from clip-data>:
// every frame from window.wmmClipRender(t), the same pure function of time the page plays. No sound.
//
//   python build.py && node tools/clip_mp4.mjs [fps]          (pages.yml runs it at deploy, after the share images)
//
// No packages: tools/chrome.mjs drives the installed Chrome over the DevTools protocol, and ffmpeg encodes.
import path from "node:path";
import { spawn } from "node:child_process";
import { SITE, serve, chrome } from "./chrome.mjs";

const FPS = +(process.argv[2] || 30);
const W = 1080, H = 1920;

const server = await serve();
const browser = await chrome(W, H);
const { send, evaluate } = browser;
await browser.open(`${server.origin}/clip/`);

// the stage fills the viewport at full size, in the light theme the clip is designed in
const { duration: DUR, file } = await evaluate(`(async () => {
  document.documentElement.dataset.theme = "light";
  const st = document.createElement("style");
  st.textContent = \`.clip-stage { position: fixed !important; inset: 0 !important; width: ${W}px !important; height: ${H}px !important;
      max-width: none !important; margin: 0 !important; border: 0 !important; border-radius: 0 !important; z-index: 2147483647; }
    .clip-stage canvas { width: ${W}px !important; height: ${H}px !important; }\`;
  document.head.append(st);
  await document.fonts.ready;
  await Promise.all(["700 80px 'Bricolage Grotesque'", "600 44px 'Atkinson Hyperlegible Next'", "500 36px 'Atkinson Hyperlegible Next'"]
    .map((f) => document.fonts.load(f)));
  dispatchEvent(new Event("resize"));
  await new Promise((r) => setTimeout(r, 600));
  return JSON.parse(document.getElementById("clip-data").textContent);
})()`);
const N = Math.round(DUR * FPS);
const OUT = path.join(SITE, "clip", file);

const ff = spawn("ffmpeg", ["-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", String(FPS), "-i", "-",
  "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-tune", "animation",
  "-movflags", "+faststart", OUT], { stdio: ["pipe", "inherit", "inherit"] });
const done = new Promise((r, j) => ff.on("close", (c) => (c ? j(new Error("ffmpeg exited " + c)) : r())));
const t0 = Date.now();
for (let i = 0; i < N; i++) {
  await evaluate(`wmmClipRender(${Math.min(i / FPS, DUR - 0.001) || 0.0001})`);
  const { data } = await send("Page.captureScreenshot", { format: "png", clip: { x: 0, y: 0, width: W, height: H, scale: 1 } });
  if (!ff.stdin.write(Buffer.from(data, "base64"))) await new Promise((r) => ff.stdin.once("drain", r));
  if (i % FPS === 0) process.stdout.write(`\r  frame ${i}/${N}  (${((Date.now() - t0) / 1000).toFixed(0)}s)`);
}
ff.stdin.end();
await done;
process.stdout.write(`\r  ${N} frames, ${DUR}s at ${FPS} fps in ${((Date.now() - t0) / 1000).toFixed(0)}s → ${OUT}\n`);

await browser.close();
server.close();
