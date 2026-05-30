// ── Portfolio Hedge (Feature 27) — hedge recommendations for saved portfolio ──
import { apiBase } from './api.js';

const _RISK_COLOR = { high: 'var(--neg)', medium: 'var(--warn)', low: 'var(--ok)' };
const _RISK_LABEL = { high: 'HIGH', medium: 'MEDIUM', low: 'LOW' };
const _TYPE_LABEL = {
  index_put:       'ATM Put',
  index_put_spread:'Put Spread',
  equity_note:     'Equity Only',
  na:              'Optional',
};

function _badge(risk) {
  const col = _RISK_COLOR[risk] || 'var(--t3)';
  return `<span style="display:inline-block;padding:2px 8px;border-radius:100px;background:${col};color:#fff;font-family:var(--fm);font-size:9px;font-weight:600;">${_RISK_LABEL[risk] || risk}</span>`;
}

function _renderItems(items) {
  const wrap = document.getElementById('ph-items');
  if (!wrap) return;
  wrap.innerHTML = items.map(item => {
    const typeLabel = _TYPE_LABEL[item.hedge_type] || item.hedge_type;
    const costLine = item.eligible && item.cost_estimate_pct > 0
      ? `<div style="margin-top:6px;font-family:var(--fm);font-size:10px;color:var(--t3);">
           Hedge type: <strong>${typeLabel}</strong> · Est. cost: <strong>${item.cost_estimate_pct.toFixed(1)}%</strong>/month of notional
         </div>`
      : '';
    const equityTag = !item.eligible
      ? `<span style="font-family:var(--fm);font-size:9px;color:var(--t3);border:1px solid var(--border);border-radius:100px;padding:1px 7px;margin-left:4px;">No F&O</span>`
      : '';
    return `
    <div class="card" style="margin-bottom:10px;padding:14px 16px;">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap;">
        <span style="font-family:var(--fm);font-size:13px;font-weight:600;">${item.instrument_id}</span>
        <span style="font-family:var(--fm);font-size:11px;color:var(--t3);">${item.allocation_pct.toFixed(0)}%</span>
        ${_badge(item.risk_level)}${equityTag}
      </div>
      <div style="font-size:12px;color:var(--t2);line-height:1.5;">${item.recommendation}</div>
      ${costLine}
    </div>`;
  }).join('');
}

export async function loadPortfolioHedge() {
  const loadingEl = document.getElementById('ph-loading');
  const emptyEl   = document.getElementById('ph-empty');
  const errorEl   = document.getElementById('ph-error');
  const contentEl = document.getElementById('ph-content');

  const _hide = el => { if (el) el.style.display = 'none'; };
  const _show = el => { if (el) el.style.display = ''; };

  _hide(emptyEl); _hide(errorEl); _hide(contentEl);
  _show(loadingEl);

  try {
    const token = sessionStorage.getItem('rita_token');
    if (!token) {
      _hide(loadingEl); _show(emptyEl);
      const msg = document.getElementById('ph-empty-msg');
      if (msg) msg.textContent = 'Sign in to see hedge analysis for your portfolio.';
      return;
    }

    const headers = { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` };
    const resp = await fetch(apiBase() + '/api/experience/fno/portfolio-hedge', { headers });

    _hide(loadingEl);

    if (resp.status === 401) {
      sessionStorage.removeItem('rita_token');
      window.location.href = '/';
      return;
    }
    if (resp.status === 404) {
      _show(emptyEl);
      return;
    }
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      _show(errorEl);
      const msg = document.getElementById('ph-error-msg');
      if (msg) msg.textContent = 'Error loading hedge analysis — ' + (err.detail || resp.statusText);
      return;
    }

    const data = await resp.json();
    const nameEl  = document.getElementById('ph-name');
    const totalEl = document.getElementById('ph-total-pct');
    if (nameEl)  nameEl.textContent  = data.portfolio_name || 'Portfolio';
    if (totalEl) totalEl.textContent = data.total_allocated_pct.toFixed(0) + '% allocated';

    const highCount = (data.recommendations || []).filter(r => r.risk_level === 'high').length;
    const badge = document.getElementById('ph-risk-badge');
    if (badge) {
      if (highCount > 0) {
        badge.textContent = highCount + ' High-Risk';
        badge.style.display = '';
      } else {
        badge.style.display = 'none';
      }
    }

    _renderItems(data.recommendations || []);
    _show(contentEl);
  } catch (e) {
    _hide(loadingEl);
    _show(errorEl);
    const msg = document.getElementById('ph-error-msg');
    if (msg) msg.textContent = 'Unable to load — ' + (e.message || 'unexpected error');
  }
}

window.loadPortfolioHedge = loadPortfolioHedge;
