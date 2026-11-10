// Accessibility smoke + screenshots of the built web against the real API (AT-062, redesigned for contract v0.5), driven over CDP.
//   node scripts/qa/web_smoke.mjs --url http://127.0.0.1:4173 --cdp 9444 --out <dir> [--prefix qa]
// Needs a running `make demo` (API in artifacts mode + built web) and a Chrome with --remote-debugging-port.
// For every territory x {Patrones, Resumen, Predicción, Explorar} (Patrones opens first: the rules are the focus) it records the page title and its one-sentence lead,
// the legends, the tables (the alternatives to the maps) with their row counts, the maps' accessible names, the states
// "no disponible todavía" (v0.5 payloads the backend has not published), the rendered text (for the wording audit)
// and a screenshot <out>/<prefix>-<territory>-<tab>.png. Explorar is visited in both views (Reglas, Datos);
// Predicción and Explorar are also keyboard-walked. Results go to <out>/web_smoke.json.
// The bare URL opens the landing page first: it is checked (its h1, the «Empezar la demo» button, the floating artifacts
// drawn from the API, a screenshot <out>/<prefix>-landing.png); the app is then opened with `?demo=1`, which skips it.
import { writeFileSync } from "node:fs";

const arg = (name, dflt) => { const i = process.argv.indexOf(`--${name}`); return i > 0 ? process.argv[i + 1] : dflt; };
const URL_ = arg("url", "http://127.0.0.1:4173");
const APP_URL = `${URL_}${URL_.includes("?") ? "&" : "?"}demo=1`;
const CDP = arg("cdp", "9444");
const OUT = arg("out", ".");
const PREFIX = arg("prefix", "qa");
// [short name, names the territory button may start with]: the API's own title wins over the web's Spanish fallback
const TERRITORIES = [["madrid", ["Madrid"]], ["germany", ["Alemania"]], ["nyc", ["Nueva York", "Taxis de Nueva York"]], ["water", ["Ríos"]]];
const TABS = [["patrones", "Patrones"], ["resumen", "Resumen"], ["prediccion", "Predicción"], ["rendimiento", "Informe de rendimiento"], ["explorar", "Explorar"]];

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
const key = (k, extra = {}) => send("Input.dispatchKeyEvent", { type: "keyDown", key: k, code: k, ...extra }).then(() => send("Input.dispatchKeyEvent", { type: "keyUp", key: k, code: k, ...extra }));
const clickBy = (sel, texts) => ev(`(()=>{const t=${JSON.stringify(texts)};const b=[...document.querySelectorAll(${JSON.stringify(sel)})].find(b=>t.some(x=>b.textContent.trim().startsWith(x)));if(b){b.click();return true}return false})()`);
const setRangeFraction = (f) => ev(`(()=>{const el=document.querySelector('input[type=range][aria-label="Hora de emisión"]');if(!el)return null;const lo=+el.min,hi=+el.max;const v=Math.round(lo+(hi-lo)*${f});const set=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;set.call(el,String(v));el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));return el.value})()`);

await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 1500, height: 1050, deviceScaleFactor: 1, mobile: false });
// The landing page (bare URL): one h1, the start button, the artifacts once the API answers.
await send("Page.navigate", { url: URL_ });
await until(`!!document.querySelector('#landing-title')`, 30000);
await until(`!!document.querySelector('[data-testid=landing-rule]')`, 30000);
await sleep(1000);
const landing = await ev(`(() => ({
  h1: [...document.querySelectorAll('h1')].map((h) => h.textContent.trim()),
  start: [...document.querySelectorAll('button')].some((b) => /^(Empezar la demo|Start the demo)$/.test(b.textContent.trim())),
  artifacts: [...document.querySelectorAll('[data-testid=landing-artifacts] figure')].map((f) => f.dataset.testid),
  overflowX: document.documentElement.scrollWidth > window.innerWidth + 1,
}))()`);
await shot(`${PREFIX}-landing`);
console.log(`landing: h1=${JSON.stringify(landing.h1)} start=${landing.start} artifacts=${JSON.stringify(landing.artifacts)} overflowX=${landing.overflowX}`);

