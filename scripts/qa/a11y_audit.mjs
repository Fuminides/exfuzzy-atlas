// Accessibility audit of the built web against the real API, driven over CDP (the manual list of docs/qa/README.md).
//   node scripts/qa/a11y_audit.mjs --url http://127.0.0.1:4173 --cdp 9444 --out <dir>
// Needs a running `make demo` and a Chrome with --remote-debugging-port. For every territory x section it records:
//   - text contrast (WCAG 1.4.3): each visible element with its own text, its colour against the first opaque
//     background behind it (text over the map canvas is skipped); 4.5:1, or 3:1 for large text;
//   - the accessibility tree (Chrome's, what a screen reader reads): interactive nodes without a name, heading levels
//     that skip one, the map regions and their names;
//   - keyboard: Enter and Space on a button of the station table select that entity (Explorar);
//   - 200 % zoom (a 750 x 525 CSS px viewport at device scale 2) and a 390 px phone: horizontal overflow, and whether
//     the time slider and the side column are on screen and reachable with Tab. Screenshots <out>/a11y-*.png.
// The landing page (the bare URL) gets the same contrast and accessibility-tree checks, at 1500 px and on a 390 px phone
// (horizontal overflow too); the app is then opened with `?demo=1`, which skips the landing.
// It does not replace a person with a real screen reader. Results go to <out>/a11y_audit.json.
import { writeFileSync } from "node:fs";

const arg = (name, dflt) => { const i = process.argv.indexOf(`--${name}`); return i > 0 ? process.argv[i + 1] : dflt; };
const URL_ = arg("url", "http://127.0.0.1:4173");
const APP_URL = `${URL_}${URL_.includes("?") ? "&" : "?"}demo=1`;
const CDP = arg("cdp", "9444");
const OUT = arg("out", ".");
const TERRITORIES = [["madrid", ["Madrid"]], ["germany", ["Alemania"]], ["nyc", ["Nueva York", "Taxis de Nueva York"]], ["water", ["Ríos"]]];
const TABS = [["patrones", "Patrones"], ["resumen", "Resumen"], ["prediccion", "Predicción"], ["rendimiento", "Informe de rendimiento"], ["explorar", "Explorar"]];
const SLIDER = 'input[type=range][aria-label="Hora de emisión"]';

const tab = await (await fetch(`http://127.0.0.1:${CDP}/json/new?about:blank`, { method: "PUT" })).json();
const ws = new WebSocket(tab.webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
let id = 0; const pending = new Map();
ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) pending.get(d.id)(d); };
const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async (expr) => (await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true })).result?.result?.value;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const until = async (expr, ms = 20000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await ev(expr)) return true; await sleep(250); } return false; };
const shot = async (name) => { const r = await send("Page.captureScreenshot", { format: "png" }); writeFileSync(`${OUT}/${name}.png`, Buffer.from(r.result.data, "base64")); };
const key = (k, code = k, text) => send("Input.dispatchKeyEvent", { type: "keyDown", key: k, code, ...(text ? { text } : {}) }).then(() => send("Input.dispatchKeyEvent", { type: "keyUp", key: k, code }));
const clickBy = (sel, texts) => ev(`(()=>{const t=${JSON.stringify(texts)};const b=[...document.querySelectorAll(${JSON.stringify(sel)})].find(b=>t.some(x=>b.textContent.trim().startsWith(x)));if(b){b.click();return true}return false})()`);
const settle = async () => { await until(`!document.querySelector('.state--loading')`, 30000); await sleep(2000); };
const viewport = (width, height, deviceScaleFactor = 1, mobile = false) =>
  send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor, mobile });

