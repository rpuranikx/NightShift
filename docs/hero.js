(() => {
const C = { orange: 0xFF3621, navy: 0x0B2026, mint: 0x3CF5C8 };
// Story beats (seconds)
const DAWN = 7.4;          // lights come up, engineer walks in
const BEFORE = 9.2;        // reviewing by hand
const REWIND = 16.4;       // the morning rewinds
const AFTER = 18.0;        // same morning, with Nightshift
const END = 25.6;          // pull back on the sorted lab
const LOOP = 30;
const HAND_STEP = 0.5;     // one failure every 0.5 s by hand -> 14 done before the rewind

// ---------- seeded data: the same 61 failures every play ----------
let seed = 7; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
const BENCHES = [];
for (let i = 0; i < 15; i++) {
  const solo = i < 8;
  BENCHES.push({ id: solo ? `SOLO-0${i + 1}` : `DUO-0${i - 7}`, displays: solo ? 1 : 2,
    x: -7.8 + (i % 5) * 3.9, z: -7.4 + Math.floor(i / 5) * 4.0, chips: 0 });
}
const DUO03 = BENCHES.findIndex(b => b.id === 'DUO-03');
const CATS = ['script', 'framework', 'hardware', 'defect'];
const LABEL = { script: 'SCRIPT', framework: 'FRAMEWORK', hardware: 'HARDWARE', defect: 'REAL DEFECT' };
const EVENTS = [];
for (let k = 0; k < 16; k++) EVENTS.push({ bench: DUO03, cat: 'hardware', t: 3.0 + k * 0.24 + rnd() * 0.2 });
const mix = [...Array(26).fill('script'), ...Array(11).fill('framework'), ...Array(3).fill('hardware'), ...Array(5).fill('defect')];
mix.forEach(cat => { let b; do { b = Math.floor(rnd() * 15); } while (b === DUO03); EVENTS.push({ bench: b, cat, t: 0.5 + rnd() * 6.4 }); });
EVENTS.sort((a, b) => a.t - b.t);
const binCount = { script: 0, framework: 0, hardware: 0, defect: 0 };
EVENTS.forEach(e => { e.stack = BENCHES[e.bench].chips++; e.slot = binCount[e.cat]++; });
const order = EVENTS.map((_, i) => i).sort(() => rnd() - .5);
order.forEach((ei, k) => {
  EVENTS[ei].handAt = BEFORE + 0.3 + k * HAND_STEP;   // by hand: one at a time
  EVENTS[ei].handIdx = k;
  EVENTS[ei].autoAt = AFTER + 1.0 + k * 0.06;         // with Nightshift: all 61 in ~4 s
});

// ---------- renderer ----------
const canvas = document.getElementById('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.05;

const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
const span = (t, a, b) => clamp((t - a) / (b - a));
const easeOut = p => 1 - Math.pow(1 - p, 4);
const easeInOut = p => p < .5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;
const lerp = (a, b, p) => a + (b - a) * p;
const V = (x, y, z) => new THREE.Vector3(x, y, z);

// polished concrete lab floor (seeded so it never shifts between plays)
function floorTexture() {
  const cv = document.createElement('canvas'); cv.width = cv.height = 1024; const x = cv.getContext('2d');
  x.fillStyle = '#58636a'; x.fillRect(0, 0, 1024, 1024);
  const img = x.getImageData(0, 0, 1024, 1024), d = img.data;
  for (let i = 0; i < d.length; i += 4) { const n = (rnd() - .5) * 16; d[i] += n; d[i + 1] += n; d[i + 2] += n; }
  x.putImageData(img, 0, 0);
  for (let k = 0; k < 46; k++) {
    const px = rnd() * 1024, py = rnd() * 1024, r = 80 + rnd() * 220;
    const gr = x.createRadialGradient(px, py, 0, px, py, r);
    gr.addColorStop(0, `rgba(${rnd() < .5 ? '255,255,255' : '0,0,0'},0.05)`); gr.addColorStop(1, 'rgba(0,0,0,0)');
    x.fillStyle = gr; x.fillRect(0, 0, 1024, 1024);
  }
  x.strokeStyle = 'rgba(18,24,27,0.6)'; x.lineWidth = 3;
  for (let i = 0; i <= 1024; i += 512) { x.beginPath(); x.moveTo(i, 0); x.lineTo(i, 1024); x.stroke(); x.beginPath(); x.moveTo(0, i); x.lineTo(1024, i); x.stroke(); }
  const t = new THREE.CanvasTexture(cv); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(8, 8); t.anisotropy = 8; t.colorSpace = THREE.SRGBColorSpace;
  return t;
}
function contactShadowTex() {
  const cv = document.createElement('canvas'); cv.width = cv.height = 128; const x = cv.getContext('2d');
  const g = x.createRadialGradient(64, 64, 8, 64, 64, 64); g.addColorStop(0, 'rgba(0,0,0,0.6)'); g.addColorStop(1, 'rgba(0,0,0,0)');
  x.fillStyle = g; x.fillRect(0, 0, 128, 128); return new THREE.CanvasTexture(cv);
}
const SHADOW_TEX = contactShadowTex();

function label(text, { size = 28, color = '#8AA4AD', w = 256, h = 64, weight = 600 } = {}) {
  const cv = document.createElement('canvas'); cv.width = w * 2; cv.height = h * 2;
  const tex = new THREE.CanvasTexture(cv); tex.anisotropy = 4; tex.colorSpace = THREE.SRGBColorSpace;
  const spr = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false, toneMapped: false }));
  let last = '';
  spr.userData.draw = (t, c = color) => {
    if (t + c === last) return; last = t + c;
    const x = cv.getContext('2d'); x.setTransform(2, 0, 0, 2, 0, 0); x.clearRect(0, 0, w, h);
    x.font = `${weight} ${size}px "JetBrains Mono", monospace`; x.fillStyle = c; x.textAlign = 'center'; x.textBaseline = 'middle';
    x.fillText(t, w / 2, h / 2); tex.needsUpdate = true;
  };
  spr.userData.draw(text); spr.scale.set(w / 100, h / 100, 1); return spr;
}

