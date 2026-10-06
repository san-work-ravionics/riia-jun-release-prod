// F42 P6 QA node harness (independent of the Engineer's f42_p6_harness.mjs).
// Reads fixtures.json (synthetic payloads, built in Python) and inputs.json (sweep inputs); prints ONE JSON line.
import fs from 'node:fs';
const FX = JSON.parse(fs.readFileSync('./fixtures.json', 'utf8'));
const IN = JSON.parse(fs.readFileSync('./inputs.json', 'utf8'));
const g = globalThis.__t = { els: {}, charts: {}, chartCalls: [], filters: { underlying: 'ALL', month: '' }, run: 0, fail: new Set(),
  delay: {}, payloads: null, payloadsByRun: null, writes: 0, calls: [] };
globalThis.document = { getElementById: () => ({ style: {}, checked: false, value: '' }) };
globalThis.Chart = function () {};
const T = await import('./js/fno/trade-analytics.js');
const out = {};
const el = id => g.els[id] || '';
const clone = o => JSON.parse(JSON.stringify(o));
const base = () => clone(FX.ok);
const reset = () => { g.els = {}; g.charts = {}; g.chartCalls = []; g.writes = 0; };
const load = async (payloads, run = 1) => { g.payloads = payloads; g.run = run; await T.loadAnalyticsPanels(); };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const strip = (a, b) => b;

// ── 1. ISO-week axis sweeps ──────────────────────────────────────────────────────────────
out.axes = IN.weekSets.map(s => ({ name: s.name, rows: s.rows.length,
  axis: T.taWeekAxis(s.rows.map(k => ({ week: k[0], fills: k[1], closed_trades: k[2], active_days: k[3] }))).map(a => ({
    key: a.key, y: a.monday.y, m: a.monday.m, d: a.monday.d, month: a.month, wk: a.wk, monthly: a.monthly, label: a.label, title: a.title,
    fills: a.fills, closed: a.closed, active_days: a.active_days })) }));
out.mondays = IN.allWeeks.map(k => { const m = T.taIsoWeekMonday(k); return [k, m && [m.y, m.m, m.d]]; });
out.mondayBad = ['', '2026-W', '2026W05', 'abc', null, undefined, 20260105, '2026-W5'].map(k => { try { return T.taIsoWeekMonday(k); } catch (e) { return 'THROW'; } });

// ── 2. formatter sweep ────────────────────────────────────────────────────────────────────
out.fmt = IN.fmtValues.map(v => { const x = v === '__NaN__' ? NaN : v === '__Inf__' ? Infinity : v === '__-Inf__' ? -Infinity : v;
  return [v, T._numShort(x), T._pnlShort(x), T._pctShort(x), T._ratioShort(x)]; });

// ── 3. weekly chart position-indexed data via the real renderer ─────────────────────────────
{ const p = base(); p.overtrading.weekly = IN.chartWeeks.map(k => ({ week: k[0], fills: k[1], closed_trades: k[2], active_days: k[3] }));
  await load(p); const c = g.charts['ta-cv-weekly'];
  out.chart = { labels: c.data.labels, fills: c.data.datasets[0].data, closed: c.data.datasets[1].data, groups: c.options.plugins.taMonthBands.groups,
    titles: c.data.labels.map((_, i) => c.options.plugins.tooltip.callbacks.title([{ dataIndex: i }])),
    after: c.data.labels.map((_, i) => c.options.plugins.tooltip.callbacks.afterBody([{ dataIndex: i }])[0]),
    ticksAutoSkip: c.options.scales.x.ticks.autoSkip, hasPlugin: (c.plugins || []).map(x => x.id) }; }

