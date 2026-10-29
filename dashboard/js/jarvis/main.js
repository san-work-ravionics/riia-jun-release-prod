// Jarvis — F44 P4b page boot. ensureDevToken() → A1 warmup (non-blocking) → A4 state → A2 session.
// P4c: the Portfolio tab shows Europe / India / US side by side (RITA Portfolio Builder layout):
// geography-overview (G, once per page session) + A5 for each location IN PARALLEL
// (Promise.allSettled), each column in its own currency (D1, nothing summed or converted). The
// sidebar location tabs stay the single "current location" control (D3, CR-7): Chat & plan,
// Concepts and the detail block follow it. Every call goes through shared/api.js api() (401 →
// ensureDevToken(true) → one retry). The only window binding is closeChartModal (modal markup).
import { ensureDevToken } from '../shared/dev-auth.js';
import { closeChartModal } from '../rita/chart-modal.js';
import { t } from './copy.js?v=3';
import {
  warmup, openSession, sendMessage, loadState, initChat, renderHistory, renderChips, appendBubble,
  appendPending, showChatError, setBusy,
} from './chat.js?v=3';
import { renderPlan } from './plan.js?v=3';
import {
  loadPortfolio, renderPortfolio, renderDetailHeader, initGrid, markSelected,
} from './portfolio.js?v=3';
import { loadInstrument, renderInstrument, renderInstrumentError, initInstrument } from './instrument.js?v=3';
import { renderConcepts, initConcepts } from './concepts.js?v=3';
import {
  LOCS, loadGeography, locCurrency, renderColumn, renderUniverse, initGeoTable,
} from './regions.js?v=3';

window.closeChartModal = closeChartModal;

const _perLoc = v => Object.fromEntries(LOCS.map(l => [l, v]));
export const S = {
  loc: 'europe', tab: 'chat', state: null, sessionId: null, inst: null, model: 'not_loaded', seq: 0,
  geo: null, geoErr: null,                                    // G — cached once per page session
  pfs: {}, pfErr: {}, pfStale: _perLoc(true), pfGen: _perLoc(0), // A5 per location
  sort: { col: 'ret', asc: false }, pfSeq: 0, detailLoc: null, mapHidden: false,
};

function _byId(id) { return document.getElementById(id); }

function applyStaticCopy() {
  document.title = t('page.title');
  document.querySelectorAll('[data-copy]').forEach(el => { el.textContent = t(el.dataset.copy); });
  const send = _byId('jv-chat-send');                              // icon button (rita.html .chat-send)
  if (send) { send.title = t('chat.send'); send.setAttribute('aria-label', t('chat.send')); }
}

function setModel(status) {
  if (S.model === 'ready' && status === 'not_loaded') return;
  S.model = status;
  const el = _byId('jv-status-model');
  if (!el) return;
  el.querySelector('.status-text').textContent = t(`status.model.${status}`);
  el.querySelector('.status-dot').className = `status-dot ${status === 'ready' ? 'ok' : status === 'unavailable' ? 'err' : 'warn'}`;
}

// ── tabs ───────────────────────────────────────────────────────────────────────
function showTab(tab) {
  S.tab = tab;
  _byId('jv-tab-chat')?.classList.toggle('is-active', tab === 'chat');
  _byId('jv-tab-portfolio')?.classList.toggle('is-active', tab === 'portfolio');
  _byId('jv-tab-concepts')?.classList.toggle('is-active', tab === 'concepts');
  for (const v of ['chat', 'portfolio', 'concepts']) { const el = _byId(`jv-view-${v}`); if (el) el.hidden = tab !== v; }
  if (tab === 'portfolio') {
    if (_pfNeedsLoad()) loadPortfolioSection();
    else if (S.mapHidden) _renderUniverse();                        // CR-P4c-1: drawn while hidden → redraw
  }
  if (tab === 'concepts') loadConceptsSection();
}

function initTabs() {
  _byId('jv-loc-tabs')?.addEventListener('click', e => {
    const b = e.target.closest('button[data-loc]');
    if (b && LOCS.includes(b.dataset.loc) && b.dataset.loc !== S.loc) selectLocation(b.dataset.loc);
  });
  _byId('jv-tab-chat')?.addEventListener('click', () => showTab('chat'));
  _byId('jv-tab-portfolio')?.addEventListener('click', () => showTab('portfolio'));
  _byId('jv-tab-concepts')?.addEventListener('click', () => showTab('concepts'));
  // Delegated: each column's "Show details" button carries data-loc (no onclick).
  _byId('sec-jv-locations')?.addEventListener('click', e => {
    const b = e.target.closest('button[data-loc]');
    if (b && LOCS.includes(b.dataset.loc) && b.dataset.loc !== S.loc) selectLocation(b.dataset.loc);
  });
}

