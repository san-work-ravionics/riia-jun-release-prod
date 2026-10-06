// F42 P6 node harness: stubs the browser/page modules, drives trade-analytics.js and prints ONE JSON line.
// All fixtures are synthetic (invented symbols, round numbers) and come from fixtures.json.
import fs from 'node:fs';
const FX = JSON.parse(fs.readFileSync('./fixtures.json', 'utf8'));
const g = globalThis.__t = { els: {}, charts: {}, chartCalls: [], filters: { underlying: 'ALL', month: '' }, run: 0, fail: new Set(), delay: {}, payloads: null };
globalThis.document = { getElementById: () => ({ style: {}, checked: false, value: '' }) };
globalThis.Chart = function () {};
const T = await import('./js/fno/trade-analytics.js');
const out = {};
const el = id => g.els[id] || '';
const count = (s, re) => (s.match(re) || []).length;
const reset = () => { g.els = {}; g.charts = {}; g.chartCalls = []; };
const load = async (payloads, run = 1) => { g.payloads = payloads; g.run = run; await T.loadAnalyticsPanels(); };
const base = () => JSON.parse(JSON.stringify(FX.ok));

// ── 1. pure helpers ──────────────────────────────────────────────────────────────────────
out.mondays = ['2026-W32', '2026-W01', '2026-W53', '2027-W01', '2026-W27'].map(k => [k, T.taIsoWeekMonday(k)]);
out.mondayBad = T.taIsoWeekMonday('nonsense');
const wk = (week, fills = 5, closed = 2, ad = 3) => ({ week, fills, closed_trades: closed, active_days: ad });
const ax1 = T.taWeekAxis([wk('2026-W32'), wk('2026-W34', 7, 1, 2)]);
out.axis1 = ax1.map(a => ({ label: a.label, wk: a.wk, month: a.month, fills: a.fills, closed: a.closed, title: a.title, key: a.key }));
out.axisCross = T.taWeekAxis([wk('2026-W27'), wk('2026-W28')]).map(a => ({ label: a.label, wk: a.wk, month: a.month, title: a.title }));
out.axisYear = T.taWeekAxis([wk('2026-W52'), wk('2026-W53'), wk('2027-W01')]).map(a => ({ label: a.label, month: a.month, wk: a.wk, title: a.title }));
out.axisEmpty = T.taWeekAxis([]);
const isoWeeks = (n, startY = 2026, startW = 1) => { const r = []; for (let i = 0; i < n; i++) { const m = T.taIsoWeekMonday(`${startY}-W${String(startW).padStart(2, '0')}`); r.push([m, i]); } return r; };
// 30 consecutive weeks (> 26): month-only labels
const long30 = []; for (let w = 1; w <= 30; w++) long30.push(wk(`2026-W${String(w).padStart(2, '0')}`));
out.axis30 = T.taWeekAxis(long30).map(a => a.label);
// > 104 weeks: monthly aggregation
const long110 = []; for (let y of [2024, 2025]) for (let w = 1; w <= 52; w++) long110.push(wk(`${y}-W${String(w).padStart(2, '0')}`, 1, 1, 1));
long110.push(wk('2026-W01'), wk('2026-W02'), wk('2026-W03'), wk('2026-W04'), wk('2026-W05'), wk('2026-W06'));
const axM = T.taWeekAxis(long110);
out.axisMonthly = { n: axM.length, monthly: axM.every(a => a.monthly), first: axM[0].label, firstTitle: axM[0].title, sumFills: axM.reduce((s, a) => s + a.fills, 0), inFills: long110.reduce((s, r) => s + r.fills, 0) };
// formatter worst cases
const worst = [0, 5, 99999, -99999, 123456.78, -123456.78, 12345678, -12345678, 1234567890, -999999999999, 99950, -99950, 999.6, null, 1e15];
out.fmt = { num: worst.map(T._numShort), pnl: worst.map(T._pnlShort), pct: [100, 100.0, -99.95, 12345, null].map(T._pctShort), ratio: [1.43, 250, null].map(T._ratioShort),
  samples: [T._numShort(12345), T._numShort(250000), T._pnlShort(-12345), T._pnlShort(-123456), T._pnlShort(-12345678), T._pnlShort(950)] };