// ── 4. leaf fuzz: every string leaf of the payload replaced by markup payloads ─────────────────
const PAYLOADS = ['<img src=x onerror=alert(1)>', '"><img src=x onerror=alert(2)>', "' onmouseover='alert(3)", '" onmouseover="alert(4)', '</td></tr></table><img src=x onerror=alert(5)>'];
const leaves = [];
const walk = (o, path) => { if (o && typeof o === 'object') for (const k of Object.keys(o)) walk(o[k], path.concat([k])); else if (typeof o === 'string') leaves.push(path); };
walk(base(), []);
const setPath = (o, path, v) => { let t = o; for (let i = 0; i < path.length - 1; i++) t = t[path[i]]; t[path[path.length - 1]] = v; };
const grabAll = async (p, run) => {
  await load(p, run);
  const parts = {};
  const snap = tag => { for (const [k, v] of Object.entries(g.els)) parts[tag + ':' + k] = v; };
  snap('base');
  T.taAnFullToggle(true); T.taAnSgExpandAll(); T.taAnDetailBToggle(); snap('open');
  for (let i = 0; i < 3; i++) { T.taAnChainPick(i); snap('pick' + i); }
  T.taAnDetailBToggle(); T.taAnFullToggle(false); T.taAnSgCollapseAll();
  return parts;
};
const tokenise = html => {   // quote-aware tag/attribute tokeniser: [{tag, attrs:[[name,value]]}]
  const tags = []; const re = /<([a-zA-Z][a-zA-Z0-9]*)/g; let m;
  while ((m = re.exec(html))) {
    let i = re.lastIndex; const attrs = [];
    for (;;) {
      while (i < html.length && /\s/.test(html[i])) i++;
      if (i >= html.length || html[i] === '>') break;
      if (html[i] === '/') { i++; continue; }
      let j = i; while (j < html.length && !/[\s=\/>]/.test(html[j])) j++;
      const name = html.slice(i, j); i = j; let val = null;
      if (html[i] === '=') { i++; if (html[i] === '"' || html[i] === "'") { const q = html[i]; const e = html.indexOf(q, i + 1); val = html.slice(i + 1, e < 0 ? html.length : e); i = e < 0 ? html.length : e + 1; }
        else { j = i; while (j < html.length && !/[\s>]/.test(html[j])) j++; val = html.slice(i, j); i = j; } }
      if (name) attrs.push([name, val]);
    }
    tags.push({ tag: m[1].toLowerCase(), attrs }); re.lastIndex = Math.max(re.lastIndex, i);
  }
  return tags;
};
const baseTags = new Set(), baseAttrs = new Set();
{ const parts = await grabAll(base(), 99); Object.values(parts).forEach(h => tokenise(h).forEach(t => { baseTags.add(t.tag); t.attrs.forEach(a => baseAttrs.add(a[0])); })); }
out.baseTags = [...baseTags].sort(); out.baseAttrs = [...baseAttrs].sort();
const okHandler = (n, v) => (n === 'onclick' && /^taAn\w+\(\d*\)$/.test(v || '')) || (n === 'ontoggle' && v === 'taAnSgToggle(this)');
const offenders = html => { const bad = [];
  tokenise(html).forEach(t => { if (!baseTags.has(t.tag)) bad.push('tag:' + t.tag);
    t.attrs.forEach(([n, v]) => { if (!baseAttrs.has(n)) bad.push('attr:' + n); if (/^on/.test(n) && !okHandler(n, v)) bad.push('handler:' + n + '=' + v); }); });
  return bad; };
out.canary = { img: offenders('<td><img src=x onerror=alert(1)></td>'), handler: offenders('<span onmouseover="x()">a</span>'), attr: offenders('<td onclick="evil()">a</td>'), clean: offenders('<td onclick="taAnChainPick(1)">a</td>'), quoteBreak: offenders('<span title="a" onerror="x">') };
out.fuzz = { leaves: leaves.map(l => l.join('.')), offenders: [], threw: [] };
let run = 100;
for (const path of leaves) {
  for (const pl of PAYLOADS) {
    const p = base(); setPath(p, path, pl);
    let parts;
    try { parts = await grabAll(p, run++); } catch (e) { out.fuzz.threw.push({ path: path.join('.'), pl, err: String(e) }); continue; }
    const bad = []; Object.entries(parts).forEach(([k, h]) => offenders(h).forEach(o => bad.push(k + ' ' + o)));
    if (bad.length) out.fuzz.offenders.push({ path: path.join('.'), pl, bad: bad.slice(0, 5) });
  }
}

// ── 5. missing-field robustness: delete every leaf (any type) one at a time ────────────────────
const allPaths = [];
const walk2 = (o, path, depth) => { if (Array.isArray(o)) { if (o.length && o[0] && typeof o[0] === 'object') walk2(o[0], path.concat([0]), depth + 1); return; }
  if (o && typeof o === 'object') for (const k of Object.keys(o)) { allPaths.push(path.concat([k])); if (depth < 5) walk2(o[k], path.concat([k]), depth + 1); } };
