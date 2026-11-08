// Jarvis — chat: A1–A4 calls, messages, chips and the inline reply cards (rev 1 B3: one renderer per
// card kind; an unknown kind renders nothing). Cards are chat summaries only; the plan view renders
// from the journey (plan.js). Every server string goes through esc() or textContent.
import { api } from '../shared/api.js';
import { esc } from './esc.js?v=3';
import { t } from './copy.js?v=20';
import { fmtRate, fmtMoney, fmtDate, fmtYears, isNum, locationName } from './format.js?v=3';

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

function _kpi(label, value) {
  return `<div class="jv-kpi"><div class="jv-kpi-label">${esc(label)}</div><div class="jv-kpi-value">${esc(value)}</div></div>`;
}

// F45 Phase D — bucket cards. Labels come from copy (the server sends only the bucket key).
const _BUCKET_LABEL = { idx: 'wn.label.idx', eq: 'wn.label.eq', com: 'wn.label.com', alt: 'wn.label.alt' };

function _bucketLabel(key) {
  return (_BUCKET_LABEL[key] && t(_BUCKET_LABEL[key])) || String(key || '');
}

function _bucketState(atRisk) {
  if (atRisk === true) return { cls: 'warn', text: t('wn.bucket.at_risk') };
  if (atRisk === false) return { cls: 'ok', text: t('wn.bucket.on_pace') };
  return { cls: 'none', text: t('wn.bucket.no_data') };
}

// The FnO link is a server string: only a same-site dashboard path is ever made clickable.
function _fnoLink(href) {
  return typeof href === 'string' && /^\/dashboard\/[A-Za-z0-9_.-]+\.html$/.test(href) ? href : '';
}