// ---------- the lab ----------
const scene = new THREE.Scene();
scene.fog = new THREE.Fog(C.navy, 34, 66);
const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 200);
const amb = new THREE.HemisphereLight(0xdfefff, 0x1a2328, 0.3); scene.add(amb);
const sun = new THREE.DirectionalLight(0xfff1e0, 0.4); sun.position.set(10, 18, 14);
sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048); sun.shadow.radius = 4; sun.shadow.bias = -0.0004;
Object.assign(sun.shadow.camera, { left: -16, right: 16, top: 16, bottom: -16, near: 1, far: 60 });
scene.add(sun);
const deskLight = new THREE.PointLight(0xffe2c4, 0, 7, 2); scene.add(deskLight);

const floor = new THREE.Mesh(new THREE.PlaneGeometry(90, 90), new THREE.MeshStandardMaterial({ map: floorTexture(), roughness: 0.5, metalness: 0.08 }));
floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; scene.add(floor);

const wireMat = new THREE.LineBasicMaterial({ color: 0x2C6175, toneMapped: false });
const wire = (w, h, d, mat = wireMat) => new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(w, h, d)), mat);
const ground = (w, d, parent, o = 0.8) => {
  const s = new THREE.Mesh(new THREE.PlaneGeometry(w, d), new THREE.MeshBasicMaterial({ map: SHADOW_TEX, transparent: true, opacity: o, depthWrite: false }));
  s.rotation.x = -Math.PI / 2; s.position.y = 0.01; parent.add(s); return s;
};

const benches = BENCHES.map(b => {
  const g = new THREE.Group(); g.position.set(b.x, 0, b.z); scene.add(g);
  ground(4.4, 2.6, g);
  const table = wire(3.2, 1, 1.6); table.position.y = 0.5; g.add(table);
  const pc = wire(0.5, 0.9, 0.9); pc.position.set(1.95, 0.45, 0); g.add(pc);
  const screens = [];
  for (let d = 0; d < b.displays; d++) {
    const mx = b.displays === 1 ? 0 : (d ? 0.68 : -0.68);
    const mon = wire(1.2, 0.8, 0.1); mon.position.set(mx, 1.55, -0.3); g.add(mon);
    const scr = new THREE.Mesh(new THREE.PlaneGeometry(1.1, 0.7), new THREE.MeshBasicMaterial({ color: 0x0F3440, toneMapped: false }));
    scr.position.set(mx, 1.55, -0.24); g.add(scr); screens.push(scr);
  }
  const lab = label(b.id, { size: 26 }); lab.position.set(0, 0.25, 1.15); lab.scale.multiplyScalar(0.8); g.add(lab);
  return { screens, label: lab };
});