['overtrading', 'buildup', 'margintrap', 'suggestions'].forEach(k => { allPaths.push([k]); walk2(base()[k], [k], 0); });
out.missing = [];
for (const path of allPaths) {
  const p = base(); let t = p; for (let i = 0; i < path.length - 1; i++) t = t[path[i]]; delete t[path[path.length - 1]];
  reset(); await load(p, run++);
  const bodies = {}; ['overtrading', 'buildup', 'margintrap', 'suggestions'].forEach(k => { bodies[k] = el(`ta-an-${k}-body`); });
  out.missing.push({ path: path.join('.'), failed: Object.entries(bodies).filter(([k, v]) => /could not be loaded/.test(v)).map(([k]) => k), status: el('ta-an-status') });
}

// ── 6. null-valued numeric fields ───────────────────────────────────────────────────────────────
out.nulls = [];
{ const numLeaves = []; const walk3 = (o, path) => { if (o && typeof o === 'object') for (const k of Object.keys(o)) walk3(o[k], path.concat([k])); else if (typeof o === 'number') numLeaves.push(path); };
  walk3(base(), []);
  for (const path of numLeaves) { const p = base(); setPath(p, path, null); reset(); await load(p, run++);
    const failed = ['overtrading', 'buildup', 'margintrap', 'suggestions'].filter(k => /could not be loaded/.test(el(`ta-an-${k}-body`)));
    const txt = Object.values(g.els).join(' ');
    out.nulls.push({ path: path.join('.'), failed, nan: /NaN|undefined|Infinity/.test(txt) ? (txt.match(/.{20}(NaN|undefined|Infinity).{10}/) || [''])[0] : '' }); } }

// ── 7. failure matrix, cache lifecycle and stale responses ────────────────────────────────────────
reset(); await load(base(), run++);
out.okA = el('ta-an-detail-a'); out.okB = el('ta-an-detail-b');
g.fail = new Set(['overtrading', 'buildup', 'margin-trap', 'suggestions', 'foundation', 'market-turn']);
await load(base(), run++);
out.allFail = { A: el('ta-an-detail-a'), B: el('ta-an-detail-b'), grid: el('ta-an-sg-grid'), sum: el('ta-an-sg-summary'), status: el('ta-an-status'),
  charts: Object.keys(g.charts), head: el('ta-an-overtrading-headline') + el('ta-an-buildup-headline') + el('ta-an-margintrap-headline') + el('ta-an-suggestions-headline'),
  chain: el('ta-bu-chain-sel') };
g.fail = new Set();
// each single failure leaves the others rendering
out.single = {};
for (const ep of ['overtrading', 'buildup', 'margin-trap', 'suggestions']) {
  g.fail = new Set([ep]); reset(); await load(base(), run++);
  out.single[ep] = { A: el('ta-an-detail-a'), B: el('ta-an-detail-b'), grid: el('ta-an-sg-grid'), sum: el('ta-an-sg-summary'), status: el('ta-an-status'),
    bodies: Object.fromEntries(['overtrading', 'buildup', 'margintrap', 'suggestions'].map(k => [k, el(`ta-an-${k}-body`)])), charts: Object.keys(g.charts),
    sgDef: el('ta-an-suggestions-def'), mtDef: el('ta-an-margintrap-def') };
  g.fail = new Set();
}
// out-of-order: run 1 slow (111 fills), run 2 fast (222)
{ reset(); const slow = base(), fast = base(); slow.overtrading.activity.fills_total = 111; slow.overtrading.by_underlying[0].key = 'SLOWSYM'; fast.overtrading.activity.fills_total = 222;
  g.delay = { 7001: 80 }; g.payloadsByRun = { 7001: slow, 7002: fast };
  g.run = 7001; const p1 = T.loadAnalyticsPanels();
  g.run = 7002; const p2 = T.loadAnalyticsPanels();
  await p2; const w2 = g.writes; const snap = { head: el('ta-an-overtrading-headline'), A: el('ta-an-detail-a'), B: el('ta-an-detail-b') };
  await p1; await sleep(20);
  out.stale = { snap, after: { head: el('ta-an-overtrading-headline'), A: el('ta-an-detail-a'), B: el('ta-an-detail-b') }, writesAtFast: w2, writesAfter: g.writes };
  g.delay = {}; g.payloadsByRun = null; }
