// Share images: one 1200×630 PNG per page, photographed from the card template that build.py writes to site/og/.
//
//   python build.py && node tools/og_images.mjs        → site/og/<key>.png (the Pages workflow runs this after build.py)
//
// Every page's <meta property="og:image"> already points at its own og/<key>.png. A card that fails to draw gets the
// site-wide image instead, so no page is ever left pointing at a missing file.
import fs from "node:fs";
import path from "node:path";
import { SITE, serve, chrome } from "./chrome.mjs";

const server = await serve();
const browser = await chrome(1200, 630);
await browser.open(`${server.origin}/og/`);
const n = await browser.evaluate("window.ogReady");
const dir = path.join(SITE, "og");
const fallback = fs.readFileSync(path.join(SITE, "assets", "og.png"));
let failed = 0;
const t0 = Date.now();
for (let i = 0; i < n; i++) {
  let key = null;
  try {
    key = await browser.evaluate(`card(${i})`);
    const { data } = await browser.send("Page.captureScreenshot", { format: "png", clip: { x: 0, y: 0, width: 1200, height: 630, scale: 1 } });
    fs.writeFileSync(path.join(dir, `${key}.png`), Buffer.from(data, "base64"));
  } catch (e) {
    failed++;
    console.error(`  card ${i} (${key ?? "?"}): ${e.message}`);
    if (key) fs.writeFileSync(path.join(dir, `${key}.png`), fallback);
  }
  if (i % 100 === 0) process.stdout.write(`\r  ${i}/${n}`);
}
await browser.close();
server.close();
const bytes = fs.readdirSync(dir).filter((f) => f.endsWith(".png")).reduce((a, f) => a + fs.statSync(path.join(dir, f)).size, 0);
console.log(`\r  ${n} share images in ${((Date.now() - t0) / 1000).toFixed(0)}s, ${(bytes / 1e6).toFixed(1)}MB` + (failed ? `, ${failed} fell back` : ""));
