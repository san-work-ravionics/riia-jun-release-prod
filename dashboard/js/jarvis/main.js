// Jarvis — F44 P4b page boot. ensureDevToken() → A1 warmup (non-blocking) → A4 state → A2 session.
// Location tabs (Europe / India / US) are the geography level (rev 1 A14): one location, one currency,
// one goal and one journey at a time. Every call goes through shared/api.js api() (401 →
// ensureDevToken(true) → one retry). The only window binding is closeChartModal (modal markup).
import { ensureDevToken } from '../shared/dev-auth.js';
import { closeChartModal } from '../rita/chart-modal.js';
import { t } from './copy.js?v=2';
import {
  warmup, openSession, sendMessage, loadState, initChat, renderHistory, renderChips, appendBubble,
  appendPending, showChatError, setBusy,
} from './chat.js?v=2';
import { renderPlan } from './plan.js?v=2';
import { loadPortfolio, renderPortfolio, initGrid, markSelected } from './portfolio.js?v=2';
import { loadInstrument, renderInstrument, renderInstrumentError, initInstrument } from './instrument.js?v=2';

window.closeChartModal = closeChartModal;

const LOCS = ['europe', 'india', 'us'];
const S = { loc: 'europe', tab: 'chat', state: null, sessionId: null, pf: null, pfLoc: null, pfStale: true, model: 'not_loaded', seq: 0 };

function _byId(id) { return document.getElementById(id); }

function applyStaticCopy() {
  document.title = t('page.title');
  document.querySelectorAll('[data-copy]').forEach(el => { el.textContent = t(el.dataset.copy); });
  const send = _byId('jv-chat-send');
  if (send) send.textContent = t('chat.send');
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
  for (const id of ['sec-jv-chat', 'sec-jv-plan']) { const el = _byId(id); if (el) el.hidden = tab !== 'chat'; }
  for (const id of ['sec-jv-portfolio', 'sec-jv-instrument']) { const el = _byId(id); if (el) el.hidden = tab !== 'portfolio'; }
  if (tab === 'portfolio' && (S.pfStale || S.pfLoc !== S.loc)) loadPortfolioSection();
}

function initTabs() {
  _byId('jv-loc-tabs')?.addEventListener('click', e => {
    const b = e.target.closest('button[data-loc]');
    if (b && LOCS.includes(b.dataset.loc) && b.dataset.loc !== S.loc) selectLocation(b.dataset.loc);
  });
  _byId('jv-tab-chat')?.addEventListener('click', () => showTab('chat'));
  _byId('jv-tab-portfolio')?.addEventListener('click', () => showTab('portfolio'));
}

// ── location / chat section ────────────────────────────────────────────────────
async function selectLocation(loc) {
  const seq = ++S.seq;
  S.loc = loc;
  S.state = null;
  S.sessionId = null;
  S.pfStale = true;
  try { history.replaceState(null, '', `#${loc}`); } catch { /* file:// or sandboxed */ }
  document.querySelectorAll('#jv-loc-tabs button[data-loc]').forEach(b => b.classList.toggle('is-active', b.dataset.loc === loc));
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
    S.pfStale = true;
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

async function loadPortfolioSection() {
  const loc = S.loc;
  const src = _byId('jv-pf-source');
  if (src) { src.textContent = '…'; src.hidden = false; }
  let pf;
  try {
    pf = await loadPortfolio(loc);                                  // A5
  } catch (e) {
    if (S.loc === loc && src) src.textContent = t('err.load', { message: e.message });
    return;
  }
  if (S.loc !== loc) return;
  S.pf = pf;
  S.pfLoc = loc;
  S.pfStale = false;
  const first = renderPortfolio(pf, loc);
  const sec = _byId('sec-jv-instrument');
  if (first) {
    if (sec) sec.hidden = S.tab !== 'portfolio';
    openInstrument(first);
  } else if (sec) {
    sec.hidden = true;
  }
}

async function openInstrument(inst) {
  const loc = S.loc;
  markSelected(inst);
  const title = _byId('jv-inst-title');
  if (title) title.textContent = `${inst} · …`;
  try {
    const data = await loadInstrument(loc, inst);                   // A6
    if (S.loc !== loc) return;
    renderInstrument(data, null, { slLimit: _slLimit(inst) });
  } catch (e) {
    if (S.loc === loc) renderInstrumentError(e.message);
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
  initInstrument();
  showTab('chat');
  await ensureDevToken();                                           // localhost: dev token (prod: login gate)
  warmup().then(r => setModel(r && r.status === 'ready' ? 'ready' : 'unavailable'))
          .catch(() => setModel('unavailable'));                     // A1, non-blocking
  await selectLocation(_initialLoc());
}

if (typeof document !== 'undefined' && document.addEventListener) {
  document.addEventListener('DOMContentLoaded', boot);
}
