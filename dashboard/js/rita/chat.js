// ── Chat ───────────────────────────────────────────────────
import { api } from './api.js';
let _chatConfs = [], _chatLats = [];

function _readGoalContext() {
  const portfolio = parseFloat(document.getElementById('inp-portfolio')?.value) || 1_000_000;
  const target    = parseFloat(document.getElementById('inp-target')?.value)    || null;
  const horizon   = parseInt(document.getElementById('inp-horizon')?.value)     || null;
  const riskEl    = document.querySelector('input[name="inp-risk"]:checked');
  const risk      = riskEl ? riskEl.value : null;
  return { portfolio_inr: portfolio, target_return_pct: target, time_horizon_days: horizon, risk_tolerance: risk };
}

function _fmtInr(n) {
  if (n >= 1_00_00_000) return '₹' + (n / 1_00_00_000).toFixed(1) + 'Cr';
  if (n >= 1_00_000)    return '₹' + (n / 1_00_000).toFixed(1) + 'L';
  return '₹' + n.toLocaleString('en-IN');
}

// Wire up textarea: auto-resize + Enter to send
(function () {
  const ta = document.getElementById('chat-ta');
  if (!ta) return;
  ta.addEventListener('input', () => {
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 80) + 'px';
  });
  ta.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChatMsg(); }
  });
})();

export function refreshChatChips() {
  const inst = (localStorage.getItem('ritaInstrument') || 'NIFTY').toUpperCase();
  document.querySelectorAll('.chat-chip[data-tmpl]').forEach(btn => {
    btn.textContent = btn.dataset.tmpl.replace(/\{inst\}/g, inst);
  });
}

export function useChip(btn) {
  const ta = document.getElementById('chat-ta');
  if (!ta) return;
  const inst = (localStorage.getItem('ritaInstrument') || 'NIFTY').toUpperCase();
  // data-query: fully resolved (dynamic chips from API); data-tmpl: static template with {inst}; fallback: textContent
  const raw = btn.dataset.query || btn.dataset.tmpl || btn.textContent;
  ta.value = raw.replace(/\{inst\}/g, inst).trim();
  ta.style.height = 'auto';
  ta.style.height = Math.min(ta.scrollHeight, 80) + 'px';
  ta.focus();
  sendChatMsg();
}

export async function sendChatMsg() {
  const ta = document.getElementById('chat-ta');
  const sendBtn = document.getElementById('chat-send');
  const query = (ta.value || '').trim();
  if (!query) return;

  ta.value = '';
  ta.style.height = 'auto';
  sendBtn.disabled = true;

  appendChatMsg('user', query);
  const tid = appendTyping();

  const ctx = _readGoalContext();
  const t0 = Date.now();
  try {
    const data = await api('/api/v1/chat', 'POST', {
      query,
      instrument:         (localStorage.getItem('ritaInstrument') || 'NIFTY').toUpperCase(),
      portfolio_inr:      ctx.portfolio_inr,
      target_return_pct:  ctx.target_return_pct,
      time_horizon_days:  ctx.time_horizon_days,
    });
    removeTyping(tid);
    appendRitaMsg(data, Date.now() - t0);
    updateChatStats(data.confidence, data.latency_ms ?? (Date.now() - t0));
  } catch (e) {
    removeTyping(tid);
    appendChatError('Could not reach RITA API. Make sure the server is running.');
  } finally {
    sendBtn.disabled = false;
    ta.focus();
  }
}

