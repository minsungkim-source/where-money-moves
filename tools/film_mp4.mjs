// Render the site film (/film/) to an mp4: every frame from window.wmmFilmRender(t), the sound from
// window.wmmFilmSound(OfflineAudioContext), so the video is the same pure function of time as the page.
//
//   python build.py && node tools/film_mp4.mjs [out.mp4] [fps]
//
// No packages: tools/chrome.mjs drives the installed Chrome over the DevTools protocol, and ffmpeg encodes.
import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import { ROOT, serve, chrome } from "./chrome.mjs";

const OUT = path.resolve(process.argv[2] || path.join(ROOT, "dist", "where-the-money-moved.mp4"));
const FPS = +(process.argv[3] || 30);
const W = 1920, H = 1080, SR = 48000;

const server = await serve();
const browser = await chrome(W, H);
const { send, evaluate } = browser;
await browser.open(`${server.origin}/film/`);

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
const wav = OUT.replace(/\.mp4$/, "") + ".sound.wav";
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

await browser.close();
server.close();
fs.rmSync(wav, { force: true });