// ── location / chat section ────────────────────────────────────────────────────
async function selectLocation(loc) {
  const seq = ++S.seq;
  S.loc = loc;
  S.state = null;
  S.sessionId = null;
  S.inst = null;
  try { history.replaceState(null, '', `#${loc}`); } catch { /* file:// or sandboxed */ }
  document.querySelectorAll('#jv-loc-tabs button[data-loc]').forEach(b => b.classList.toggle('is-active', b.dataset.loc === loc));
  _markActiveColumn(loc);
  if (S.tab === 'portfolio') _renderDetail(loc, { openFirst: false });   // from cache, no request
  renderHistory([]);
  renderChips([]);
  showChatError('');
  let state;
  try {
    state = await loadState(loc);                                   // A4
  } catch (e) {
    if (seq === S.seq) showChatError(t('err.load', { message: e.message }), true);
    return;
  }
  if (seq !== S.seq) return;
  S.state = state;
  setModel(state.chat_model);
  renderHistory(state.messages);
  renderChips(state.chips);
  renderPlan(state);
  try {
    const sess = await openSession(loc);                            // A2
    if (seq === S.seq) S.sessionId = sess.session_id;
  } catch (e) {
    if (seq === S.seq) showChatError(e.message);
  }
  if (seq === S.seq && S.tab === 'portfolio') loadPortfolioSection();
  if (seq === S.seq && S.tab === 'concepts') loadConceptsSection();
}

function _refreshState(loc) {
  loadState(loc).then(st => {
    if (S.loc !== loc) return;
    S.state = st;
    renderPlan(st);
  }).catch(() => { /* the reply's journey is already rendered */ });
}

async function onSend(text) {
  const loc = S.loc;
  showChatError('');
  appendBubble('user', text);
  const pending = appendPending();
  setBusy(true);
  try {
    if (!S.sessionId) S.sessionId = (await openSession(loc)).session_id;
    let res;
    try {
      res = await sendMessage(S.sessionId, text, loc);              // A3
    } catch (e) {
      if (!/session not found/i.test(e.message)) throw e;
      S.sessionId = (await openSession(loc)).session_id;             // idle-closed session → reopen once
      res = await sendMessage(S.sessionId, text, loc);
    }
    pending?.remove();
    if (S.loc !== loc) return;
    setModel('ready');
    appendBubble('assistant', res.reply.text, res.reply.cards);
    renderChips(res.reply.chips);
    renderPlan(S.state, res.journey || null);
    _invalidatePf(loc);                                             // only this location's A5
    _refreshState(loc);                                             // live_holdings + plan_stale
  } catch (e) {
    pending?.remove();
    if (/chat model unavailable/i.test(e.message)) setModel('unavailable');
    showChatError(e.message);
  } finally {
    setBusy(false);
  }
}

// ── portfolio + instrument sections ────────────────────────────────────────────
function _slLimit(inst) {
  const j = S.state && S.state.journey;
  if (!j) return null;
  const tr = (j.tracking || []).find(x => x.instrument_id === inst);
  if (tr) return tr.sl_drawdown_limit;
  const h = ((j.selection && j.selection.holdings) || []).find(x => x.instrument_id === inst);
  return h ? h.sl_drawdown_limit : null;
}

function _byIdText(id, text) { const el = _byId(id); if (el) { el.textContent = text; el.hidden = !text; } }

function _pfNeedsLoad() {
  return !S.geo || LOCS.some(l => S.pfStale[l]) || S.detailLoc !== S.loc;
}

function _invalidatePf(loc) {
  S.pfStale[loc] = true;
  S.pfGen[loc] += 1;                                                // an in-flight A5 for loc is dropped
}

// One A5 request per location at a time; a response that an invalidation overtook is dropped.
const _pfReq = {};
function _fetchPf(loc) {
  const cur = _pfReq[loc];
  if (cur && cur.gen === S.pfGen[loc]) return cur.promise;
  const gen = S.pfGen[loc];
  const promise = loadPortfolio(loc).then(pf => {                   // A5
    if (gen !== S.pfGen[loc]) return S.pfs[loc] || null;
    S.pfs[loc] = pf;
    S.pfErr[loc] = null;
    S.pfStale[loc] = false;
    return pf;
  }, e => {
    if (gen === S.pfGen[loc]) S.pfErr[loc] = e.message;
    throw e;
  }).finally(() => { if (_pfReq[loc] && _pfReq[loc].gen === gen) delete _pfReq[loc]; });
  _pfReq[loc] = { gen, promise };
  return promise;
}

let _geoReq = null;
function _fetchGeo() {
  if (S.geo) return Promise.resolve(S.geo);
  if (!_geoReq) {
    _geoReq = loadGeography().then(g => { S.geo = g; S.geoErr = null; return g; },   // G
                                   e => { S.geoErr = e.message; throw e; })        // not cached → retried next open
                             .finally(() => { _geoReq = null; });
  }
  return _geoReq;
}

function _markActiveColumn(loc) {
  for (const l of LOCS) {
    _byId(`jv-loc-col-${l}`)?.classList.toggle('is-active', l === loc);
    const b = document.querySelector(`#jv-loc-col-${l} button[data-loc]`);
    if (b) b.textContent = t(l === loc ? 'loc.details.active' : 'loc.details');
  }
}

