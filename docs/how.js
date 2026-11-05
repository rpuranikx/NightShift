// How it works: a scroll story in the same wireframe lab as the film.
// The failures leave the benches, pass through the bronze, silver and gold tables,
// and land in the bin for their cause. Scroll position drives everything.
// With reduced motion, or if WebGL is missing, the section stays a plain list and map.
import * as T from './vendor/three.module.min.js';

const section = document.getElementById('how');
const canvas = section && section.querySelector('.story-canvas');
const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;

function webgl() {
  try { const c = document.createElement('canvas'); return !!(c.getContext('webgl2') || c.getContext('webgl')); } catch { return false; }
}

if (section && canvas && !reduce && webgl()) start();

async function start() {
  try { await document.fonts.load('600 54px Sora'); } catch {}
  section.classList.add('is-live');

  const NAVY = '#0B2026', ORANGE = '#FF3621', MINT = '#3CF5C8', CYAN = '#5fd9e8';
  const renderer = new T.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  renderer.toneMapping = T.ACESFilmicToneMapping;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = T.PCFSoftShadowMap;

  const scene = new T.Scene();
  scene.background = new T.Color(NAVY);
  scene.fog = new T.Fog(NAVY, 16, 36);
  const cam = new T.PerspectiveCamera(36, 1, 0.1, 100);

  scene.add(new T.HemisphereLight('#9fd6e0', '#0b1a1f', 0.6));
  const key = new T.DirectionalLight('#ffffff', 1.6);
  key.position.set(6, 12, 6);
  key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  Object.assign(key.shadow.camera, { left: -14, right: 14, top: 14, bottom: -14 });
  scene.add(key);

  // A concrete floor, the same as the film's: wireframe is only for the hardware.
  const fc = document.createElement('canvas'); fc.width = fc.height = 512;
  const g = fc.getContext('2d');
  g.fillStyle = '#2a3438'; g.fillRect(0, 0, 512, 512);
  for (let i = 0; i < 9000; i++) { const v = (40 + Math.random() * 30) | 0; g.fillStyle = `rgba(${v},${v + 8},${v + 12},.25)`; g.fillRect(Math.random() * 512, Math.random() * 512, 2, 2); }
  g.strokeStyle = 'rgba(0,0,0,.35)'; g.lineWidth = 3;
  for (let i = 0; i <= 512; i += 128) { g.beginPath(); g.moveTo(i, 0); g.lineTo(i, 512); g.stroke(); g.beginPath(); g.moveTo(0, i); g.lineTo(512, i); g.stroke(); }
  const ft = new T.CanvasTexture(fc); ft.wrapS = ft.wrapT = T.RepeatWrapping; ft.repeat.set(10, 10); ft.colorSpace = T.SRGBColorSpace;
  const floor = new T.Mesh(new T.PlaneGeometry(80, 80), new T.MeshStandardMaterial({ map: ft, roughness: 0.92 }));
  floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; scene.add(floor);

  const wire = (geo, color, opacity = 1) => new T.LineSegments(new T.EdgesGeometry(geo), new T.LineBasicMaterial({ color, transparent: true, opacity }));
  const label = (text, color, w = 2, h = 0.5) => {
    const lc = document.createElement('canvas'); lc.width = 512; lc.height = 128;
    const l = lc.getContext('2d'); l.fillStyle = color; l.font = '600 56px Sora, sans-serif'; l.textAlign = 'center'; l.fillText(text, 256, 82);
    const tex = new T.CanvasTexture(lc); tex.colorSpace = T.SRGBColorSpace;
    const sp = new T.Sprite(new T.SpriteMaterial({ map: tex, transparent: true, depthWrite: false }));
    sp.scale.set(w, h, 1); return sp;
  };

  // Fifteen benches.
  const benches = [];
  for (let r = 0; r < 3; r++) for (let k = 0; k < 5; k++) {
    const b = new T.Group();
    b.add(wire(new T.BoxGeometry(1.6, 0.9, 0.8), CYAN, 0.7));
    const scr = wire(new T.BoxGeometry(1, 0.6, 0.05), CYAN, 0.8); scr.position.set(0, 0.8, -0.2); b.add(scr);
    b.position.set(-4 + k * 2.2, 0.45, -3 + r * 1.8); scene.add(b); benches.push(b);
  }

  // Bronze, silver and gold, stacked.
  const slabs = [['Bronze', '#CD7F32'], ['Silver', '#C0C8CC'], ['Gold', '#FFC94D']].map(([name, c], i) => {
    const s = wire(new T.BoxGeometry(5, 0.5, 3), c, 0.9);
    s.position.set(7, 2 + i * 1.4, 0);
    s.add(new T.Mesh(new T.BoxGeometry(5, 0.5, 3), new T.MeshBasicMaterial({ color: c, transparent: true, opacity: 0.06, depthWrite: false })));
    const l = label(name, c); l.position.set(-3.4, 0, 1.5); s.add(l);
    scene.add(s); return s;
  });

  // The four causes, plus the queue for a person.
  const binDefs = [['Script', 18], ['Framework', 9], ['Hardware', 22], ['Real defect', 8], ['Needs a look', 4]];
  const bins = binDefs.map(([name], i) => {
    const col = i === 4 ? MINT : ORANGE;
    const b = wire(new T.BoxGeometry(1.5, 1, 1.5), col, 0.9);
    b.position.set(4.5 + i * 1.8, 0.5, 4.5);
    const l = label(name, col); l.position.set(0, 1, 0); b.add(l);
    scene.add(b); return b;
  });

  // Sixty-one failures.
  const cats = binDefs.flatMap(([, n], i) => Array(n).fill(i));
  for (let i = cats.length - 1; i > 0; i--) { const j = (i * 7919) % (i + 1); [cats[i], cats[j]] = [cats[j], cats[i]]; }
  const chipGeo = new T.BoxGeometry(0.22, 0.22, 0.22);
  const slot = [0, 0, 0, 0, 0];
  const chips = cats.map((cat, i) => {
    const m = new T.Mesh(chipGeo, new T.MeshStandardMaterial({ color: ORANGE, emissive: ORANGE, emissiveIntensity: 0.6 }));
    m.castShadow = true;
    const seed = ((i * 2654435761) % 1000) / 1000;
    const bench = benches[i % 15].position;
    const home = bench.clone().add(new T.Vector3((seed - 0.5) * 1.2, 0.95 + ((i * 37) % 10) / 25, ((i * 13) % 10) / 20 - 0.25));
    const n = slot[cat]++;
    const bin = bins[cat].position;
    const end = new T.Vector3(bin.x + ((n % 3) - 1) * 0.4, 0.14 + Math.floor(n / 9) * 0.22, bin.z + ((Math.floor(n / 3) % 3) - 1) * 0.4);
    const mid = new T.Vector3(7 + (seed - 0.5) * 4, 2, (seed * 2 - 1) * 1.2);
    m.userData = { home, end, mid, cat, seed, d: (i / cats.length) * 0.5 };
    scene.add(m); return m;
  });

  const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));
  const ease = (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2);
  const lerp = (a, b, p) => a + (b - a) * p;
  // Camera stops for each step: position x, y, z, then where it looks.
  const keys = [[-1, 6, 13, 0, 1, 0], [2, 7, 12, 5, 2.6, 0], [4, 5, 11, 7, 1.5, 2], [7, 8.5, 14.5, 8.4, 0.9, 3.4]];
  const steps = [...section.querySelectorAll('.story-steps > li')];
  const bars = [...section.querySelectorAll('.story-bar i')];
  const tmp = new T.Vector3(), col = new T.Color();
  let wide = true;

  function resize() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    wide = w / h > 1.1;
    cam.aspect = w / h;
    cam.fov = wide ? 36 : 58;
    // On wide screens, push the scene right so the words on the left sit on empty floor.
    if (wide) cam.setViewOffset(w * 1.3, h, 0, 0, w, h); else cam.clearViewOffset();
    cam.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(canvas); resize();

  let visible = false, raf = 0;
  new IntersectionObserver(([e]) => { visible = e.isIntersecting; if (visible && !raf) raf = requestAnimationFrame(tick); }).observe(section);

  function progress() {
    const r = section.getBoundingClientRect();
    return clamp(-r.top / Math.max(1, r.height - innerHeight)) * 3;
  }

  function tick(now) {
    raf = 0;
    if (!visible) return;
    const p = progress(), t = now / 1000;
    const i = Math.min(2, Math.floor(p)), f = ease(p - i), a = keys[i], b = keys[i + 1];
    cam.position.set(lerp(a[0], b[0], f), lerp(a[1], b[1], f), lerp(a[2], b[2], f));
    cam.lookAt(lerp(a[3], b[3], f), lerp(a[4], b[4], f), lerp(a[5], b[5], f));

    const on = Math.min(3, Math.round(p));
    steps.forEach((s, k) => s.classList.toggle('on', k === on));
    bars.forEach((s, k) => s.classList.toggle('on', k <= on));

    chips.forEach((m) => {
      const u = m.userData;
      const q1 = clamp((p - 0.3 - u.d) / 0.6);
      const rise = clamp((p - 0.6 - u.d) / 0.8);
      const q2 = clamp((p - 1.3 - u.d) / 0.7);
      tmp.copy(u.mid); tmp.y = 2 + rise * 2.8;
      m.position.copy(u.home); m.position.y += Math.sin(t * 2 + u.seed * 9) * 0.05 * (1 - q1);
      if (q1 > 0) m.position.lerp(tmp, ease(q1));
      if (q2 > 0) { m.position.lerpVectors(tmp, u.end, ease(q2)); m.position.y += Math.sin(q2 * Math.PI) * 1.5; }
      const spin = 1 - q2;
      m.rotation.set(t * u.seed * spin, t * 0.7 * spin, 0);
      col.set(q2 > 0.95 && u.cat === 4 ? MINT : ORANGE);
      m.material.color.copy(col); m.material.emissive.copy(col);
    });
    slabs.forEach((s, k) => { s.material.opacity = 0.3 + 0.6 * clamp((p - 0.5 - k * 0.2) * 2); });

    renderer.render(scene, cam);
    raf = requestAnimationFrame(tick);
  }
}