function appendChatMsg(role, text) {
  const box = document.getElementById('chat-messages');
  const div = document.createElement('div');
  div.className = 'cmsg ' + role;
  const bubble = document.createElement('div');
  bubble.className = 'cbubble';
  bubble.textContent = text;
  div.appendChild(bubble);
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function appendTyping() {
  const box = document.getElementById('chat-messages');
  const id = 'typing-' + Date.now();
  const div = document.createElement('div');
  div.className = 'cmsg rita';
  div.id = id;
  div.innerHTML = '<div class="cbubble"><span class="tdot"></span><span class="tdot"></span><span class="tdot"></span></div>';
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
  return id;
}

function removeTyping(id) {
  const el = document.getElementById(id);
  if (el) el.remove();
}

function appendRitaMsg(data, elapsed) {
  const box = document.getElementById('chat-messages');
  const div = document.createElement('div');
  div.className = 'cmsg rita';

  const conf = typeof data.confidence === 'number' ? data.confidence : null;
  const lat = data.latency_ms ?? elapsed;
  const confPct = conf !== null ? Math.round(conf * 100) + '%' : '—';
  const confCls = conf === null ? '' : conf >= 0.6 ? 'pos' : conf >= 0.42 ? 'neu' : 'neg';
  const intent = (data.intent || '').replace(/_/g, ' ');

  div.innerHTML = `
    <div class="cbubble">${chatMd(escChatHtml(data.response || '(no response)'))}</div>
    <div style="display:flex;gap:8px;align-items:center;margin-top:3px;flex-wrap:wrap">
      ${intent ? `<span style="font-family:var(--fm);font-size:9px;text-transform:uppercase;letter-spacing:.05em;color:var(--t3);background:var(--surface2);border:1px solid var(--border);border-radius:3px;padding:1px 5px">${escChatHtml(intent)}</span>` : ''}
      ${conf !== null ? `<span style="font-family:var(--fm);font-size:9px;color:var(--${confCls === 'pos' ? 'build' : confCls === 'neu' ? 'run' : confCls === 'neg' ? 'danger' : 't3'})">${confPct} conf</span>` : ''}
      ${lat ? `<span style="font-family:var(--fm);font-size:9px;color:var(--t4)">${lat}ms</span>` : ''}
    </div>`;

  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function appendChatError(msg) {
  const box = document.getElementById('chat-messages');
  const div = document.createElement('div');
  div.className = 'cmsg rita';
  div.innerHTML = `<div class="cbubble" style="background:var(--danger-bg);border-color:var(--danger-bd);color:var(--danger)">${escChatHtml(msg)}</div>`;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function escChatHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function chatMd(s) {
  // Basic markdown: **bold**, *italic*, newlines
  return s
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/\n/g, '<br>');
}

export function showAlerts(alerts) {
  const box = document.getElementById('chat-messages');
  if (!box || !alerts || !alerts.length) return;
  alerts.forEach(a => {
    const div = document.createElement('div');
    div.className = 'cmsg rita';
    const isDanger = a.severity === 'danger';
    div.innerHTML = `<div class="cbubble" style="background:var(--${isDanger ? 'danger' : 'warn'}-bg,#fff7ed);border-color:var(--${isDanger ? 'danger' : 'warn'}-bd,#fed7aa);color:var(--${isDanger ? 'danger' : 'warn'})">⚠ ${chatMd(escChatHtml(a.message))}</div>`;
    box.appendChild(div);
  });
  box.scrollTop = box.scrollHeight;
}

export function updateChips(chips) {
  const box = document.getElementById('chat-chips');
  const status = document.getElementById('chip-status');
  if (!box || !chips || !chips.length) return;
  box.innerHTML = chips.map(c =>
    `<button class="chat-chip" onclick="useChip(this)" data-query="${escChatHtml(c.query)}">${escChatHtml(c.label)}</button>`
  ).join('');
  if (status) status.textContent = 'live';
}

export function clearChat() {
  const box = document.getElementById('chat-messages');
  const ctx = _readGoalContext();
  const inst = (localStorage.getItem('ritaInstrument') || 'NIFTY');
  const parts = [`Hi! Ask me about the ${inst} instrument — returns, risk, allocation, or stress scenarios.`];
  if (ctx.portfolio_inr) parts.push(`Portfolio: **${_fmtInr(ctx.portfolio_inr)}**`);
  if (ctx.risk_tolerance) parts.push(`Risk: **${ctx.risk_tolerance}**`);
  if (ctx.target_return_pct) parts.push(`Target: **${ctx.target_return_pct}% CAGR**`);
  if (ctx.time_horizon_days) parts.push(`Horizon: **${Math.round(ctx.time_horizon_days / 30)}m**`);
  const welcome = parts.length > 1
    ? parts[0] + ' I\'ve loaded your goal context: ' + parts.slice(1).join(' · ') + '.'
    : parts[0] + ' Market sentiment, return estimates, allocation advice, or stress scenarios.';
  box.innerHTML = `<div class="cmsg rita"><div class="cbubble">${chatMd(escChatHtml(welcome))}</div></div>`;
  _chatConfs = []; _chatLats = [];
  const qEl = document.getElementById('cs-count');
  const cEl = document.getElementById('cs-conf');
  const lEl = document.getElementById('cs-lat');
  if (qEl) qEl.textContent = '0';
  if (cEl) cEl.textContent = '—';
  if (lEl) lEl.textContent = '—';
}

function updateChatStats(conf, lat) {
  if (conf != null) _chatConfs.push(conf);
  if (lat != null) _chatLats.push(lat);
  const n = _chatConfs.length;
  const avgConf = n > 0 ? (_chatConfs.reduce((a, b) => a + b, 0) / n * 100).toFixed(0) + '%' : '—';
  const avgLat = _chatLats.length > 0 ? Math.round(_chatLats.reduce((a, b) => a + b, 0) / _chatLats.length) + 'ms' : '—';
  const qEl = document.getElementById('cs-count');
  const cEl = document.getElementById('cs-conf');
  const lEl = document.getElementById('cs-lat');
  if (qEl) qEl.textContent = n;
  if (cEl) cEl.textContent = avgConf;
  if (lEl) lEl.textContent = avgLat;
}