function _renderColumn(loc) {
  renderColumn(loc, { geo: S.geo, geoErr: S.geoErr, pf: S.pfs[loc] || null,
                      pfErr: S.pfStale[loc] ? S.pfErr[loc] : null });
}

// Chart.js can't size a hidden canvas: remember when the map was drawn with Portfolio hidden
// (Concepts loads the portfolio data first) so showTab('portfolio') redraws it from the cache.
function _renderUniverse() { S.mapHidden = S.tab !== 'portfolio'; renderUniverse(S.geo, S.pfs, S.sort); }

function _onSort(col) {
  S.sort = S.sort.col === col ? { col, asc: !S.sort.asc } : { col, asc: ['id', 'loc', 'ccy', 'signal'].includes(col) };
  _renderUniverse();
}

// The detail block follows the current location (D2): one block, rendered from that location's A5.
async function _renderDetail(loc, { openFirst = true } = {}) {
  if (S.loc !== loc) return;
  const pf = S.pfs[loc];
  const sec = _byId('sec-jv-instrument');
  if (!pf || (S.pfErr[loc] && S.pfStale[loc])) {
    renderDetailHeader(loc, locCurrency(loc, null));
    if (S.pfErr[loc]) _byIdText('jv-pf-source', t('err.load', { message: S.pfErr[loc] }));
    if (sec) sec.hidden = true;
    S.detailLoc = null;
    return;
  }
  const first = renderPortfolio(pf, loc);
  S.detailLoc = loc;
  if (!openFirst) { if (sec) sec.hidden = true; return; }
  if (first) {
    if (sec) sec.hidden = false;
    await openInstrument(first);
  } else if (sec) {
    sec.hidden = true;
  }
}

// G + A5 × 3 fire together; each answer renders as it lands (progressive), the map and the table
// once everything has settled. A failed call only blanks its own block (allSettled, never all).
export async function loadPortfolioSection() {
  const seq = ++S.pfSeq;
  const loc = S.loc;
  S.inst = null;
  _markActiveColumn(loc);
  _byIdText('jv-pf-status', t('pf.loading'));
  const src = _byId('jv-pf-source');
  if (src && (S.pfStale[loc] || !S.pfs[loc])) { src.textContent = '…'; src.hidden = false; }
  let detail = null;
  const jobs = [_fetchGeo().catch(() => null).then(() => { LOCS.forEach(_renderColumn); })];
  for (const l of LOCS) {
    const fresh = S.pfs[l] && !S.pfStale[l];
    const job = (fresh ? Promise.resolve(S.pfs[l]) : _fetchPf(l)).catch(() => null).then(() => {
      _renderColumn(l);
      if (l === S.loc) detail = _renderDetail(l);
    });
    jobs.push(job);
  }
  await Promise.allSettled(jobs);
  if (seq !== S.pfSeq) return;
  _renderUniverse();
  _byIdText('jv-pf-status', '');
  if (detail) await detail;
}

async function openInstrument(inst) {
  const loc = S.loc;
  markSelected(inst);
  const title = _byId('jv-inst-title');
  if (title) title.textContent = `${inst} · …`;
  try {
    const data = await loadInstrument(loc, inst);                   // A6
    if (S.loc !== loc) return;
    S.inst = data;
    renderInstrument(data, null, { slLimit: _slLimit(inst) });
  } catch (e) {
    if (S.loc === loc) renderInstrumentError(e.message);
  }
}

// ── concepts: the user's own numbers from A4 / A5 / A6 (loaded here only when not yet loaded) ──
async function loadConceptsSection() {
  const loc = S.loc;
  renderConcepts({ state: S.state, pf: S.pfs[loc] || null, inst: S.inst }, loc);
  if (S.state && (S.pfStale[loc] || !S.pfs[loc] || S.detailLoc !== loc)) {
    await loadPortfolioSection();
    if (S.loc === loc && S.tab === 'concepts') renderConcepts({ state: S.state, pf: S.pfs[loc] || null, inst: S.inst }, loc);
  }
}

// ── boot ───────────────────────────────────────────────────────────────────────
function _initialLoc() {
  const h = (location.hash || '').replace('#', '');
  return LOCS.includes(h) ? h : 'europe';
}

async function boot() {
  applyStaticCopy();
  initTabs();
  initChat(onSend);
  initGrid(openInstrument);
  initGeoTable(_onSort);
  initInstrument();
  initConcepts();
  showTab('chat');
  await ensureDevToken();                                           // localhost: dev token (prod: login gate)
  warmup().then(r => setModel(r && r.status === 'ready' ? 'ready' : 'unavailable'))
          .catch(() => setModel('unavailable'));                     // A1, non-blocking
  await selectLocation(_initialLoc());
}

if (typeof document !== 'undefined' && document.addEventListener) {
  document.addEventListener('DOMContentLoaded', boot);
}