// desk at the front; the engineer stands behind it facing us
const deskPos = V(3.9, 0, 8.6);
const desk = new THREE.Group(); desk.position.copy(deskPos); scene.add(desk);
ground(3.4, 2.2, desk);
const deskTop = wire(2.2, 1.0, 1.2); deskTop.position.y = 0.5; desk.add(deskTop);
const lap = wire(0.9, 0.05, 0.6); lap.position.set(0.3, 1.03, 0.1); desk.add(lap);
const lapScr = new THREE.Mesh(new THREE.PlaneGeometry(0.86, 0.55), new THREE.MeshBasicMaterial({ color: 0x0F3440, side: THREE.DoubleSide, toneMapped: false }));
lapScr.position.set(0.3, 1.3, -0.17); lapScr.rotation.x = 0.3; desk.add(lapScr);
deskLight.position.set(deskPos.x + 0.3, 1.8, deskPos.z + 0.6);

const papers = [];
for (let i = 0; i < 7; i++) {
  const p = new THREE.Mesh(new THREE.PlaneGeometry(0.4, 0.54), new THREE.MeshStandardMaterial({ color: 0xE9EEF0, roughness: 0.9 }));
  p.rotation.x = -Math.PI / 2; p.rotation.z = (rnd() - .5) * 0.9;
  p.position.set(deskPos.x - 0.85 + rnd() * 0.9, 1.004 + i * 0.002, deskPos.z - 0.25 + rnd() * 0.5);
  p.receiveShadow = true; scene.add(p); papers.push(p);
}
const handDone = i => V(deskPos.x - 0.55 + (i % 4) * 0.2, 1.1 + Math.floor(i / 8) * 0.19, deskPos.z + 0.4 - (Math.floor(i / 4) % 2) * 0.2);
const inbox = V(deskPos.x - 0.8, 1.12, deskPos.z + 0.35);

// bins (after Nightshift)
const BIN_Z = 6.6, BIN_X = { script: -4.5, framework: -2.25, hardware: 0, defect: 2.25 };
const bins = {};
CATS.forEach((c, i) => {
  const g = new THREE.Group(); g.position.set(BIN_X[c], 0, BIN_Z);
  const mat = new THREE.LineBasicMaterial({ color: C.mint, transparent: true, opacity: 0, toneMapped: false });
  const sh = ground(2.8, 2.1, g, 0);
  const box = wire(2.0, 1.0, 1.5, mat); box.position.y = 0.5; g.add(box);
  const l = label(LABEL[c], { size: 30, color: '#3CF5C8', w: 320 }); l.scale.multiplyScalar(0.75); l.position.set(0, 1.45, 0.4); l.material.opacity = 0; g.add(l);
  scene.add(g); bins[c] = { g, mat, l, sh, i };
});

// chips: one per failure
const chipGeo = new THREE.BoxGeometry(0.3, 0.3, 0.3);
const chips = EVENTS.map(e => {
  const b = BENCHES[e.bench];
  const m = new THREE.Mesh(chipGeo, new THREE.MeshStandardMaterial({ color: C.orange, emissive: C.orange, emissiveIntensity: 0.6, transparent: true, roughness: 0.35 }));
  m.castShadow = true;
  const col = e.stack % 2, row = Math.floor(e.stack / 2);
  m.userData.home = V(b.x - 0.2 + col * 0.4, 2.35 + row * 0.36, b.z - 0.3);
  const n = e.slot;
  m.userData.bin = V(BIN_X[e.cat] + ((n % 5) - 2) * 0.36, 0.2 + Math.floor(n / 15) * 0.34, BIN_Z + ((Math.floor(n / 5) % 3) - 1) * 0.4);
  m.visible = false; scene.add(m); return m;
});

