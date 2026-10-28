// Jarvis — chat: A1–A4 calls, messages, chips and the inline reply cards (rev 1 B3: one renderer per
// card kind; an unknown kind renders nothing). Cards are chat summaries only; the plan view renders
// from the journey (plan.js). Every server string goes through esc() or textContent.
import { api } from '../shared/api.js';
import { esc } from './esc.js?v=2';
import { t } from './copy.js?v=2';
import { fmtRate, fmtMoney, fmtDate, fmtYears, isNum } from './format.js?v=2';

// ── API (every call through api(): 401 → ensureDevToken(true) → one retry) ─────
export function warmup() {
  return api('/api/v1/workflow/jarvis/warmup', 'POST');
}

export function openSession(location) {
  return api('/api/v1/workflow/jarvis/session', 'POST', { location });
}

export function sendMessage(sessionId, text, location) {
  return api('/api/v1/workflow/jarvis/message', 'POST', { session_id: sessionId, text, location });
}

export function loadState(location) {
  return api(`/api/v1/experience/jarvis/state?location=${encodeURIComponent(location)}`);
}

// ── small shared renders ───────────────────────────────────────────────────────
export function actionText(a) {
  return a ? t(`action.${a}`) || a : '—';
}

export function reasonText(r) {
  return t(`reason.${r}`) || r || '—';
}