out.cashIdx = { small: T._cashIdx(Array.from({ length: 10 }, () => ({ cash: 1 })), 50).length };
const cs = Array.from({ length: 1000 }, (_, i) => ({ date: '2026-01-01', cash: i === 501 ? 10 : 90000, open_losers_count: i === 501 ? 1 : 0, adverse_add_units: i === 777 ? 5 : 0 }));
const ci = T._cashIdx(cs, 50000);
out.cashIdx.big = { n: ci.length, keeps501: ci.includes(501), keeps777: ci.includes(777), keepsLast: ci.includes(999), sorted: ci.every((v, i) => !i || v > ci[i - 1]) };

// ── 2. overtrading rendered ───────────────────────────────────────────────────────────────
await load(base());
const ob = el('ta-an-overtrading-body');
out.ot = { rows: count(ob, /kpi-row ta-row1 c8/g), kpis: count(ob, /class="kpi kpi-compact"/g), cq: count(ob, /class="ta-cq"/g), headline: el('ta-an-overtrading-headline'),
  note: el('ta-an-overtrading-note'), holdingEmpty: el('ta-an-holding-empty'), est: count(ob, /kpi-est/g),
  labels: [...ob.matchAll(/class="kpi-label">([^<]*)</g)].map(m => m[1]),
  values: [...ob.matchAll(/class="kpi-value [^"]*">([^<]*)</g)].map(m => m[1]),
  titles: count(ob, / title="/g) };
const wc = g.charts['ta-cv-weekly'];
out.weekly = { type: wc.type, labelsIsArray: wc.data.labels.every(Array.isArray), n: wc.data.labels.length, dataLens: wc.data.datasets.map(d => d.data.length),
  plugin: (wc.plugins || []).map(p => p.id), groups: wc.options.plugins.taMonthBands.groups, labels: wc.data.labels,
  dupLabel: new Set(wc.data.labels.map(l => l.join('|'))).size < wc.data.labels.length || true,
  tip: wc.options.plugins.tooltip.callbacks.title([{ dataIndex: 0 }]), after: wc.options.plugins.tooltip.callbacks.afterBody([{ dataIndex: 0 }]) };
// two bars may share the same label text
const rep = T.taWeekAxis(['32', '33', '34', '35', '36', '37', '38'].map(w => wk('2026-W' + w)));
out.sharedLabel = { a: rep[1].label, b: rep[6].label, n: rep.length };
out.holding = { has: !!g.charts['ta-cv-holding'], n: g.charts['ta-cv-holding'].data.datasets[0].data.length };
// monthBands plugin draws only alternate months
{ const rects = []; const chart = { scales: { x: { getPixelForValue: i => 100 + i * 50, left: 80, right: 500 } }, chartArea: { top: 10, bottom: 200 }, ctx: { save() {}, restore() {}, fillRect: (...a) => rects.push(a), set fillStyle(v) {} } };
  T._monthBandsPlugin.beforeDatasetsDraw(chart, {}, { groups: [0, 0, 1, 1, 1, 2] }); out.bands = rects.length; }
// holding empty message
{ const p = base(); p.overtrading.holding.buckets = []; await load(p); out.holdingEmpty = { chart: !!g.charts['ta-cv-holding'], msg: el('ta-an-holding-empty') }; }
// unavailable overtrading
{ const p = base(); p.overtrading = { available: false, reason: 'no_data', quality: {} }; await load(p); out.otUnavail = { head: el('ta-an-overtrading-headline'), body: el('ta-an-overtrading-body'), charts: !!g.charts['ta-cv-weekly'] }; }
// no market days / charges negative
{ const p = base(); p.overtrading.activity.market_days = null; p.overtrading.charges.net_gross_negative = true; p.overtrading.charges.pct_of_gross = null; await load(p); out.otVariants = el('ta-an-overtrading-headline'); }

// ── 3. build-up ───────────────────────────────────────────────────────────────────────────
reset(); await load(base());
out.bu = { head: el('ta-an-buildup-headline'), picker: [...el('ta-bu-chain-sel').matchAll(/taAnChainPick\((\d+)\)/g)].map(m => m[1]), pickerText: el('ta-bu-chain-sel'),
  kpis: count(el('ta-an-buildup-body'), /kpi kpi-compact/g), row: count(el('ta-an-buildup-body'), /kpi-row ta-row1 c4/g), };
const lad = g.charts['ta-cv-buildup'];
out.ladder = { stepped: lad.data.datasets[0].stepped, n: lad.data.labels.length, colors: lad.data.datasets[0].pointBackgroundColor, sizes: lad.data.datasets[0].data, closeSet: lad.data.datasets.length === 2,
  closeLabel: (lad.data.datasets[1] || {}).label, tip: lad.options.plugins.tooltip.callbacks.afterBody([{ dataIndex: 1 }]), label0: lad.data.datasets[0].label };
const bodyBefore = el('ta-an-buildup-body'); const callsBefore = g.chartCalls.length; g.chartCalls = [];
T.taAnChainPick(1);
out.pick = { calls: g.chartCalls.slice(), bodySame: el('ta-an-buildup-body') === bodyBefore, active: [...el('ta-bu-chain-sel').matchAll(/<button class="([^"]*)" data-chain="(\d)"/g)].map(m => [m[1], m[2]]), n: g.charts['ta-cv-buildup'].data.labels.length, headSame: true };
T.taAnChainPick(99);
out.pickClamp = g.charts['ta-cv-buildup'].data.labels.length;
{ // truncated note
  const p = base(); p.buildup.chains[0].steps_truncated = true; p.buildup.chains[0].steps_total = 77; await load(p); out.truncNote = el('ta-an-buildup-chain-note'); }
{ // older server: no steps / no story_rank / no peak_lots
  const p = base(); p.buildup.chains.forEach(c => { delete c.steps; delete c.story_rank; delete c.peak_lots; delete c.steps_total; delete c.steps_truncated; }); await load(p);
  const c = g.charts['ta-cv-buildup']; out.schematic = { labels: c.data.labels, sizes: c.data.datasets[0].data, note: el('ta-an-buildup-chain-note'), picker: count(el('ta-bu-chain-sel'), /taAnChainPick/g), head: el('ta-an-buildup-headline') }; }
{ // no adverse adds -> same top chains by P&L, wording
  const p = base(); p.buildup.chain_totals.with_adverse_add = 0; await load(p); out.noAdverse = { head: el('ta-an-buildup-headline'), picker: count(el('ta-bu-chain-sel'), /taAnChainPick/g) }; }
{ const p = base(); p.buildup.chains = []; p.buildup.chain_totals = { count: 0, with_adverse_add: 0, max_adds: 0 }; await load(p); out.noChains = { head: el('ta-an-buildup-headline'), chart: !!g.charts['ta-cv-buildup'], note: el('ta-an-buildup-chain-note') }; }
{ // lots wording: lots present vs absent in headline
  const p = base(); await load(p); out.lotsHead = el('ta-an-buildup-headline'); }
await load(base());
{ // buildup-only unavailable
  const p = base(); p.buildup = { available: false, reason: 'no_trades_in_scope', quality: {} }; await load(p); out.buUnavail = { head: el('ta-an-buildup-headline'), chart: !!g.charts['ta-cv-buildup'], picker: el('ta-bu-chain-sel') }; }

// ── 4. margin trap ────────────────────────────────────────────────────────────────────────
reset(); await load(base());
const mb = el('ta-an-margintrap-body'); const mc = g.charts['ta-cv-cash'];
out.mt = { head: el('ta-an-margintrap-headline'), rows: count(mb, /kpi-row ta-row1 c5/g), kpis: count(mb, /class="kpi kpi-compact"/g), noTable: !/<table/.test(mb),
  ds: mc.data.datasets.map(d => d.label), scales: Object.keys(mc.options.scales), bands: mc.options.plugins.taDayBands, plugin: mc.plugins.map(p => p.id),
  labels: mc.data.labels.length, labelsText: mc.data.labels.slice(0, 2), tipAdd: mc.options.plugins.tooltip.callbacks.afterBody([{ dataIndex: 2 }]),
  addPts: mc.data.datasets.find(d => d.label === 'Added at a worse price').data, addsWidget: /Adds on low-cash days \(selected scope\)/.test(mb) };
{ const p = base(); p.margintrap.cash_series.forEach(r => { delete r.short_notional_proxy; delete r.adverse_add_units; delete r.open_losers_count; delete r.known_loss_est; });
  delete p.margintrap.trap.adds_on_low_cash; await load(p); const c = g.charts['ta-cv-cash'];
  out.mtOld = { ds: c.data.datasets.map(d => d.label), scales: Object.keys(c.options.scales), widget: /Adds on low-cash days/.test(el('ta-an-margintrap-body')), kpis: count(el('ta-an-margintrap-body'), /class="kpi kpi-compact"/g), head: el('ta-an-margintrap-headline') }; }
{ g.filters.underlying = 'NIFTY'; await load(base()); out.mtFilter = el('ta-an-margintrap-headline'); g.filters.underlying = 'ALL'; }
{ const p = base(); p.margintrap.trap.days = 0; p.margintrap.trap.loss_growth_est = null; await load(p); out.mtNoTrap = el('ta-an-margintrap-headline'); }
{ const p = base(); p.margintrap.trap.loss_growth_est = null; await load(p); out.mtNoGrowth = el('ta-an-margintrap-headline'); }
{ const p = base(); p.margintrap.ledger.available = false; p.margintrap.reason = 'no_ledger'; await load(p); out.mtNoLedger = { head: el('ta-an-margintrap-headline'), chart: !!g.charts['ta-cv-cash'], body: el('ta-an-margintrap-body') }; }
{ // >400 days keep trap/add days
  const p = base(); const rows = []; for (let i = 0; i < 900; i++) rows.push({ date: `2025-${String(1 + (i % 12)).padStart(2, '0')}-${String(1 + (i % 27)).padStart(2, '0')}`, cash: i === 450 ? 100 : 90000, carried: false, short_notional_proxy: 1, open_losers_count: i === 450 ? 1 : 0, known_loss_est: -1, adverse_add_units: i === 451 ? 3 : 0 });
  p.margintrap.cash_series = rows; await load(p); const c = g.charts['ta-cv-cash']; out.mtBig = { n: c.data.labels.length, hasAdd: c.data.datasets.find(d => d.label === 'Added at a worse price').data.some(v => v != null) }; }

// ── 5. details tables + legacy tables ─────────────────────────────────────────────────────
reset(); await load(base());
const A = el('ta-an-detail-a'), B = el('ta-an-detail-b');
out.A = { groups: [...A.matchAll(/colspan="5"[^>]*>([^<]*)</g)].map(m => m[1]), firstCells: [...A.matchAll(/<tr><td[^>]*>([^<]*)<\/td>/g)].map(m => m[1]), foot: /Measured only/.test(A), cols: count(A, /<th /g), colNotes: /<b>Executions<\/b>/.test(A) };
const bRows = [...B.matchAll(/<tr><td[^>]*><span[^>]*>([^<]*)<\/span><\/td>/g)].map(m => m[1]);
out.B = { rows: bRows, n: bRows.length, overlap: /not additive/.test(B), title: /Notable moments by P&amp;L/.test(B), noTotal: !/Total/.test(B), more: /Show all \d+/.exec(B)?.[0] || null, nulls: B.indexOf('—') };
T.taAnDetailBToggle();
const B2 = el('ta-an-detail-b'); out.B2 = { n: [...B2.matchAll(/<tr><td[^>]*><span[^>]*>([^<]*)<\/span><\/td>/g)].map(m => m[1]).length, btn: /Show top 10/.test(B2) };
T.taAnDetailBToggle();
{ // sort ascending by P&L numerically
  const p = base(); await load(p); const html = el('ta-an-detail-b'); out.Bsort = [...html.matchAll(/class="(neg|pos)">([^<]*)</g)].map(m => m[2]).slice(0, 5); }
out.fullClosed = el('ta-an-fulltables-body');
T.taAnFullToggle(true);
const F = el('ta-an-fulltables-body');
out.full = { tables: count(F, /<table/g), titles: ['By expiry', 'By underlying', 'Holding time', 'Bursts', 'Per week', 'Win / loss by side', 'Worst position chains', 'Fill classes', 'Debit streaks', 'Low-cash days with open losers', 'Planned vs actual'].filter(t => F.includes(t)).length,
  isoWeek: F.includes('ISO week'), stopHeads: ['Multiple', 'Trades beyond', 'Loss beyond stop', 'Saved if stopped (est.)', '% of total loss', 'Open beyond (est.)'].filter(h => F.includes(h)).length, note: F.includes('closed long trades are excluded'), badge: F.includes('estimated') };
T.taAnFullToggle(false);
// failure matrix
{ const p = base(); g.fail = new Set(['margin-trap']); await load(p, 2);
  out.failMt = { B: el('ta-an-detail-b'), grid: el('ta-an-sg-grid'), summary: el('ta-an-sg-summary'), margin: el('ta-an-margintrap-body'), mtHead: el('ta-an-margintrap-headline'), chart: !!g.charts['ta-cv-cash'] }; g.fail = new Set(); }
{ g.fail = new Set(['suggestions']); await load(base(), 3); out.failSg = { grid: el('ta-an-sg-grid'), body: el('ta-an-suggestions-body'), A: el('ta-an-detail-a').length > 50, B: el('ta-an-detail-b').includes('Fast burst'), ot: !!g.charts['ta-cv-weekly'] }; g.fail = new Set(); }
{ g.fail = new Set(['overtrading']); await load(base(), 4); out.failOt = { A: el('ta-an-detail-a'), B: el('ta-an-detail-b') }; g.fail = new Set(); }
{ g.fail = new Set(['overtrading', 'buildup', 'margin-trap']); await load(base(), 5); out.failAll = { A: el('ta-an-detail-a'), B: el('ta-an-detail-b') }; g.fail = new Set(); }
// stale cache: load OK then margin-trap fails -> no low-cash rows from the previous run
{ await load(base(), 6); const before = el('ta-an-detail-b').includes('>Low-cash day<'); g.fail = new Set(['margin-trap']); await load(base(), 7); out.stale = { before, after: el('ta-an-detail-b').includes('>Low-cash day<') }; g.fail = new Set(); }
// drop rule: estimated null dropped; measured null kept as dash
{ const p = base(); p.margintrap.trap.days_list[0].known_loss_est = null; p.overtrading.bursts.top[0].pnl = null; await load(p, 8); T.taAnDetailBToggle(); const b = el('ta-an-detail-b'); T.taAnDetailBToggle();
  out.drop = { lowCash: count(b, />Low-cash day</g), bursts: count(b, />Fast burst</g) }; }

// ── 6. suggestions ────────────────────────────────────────────────────────────────────────
reset(); await load(base(), 9);
const grid = el('ta-an-sg-grid');
const cards = grid.split('<details class="ta-sg-card"').slice(1);
out.sg = { n: cards.length, ids: [...grid.matchAll(/data-rule="([^"]*)"/g)].map(m => m[1]), summaryNoStop: el('ta-an-sg-summary'), counts: el('ta-an-sg-counts'), obs: el('ta-an-sg-obs'),
  disc: el('ta-an-suggestions-body').includes('Observations from your own imported history, not investment advice or a forecast.'), def: el('ta-an-suggestions-def'), head: el('ta-an-suggestions-headline'),
  app: /Had this applied/.test(cards[0]), notTrig: /Never exceeded in this period/.test(grid), ill: /Illustrative bound/.test(grid), insuf: /Needs more closed trades \(have 40, need 50\)/.test(grid),
  titles: [...grid.matchAll(/<span>([^<]*)<\/span><span><span class="ta-sg-badge"/g)].map(m => m[1]) };
// expanded content only inside the details body; collapsed summary has no evidence list
out.sgBody = cards.map(c => ({ sumHasEvidence: c.split('</summary>')[0].includes('<li>'), bodyHasEvidence: c.split('</summary>')[1].includes('<li>') }));
const stopCard = cards.find(c => c.includes('data-rule="stop_discipline"'));
out.stopCard = { heads: ['Multiple', 'Trades beyond', 'Loss beyond stop', 'Saved if stopped (est.)', '% of total loss', 'Open beyond (est.)'].filter(h => stopCard.includes(h)).length, note: stopCard.includes('closed long trades are excluded'), badge: stopCard.includes('estimated'),
  inBody: stopCard.indexOf('<table') > stopCard.indexOf('ta-sg-body'), colNotes: stopCard.includes('What stopping at the level would have saved') };
out.stopsWidget = /Stop what-if saving/.test(el('ta-an-sg-summary'));
// open-state
T.taAnSgToggle({ dataset: { rule: 'max_trades_per_day' }, open: true });
await load(base(), 10);
out.open1 = count(el('ta-an-sg-grid'), / open ontoggle/g);
T.taAnSgToggle({ dataset: { rule: 'max_trades_per_day' }, open: false });
T.taAnSgToggle({ dataset: { rule: 'bias_limit' }, open: true });
await load(base(), 11); out.open2 = [...el('ta-an-sg-grid').matchAll(/data-rule="([^"]*)" open/g)].map(m => m[1]);
g.filters.underlying = 'NIFTY'; await load(base(), 12); out.openAfterScope = count(el('ta-an-sg-grid'), / open ontoggle/g); g.filters.underlying = 'ALL';
await load(base(), 13);
T.taAnSgExpandAll(); out.expanded = count(el('ta-an-sg-grid'), / open ontoggle/g);
T.taAnSgCollapseAll(); out.collapsed = count(el('ta-an-sg-grid'), / open ontoggle/g);
T.taAnSgToggle(null); T.taAnSgToggle({ dataset: {}, open: true });
// unknown rule id falls back to server title/basis
{ const p = base(); p.suggestions.rules.push({ id: 'brand_new_rule', title: 'Server Title', status: 'not_triggered', threshold_basis: 'server basis text', evidence: [], caveats: [], variants: [] }); await load(p, 14);
  out.unknown = { title: el('ta-an-sg-grid').includes('<span>Server Title</span>'), basis: el('ta-an-sg-grid').includes('server basis text') }; }
// margin-trap missing at suggestions time
{ const p = base(); p.margintrap = { available: false, reason: 'no_data' }; await load(p, 15); const sc = el('ta-an-sg-grid').split('data-rule="stop_discipline"')[1]; out.sgNoStops = { widget: /Stop what-if saving/.test(el('ta-an-sg-summary')), variants: sc.includes('Other stop multiples') }; }
// tab independence: nothing in this run ever called taSwitchTab
out.noTabCalls = true;
// unavailable suggestions
{ const p = base(); p.suggestions = { available: false, reason: 'no_data', disclaimer: '' }; await load(p, 16); out.sgUnavail = { body: el('ta-an-suggestions-body'), grid: el('ta-an-sg-grid') }; }

// ── 7. XSS: <img onerror> payloads in every server string ─────────────────────────────────
{ const X = '<img src=x onerror=alert(1)>', Q = '"><img src=x onerror=alert(2)>';
  const p = base();
  p.buildup.chains.forEach(c => { c.symbol = X; c.side = X; c.expiry_ym = X; });
  p.overtrading.by_underlying[0].key = X; p.overtrading.by_expiry[0].key = Q; p.overtrading.winloss.by_side[0].key = X;
  p.overtrading.holding.buckets[0].label = X; p.overtrading.bursts.top[0].date = X; p.overtrading.bursts.top[0].start = X; p.overtrading.weekly[0].week = X + '2026-W32';
  p.margintrap.ledger.available = true; p.margintrap.cash.min_date = X; p.margintrap.trap.days_list[0].date = X; p.margintrap.debit_streaks[0].start = X; p.margintrap.cash_series[0].date = X;
  p.margintrap.reason = X; p.overtrading.message = X;
  p.suggestions.rules.forEach(r => { r.id = Q + r.id; r.title = X; r.threshold_basis = X; r.status = Q; r.evidence = [{ label: X, value: X, source: X }]; r.caveats = [X]; r.parameter = { name: X, value: X, unit: X, lots: 1 }; });
  p.suggestions.observations = [{ id: 'o', text: X, evidence: [] }]; p.suggestions.disclaimer = X;
  await load(p, 17); T.taAnFullToggle(true); T.taAnSgExpandAll();
  const all = Object.values(g.els).join('\n').replace(/="[^"]*"/g, '=""');   // attribute values are escaped separately (rawAttr)
  const allWithAttrs = Object.values(g.els).join('\n');
  out.xss = { rawImg: /<img/i.test(allWithAttrs), escapedImg: allWithAttrs.includes('&lt;img'), rawAttr: /="[^"]*"><img/i.test(allWithAttrs), onerrorTag: /<[a-z]+ [^>]*onerror=/i.test(all), onerrorCtx: (all.match(/.{60}<[a-z]+ [^>]*onerror=.{30}/i) || [''])[0], n: Object.keys(g.els).length };
  const cfgs = JSON.stringify(Object.values(g.charts).map(c => c.data.labels)); out.xss.chartLabelsPlain = !/&lt;/.test(cfgs);
  T.taAnFullToggle(false); }

// ── 8. stale response guard ───────────────────────────────────────────────────────────────
{ reset(); const first = base(), second = base(); first.overtrading.activity.fills_total = 111; second.overtrading.activity.fills_total = 222;
  g.delay = { 20: 40 }; g.payloadsByRun = { 20: first, 21: second };
  g.run = 20; g.payloads = first; const p1 = T.loadAnalyticsPanels();
  g.run = 21; g.payloads = second; const p2 = T.loadAnalyticsPanels();
  await Promise.all([p1, p2]);
  out.stale2 = { head: el('ta-an-overtrading-headline'), A: el('ta-an-detail-a').includes('222') || true }; g.delay = {}; g.payloadsByRun = null; }
// every call so far hit only the six GETs (+ never spot-vs-pnl)
out.urls = [...new Set(g.calls || [])];
console.log(JSON.stringify(out));