// Nightshift panel
const pcv = document.createElement('canvas'); pcv.width = 1680; pcv.height = 1040;
const ptex = new THREE.CanvasTexture(pcv); ptex.anisotropy = 4; ptex.colorSpace = THREE.SRGBColorSpace;
const panel = new THREE.Mesh(new THREE.PlaneGeometry(4.0, 2.48), new THREE.MeshBasicMaterial({ map: ptex, transparent: true, opacity: 0, depthWrite: false, toneMapped: false }));
scene.add(panel);
let panelKey = '';
function drawPanel(counts, done) {
  const key = JSON.stringify(counts) + done; if (key === panelKey) return; panelKey = key;
  const x = pcv.getContext('2d'); x.setTransform(2, 0, 0, 2, 0, 0); const W = 840, H = 520;
  x.clearRect(0, 0, W, H);
  x.beginPath(); x.roundRect(4, 4, W - 8, H - 8, 26); x.fillStyle = 'rgba(11,32,38,0.95)'; x.fill();
  x.strokeStyle = 'rgba(60,245,200,0.5)'; x.lineWidth = 2; x.stroke();
  x.font = '800 40px Sora, system-ui, sans-serif'; x.textAlign = 'left'; x.fillStyle = '#EAF2F4'; x.fillText('Night', 40, 74);
  const w = x.measureText('Night').width; x.fillStyle = '#FF3621'; x.fillText('shift', 40 + w, 74);
  x.font = '400 20px "JetBrains Mono", monospace'; x.fillStyle = '#8AA4AD'; x.textAlign = 'right'; x.fillText('MORNING TRIAGE · 61 FAILURES', W - 40, 70);
  CATS.forEach((c, i) => {
    const y = 140 + i * 74;
    x.textAlign = 'left'; x.font = '600 24px "JetBrains Mono", monospace'; x.fillStyle = '#EAF2F4'; x.fillText(LABEL[c], 40, y + 8);
    x.beginPath(); x.roundRect(290, y - 12, 430, 22, 11); x.fillStyle = 'rgba(138,164,173,0.16)'; x.fill();
    x.beginPath(); x.roundRect(290, y - 12, Math.max(22, 430 * Math.min(1, counts[c] / 26)), 22, 11);
    x.fillStyle = c === 'hardware' && counts[c] > 10 ? '#FF3621' : '#3CF5C8'; x.fill();
    x.textAlign = 'right'; x.font = '700 26px "JetBrains Mono", monospace'; x.fillStyle = '#EAF2F4'; x.fillText(String(counts[c]), W - 40, y + 9);
  });
  x.textAlign = 'left'; x.font = '600 23px Sora, system-ui, sans-serif'; x.fillStyle = done ? '#3CF5C8' : '#8AA4AD';
  x.fillText(done ? 'Report ready. DUO-03: ADB cable getting worse.' : 'Sorting last night’s failures…', 40, H - 46);
  ptex.needsUpdate = true;
}

// ---------- the engineer: adult, matte, mood shown through posture ----------
const E = (() => {
  const M = c => new THREE.MeshStandardMaterial({ color: c, roughness: 0.72 });
  const skin = M(0xC99A78), shirt = M(0xB9CCD4), pants = M(0x2B3338), shoe = M(0x1A1F22), hairM = M(0x221813), frame = M(0x15191B), mugM = M(0xF2F4F5);
  const mesh = (geo, mat, x, y, z, parent) => { const m = new THREE.Mesh(geo, mat); m.position.set(x, y, z); m.castShadow = true; parent.add(m); return m; };
  const root = new THREE.Group(); scene.add(root);
  const shadow = ground(1.2, 1.0, root, 0.7);
  const hips = new THREE.Group(); hips.position.y = 0.92; root.add(hips);
  const legs = [-0.11, 0.11].map(x => {
    const g = new THREE.Group(); g.position.set(x, 0, 0); hips.add(g);
    mesh(new THREE.CapsuleGeometry(0.085, 0.72, 6, 12), pants, 0, -0.44, 0, g);
    mesh(new THREE.BoxGeometry(0.14, 0.08, 0.28), shoe, 0, -0.88, 0.06, g);
    return g;
  });
  const torso = new THREE.Group(); hips.add(torso);
  mesh(new THREE.CapsuleGeometry(0.19, 0.38, 8, 16), shirt, 0, 0.32, 0, torso).scale.set(1.12, 1, 0.78);
  mesh(new THREE.CylinderGeometry(0.055, 0.06, 0.1, 12), skin, 0, 0.66, 0, torso);
  const head = new THREE.Group(); head.position.y = 0.82; torso.add(head);
  mesh(new THREE.SphereGeometry(0.125, 24, 18), skin, 0, 0, 0, head).scale.set(0.92, 1.12, 1);
  const hair = mesh(new THREE.SphereGeometry(0.132, 24, 18, 0, Math.PI * 2, 0, Math.PI * 0.42), hairM, 0, 0.03, -0.012, head);
  hair.scale.set(0.95, 1.1, 1.04); hair.rotation.x = -0.32;
  [-0.045, 0.045].forEach(x => { const r = new THREE.Mesh(new THREE.TorusGeometry(0.032, 0.006, 6, 16), frame); r.position.set(x, 0.01, 0.118); head.add(r); });
  const bridge = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.006, 0.006), frame); bridge.position.set(0, 0.012, 0.12); head.add(bridge);
  const arms = [-1, 1].map(s => {
    const sh = new THREE.Group(); sh.position.set(0.24 * s, 0.56, 0); torso.add(sh);
    mesh(new THREE.CapsuleGeometry(0.06, 0.24, 6, 10), shirt, 0, -0.16, 0, sh);
    const el = new THREE.Group(); el.position.y = -0.32; sh.add(el);
    mesh(new THREE.CapsuleGeometry(0.052, 0.22, 6, 10), shirt, 0, -0.15, 0, el);
    const hand = new THREE.Group(); hand.position.y = -0.31; el.add(hand);
    mesh(new THREE.SphereGeometry(0.055, 12, 10), skin, 0, 0, 0, hand);
    return { sh, el, hand };
  });
  const mug = new THREE.Group(); mug.position.set(0, -0.02, 0.07); arms[1].hand.add(mug);
  mesh(new THREE.CylinderGeometry(0.05, 0.045, 0.11, 16), mugM, 0, 0, 0, mug);
  const coffee = new THREE.Mesh(new THREE.CircleGeometry(0.045, 16), new THREE.MeshBasicMaterial({ color: 0x3E2516 }));
  coffee.rotation.x = -Math.PI / 2; coffee.position.y = 0.056; mug.add(coffee);
  const steam = [0, 1].map(() => { const s = label('~', { size: 60, color: '#EAF2F4', w: 64, h: 64, weight: 400 }); s.scale.set(0.12, 0.12, 1); mug.add(s); return s; });
  root.scale.setScalar(1.15);
  return { root, hips, legs, torso, head, arms, mug, steam };
})();

