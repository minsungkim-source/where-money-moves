/* Where Money Moves — 3D view of a province map.
   Loaded only when someone presses "3D" (app.js imports it on demand), so the 2D pages never pay for three.js.

   It needs no data of its own: it reads the 2D SVG already on the page.
     · each <a data-tip> → one province: its <path d> is our own "M x,y L x,y … Z" format, so it parses exactly
     · data-p-{lens}  → height (percentile rank within the layer, 0–100)
     · data-b-{lens}  → colour bin, resolved from the same CSS ramp tokens as the 2D map (--s1 … --s7, #hatch → --null)
   The 2D map stays in the page (hidden) and keeps driving the lens buttons, so the two views never disagree. */
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const MAX_H = 46;          // tallest extrusion, in map units (the SVG viewBox is ~330–600 wide)
const BASE_H = 1.5;        // every province has a plinth, so "no data" still reads as land

function parsePath(d) {
  const rings = [];
  for (const sub of d.split("M").filter(Boolean)) {
    const pts = sub.replace(/Z/g, "").split("L").map((p) => p.split(",").map(Number));
    if (pts.length >= 3 && pts.every((p) => p.length === 2 && isFinite(p[0]) && isFinite(p[1]))) rings.push(pts);
  }
  return rings;
}

function area(r) {
  let a = 0;
  for (let i = 0, j = r.length - 1; i < r.length; j = i++) a += (r[j][0] + r[i][0]) * (r[j][1] - r[i][1]);
  return a / 2;
}

function cssColor(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return new THREE.Color(v || fallback);
}

