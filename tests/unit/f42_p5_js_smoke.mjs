// Node harness (no DOM library) for dashboard/js/fno/trade-import.js; prints one JSON object.
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const root = process.argv[2];
const els = {};
const mk = id => (els[id] ||= { id, style: {}, dataset: {}, innerHTML: '', textContent: '', value: '', disabled: false, checked: false });
globalThis.document = { getElementById: id => mk(id), querySelectorAll: () => [], addEventListener() {}, body: {} };
globalThis.window = { confirm: () => true, dispatchEvent() {}, addEventListener() {}, location: { hostname: 'localhost', href: '' } };
globalThis.Event = class {};
globalThis.Chart = { defaults: { font: {}, plugins: { legend: { labels: {} }, tooltip: {} }, scale: {}, scales: {}, elements: {} }, register() {} };
globalThis.sessionStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.localStorage = { getItem: () => null, setItem() {} };
const calls = [];
let status = null;
let statusDelayMs = 0;
let sampleReply = { status: 'loaded', message: 'ok' };
globalThis.fetch = async (url, opts) => {
  calls.push(`${opts.method} ${url}`);
  const j = o => ({ ok: true, status: 200, json: async () => o });
  if (url.includes('/sample')) return j(sampleReply);
  if (url.includes('import-status')) {
    if (statusDelayMs) await new Promise(r => setTimeout(r, statusDelayMs));
    return j(status);
  }
  if (url.includes('imported-trades')) return j({ items: [], total: 0, total_pages: 1, page: 1 });
  return j({});
};
const m = await import(pathToFileURL(path.join(root, 'dashboard/js/fno/trade-import.js')).href);
const base = { has_data: false, scope: { expiry_months: [7], expiry_year: 2026, underlyings: ['NIFTY'], date_from: '2026-07-01' },
  limits: { allowed_extensions: ['.csv'] }, trades: {}, pnl: {}, ledger: {}, last_imports: {}, recent_runs: [] };
const sm = o => ({ enabled: true, loaded: false, offer: false, can_load: false, unavailable_reason: null, window: null, file_prefix: 'SAMPLE_', ...o });
const out = {};
const shown = id => els[id].style.display === '';

status = { ...base, sample: sm({ offer: true, can_load: true }) };
await m.loadImportPanel();
out.offer = { card: shown('ta-imp-sample-card'), btnDisabled: els['ta-imp-sample-btn'].disabled, cta: shown('ta-empty-cta'), banner: els['ta-sample-banner'].style.display };

status = { ...base, has_data: true, sample: sm({ loaded: true, window: { from: '2026-07-01', to: '<b>2026-09-18' } }) };
await m.loadImportPanel();
out.loaded = { banner: shown('ta-sample-banner'), text: els['ta-sample-banner-text'].innerHTML, fileDisabled: els['ta-imp-file'].disabled,
  uploadDisabled: els['ta-imp-upload-btn'].disabled, cta: els['ta-empty-cta'].style.display, chosen: els['ta-imp-chosen'].innerHTML };

status = { ...base };
await m.loadImportPanel();
out.legacy = { banner: els['ta-sample-banner'].style.display, card: els['ta-imp-sample-card'].style.display, fileDisabled: els['ta-imp-file'].disabled };

status = { ...base, sample: sm({ offer: true, unavailable_reason: 'sample_files_missing' }) };
await m.loadImportPanel();
out.unavailable = { note: els['ta-imp-sample-note'].textContent, btnDisabled: els['ta-imp-sample-btn'].disabled };

// load: POST then refresh
calls.length = 0;
status = { ...base, sample: sm({ offer: true, can_load: true }) };
await m.loadImportPanel();
await m.taSampleLoad();
out.load = calls.filter(c => c.includes('console-import') || c.includes('import-status'));

// A1: a refusal must survive a LATE import-status render (loadTradeAnalysis does not await it)
sampleReply = { status: 'refused', reason: 'sample_failed', message: 'Sample <b>failed' };
statusDelayMs = 60;
await m.taSampleLoad();
await new Promise(r => setTimeout(r, 250));
statusDelayMs = 0;
out.refusal = { note: els['ta-imp-sample-note'].innerHTML, banner: els['ta-imp-banner'].textContent };

sampleReply = { status: 'loaded', message: 'ok' };
calls.length = 0;
out.removed = await m.taSampleRemove();
out.deleteCall = calls.filter(c => c.startsWith('DELETE'));
out.noteAfterRemove = els['ta-imp-sample-note'].textContent;
console.log(JSON.stringify(out));