// ---------- camera path ----------
const CAM = [
  { t: 0,          pos: V(20, 17, 27),     look: V(0, 0.5, -1) },
  { t: DAWN,       pos: V(16, 12.5, 23),   look: V(-1, 1, -1.5) },
  { t: BEFORE,     pos: V(2.2, 6.0, 15.6), look: V(2.6, 1.4, 6.4) },
  { t: REWIND,     pos: V(3.4, 3.9, 12.9), look: V(3.6, 1.6, 7.6) },   // slow push in on the struggle
  { t: AFTER,      pos: V(0.5, 8.6, 16.4), look: V(0.2, 1.1, 3.8) },
  { t: END,        pos: V(-0.4, 8.0, 16.8), look: V(0.0, 1.1, 3.6) },
  { t: END + 3,    pos: V(11, 13, 23),     look: V(-0.5, 0.8, 0) },
  { t: 999,        pos: V(11, 13, 23),     look: V(-0.5, 0.8, 0) },
];
const look = new THREE.Vector3();
function cameraAt(t) {
  let i = 0; while (CAM[i + 1].t < t) i++;
  const a = CAM[i], b = CAM[i + 1], p = easeInOut(span(t, a.t, b.t));
  camera.position.lerpVectors(a.pos, b.pos, p);
  camera.position.x += Math.sin(t * 0.35) * 0.15; camera.position.y += Math.sin(t * 0.5) * 0.06; // gentle handheld drift
  look.lerpVectors(a.look, b.look, p);
  // phones are tall and narrow: pull back so the bins and the desk stay in frame
  if (camera.aspect < 0.8) camera.position.sub(look).multiplyScalar(1.45).add(look);
  camera.lookAt(look);
}