await send("Page.navigate", { url: APP_URL });
await until(`!!document.querySelector('nav[aria-label="Territorio"] button')`, 30000);

const probe = `(() => {
  const q = (s) => [...document.querySelectorAll(s)];
  const txt = (el) => (el?.innerText ?? '').replace(/\\s+/g, ' ').trim();
  const name = (el) => (el.getAttribute('aria-label') || el.textContent || el.title || '').trim();
  const main = document.querySelector('main');
  const tabbable = (root) => root ? [...root.querySelectorAll('button,input,select,textarea,a[href],[tabindex]')].filter(e => !e.disabled && e.tabIndex >= 0 && e.offsetParent !== null) : [];
  const rail = document.querySelector('.rail');
  const tables = q('main table').map(t => ({ name: (t.querySelector('caption')?.textContent || t.getAttribute('aria-label') || '').trim(), rows: t.querySelectorAll('tbody tr').length }));
  return {
    title: document.querySelector('h1')?.textContent ?? null,
    lead: document.querySelector('[data-testid=page-lead]')?.textContent?.replace(/\\s+/g, ' ').trim() ?? null,
    mapTitle: document.querySelector('.map-title')?.textContent ?? null,
    mapRegions: q('.map[role=region]').map(m => m.getAttribute('aria-label')),
    tables,
    legends: q('section.legend').map(l => ({ label: l.getAttribute('aria-label'), text: txt(l).slice(0, 500) })),
    notYet: q('[data-testid=not-yet]').map(txt),
    horizon: txt(document.querySelector('[data-testid=horizon]')) || null,
    horizonSentence: txt(document.querySelector('[data-testid=horizon-sentence]')) || null,
    accuracySentence: txt(document.querySelector('[data-testid=accuracy-sentence]')) || null,
    perfBars: q('[data-testid=perf-bars] li').map((li) => li.dataset.key),
    reportLink: !!document.querySelector('[data-testid=report-link]'),
    // in the report the accuracy block sits inside the folded «Detalle técnico»: present, not visible
    accuracyBlock: !!document.querySelector('[data-testid=accuracy-sentence]'),
    ruleCards: q('li.rule-card').length,
    ruleSentences: q('[data-testid=rule-sentence]').slice(0, 3).map(txt),
    variableBars: q('ul.hbars li').length,
    rulesFirst: (() => { const r = document.querySelector('.patterns-main'), a = document.querySelector('.patterns-aside'); return r && a ? !!(r.compareDocumentPosition(a) & Node.DOCUMENT_POSITION_FOLLOWING) : null; })(),
    dataLine: document.querySelector('[data-testid=data-line]')?.textContent?.replace(/\\s+/g, ' ').trim() ?? null,
    dataStripHeight: document.querySelector('.data-strip')?.getBoundingClientRect().height ?? null,
    firstTab: document.querySelector('[role=tab]')?.textContent ?? null,
    charts: q('svg.group-chart').length,
    // text the redesign owns: nothing in it may be a raw identifier (snake_case) or a model/data version
    ownedText: ['.page-head', '.data-strip', '.data-line', '.horizon-box', '.accuracy', '.rule-cards', '.hbars', '#por-zonas', '.charts-title', '.charts'].map(s => q(s).map(txt).join(' ')).join(' '),
    attribution: document.querySelector('.map-attribution')?.textContent ?? null,
    footerAttribution: document.querySelector('[data-testid=attribution]')?.textContent ?? null,
    railTabbable: tabbable(rail).length, railUnnamed: tabbable(rail).filter(e => !name(e) && !e.labels?.length).length,
    unnamedMain: tabbable(main).filter(e => !name(e) && !e.labels?.length).length,
    tabsOk: q('[role=tab]').length === 5 && q('[role=tab][aria-selected=true]').length === 1,
    error: document.querySelector('.state--error')?.textContent ?? null,
    text: document.body.innerText,
  };
})()`;