// ---- text contrast, in the page
const contrastProbe = `(() => {
  const parse = (s) => { const m = s.match(/rgba?\\(([^)]+)\\)/); if (!m) return null; const p = m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const blend = (top, under) => ({ r: top.r * top.a + under.r * (1 - top.a), g: top.g * top.a + under.g * (1 - top.a), b: top.b * top.a + under.b * (1 - top.a), a: 1 });
  const hex = (c) => '#' + [c.r, c.g, c.b].map((v) => Math.round(v).toString(16).padStart(2, '0')).join('');
  const out = []; let checked = 0, overMap = 0, disabled = 0;
  const els = [...document.querySelectorAll('body *')].filter((el) => [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()));
  for (const el of els) {
    const cs = getComputedStyle(el); const rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0 || cs.visibility !== 'visible' || +cs.opacity === 0) continue;
    if (el.closest('[aria-hidden=true], .sr-only, .visually-hidden')) continue;
    // WCAG 1.4.3 exempts inactive controls (a disabled "−1 d" at the start of the range)
    if (el.closest(':disabled, [aria-disabled=true]')) { disabled++; continue; }
    // the backgrounds behind the text, nearest first, until an opaque one; the map canvas ends the walk
    const layers = []; let node = el, map = false;
    while (node && node.nodeType === 1) {
      if (node.classList.contains('maplibregl-map') || node.tagName === 'CANVAS') { map = true; break; }
      const bg = parse(getComputedStyle(node).backgroundColor);
      if (bg && bg.a > 0) { layers.push(bg); if (bg.a >= 1) break; }
      node = node.parentElement;
    }
    if (map && !(layers.length && layers[layers.length - 1].a >= 1)) { overMap++; continue; }
    let bg = { r: 255, g: 255, b: 255, a: 1 };
    for (const l of layers.reverse()) bg = blend(l, bg);
    const fg0 = parse(cs.color); if (!fg0) continue;
    const fg = blend({ ...fg0, a: fg0.a * +cs.opacity }, bg);
    const [hi, lo] = [lum(fg), lum(bg)].sort((a, b) => b - a);
    const ratio = (hi + 0.05) / (lo + 0.05);
    const size = parseFloat(cs.fontSize), bold = +cs.fontWeight >= 700;
    const large = size >= 24 || (size >= 18.66 && bold);
    const need = large ? 3 : 4.5; checked++;
    if (ratio < need) {
      const text = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join(' ').replace(/\\s+/g, ' ').trim().slice(0, 60);
      out.push({ ratio: Math.round(ratio * 100) / 100, need, fg: hex(fg), bg: hex(bg), size, cls: el.className && typeof el.className === 'string' ? el.className.split(' ')[0] : el.tagName.toLowerCase(), text });
    }
  }
  return { checked, overMap, disabled, failures: out };
})()`;

// ---- accessibility tree (what assistive technology gets)
const INTERACTIVE = new Set(["button", "link", "checkbox", "radio", "slider", "combobox", "textbox", "tab", "searchbox", "switch", "menuitem", "spinbutton", "listbox"]);
async function axAudit() {
  const { result } = await send("Accessibility.getFullAXTree");
  const nodes = result?.nodes ?? [];
  const live = nodes.filter((n) => !n.ignored);
  const role = (n) => n.role?.value;
  const name = (n) => (n.name?.value ?? "").trim();
  const unnamed = live.filter((n) => INTERACTIVE.has(role(n)) && !name(n)).map((n) => role(n));
  const headings = live.filter((n) => role(n) === "heading").map((n) => ({ level: +(n.properties?.find((p) => p.name === "level")?.value?.value ?? 0), name: name(n).slice(0, 60) }));
  const skips = [];
  for (let i = 1; i < headings.length; i++) if (headings[i].level > headings[i - 1].level + 1) skips.push(`${headings[i - 1].level}→${headings[i].level} «${headings[i].name}»`);
  const regions = live.filter((n) => role(n) === "region").map(name);
  const landmarks = [...new Set(live.map(role).filter((r) => ["main", "navigation", "banner", "contentinfo", "complementary"].includes(r)))];
  return { interactive: live.filter((n) => INTERACTIVE.has(role(n))).length, unnamed, headings: headings.map((h) => `h${h.level} ${h.name}`), skips, regions, landmarks };
}

// ---- layout under zoom / phone width
const layoutProbe = `(() => {
  const vw = window.innerWidth;
  const r = (s) => { const el = document.querySelector(s); if (!el) return null; const b = el.getBoundingClientRect(); return { left: Math.round(b.left), right: Math.round(b.right), width: Math.round(b.width), visible: b.width > 0 && b.height > 0 && getComputedStyle(el).visibility === 'visible' }; };
  const wide = [...document.querySelectorAll('body *')].filter((el) => { const b = el.getBoundingClientRect(); return b.width > 0 && b.right > vw + 1 && getComputedStyle(el).position !== 'fixed'; })
    .filter((el) => !el.closest('.table-scroll, [data-scroll], .maplibregl-map, .lp-arts') && getComputedStyle(el.parentElement || el).overflowX === 'visible')
    .slice(0, 5).map((el) => (el.className && typeof el.className === 'string' ? '.' + el.className.split(' ')[0] : el.tagName.toLowerCase()) + ' ' + Math.round(el.getBoundingClientRect().right));
  // the landing's artifacts bleed off the edges on purpose (clipped by the hero, never scrolled to)
  return { vw, scrollWidth: document.documentElement.scrollWidth, overflowX: document.documentElement.scrollWidth > vw + 1, wide, slider: r(${JSON.stringify(SLIDER)}), rail: r('.rail') };
})()`;
async function tabReaches(selector, max = 120) {
  await ev(`document.activeElement && document.activeElement.blur(); window.scrollTo(0, 0)`);
  for (let i = 1; i <= max; i++) {
    await key("Tab", "Tab");
    if (await ev(`!!document.activeElement && document.activeElement.matches(${JSON.stringify(selector)})`)) return i;
  }
  return null;
}

