// ── FnO Trade Analysis — Console import panel (F42 Phase 2) ────────────────────
// Upload Zerodha Console exports (Tradebook CSV, P&L XLSX/CSV, Ledger CSV), show import
// coverage and a paged table of imported trades.  PERSONAL DATA: every file-derived string
// goes through _esc before innerHTML.
//   POST   /api/v1/workflow/fno/console-import                 (multipart `files`)
//   DELETE /api/v1/workflow/fno/console-import?confirm=true
//   GET    /api/v1/experience/fno/trade-analysis/import-status
//   GET    /api/v1/experience/fno/trade-analysis/imported-trades

import { api, apiUpload } from './api.js';
import { setEl } from '../shared/utils.js';

const _UPLOAD = '/api/v1/workflow/fno/console-import';
const _STATUS = '/api/v1/experience/fno/trade-analysis/import-status';
const _TRADES = '/api/v1/experience/fno/trade-analysis/imported-trades';
const _MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

let _files = [];
let _limits = null;
let _page = 1;
let _totalPages = 1;
let _filtersReady = false;
let _busy = false;

const _esc = v => String(v == null ? '' : v)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const _num = (v, d = 0) => v == null ? '—'
  : Number(v).toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d });
const _dash = v => (v == null || v === '') ? '—' : _esc(v);
const _row = cells => '<tr>' + cells.map(c => `<td>${c}</td>`).join('') + '</tr>';
const _fill = (id, rows, cols, empty) => setEl(id, rows.length ? rows.join('')
  : `<tr><td colspan="${cols}" style="color:var(--t3);text-align:center">${empty}</td></tr>`);
const _el = id => document.getElementById(id);

function _banner(text) {
  const b = _el('ta-imp-banner');
  if (!b) return;
  b.style.display = text ? '' : 'none';
  b.textContent = text || '';
}

function _setBusy(flag) {
  _busy = flag;
  const btn = _el('ta-imp-upload-btn');
  if (btn) btn.disabled = flag || _files.length === 0;
}

function _range(a, b) { return (a || b) ? `${_dash(a)} → ${_dash(b)}` : '—'; }

function _runLine(label, r) {
  return `<div>${_esc(label)}: ${r ? `${_dash(r.file_name)} · ${_dash(r.status)} · +${_num(r.rows_inserted)} / ${_num(r.rows_skipped)} dup · ${_dash(r.created_at)}` : 'never'}</div>`;
}

function _renderStatus(s) {
  _limits = s.limits || null;
  const t = s.trades || {};
  const p = s.pnl || {};
  const l = s.ledger || {};
  setEl('ta-imp-cov-first', _dash(t.first_date));
  setEl('ta-imp-cov-last', _dash(t.last_date));
  setEl('ta-imp-cov-trades', _num(t.count));
  setEl('ta-imp-cov-inscope', `${_num(t.in_scope_count)} <span style="font-size:11px;color:var(--t3)">from ${_dash((s.scope || {}).date_from)} · ${_num(t.fut_count)} FUT · ${_num(t.unparsed_count)} unparsed</span>`);
  setEl('ta-imp-cov-ledger', `${_num(l.count)} <span style="font-size:11px;color:var(--t3)">${_range(l.first_date, l.last_date)}</span>`);
  setEl('ta-imp-cov-pnl', `${_num(p.line_count)} <span style="font-size:11px;color:var(--t3)">${(p.periods || []).map(x => `${_dash(x.from)} → ${_dash(x.to)}`).join(' · ') || '—'}</span>`);
  const li = s.last_imports || {};
  setEl('ta-imp-last', s.has_data || (s.recent_runs || []).length
    ? _runLine('Tradebook', li.tradebook) + _runLine('P&L', li.pnl) + _runLine('Ledger', li.ledger)
    : 'No Console files imported yet — choose files above');
  _fill('ta-imp-runs-body', (s.recent_runs || []).map(r => _row([
    _dash(r.created_at), _dash(r.kind), _dash(r.file_name), _dash(r.status), _num(r.rows_parsed),
    _num(r.rows_inserted), _num(r.rows_updated), _num(r.rows_skipped), _num(r.rows_rejected),
    _range(r.period_from, r.period_to),
  ])), 10, 'No imports yet');

  if (!_filtersReady) {
    const sc = s.scope || {};
    const msel = _el('ta-imp-month');
    if (msel) {
      msel.innerHTML = '<option value="">All expiries</option>' + (sc.expiry_months || [])
        .map(m => `<option value="${_esc(m)}">${_esc(_MONTHS[m - 1] || m)} ${_esc(sc.expiry_year)}</option>`).join('');
    }
    const usel = _el('ta-imp-und');
    if (usel) {
      usel.innerHTML = '<option value="ALL">All</option>' + (sc.underlyings || [])
        .map(u => `<option value="${_esc(u)}">${_esc(u)}</option>`).join('');
    }
    const from = _el('ta-imp-from');
    if (from && !from.value) from.value = sc.date_from || '';
    setEl('ta-imp-from-hint', sc.date_from ? `from ${_esc(sc.date_from)} (default; clear = default)` : '');
    _filtersReady = true;
  }
}