export function mount(svg, host, opts = {}) {
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const vb = svg.viewBox.baseVal;
  const cx = vb.width / 2, cy = vb.height / 2;

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  host.appendChild(renderer.domElement);
  renderer.domElement.setAttribute("aria-hidden", "true");

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(32, 1, 1, 6000);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.maxPolarAngle = Math.PI * 0.46;           // never under the ground
  controls.screenSpacePanning = false;

  scene.add(new THREE.HemisphereLight(0xffffff, 0x8899aa, 1.6));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.position.set(-0.6, 1.2, 0.8).multiplyScalar(800);
  scene.add(sun);

  // ── provinces: one extruded mesh each, scaled in Y to the lens height
  const units = [];
  for (const a of svg.querySelectorAll(".units a[data-tip]")) {
    const path = a.querySelector("path");
    const rings = parsePath(path.getAttribute("d"));
    if (!rings.length) continue;
    const shapes = rings.filter((r) => Math.abs(area(r)) > 0.4).map((r) =>
      new THREE.Shape(r.map(([x, y]) => new THREE.Vector2(x - cx, -(y - cy)))));
    if (!shapes.length) continue;
    const geo = new THREE.ExtrudeGeometry(shapes, { depth: 1, bevelEnabled: false, curveSegments: 1 });
    geo.rotateX(-Math.PI / 2);                            // extrude upwards (+Y); map lies on the XZ plane
    const mat = new THREE.MeshStandardMaterial({ roughness: 0.72, metalness: 0.04 });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.userData = { a, path, h: BASE_H, rings };
    mesh.scale.y = BASE_H;
    scene.add(mesh);
    units.push(mesh);
  }

  // outlines on the top face only (walls stay clean): one closed line per ring at y = 1, which the mesh's
  // y-scale lifts to the current height
  const edgeMat = new THREE.LineBasicMaterial({ transparent: true, opacity: 0.6 });
  for (const m of units) {
    for (const r of m.userData.rings) {
      if (Math.abs(area(r)) <= 0.4) continue;
      const g = new THREE.BufferGeometry().setFromPoints(r.map(([x, y]) => new THREE.Vector3(x - cx, 1.001, y - cy)));
      m.add(new THREE.LineLoop(g, edgeMat));
    }
  }

  function palette() {
    const pal = { n: cssColor("--null", "#f1f1ee") };
    for (let i = 1; i <= 7; i++) pal[i] = cssColor(`--s${i}`, "#88aaaa");
    edgeMat.color = cssColor("--paper", "#ffffff");
    return pal;
  }
  let pal = palette();

  let anim = null;
  function apply(lens, instant) {
    const from = units.map((m) => m.scale.y);
    const to = units.map((m) => {
      const p = parseFloat(m.userData.path.getAttribute(`data-p-${lens}`));
      return isFinite(p) ? BASE_H + (p / 100) * MAX_H : BASE_H;
    });
    units.forEach((m) => {
      const b = m.userData.path.getAttribute(`data-b-${lens}`) || "n";
      m.material.color.copy(pal[b] || pal.n);
    });
    if (instant || reduced) { units.forEach((m, i) => (m.scale.y = to[i])); return; }
    const t0 = performance.now(), dur = 700;
    anim = (now) => {
      const k = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - k, 3);
      units.forEach((m, i) => (m.scale.y = from[i] + (to[i] - from[i]) * e));
      if (k >= 1) anim = null;
    };
  }

  // ── camera: tilted view, distance found by projecting the real bounding box onto the screen.
  // A bounding sphere wastes most of the frame on tall, thin countries (Vietnam); this fills it.
  const box = new THREE.Box3();
  units.forEach((m) => box.expandByObject(m));
  box.max.y = MAX_H + BASE_H;
  const centre = box.getCenter(new THREE.Vector3()).setY(MAX_H * 0.2);
  const corners = [];
  for (const x of [box.min.x, box.max.x]) for (const y of [0, box.max.y]) for (const z of [box.min.z, box.max.z]) corners.push(new THREE.Vector3(x, y, z));
  const dir = new THREE.Vector3(0, 1.15, 1).normalize();             // ~49° above the horizon, looking north
  let userMoved = false;
  controls.addEventListener("start", () => { userMoved = true; });
  function fits(d) {
    camera.position.copy(centre).addScaledVector(dir, d);
    camera.lookAt(centre);
    camera.updateMatrixWorld();
    return corners.every((c) => { const p = c.clone().project(camera); return Math.abs(p.x) < 0.94 && Math.abs(p.y) < 0.94; });
  }
  function fit() {
    const w = host.clientWidth, h = host.clientHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    if (userMoved) return;                                            // never yank the camera after someone turned it
    let lo = 10, hi = 20000;
    for (let i = 0; i < 40; i++) { const mid = (lo + hi) / 2; if (fits(mid)) hi = mid; else lo = mid; }
    fits(hi);
    controls.target.copy(centre);
    controls.minDistance = hi * 0.35;
    controls.maxDistance = hi * 1.8;
    controls.update();
  }
  fit();

  // ── hover tooltip and click-through, through the same .tip element as the 2D map
  const ray = new THREE.Raycaster(), mouse = new THREE.Vector2();
  const tip = document.querySelector(".tip");
  let hovered = null, downAt = null;
  function pick(ev) {
    const r = renderer.domElement.getBoundingClientRect();
    mouse.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(mouse, camera);
    const hit = ray.intersectObjects(units, false)[0];
    return hit ? hit.object : null;
  }
  function onMove(ev) {
    const m = pick(ev);
    if (hovered && hovered !== m) hovered.material.emissive.setHex(0x000000);
    hovered = m;
    renderer.domElement.style.cursor = m ? "pointer" : "grab";
    if (!m) { if (tip) tip.hidden = true; return; }
    m.material.emissive.setHex(0x222222);
    if (tip && opts.tipHTML) {
      tip.replaceChildren(opts.tipHTML(JSON.parse(m.userData.a.dataset.tip), svg.dataset.lens));
      tip.hidden = false;
      tip.style.left = Math.min(innerWidth - 110, Math.max(110, ev.clientX)) + "px";
      tip.style.top = ev.clientY + "px";
    }
  }
  const el = renderer.domElement;
  el.addEventListener("pointermove", onMove);
  el.addEventListener("pointerleave", () => { if (tip) tip.hidden = true; });
  el.addEventListener("pointerdown", (ev) => { downAt = [ev.clientX, ev.clientY]; });
  el.addEventListener("pointerup", (ev) => {           // a click, not the end of a drag
    if (!downAt || Math.hypot(ev.clientX - downAt[0], ev.clientY - downAt[1]) > 6) return;
    const m = pick(ev);
    if (m) location.href = m.userData.a.getAttribute("href");
  });

  // follow the lens buttons (they set data-lens on the hidden SVG) and the theme toggle
  const lensObs = new MutationObserver(() => apply(svg.dataset.lens));
  lensObs.observe(svg, { attributes: true, attributeFilter: ["data-lens"] });
  const themeObs = new MutationObserver(() => { pal = palette(); apply(svg.dataset.lens, true); });
  themeObs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  const ro = new ResizeObserver(fit);
  ro.observe(host);

  apply(svg.dataset.lens, true);
  if (!reduced) units.forEach((m) => (m.scale.y = BASE_H));      // rise from the plinth once, on open
  apply(svg.dataset.lens);

  let raf = 0, alive = true;
  (function loop(now) {
    if (!alive) return;
    if (anim) anim(now);
    controls.update();
    renderer.render(scene, camera);
    raf = requestAnimationFrame(loop);
  })(performance.now());

  return function dispose() {
    alive = false;
    cancelAnimationFrame(raf);
    lensObs.disconnect(); themeObs.disconnect(); ro.disconnect();
    controls.dispose();
    units.forEach((m) => { m.geometry.dispose(); m.material.dispose(); m.children.forEach((c) => c.geometry.dispose()); });
    edgeMat.dispose();
    renderer.dispose();
    el.remove();
    if (tip) tip.hidden = true;
  };
}