await send("Page.enable");
await send("Accessibility.enable");
const results = { contrast: {}, ax: {}, keyboard: {}, layout: {} };

// The landing page, desktop and phone: text contrast, the accessibility tree (one h1, no unnamed control), overflow.
for (const [mode, vp] of [["desktop", [1500, 1050]], ["phone390", [390, 844, 3, true]]]) {
  await viewport(...vp);
  await send("Page.navigate", { url: URL_ });
  await until(`!!document.querySelector('#landing-title')`, 30000);
  await until(`!!document.querySelector('[data-testid=landing-rule]')`, 30000);
  await sleep(1200);
  results.contrast[`landing-${mode}`] = await ev(contrastProbe);
  results.ax[`landing-${mode}`] = await axAudit();
  results.layout[`landing-${mode}`] = await ev(layoutProbe);
  await shot(`a11y-landing-${mode}`);
}

await viewport(1500, 1050);
await send("Page.navigate", { url: APP_URL });
await until(`!!document.querySelector('nav[aria-label="Territorio"] button')`, 30000);
for (const [short, names] of TERRITORIES) {
  if (!(await clickBy('nav[aria-label="Territorio"] button', names))) { results.contrast[short] = { error: "territory not found" }; continue; }
  await settle();
  for (const [tabId, label] of TABS) {
    await clickBy("[role=tab]", [label]); await settle();
    const views = tabId === "explorar" ? [["rules", "Reglas en el mapa"], ["data", "Datos observados"]] : [[null, null]];
    for (const [view, viewLabel] of views) {
      if (viewLabel) { await clickBy("button", [viewLabel]); await settle(); }
      const k = view ? `${short}-${tabId}-${view}` : `${short}-${tabId}`;
      results.contrast[k] = await ev(contrastProbe);
      results.ax[k] = await axAudit();
      if (tabId === "explorar" && view === "rules") {
        const ids = await ev(`[...document.querySelectorAll('tr[data-entity] button')].slice(0, 2).map((b) => b.closest('tr').dataset.entity)`);
        const kb = {};
        for (const [i, [keyName, code, text]] of [["Enter", "Enter", "\r"], [" ", "Space", " "]].entries()) {
          const e = ids?.[i]; if (!e) continue;
          await ev(`document.querySelector('tr[data-entity="${e}"] button').focus()`);
          await key(keyName, code, text); await sleep(600);
          kb[code] = await ev(`document.querySelector('tr[data-entity="${e}"] button')?.getAttribute('aria-pressed') === 'true'`);
        }
        results.keyboard[short] = kb;
      }
    }
  }
  // zoom 200 % and phone width, on Predicción and Explorar (the sections with the time slider)
  for (const [mode, vp] of [["zoom200", [750, 525, 2, false]], ["phone390", [390, 844, 3, true]]]) {
    await viewport(...vp); await sleep(800);
    for (const [tabId, label] of [["prediccion", "Predicción"], ["explorar", "Explorar"]]) {
      await clickBy("[role=tab]", [label]); await settle();
      const lay = await ev(layoutProbe);
      lay.sliderTabStops = lay.slider ? await tabReaches(SLIDER) : null;
      results.layout[`${short}-${tabId}-${mode}`] = lay;
      if (short === "madrid" || short === "nyc") { await ev("window.scrollTo(0, 0)"); await shot(`a11y-${short}-${tabId}-${mode}`); }
    }
    await viewport(1500, 1050); await sleep(500);
  }
}
writeFileSync(`${OUT}/a11y_audit.json`, JSON.stringify(results, null, 2));
const nFail = Object.values(results.contrast).reduce((s, c) => s + (c.failures?.length ?? 0), 0);
console.log(`contrast failures: ${nFail}; unnamed interactive: ${Object.values(results.ax).reduce((s, a) => s + a.unnamed.length, 0)}; keyboard: ${JSON.stringify(results.keyboard)}`);
process.exit(0);