function _renderTrades(d) {
  _totalPages = d.total_pages || 1;
  _page = d.page || 1;
  _fill('ta-imp-trades-body', (d.items || []).map(t => _row([
    _dash(t.trade_date), _dash((t.order_execution_time || '').replace('T', ' ').slice(11, 19) || null),
    _dash(t.symbol), _dash(t.underlying), _dash(t.instrument_type), _num(t.strike),
    _dash(t.expiry_date), _dash(t.trade_type), _num(t.quantity), _num(t.price, 2),
    _dash(t.trade_id), _dash(t.order_id),
  ])), 12, 'No imported trades match the filters');
  setEl('ta-imp-page-info', `Page ${_num(_page)} of ${_num(_totalPages)} · ${_num(d.total)} trades`);
  const prev = _el('ta-imp-prev');
  const next = _el('ta-imp-next');
  if (prev) prev.disabled = _page <= 1;
  if (next) next.disabled = _page >= _totalPages;
}

function _renderFailure() {
  ['first', 'last', 'trades', 'inscope', 'ledger', 'pnl'].forEach(k => setEl(`ta-imp-cov-${k}`, '—'));
  setEl('ta-imp-last', '—');
  _fill('ta-imp-runs-body', [], 10, '—');
  _fill('ta-imp-trades-body', [], 12, '—');
}

function _tradesQuery() {
  const qs = new URLSearchParams({ page: String(_page), page_size: '50' });
  const und = (_el('ta-imp-und') || {}).value;
  const month = (_el('ta-imp-month') || {}).value;
  const from = (_el('ta-imp-from') || {}).value;
  const side = (_el('ta-imp-side') || {}).value;
  if (und) qs.set('underlying', und);
  if (month) qs.set('expiry_month', month);
  if (from) qs.set('date_from', from);
  if (side) qs.set('side', side);
  qs.set('include_fut', String(!!(_el('ta-imp-fut') || {}).checked));
  return qs.toString();
}

async function _loadTrades() {
  _renderTrades(await api(`${_TRADES}?${_tradesQuery()}`));
}

export async function loadImportPanel() {
  try {
    _renderStatus(await api(_STATUS));
    await _loadTrades();
    _banner('');
  } catch (e) {
    _renderFailure();
    _banner(e.message || 'Imported data could not be loaded.');
  }
}

export function taImpFilesChosen(fileList) {
  const picked = Array.from(fileList || []);
  const exts = (_limits && _limits.allowed_extensions) || null;
  const maxBytes = _limits && _limits.max_file_bytes;
  const maxFiles = _limits && _limits.max_files;
  const problems = [];
  _files = picked.filter(f => {
    const ext = '.' + String(f.name).split('.').pop().toLowerCase();
    if (exts && !exts.includes(ext)) { problems.push(`${f.name}: unsupported type`); return false; }
    if (maxBytes && f.size > maxBytes) { problems.push(`${f.name}: larger than ${_num(maxBytes / 1048576, 0)} MB`); return false; }
    return true;
  });
  if (maxFiles && _files.length > maxFiles) {
    problems.push(`At most ${maxFiles} files per upload`);
    _files = _files.slice(0, maxFiles);
  }
  setEl('ta-imp-chosen', _files.length
    ? _files.map(f => `${_esc(f.name)} (${_num(f.size / 1024, 0)} KB)`).join(' · ') : 'No files chosen');
  _banner(problems.join(' · '));
  _setBusy(_busy);
}

function _renderResults(res) {
  const rows = (res.files || []).map(f => {
    const msgs = (f.errors || []).map(e => `${_dash(e.code)}${e.row != null ? ' @row ' + _esc(e.row) : ''}: ${_dash(e.message)}`)
      .concat((f.warnings || []).map(_esc)).join('<br>');
    return _row([
      _dash(f.file_name), _dash(f.kind), _dash(f.status), _num(f.rows_parsed), _num(f.inserted),
      _num(f.skipped_duplicates), _num(f.rejected), _range((f.period || {}).from, (f.period || {}).to),
      msgs || '—',
    ]);
  });
  _fill('ta-imp-result-body', rows, 9, 'No upload yet');
}

export async function taImpUpload() {
  if (_busy || !_files.length) return;
  _setBusy(true);
  setEl('ta-imp-progress', `Uploading ${_files.length} file(s)…`);
  try {
    const fd = new FormData();
    _files.forEach(f => fd.append('files', f));
    const res = await apiUpload(_UPLOAD, fd);
    if (res) _renderResults(res);
    const input = _el('ta-imp-file');
    if (input) input.value = '';
    _files = [];
    setEl('ta-imp-chosen', 'No files chosen');
    _page = 1;
    _banner('');
    await loadImportPanel();
  } catch (e) {
    _banner(e.message || 'Upload failed.');
  } finally {
    setEl('ta-imp-progress', '');
    _setBusy(false);
  }
}

export async function taImpSetFilter() {
  _page = 1;
  try { await _loadTrades(); _banner(''); } catch (e) { _banner(e.message || 'Trades could not be loaded.'); }
}

export async function taImpPage(delta) {
  const n = _page + (Number(delta) || 0);
  if (n < 1 || n > _totalPages) return;
  _page = n;
  try { await _loadTrades(); _banner(''); } catch (e) { _banner(e.message || 'Trades could not be loaded.'); }
}

export function taImpRefresh() {
  return loadImportPanel();
}

export async function taImpDelete() {
  if (!window.confirm('Delete ALL your imported Console data (trades, P&L, ledger, import history)? This cannot be undone.')) return;
  try {
    await api(`${_UPLOAD}?confirm=true`, 'DELETE');
    _page = 1;
    setEl('ta-imp-result-body', '');
    await loadImportPanel();
  } catch (e) {
    _banner(e.message || 'Delete failed.');
  }
}