// three overlapping loads, the middle finishing last
{ reset(); const a = base(), b = base(), c = base(); a.overtrading.activity.fills_total = 101; b.overtrading.activity.fills_total = 202; c.overtrading.activity.fills_total = 303;
  g.delay = { 7101: 10, 7102: 90, 7103: 40 }; g.payloadsByRun = { 7101: a, 7102: b, 7103: c };
  const ps = []; for (const r of [7101, 7102, 7103]) { g.run = r; ps.push(T.loadAnalyticsPanels()); }
  await Promise.all(ps); await sleep(20);
  out.stale3 = { head: el('ta-an-overtrading-headline'), A: el('ta-an-detail-a') }; g.delay = {}; g.payloadsByRun = null; }
// stale load must not repopulate cache: new load fails everything quickly while an older success lands late
{ reset(); const slow = base(); g.delay = { 7201: 80 }; g.payloadsByRun = { 7201: slow, 7202: base() };
  g.run = 7201; const p1 = T.loadAnalyticsPanels(); g.fail = new Set(['overtrading', 'buildup', 'margin-trap', 'suggestions', 'foundation', 'market-turn']);
  g.run = 7202; const p2 = T.loadAnalyticsPanels(); await p2; g.fail = new Set(); await p1; await sleep(20);
  out.staleAfterFail = { A: el('ta-an-detail-a'), B: el('ta-an-detail-b'), body: el('ta-an-overtrading-body'), grid: el('ta-an-sg-grid') }; g.delay = {}; g.payloadsByRun = null; }

// ── 8. open-state Set vs scope changes ─────────────────────────────────────────────────────────────
const opens = () => [...el('ta-an-sg-grid').matchAll(/data-rule="([^"]*)" open/g)].map(m => m[1]);
out.scope = {};
{ reset(); g.filters = { underlying: 'ALL', month: '' }; await load(base(), run++);
  T.taAnSgToggle({ dataset: { rule: 'max_trades_per_day' }, open: true }); T.taAnSgToggle({ dataset: { rule: 'bias_limit' }, open: true });
  await load(base(), run++); out.scope.same = opens();
  g.filters = { underlying: 'NIFTY', month: '' }; await load(base(), run++); out.scope.underlying = opens();
  T.taAnSgToggle({ dataset: { rule: 'max_trades_per_day' }, open: true }); await load(base(), run++); out.scope.sameAfterUnderlying = opens();
  g.filters = { underlying: 'NIFTY', month: '2026-09' }; await load(base(), run++); out.scope.month = opens();
  T.taAnSgToggle({ dataset: { rule: 'max_trades_per_day' }, open: true });
  await T.taAnFromChanged('2026-07-15'); out.scope.from = opens();
  T.taAnSgToggle({ dataset: { rule: 'max_trades_per_day' }, open: true });
  await T.taAnToggleEstimate(false); out.scope.estimate = opens();
  T.taAnSgToggle({ dataset: { rule: 'max_trades_per_day' }, open: true });
  await T.taAnToggleEstimate(false); out.scope.estimateSame = opens();
  T.taAnSgExpandAll(); out.scope.expanded = opens().length;
  await load(base(), run++); out.scope.expandedAfterReload = opens().length;
  T.taAnSgToggle({ dataset: { rule: 'bias_limit' }, open: false }); await load(base(), run++); out.scope.afterClose = opens().length;
  T.taAnSgCollapseAll(); out.scope.collapsed = opens().length;
  T.taAnSgExpandAll(); g.filters = { underlying: 'BANKNIFTY', month: '2026-09' }; await load(base(), run++); out.scope.expandedThenScope = opens().length;
  g.filters = { underlying: 'ALL', month: '' }; await T.taAnFromChanged(''); await T.taAnToggleEstimate(true);
  out.scope.nRules = (el('ta-an-sg-grid').match(/data-rule=/g) || []).length;
  // suggestions unavailable at the moment of a scope change, then available again
  T.taAnSgExpandAll(); const un = base(); un.suggestions = { available: false, reason: 'no_data', disclaimer: '' }; g.filters = { underlying: 'NIFTY', month: '' };
  await load(un, run++); await load(base(), run++); out.scope.afterUnavailableGap = opens().length; g.filters = { underlying: 'ALL', month: '' }; }