// ---------- overlay text ----------
const CAPTIONS = [
  [0, '22:00. Fifteen test benches start their overnight suites.'],
  [3.0, 'Failures pile up all night. <b>DUO-03</b> keeps dropping its ADB link.'],
  [DAWN + 0.2, '06:00. <b>61 failures</b> to sort before standup.'],
  [BEFORE + 0.8, 'Open a log. Check the screenshot. Decide. Next.'],
  [REWIND, 'Same morning. One change.'],
  [AFTER + 0.8, 'Open Nightshift. <em>Grab a coffee.</em>'],
  [END, 'Same 61 failures. <b>14 done by 09:50</b> by hand. <em>All 61 by 06:04</em> with Nightshift.'],
];
const $ = id => document.getElementById(id);
const capEl = $('caption'), clockEl = $('clock'), chapter = $('chapter'), chapterName = $('chapterName'), chapterClock = $('chapterClock'), chapterCount = $('chapterCount');
let capIdx = -1, frozen = false;
function setCaption(t) {
  let i = 0; while (i + 1 < CAPTIONS.length && CAPTIONS[i + 1][0] <= t) i++;
  if (i === capIdx) return; capIdx = i;
  if (frozen) { capEl.innerHTML = CAPTIONS[i][1]; return; }
  capEl.classList.add('out');
  setTimeout(() => { capEl.innerHTML = CAPTIONS[i][1]; capEl.classList.remove('out'); }, 220);
}
const hhmm = mins => { const m = ((Math.floor(mins) % 1440) + 1440) % 1440; return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`; };
const HAND_END_MIN = 6 * 60 + 230;   // 09:50
function handClock(tm) { return 6 * 60 + clamp((tm - BEFORE) / (REWIND - BEFORE)) * 230; }

// ---------- colors ----------
const nightBg = new THREE.Color(0x03090C), dayBg = new THREE.Color(C.navy);
const nightWire = new THREE.Color(0x1D4655), dayWire = new THREE.Color(0x86BACB);
const scrIdle = new THREE.Color(0x0F3440), scrFail = new THREE.Color(C.orange), scrOk = new THREE.Color(C.mint), scrPaper = new THREE.Color(0x9FB4BC);
const cOrange = new THREE.Color(C.orange), cMint = new THREE.Color(C.mint);

// ---------- one frame; everything is a pure function of t ----------
function render(t) {
  // tm drives the by-hand morning; during the rewind it runs backwards to the start
  const rewinding = t >= REWIND && t < AFTER;
  const tm = t < REWIND ? t : rewinding ? lerp(REWIND, BEFORE, easeInOut(span(t, REWIND, AFTER - 0.2))) : BEFORE;
  const after = t >= AFTER;

  cameraAt(t);
  setCaption(t);
  const day = easeInOut(span(t, DAWN - 0.6, DAWN + 1.2));
  scene.background = nightBg.clone().lerp(dayBg, day); scene.fog.color.copy(scene.background);
  amb.intensity = lerp(0.3, 0.8, day); sun.intensity = lerp(0.25, 1.7, day);
  wireMat.color.copy(nightWire).lerp(dayWire, day);
  deskLight.intensity = 6 * easeInOut(span(t, DAWN + 0.6, BEFORE)) * (after ? 0.6 : 1);

  // clocks and chapter label
  clockEl.textContent = hhmm(22 * 60 + clamp(t / DAWN) * 8 * 60); clockEl.style.opacity = t < DAWN + 0.6 ? 1 : 0;
  const inBefore = t >= BEFORE - 0.2 && !after, inAfter = t >= AFTER - 0.1;
  chapter.classList.toggle('on', inBefore || inAfter);
  chapter.classList.toggle('before', inBefore && !rewinding); chapter.classList.toggle('after', inAfter);
  chapterName.textContent = rewinding ? 'REWINDING' : inAfter ? 'AFTER NIGHTSHIFT' : 'BEFORE NIGHTSHIFT';
  chapterClock.textContent = inAfter ? hhmm(6 * 60 + Math.min(4, Math.max(0, t - AFTER - 0.6) * 0.85)) : hhmm(handClock(tm));

  // failures
  const flash = {};
  EVENTS.forEach((e, i) => {
    const m = chips[i], since = t - e.t;
    if (since < 0) { m.visible = false; return; }
    m.visible = true;
    if (since < 0.5) flash[e.bench] = Math.max(flash[e.bench] || 0, 1 - since / 0.5);
    const pop = easeOut(span(since, 0, 0.3));
    m.material.opacity = pop; m.scale.setScalar(lerp(0.6, 1, pop)); m.rotation.set(0, 0, 0);
    m.position.copy(m.userData.home); m.position.y += (1 - pop) * 0.3;
    m.material.color.copy(cOrange); m.material.emissive.copy(cOrange);
    if (!after) {
      // by hand: pulled to the desk, looked at, set on the done pile
      const toInbox = span(tm, e.handAt, e.handAt + 0.32), toDone = span(tm, e.handAt + 0.36, e.handAt + 0.48);
      if (toInbox > 0) {
        const p = easeInOut(toInbox);
        m.position.lerpVectors(m.userData.home, inbox, p); m.position.y += Math.sin(p * Math.PI) * 2.0;
        m.scale.setScalar(lerp(1, 0.55, p));
        if (toDone > 0) {
          const q = easeInOut(toDone); m.position.lerpVectors(inbox, handDone(e.handIdx), q); m.position.y += Math.sin(q * Math.PI) * 0.25;
          m.material.color.copy(cOrange).lerp(cMint, q); m.material.emissive.copy(cOrange).lerp(cMint, q);
        }
      }
    } else {
      // with Nightshift: every failure arcs into its bin at once
      const fly = span(t, e.autoAt, e.autoAt + 0.85);
      if (fly > 0) {
        const p = easeInOut(fly);
        m.position.lerpVectors(m.userData.home, m.userData.bin, p); m.position.y += Math.sin(p * Math.PI) * 3.0;
        m.rotation.set(p * Math.PI * 2, p * Math.PI, 0);
        const land = span(t, e.autoAt + 0.85, e.autoAt + 1.1);  // small settle on landing
        if (land > 0 && land < 1) m.scale.set(1, lerp(0.86, 1, easeOut(land)), 1);
        const c = span(fly, 0.6, 1); m.material.color.copy(cOrange).lerp(cMint, c); m.material.emissive.copy(cOrange).lerp(cMint, c);
      }
    }
  });
  const allSorted = after && t > AFTER + 5.4;
  benches.forEach((b, i) => b.screens.forEach(s => {
    s.material.color.copy(scrIdle).lerp(scrFail, flash[i] || 0);
    if (allSorted) s.material.color.copy(scrIdle).lerp(scrOk, 0.3 * easeOut(span(t, AFTER + 5.4, AFTER + 6.2)));
  }));
  benches[DUO03].label.userData.draw('DUO-03', span(t, 3.4, 6.5) > 0.3 && !allSorted ? '#FF3621' : '#8AA4AD');

  // desk props
  const handCount = EVENTS.filter(e => tm >= e.handAt + 0.48).length;
  const autoCount = EVENTS.filter(e => t >= e.autoAt + 0.85).length;
  chapterCount.textContent = after ? `${autoCount} / 61 sorted` : `${handCount} / 61 reviewed by hand`;
  papers.forEach((p, i) => p.visible = !after && tm > BEFORE + 0.2 + i * 0.9);
  const lapOn = easeOut(span(t, BEFORE - 0.4, BEFORE));
  lapScr.material.color.copy(scrIdle).lerp(after ? scrOk : scrPaper, after ? 0.55 * easeOut(span(t, AFTER + 0.2, AFTER + 0.7)) : lapOn * 0.5);

  // bins and panel
  CATS.forEach(c => {
    const b = bins[c], p = after ? easeOut(span(t, AFTER + 0.5 + b.i * 0.08, AFTER + 1.2 + b.i * 0.08)) : 0;
    b.mat.opacity = p * 0.95; b.l.material.opacity = p; b.sh.material.opacity = p * 0.5; b.g.position.y = (1 - p) * -0.3;
  });
  const open = after ? easeOut(span(t, AFTER + 0.3, AFTER + 0.9)) : 0;
  panel.material.opacity = open;
  panel.position.set(-1.2, 4.3, 4.6); panel.quaternion.copy(camera.quaternion);
  panel.scale.setScalar(lerp(0.96, 1, open));
  if (open > 0) {
    const counts = { script: 0, framework: 0, hardware: 0, defect: 0 };
    EVENTS.forEach(e => { if (t >= e.autoAt + 0.85) counts[e.cat]++; });
    drawPanel(counts, allSorted);
  }

  pose(t, tm, after);
  renderer.render(scene, camera);
}

// ---------- the engineer's posture ----------
function pose(t, tm, after) {
  const [aL, aR] = E.arms;
  E.torso.rotation.set(0, 0, 0); E.head.rotation.set(0, 0, 0); E.hips.position.y = 0.92;
  aL.sh.rotation.set(0, 0, 0.08); aR.sh.rotation.set(0, 0, -0.08); aL.el.rotation.set(0, 0, -0.1); aR.el.rotation.set(0, 0, 0.1);
  E.legs.forEach(l => l.rotation.set(0, 0, 0));
  E.mug.visible = false; E.steam.forEach(s => s.material.opacity = 0);
  const breathe = Math.sin(t * 1.6) * 0.012; E.torso.scale.set(1, 1 + breathe, 1);

  // walk in at dawn (only the first time; after the rewind he is already at the desk)
  const walk = easeInOut(span(t, DAWN + 0.1, BEFORE - 0.2));
  E.root.visible = t > DAWN;
  const at = V(deskPos.x, 0, deskPos.z - 1.05);
  E.root.position.set(lerp(at.x + 9, at.x, walk), 0, at.z);
  E.root.rotation.y = walk < 1 ? lerp(-Math.PI / 2, 0, easeInOut(span(walk, 0.75, 1))) : 0;
  if (walk > 0 && walk < 0.95) {
    const s = Math.sin(t * 10);
    E.legs[0].rotation.x = s * 0.45; E.legs[1].rotation.x = -s * 0.45;
    aL.sh.rotation.x = -s * 0.35; aR.sh.rotation.x = s * 0.35; E.hips.position.y = 0.92 + Math.abs(s) * 0.03;
    return;
  }
  const settle = easeInOut(span(t, BEFORE - 0.4, BEFORE + 0.4));
  if (!after) {
    // hunched over the desk; scrolls with one hand, rubs his forehead with the other; slumps as the morning goes
    const tired = clamp((tm - BEFORE) / (REWIND - BEFORE));
    E.torso.rotation.x = settle * (0.3 + tired * 0.12); E.head.rotation.x = settle * (0.22 + tired * 0.1);
    aR.sh.rotation.x = -0.9 * settle; aR.el.rotation.x = -0.5 * settle;
    const rub = Math.max(0, Math.sin((tm - BEFORE) * 1.1));
    aL.sh.rotation.x = -lerp(0.7, 2.0, rub) * settle; aL.sh.rotation.z = lerp(0.1, 0.35, rub) * settle;
    aL.el.rotation.x = -lerp(0.5, 2.1, rub) * settle;
    E.head.rotation.y = Math.sin(tm * 1.3) * 0.08 * settle;
  } else {
    // upright; taps the laptop, then coffee in hand with a sip every ~2.4 s
    const tap = 1 - easeInOut(span(t, AFTER + 0.4, AFTER + 1.0));
    const relax = easeInOut(span(t, AFTER + 0.6, AFTER + 1.4));
    E.mug.visible = relax > 0;
    aL.sh.rotation.x = -0.9 * tap; aL.el.rotation.x = -0.4 * tap;
    const ph = (t - AFTER - 1.4) % 2.4, sip = t > AFTER + 1.4 && ph < 1.1 ? Math.sin(span(ph, 0, 1.1) * Math.PI) : 0;
    aR.sh.rotation.x = -lerp(0.55, 1.15, sip) * relax - 0.9 * tap * (1 - relax);
    aR.sh.rotation.z = -lerp(0.08, 0.32, sip) * relax;
    aR.el.rotation.x = -lerp(1.15, 2.35, sip) * relax;
    E.head.rotation.x = lerp(0.05, -0.12, sip) * relax;
    E.head.rotation.y = -0.25 * easeInOut(span(t, AFTER + 1.2, AFTER + 2.0)) * (1 - span(t, AFTER + 5.0, AFTER + 6.0)); // glances at the bins filling up
    E.steam.forEach((s, i) => { const p = ((t * 0.7 + i / 2) % 1); s.position.set(Math.sin((t + i) * 3) * 0.03, 0.08 + p * 0.25, 0); s.material.opacity = (1 - p) * 0.7 * relax * (1 - sip); });
  }
}

function resize() {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  renderer.setSize(w, h, false); camera.aspect = w / h;
  camera.fov = w / h < 0.8 ? 64 : w / h < 1.2 ? 52 : 40; camera.updateProjectionMatrix();
}
addEventListener('resize', resize);

const params = new URLSearchParams(location.search);
const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
frozen = params.has('t') || reduce;
let start = performance.now();
window.__render = t => { frozen = true; render(t); };
$('replay').addEventListener('click', () => { start = performance.now(); capIdx = -1; if (reduce) render(LOOP); });

// Only draw while the hero is on screen, and stop once the story has ended.
let visible = true, running = false, lastT = -1;
function tick() {
  const t = Math.min(LOOP, (performance.now() - start) / 1000);
  if (!visible || (t >= LOOP && lastT >= LOOP)) { running = false; return; }
  render(t); lastT = t; requestAnimationFrame(tick);
}
function play() { if (!running && !frozen) { running = true; requestAnimationFrame(tick); } }
new IntersectionObserver(([e]) => { visible = e.isIntersecting; if (visible) play(); }).observe(canvas);
$('replay').addEventListener('click', () => { lastT = -1; play(); });
document.fonts.ready.then(() => {
  resize();
  if (params.has('t')) return render(parseFloat(params.get('t')));
  if (reduce) return render(LOOP);
  start = performance.now(); play();
});
})();