function _holdingsTable(holdings) {
  const rows = (holdings || []).map(h => `<tr>
      <td class="mono">${esc(h.instrument_id)}</td>
      <td class="num">${esc(isNum(h.allocation_pct) ? `${h.allocation_pct}%` : '—')}</td>
      <td>${esc(actionText(h.model_action))}</td></tr>`).join('');
  return `<table class="jv-table jv-table-sm"><thead><tr>
      <th>${esc(t('plan.selection.col.instrument'))}</th><th class="num">${esc(t('plan.selection.col.weight'))}</th>
      <th>${esc(t('plan.selection.col.model'))}</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function _kpi(label, value) {
  return `<div class="jv-kpi"><div class="jv-kpi-label">${esc(label)}</div><div class="jv-kpi-value">${esc(value)}</div></div>`;
}

function _excludedList(rows) {
  if (!rows || !rows.length) return '';
  const items = rows.map(r => `<li><span class="mono">${esc(r.instrument_id)}</span> — ${esc(reasonText(r.reason))}</li>`).join('');
  return `<div class="jv-card-sub">${esc(t('plan.excluded.title'))}</div><ul class="jv-list">${items}</ul>`;
}

const _SOURCE = { saved: () => t('src.saved'), model_sleeves: () => t('src.model_sleeves'),
                  mixed: () => `${t('src.saved')} + ${t('src.model_sleeves')}` };

// ── card renderers: data fields only as in tests/unit/fixtures/f44_p4_contract.json ─
const CARD_RENDERERS = {
  goal(d) {
    return `<div class="jv-card-title">${esc(t('plan.goal.title'))}</div><div class="jv-kpis">
      ${_kpi(t('plan.goal.return'), fmtRate(d.goal_return))}
      ${_kpi(t('plan.goal.horizon'), fmtYears(d.horizon_years))}
      ${_kpi(t('plan.goal.value'), fmtMoney(d.goal_value, d.currency))}
      ${_kpi(t('plan.goal.saved'), fmtDate(d.plan_updated_at))}</div>`;
  },
  selection(d) {
    const head = d.meets_goal ? `<div class="jv-card-sub ok">${esc(t('plan.selection.meets'))}</div>` : '';
    return `<div class="jv-card-title">${esc(t('plan.selection.title'))}</div>${head}${_holdingsTable(d.holdings)}`;
  },
  closest(d) {
    return `<div class="jv-card-title warn">${esc(t('plan.selection.cant'))}</div>${_holdingsTable(d.holdings)}`;
  },
  why(d) {
    const rows = (d.rows || []).map(r => ({ instrument_id: r.instrument_id, allocation_pct: r.allocation_pct, model_action: r.today_action }));
    return `<div class="jv-card-title">${esc(t('plan.selection.title'))}</div>${_holdingsTable(rows)}${_excludedList(d.excluded)}`;
  },
  tracking(d) {
    const limit = isNum(d.sl_drawdown_limit) ? fmtRate(Math.abs(d.sl_drawdown_limit)) : '—';
    const rows = (d.holdings || []).map(h => ({ instrument_id: h.instrument_id, allocation_pct: null, model_action: h.today_action }));
    return `<div class="jv-card-title">${esc(t('plan.tracking.title', { date: fmtDate(d.entry_date) }))}</div>
      <div class="jv-card-sub">${esc(t('plan.tracking.sl', { limit, next_reset: fmtDate(d.next_reset) }))}</div>${_holdingsTable(rows)}`;
  },
  progress(d) {
    const src = (_SOURCE[d.source] || (() => ''))();
    const status = d.status ? t(`target.status.${d.status}`) : '';
    return `<div class="jv-card-title">${esc(src)}</div>
      ${status ? `<div class="jv-card-sub">${esc(status)}</div>` : ''}<div class="jv-kpis">
      ${_kpi(t('target.kpi.to_date'), fmtRate(d.target_to_date))}
      ${_kpi(t('target.kpi.actual'), fmtRate(d.ytd_return))}
      ${_kpi(t('target.kpi.required'), fmtRate(d.required_return))}</div>`;
  },
  proposal(d) {
    return `<div class="jv-card-title">${esc(t('plan.proposal.title'))}</div>
      <div class="jv-card-sub">${esc(t('plan.proposal.text', { n: d.reselections_next, max: d.max_reselections }))}</div>
      ${_holdingsTable(d.holdings)}`;
  },
  what_if(d) {
    const rows = (d.rows || []).map(r => `<tr><td class="mono">${esc(r.instrument_id)}</td><td class="num">${esc(fmtRate(r.sl_distance))}</td></tr>`).join('');
    return `<table class="jv-table jv-table-sm"><thead><tr><th>${esc(t('grid.col.instrument'))}</th>
      <th class="num">${esc(t('grid.col.sl'))}</th></tr></thead><tbody>${rows}</tbody></table>`;
  },
  hedge(d) {
    return `<div class="jv-kpis">${_kpi(t('grid.title'), isNum(d.n_hedged) ? String(d.n_hedged) : '—')}
      ${_kpi(t('engine.col.covers'), isNum(d.coverage) ? `${d.coverage}%` : '—')}</div>`;
  },
  excluded(d) {
    return _excludedList(d.rows);
  },
};

export const CARD_KINDS = Object.keys(CARD_RENDERERS);

export function cardHtml(card) {
  const fn = card && CARD_RENDERERS[card.kind];
  if (!fn || !card.data) return '';
  return `<div class="jv-card jv-card-${esc(card.kind)}">${fn(card.data)}</div>`;
}

export function bubbleHtml(role, text, cards = []) {
  const who = role === 'user' ? 'user' : 'assistant';
  const cardsHtml = (cards || []).map(cardHtml).join('');
  return `<div class="jv-msg jv-msg-${who}"><div class="jv-bubble">${esc(text)}</div>${cardsHtml}</div>`;
}

export function chipsHtml(chips) {
  return (chips || []).map((c, i) => `<button type="button" class="jv-chip" data-idx="${i}">${esc(c.label)}</button>`).join('');
}

// ── DOM ────────────────────────────────────────────────────────────────────────
let _chips = [];

function _log() { return document.getElementById('jv-chat-log'); }

function _scroll() {
  const log = _log();
  if (log) log.scrollTop = log.scrollHeight;
}

export function renderHistory(messages) {
  const log = _log();
  if (!log) return;
  log.innerHTML = (messages || []).map(m => bubbleHtml(m.role, m.text)).join('');
  _scroll();
}

export function appendBubble(role, text, cards = []) {
  const log = _log();
  if (!log) return null;
  log.insertAdjacentHTML('beforeend', bubbleHtml(role, text, cards));
  _scroll();
  return log.lastElementChild;
}

export function appendPending() {
  const log = _log();
  if (!log) return null;
  log.insertAdjacentHTML('beforeend', '<div class="jv-msg jv-msg-assistant jv-pending"><div class="jv-bubble"><span class="jv-dots"><i></i><i></i><i></i></span></div></div>');
  _scroll();
  return log.lastElementChild;
}

export function renderChips(chips) {
  _chips = chips || [];
  const el = document.getElementById('jv-chat-chips');
  if (el) el.innerHTML = chipsHtml(_chips);
}

// raw = true: message is already a full UI string (e.g. err.load); otherwise it is wrapped in chat.error.send.
export function showChatError(message, raw = false) {
  const el = document.getElementById('jv-chat-error');
  if (!el) return;
  el.textContent = message ? (raw ? message : t('chat.error.send', { message })) : '';
  el.hidden = !message;
}

export function setBusy(busy) {
  const btn = document.getElementById('jv-chat-send');
  const inp = document.getElementById('jv-chat-input');
  if (btn) btn.disabled = busy;
  if (inp) inp.disabled = busy;
}

// onSend(text) → Promise. Chips are delegated on the container (data-idx, never ids in onclick).
export function initChat(onSend) {
  const form = document.getElementById('jv-chat-form');
  const inp = document.getElementById('jv-chat-input');
  if (inp) inp.placeholder = t('chat.placeholder');
  form?.addEventListener('submit', e => {
    e.preventDefault();
    const text = (inp.value || '').trim();
    if (!text) return;
    inp.value = '';
    onSend(text);
  });
  document.getElementById('jv-chat-chips')?.addEventListener('click', e => {
    const b = e.target.closest('button[data-idx]');
    if (!b || b.disabled) return;
    const chip = _chips[Number(b.dataset.idx)];
    if (chip) onSend(chip.text);
  });
}