// ── 9. details tables, legacy tables ──────────────────────────────────────────────────────────────────
reset(); g.filters = { underlying: 'ALL', month: '' }; await load(base(), run++);
T.taAnFullToggle(true); out.fullHtml = el('ta-an-fulltables-body');
out.defs = { mt: el('ta-an-margintrap-def'), sg: el('ta-an-suggestions-def'), mtBody: el('ta-an-margintrap-body'), mtHead: el('ta-an-margintrap-headline') };
T.taAnDetailBToggle(); out.bAll = el('ta-an-detail-b'); T.taAnDetailBToggle(); out.bTop = el('ta-an-detail-b');
out.bAllStateAfter = el('ta-an-detail-b');
// scenario: null P&L variants in Table B
{ const p = base();
  p.overtrading.bursts.top[1].pnl = null;                    // measured burst with null P&L -> kept as dash
  p.buildup.chains[3].pnl_measured = null;                    // measured position with null P&L (defensive) -> kept as dash
  p.margintrap.trap.days_list[1].known_loss_est = null;       // estimated low-cash day with null P&L -> dropped
  reset(); await load(p, run++); T.taAnDetailBToggle(); out.bNull = el('ta-an-detail-b'); T.taAnDetailBToggle(); }
// scenario: ties in P&L order by date
{ const p = base(); p.overtrading.bursts.top.forEach((b, i) => { b.pnl = -1000; b.date = `2026-08-${String(20 - i).padStart(2, '0')}`; });
  p.buildup.chains = []; p.buildup.chain_totals = { count: 0, with_adverse_add: 0, max_adds: 0 }; p.margintrap.trap.days_list = [];
  reset(); await load(p, run++); out.bTie = el('ta-an-detail-b'); }
// sources entirely sparse
{ const p = base(); p.overtrading.bursts = { available: false, reason: 'no_timestamps' }; p.buildup.chains = []; p.margintrap.trap.days_list = [];
  reset(); await load(p, run++); out.bEmpty = el('ta-an-detail-b'); out.aEmpty = el('ta-an-detail-a'); }

// ── 10. tab independence and no Behaviour DOM needed ────────────────────────────────────────────────────
g.filters = { underlying: 'ALL', month: '' }; reset(); await load(base(), run++);
out.noTab = { grid: el('ta-an-sg-grid'), sum: el('ta-an-sg-summary'), stops: /Planned vs actual/.test(el('ta-an-sg-grid')) };
// the Behaviour panels' DOM ids are absent: nothing read from the document by Suggestions
{ globalThis.document = { getElementById: () => null }; reset(); await load(base(), run++); out.noDom = { grid: el('ta-an-sg-grid').length, a: el('ta-an-detail-a').length };
  globalThis.document = { getElementById: () => ({ style: {}, checked: false, value: '' }) }; }

// ── 11. whole-render text for the wording scan ──────────────────────────────────────────────────────────────
reset(); await load(base(), run++); T.taAnFullToggle(true); T.taAnSgExpandAll(); T.taAnDetailBToggle();
out.allText = Object.fromEntries(Object.entries(g.els));
T.taAnFullToggle(false);
{ const c = g.charts; out.chartStrings = JSON.stringify(Object.fromEntries(Object.entries(c).map(([k, v]) => [k, { labels: v.data.labels, ds: v.data.datasets.map(d => d.label) }]))); }

// ── 12. extreme / odd data renders ───────────────────────────────────────────────────────────────────────────
out.odd = {};
{ const p = base(); p.margintrap.cash_series = []; reset(); await load(p, run++); out.odd.noSeries = { chart: !!g.charts['ta-cv-cash'], body: el('ta-an-margintrap-body').length > 0, status: el('ta-an-status') }; }
{ const p = base(); p.overtrading.weekly = [{ week: '2026-W30', fills: 3, closed_trades: 1, active_days: 1 }]; reset(); await load(p, run++); const c = g.charts['ta-cv-weekly']; out.odd.oneWeek = { n: c.data.labels.length, label: c.data.labels[0] }; }
{ const p = base(); p.overtrading.weekly = [{ week: 'garbage', fills: 3 }]; reset(); await load(p, run++); out.odd.badWeek = { chart: !!g.charts['ta-cv-weekly'], body: el('ta-an-overtrading-body').length }; }
{ const p = base(); p.buildup.chains.forEach(c => { c.steps = c.steps.map(s => ({ ...s, lots_after: null })); }); reset(); await load(p, run++); const c = g.charts['ta-cv-buildup']; out.odd.unitsLadder = { label: c.data.datasets[0].label, sizes: c.data.datasets[0].data }; }
{ const p = base(); p.buildup.chains[0].steps = p.buildup.chains[0].steps.slice(0, 1); reset(); await load(p, run++); const c = g.charts['ta-cv-buildup']; out.odd.oneStep = { n: c.data.labels.length, ds: c.data.datasets.length }; }