// ── card renderers: data fields only as in tests/unit/fixtures/f44_p4_contract.json ─
const CARD_RENDERERS = {
  goal(d) {
    return `<div class="jv-card-title">${esc(t('plan.goal.title'))}</div><div class="jv-kpis">
      ${_kpi(t('plan.goal.return'), fmtRate(d.goal_return))}
      ${_kpi(t('plan.goal.horizon'), fmtYears(d.horizon_years))}
      ${_kpi(t('plan.goal.value'), fmtMoney(d.goal_value, d.currency))}
      ${_kpi(t('plan.goal.saved'), fmtDate(d.plan_updated_at))}</div>`;
  },
  hedge(d) {
    return `<div class="jv-kpis">${_kpi(t('grid.title'), isNum(d.n_hedged) ? String(d.n_hedged) : '—')}
      ${_kpi(t('engine.col.covers'), isNum(d.coverage) ? `${d.coverage}%` : '—')}</div>`;
  },
  bucket_progress(d) {
    const rows = (d.buckets || []).map(b => {
      const st = _bucketState(b.at_risk);
      return `<tr><td>${esc(_bucketLabel(b.key))}</td>
        <td class="num">${esc(fmtRate(b.ytd_return))}</td><td class="num">${esc(fmtRate(b.target_to_date))}</td>
        <td class="num">${esc(fmtRate(b.gap))}</td><td><span class="jv-badge ${esc(st.cls)}">${esc(st.text)}</span></td></tr>`;
    }).join('');
    return `<div class="jv-card-title">${esc(t('chat.bucket.progress.title'))}</div>
      <table class="jv-table jv-table-sm"><thead><tr><th>${esc(t('wn.bucket.col.bucket'))}</th>
      <th class="num">${esc(t('wn.bucket.col.actual_ytd'))}</th><th class="num">${esc(t('wn.bucket.col.target_ytd'))}</th>
      <th class="num">${esc(t('wn.bucket.col.gap'))}</th><th></th></tr></thead><tbody>${rows}</tbody></table>`;
  },
  bucket_status(d) {
    const st = _bucketState(d.at_risk);
    const chips = (d.instruments || []).map(i => `<span class="jv-hold-chip"><b class="mono">${esc(i)}</b></span>`).join('');
    return `<div class="jv-card-title">${esc(_bucketLabel(d.key))} <span class="jv-badge ${esc(st.cls)}">${esc(st.text)}</span></div>
      <div class="jv-kpis">
      ${_kpi(t('wn.bucket.col.actual_ytd'), fmtRate(d.ytd_return))}
      ${_kpi(t('wn.bucket.col.target_ytd'), fmtRate(d.target_to_date))}
      ${_kpi(t('wn.bucket.col.gap'), fmtRate(d.gap))}</div>
      ${chips ? `<div class="jv-hold-chips">${chips}</div>` : ''}`;
  },
  hedge_signal(d) {
    const risky = d.at_risk_buckets || [];
    const link = _fnoLink(d.fno_link);
    const cta = risky.length && link ? `<a class="jv-wn-hedge-cta" href="${esc(link)}">${esc(t('wn.bucket.review_hedge'))}</a>` : '';
    const head = risky.length
      ? risky.map(k => `<span class="jv-badge warn">${esc(_bucketLabel(k))}</span>`).join(' ')
      : `<span class="jv-badge ${d.all_on_track ? 'ok' : 'none'}">${esc(d.all_on_track ? t('chat.hedge.none') : t('wn.bucket.no_data'))}</span>`;
    return `<div class="jv-card-title">${esc(t('chat.hedge.title'))}</div><div class="jv-hold-chips">${head}</div>${cta}`;
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
  document.querySelectorAll('#jv-chat-groups .jv-q').forEach(b => { b.disabled = busy; });
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


// ── key highlights (top panel): the saved plan + this year's return, region-neutral wording ──────────
export function highlightsHtml(state, pf, location) {
  const goal = state && ((state.journey) || state.goal);
  const perf = pf && pf.perf;
  const tile = (label, value, cls = '') =>
    `<div class="kpi kpi-sm"><div class="kpi-label">${esc(label)}</div><div class="kpi-value ${cls}">${esc(value)}</div></div>`;
  const has = goal && isNum(goal.goal_return);
  const ytd = perf && isNum(perf.ytd_return) ? perf.ytd_return : null;
  return [
    tile(t('hl.region'), locationName(location)),
    tile(t('hl.plan_return'), has ? fmtRate(goal.goal_return) : t('hl.no_plan')),
    tile(t('hl.horizon'), has ? fmtYears(goal.horizon_years) : '—'),
    tile(t('hl.goal_value'), has ? fmtMoney(goal.goal_value, goal.currency) : '—'),
    tile(t('hl.saved'), has ? fmtDate(goal.plan_updated_at) : '—'),
    tile(t('hl.journey'), state && state.journey ? t(`state.${state.journey.state}`) : t('state.no_goal')),
    tile(t('hl.ytd'), ytd === null ? '—' : fmtRate(ytd), ytd === null ? '' : (ytd >= 0 ? 'pos' : 'neg')),
    tile(t('hl.target'), perf && isNum(perf.target_to_date) ? fmtRate(perf.target_to_date) : '—'),
  ].join('');
}

export function renderHighlights(state, pf, location) {
  const el = document.getElementById('jv-chat-highlights');
  if (el) el.innerHTML = highlightsHtml(state, pf, location);
}

// ── question groups (left panel) ─────────────────────────────────────────────────────────────
export const QUESTION_GROUPS = [
  { key: 'g1', badge: 'p1', qs: ['goal'] },
  { key: 'g3', badge: 'p3', qs: ['build', 'why', 'closest'] },
  { key: 'g4', badge: 'p4', qs: ['track', 'doing', 'stop'] },
  { key: 'g5', badge: 'p5', qs: ['protect'] },
];

export function groupsHtml() {
  return QUESTION_GROUPS.map(g => `<div class="phase-group">
    <div class="phase-hdr"><span class="phase-step-badge ${g.badge}">${esc(t(`chat.${g.key}.tag`))}</span><span class="phase-name">${esc(t(`chat.${g.key}`))}</span></div>
    ${g.qs.map(q => `<button type="button" class="jv-q" data-q="${q}">${esc(t(`chat.q.${q}`))}</button>`).join('')}
  </div>`).join('');
}

export function initGroups(onSend) {
  const el = document.getElementById('jv-chat-groups');
  if (!el) return;
  el.innerHTML = groupsHtml();
  el.addEventListener('click', e => {
    const b = e.target.closest('button[data-q]');
    if (!b || b.disabled) return;
    onSend(t(`chat.q.${b.dataset.q}`).replace(/\?$/, ''));
  });
}

// ── voice: talk (browser SpeechRecognition) and listen (browser speechSynthesis) ────────────────
let _speakOn = false;

export function speakReply(text) {
  if (!_speakOn || typeof window === 'undefined' || !window.speechSynthesis || !text) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(String(text));
  u.lang = navigator.language || 'en-US';
  window.speechSynthesis.speak(u);
}

export function initVoice(onSend) {
  const mic = document.getElementById('jv-chat-mic');
  const spk = document.getElementById('jv-chat-speak');
  const status = document.getElementById('jv-chat-voice-status');
  const inp = document.getElementById('jv-chat-input');
  if (!mic) return;
  const setStatus = txt => { if (status) status.textContent = txt || ''; };
  try { _speakOn = localStorage.getItem('jvSpeak') === '1'; } catch { /* storage blocked */ }
  if (spk) {
    spk.checked = _speakOn;
    spk.addEventListener('change', () => {
      _speakOn = spk.checked;
      try { localStorage.setItem('jvSpeak', _speakOn ? '1' : '0'); } catch { /* storage blocked */ }
      if (!_speakOn && window.speechSynthesis) window.speechSynthesis.cancel();
    });
  }
  const SR = typeof window !== 'undefined' && (window.SpeechRecognition || window.webkitSpeechRecognition);
  mic.title = SR ? t('voice.mic') : t('voice.unsupported');
  if (!SR) { mic.disabled = true; return; }
  const rec = new SR();
  rec.lang = navigator.language || 'en-US';
  rec.interimResults = true;
  rec.continuous = false;
  let listening = false;
  const setListening = on => {
    listening = on;
    mic.classList.toggle('is-listening', on);
    mic.setAttribute('aria-pressed', on ? 'true' : 'false');
    mic.title = on ? t('voice.stop') : t('voice.mic');
    setStatus(on ? t('voice.listening') : '');
  };
  rec.onresult = e => {
    let text = '';
    let final = false;
    for (let i = e.resultIndex; i < e.results.length; i += 1) {
      text += e.results[i][0].transcript;
      if (e.results[i].isFinal) final = true;
    }
    if (inp) inp.value = text;
    if (final && text.trim()) {
      if (inp) inp.value = '';
      onSend(text.trim());
    }
  };
  rec.onend = () => setListening(false);
  rec.onerror = e => {
    setListening(false);
    if (e.error && e.error !== 'no-speech' && e.error !== 'aborted') setStatus(t('voice.error', { message: e.error }));
  };
  mic.addEventListener('click', () => {
    if (listening) { rec.stop(); return; }
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    try { rec.start(); setListening(true); } catch { /* already started */ }
  });
}