const settle = async () => {
  await until(`!document.querySelector('.state--loading')`, 30000);
  await sleep(2500);
};

async function keyboardWalk(selector) {
  const kb = { distinct: 0, slider: null };
  await ev(`(()=>{const f=document.querySelector(${JSON.stringify(selector)});f&&f.focus();return !!f})()`);
  const seen = new Set();
  for (let i = 0; i < 6; i++) {
    await key("Tab", { windowsVirtualKeyCode: 9 });
    const active = await ev(`(()=>{const a=document.activeElement;return a?(a.tagName+':'+(a.getAttribute('aria-label')||a.textContent||'').trim().slice(0,40)):null})()`);
    if (active) seen.add(active);
  }
  kb.distinct = seen.size;
  const before = await ev(`document.querySelector('input[type=range][aria-label="Hora de emisión"]')?.value ?? null`);
  if (before !== null) {
    await ev(`document.querySelector('input[type=range][aria-label="Hora de emisión"]').focus()`);
    await key("PageDown", { windowsVirtualKeyCode: 34 });
    await sleep(400);
    kb.slider = { before, after: await ev(`document.querySelector('input[type=range][aria-label="Hora de emisión"]')?.value ?? null`) };
  }
  await ev(`document.activeElement&&document.activeElement.blur()`);
  return kb;
}

const results = { landing };
for (const [short, names] of TERRITORIES) {
  if (!(await clickBy(".territories button", names))) throw new Error(`no territory button for ${short}`);
  await sleep(1500);
  for (const [tabId, label] of TABS) {
    await clickBy("[role=tab]", [label]);
    // Explorar has two views (Reglas en el mapa, Datos observados); the others one
    const views = tabId === "explorar" ? [["rules", "Reglas en el mapa"], ["data", "Datos observados"]] : [[null, null]];
    for (const [view, viewLabel] of views) {
      if (viewLabel) await clickBy(".modes button", [viewLabel]);
      await settle();
      if (tabId === "prediccion" || tabId === "explorar") {
        await until(`!!document.querySelector('.map-title')`, 30000);
        await setRangeFraction(short === "madrid" ? 0.039 : 0.5); // Madrid: 2025-01-15 ~08:00 local
        await sleep(3500);
        await ev(`(()=>{const b=document.querySelector('table.stations tbody button');if(b){b.click();return true}return false})()`);
        await sleep(2500);
      }
      await ev(`document.querySelector('.rail')&&(document.querySelector('.rail').scrollTop=0);document.querySelector('main').scrollTop=0`);
      const r = await ev(probe);
      const shotName = `${PREFIX}-${short}-${tabId}${view ? "-" + view : ""}`;
      await shot(shotName);
      const { text, ...rest } = r ?? {};
      writeFileSync(`${OUT}/${shotName}.txt`, text ?? "");
      const kb = tabId === "prediccion" || tabId === "explorar" ? await keyboardWalk(".rail button, .rail input, .rail [tabindex]") : null;
      results[tabId === "explorar" ? `${short}-explorar-${view}` : `${short}-${tabId}`] = { ...rest, view, keyboard: kb };
      console.log(`${short}/${tabId}${view ? "/" + view : ""}: h1=${JSON.stringify(rest.title)} legends=${rest.legends?.length} tables=${JSON.stringify(rest.tables?.map((t) => t.rows))} notYet=${rest.notYet?.length} err=${rest.error}`);
    }
  }
}
writeFileSync(`${OUT}/web_smoke.json`, JSON.stringify(results, null, 2));
ws.close();
await fetch(`http://127.0.0.1:${CDP}/json/close/${tab.id}`).catch(() => {});
process.exit(0);