// ── 13. unavailable / empty / malformed payloads ───────────────────────────────────────────────────────────────────
out.unavail = {};
{ const p = base(); ['overtrading', 'buildup', 'margintrap', 'suggestions'].forEach(k => { p[k] = { available: false, reason: 'no_data', quality: {} }; });
  reset(); await load(p, run++);
  out.unavail.all = { heads: ['overtrading', 'buildup', 'margintrap', 'suggestions'].map(k => el(`ta-an-${k}-headline`)),
    bodies: ['overtrading', 'buildup', 'margintrap', 'suggestions'].map(k => el(`ta-an-${k}-body`)), charts: Object.keys(g.charts), A: el('ta-an-detail-a'), B: el('ta-an-detail-b'),
    grid: el('ta-an-sg-grid'), sum: el('ta-an-sg-summary'), chain: el('ta-bu-chain-sel'), status: el('ta-an-status'), note: el('ta-an-overtrading-note'), holding: el('ta-an-holding-empty') }; }
{ const p = base(); ['overtrading', 'buildup', 'margintrap', 'suggestions'].forEach(k => { p[k] = {}; }); reset();
  try { await load(p, run++); out.unavail.emptyObj = { threw: false, status: el('ta-an-status'), A: el('ta-an-detail-a'), B: el('ta-an-detail-b') }; } catch (e) { out.unavail.emptyObj = { threw: String(e) }; } }
{ const p = base(); p.overtrading = null; p.buildup = undefined; reset(); try { await load(p, run++); out.unavail.nullPanels = { threw: false, status: el('ta-an-status') }; } catch (e) { out.unavail.nullPanels = { threw: String(e) }; } }
out.badShape = {};
for (const [name, mut] of [['chainsObject', p => { p.buildup.chains = {}; }], ['weeklyString', p => { p.overtrading.weekly = 'x'; }], ['topObject', p => { p.overtrading.bursts.top = {}; }],
  ['daysListObject', p => { p.margintrap.trap.days_list = {}; }], ['rulesObject', p => { p.suggestions.rules = {}; }]]) {
  const p = base(); mut(p); reset();
  try { await load(p, run++); out.badShape[name] = { threw: false, status: el('ta-an-status'), A: el('ta-an-detail-a').length, B: el('ta-an-detail-b').length }; } catch (e) { out.badShape[name] = { threw: String(e) }; }
  try { T.taAnFullToggle(true); T.taAnFullToggle(false); } catch (e) { out.badShape[name].fullThrew = String(e); }
}
// sparse but available
{ const p = base(); p.overtrading = { available: true, quality: {}, weekly: [], activity: {}, winloss: {}, churn: {}, charges: {}, holding: {}, bursts: {} };
  p.buildup = { available: true, quality: {}, chains: [], chain_totals: {}, averaging: {}, events: {}, lots: {} };
  p.margintrap = { available: true, quality: {}, ledger: { available: true }, cash: {}, cash_series: [], debit_streaks: [], trap: {}, stops: {} };
  p.suggestions = { available: true, quality: {}, rules: [], observations: [], combined: {}, sample: {} };
  reset(); try { await load(p, run++); out.unavail.sparse = { threw: false, status: el('ta-an-status'), bodies: ['overtrading', 'buildup', 'margintrap', 'suggestions'].map(k => el(`ta-an-${k}-body`)),
    heads: ['overtrading', 'buildup', 'margintrap', 'suggestions'].map(k => el(`ta-an-${k}-headline`)), charts: Object.keys(g.charts), all: Object.values(g.els).join(' ') }; } catch (e) { out.unavail.sparse = { threw: String(e) }; } }
console.log(JSON.stringify(out));
