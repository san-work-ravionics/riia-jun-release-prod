// ── Risk Overview — ops Risk page ─────────────────────────────────────────────
import { apiFetch } from './api.js';

async function _fetchAnalytics() {
  const token = sessionStorage.getItem('auth_token');
  const mode  = token ? 'real' : 'mock';
  const hdrs  = token ? { Authorization: `Bearer ${token}` } : {};
  return apiFetch(`/api/v1/experience/fno/portfolio-analytics?mode=${mode}`, { headers: hdrs });
}

function fmtEur(v) {
  if (v == null || isNaN(v)) return '—';
  const abs = Math.abs(v);
  const sign = v < 0 ? '-' : '';
  return sign + '€' + abs.toLocaleString('en-EU', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

function fmtNum(v, dec = 2) {
  if (v == null || isNaN(v)) return '—';
  return Number(v).toFixed(dec);
}

export async function loadRisk() {
  const strip = document.getElementById('risk-kpi-strip');
  const posWrap = document.getElementById('risk-positions-wrap');
  const stressWrap = document.getElementById('risk-stress-wrap');
  const hqWrap = document.getElementById('risk-hq-wrap');
  if (strip) strip.innerHTML = '<div class="kpi"><div class="kpi-ey">Loading…</div></div>';

  const d = await _fetchAnalytics();
  if (!d) {
    if (strip) strip.innerHTML =
      '<div class="kpi"><div class="kpi-ey">Risk Data</div><div class="kpi-val danger">Unavailable</div></div>';
    return;
  }

  const ng        = d.net_greeks || {};
  const meta      = d.portfolio_meta || {};
  const positions = d.positions || [];
  const stress    = d.stress || [];
  const hq        = (d.hedge_quality || {}).positions || [];
  const greeks    = d.greeks || [];

  const dailyTheta = greeks.reduce((s, g) => s + (g.net_theta_eur_day || 0), 0);
  const totalPnl   = positions.reduce((s, p) => s + (p.pnl || 0), 0);
  const deltaClass = ng.delta >= 0.8 ? 'ok' : ng.delta >= 0.5 ? 'warn' : 'danger';

  // ── KPI strip ──────────────────────────────────────────────────────────────
  if (strip) strip.innerHTML = `
    <div class="kpi">
      <div class="kpi-ey">Portfolio Value</div>
      <div class="kpi-val">${fmtEur(meta.total_value_eur)}</div>
      <div class="kpi-sub">${d.mode === 'real' ? 'live' : 'mock'}</div>
    </div>
    <div class="kpi">
      <div class="kpi-ey">Net Delta</div>
      <div class="kpi-val ${ng.delta != null ? deltaClass : ''}">${fmtNum(ng.delta)}</div>
      <div class="kpi-sub">portfolio exposure</div>
    </div>
    <div class="kpi">
      <div class="kpi-ey">Daily Theta</div>
      <div class="kpi-val ${dailyTheta < 0 ? 'danger' : 'ok'}">${fmtEur(dailyTheta)}</div>
      <div class="kpi-sub">EUR / day time decay</div>
    </div>
    <div class="kpi">
      <div class="kpi-ey">Net Vega</div>
      <div class="kpi-val">${fmtEur(ng.vega)}</div>
      <div class="kpi-sub">EUR per 1% vol move</div>
    </div>
    <div class="kpi">
      <div class="kpi-ey">Unrealised P&amp;L</div>
      <div class="kpi-val ${totalPnl >= 0 ? 'ok' : 'danger'}">${fmtEur(totalPnl)}</div>
      <div class="kpi-sub">across all positions</div>
    </div>`;

  // ── Positions table ────────────────────────────────────────────────────────
  if (posWrap) posWrap.innerHTML = `
    <div class="c-ey" style="margin-bottom:8px;">
      <div class="ey-d" style="background:var(--ops)"></div>Positions
    </div>
    <div class="tbl-wrap">
      <table>
        <thead><tr><th>Instrument</th><th>Value (EUR)</th><th>P&amp;L</th><th>Chg %</th><th>Delta</th></tr></thead>
        <tbody>${positions.length ? positions.map(p => {
          const g     = greeks.find(r => r.und === p.und);
          const delta = g ? fmtNum(g.delta) : '—';
          return `<tr>
            <td><span style="font-weight:600;">${p.und}</span>
                <span style="font-size:10px;color:var(--t3);display:block;">${p.type} ${p.side}</span></td>
            <td style="font-family:var(--fm);">${fmtEur(p.position_eur)}</td>
            <td style="font-family:var(--fm);color:${p.pnl >= 0 ? 'var(--build)' : 'var(--danger)'};">${fmtEur(p.pnl)}</td>
            <td style="font-family:var(--fm);color:${p.chg >= 0 ? 'var(--build)' : 'var(--danger)'};">${fmtNum(p.chg)}%</td>
            <td style="font-family:var(--fm);">${delta}</td>
          </tr>`;
        }).join('') : '<tr><td colspan="5" style="text-align:center;color:var(--t3);">No positions</td></tr>'}
        </tbody>
      </table>
    </div>`;

  // ── Stress scenarios table ─────────────────────────────────────────────────
  if (stressWrap) stressWrap.innerHTML = `
    <div class="c-ey" style="margin-bottom:8px;">
      <div class="ey-d" style="background:var(--danger,#c0392b)"></div>Stress Scenarios
    </div>
    <div class="tbl-wrap">
      <table>
        <thead><tr><th>Scenario</th><th>Move</th><th>Unhedged</th><th>Hedged</th></tr></thead>
        <tbody>${stress.length ? stress.map(s => `
          <tr>
            <td>${s.label}</td>
            <td style="font-family:var(--fm);color:${s.move_pct < 0 ? 'var(--danger)' : 'var(--build)'};">${s.move_pct > 0 ? '+' : ''}${s.move_pct}%</td>
            <td style="font-family:var(--fm);color:${s.portfolio_pnl_eur >= 0 ? 'var(--build)' : 'var(--danger)'};">${fmtEur(s.portfolio_pnl_eur)}</td>
            <td style="font-family:var(--fm);color:${s.hedged_pnl_eur >= 0 ? 'var(--build)' : 'var(--danger)'};">${fmtEur(s.hedged_pnl_eur)}</td>
          </tr>`).join('') : '<tr><td colspan="4" style="text-align:center;color:var(--t3);">No scenarios</td></tr>'}
        </tbody>
      </table>
    </div>`;

  // ── Hedge quality chips ────────────────────────────────────────────────────
  if (hqWrap) {
    const tierColor = { A: 'var(--build)', B: 'var(--sense)', C: 'var(--warn)', D: 'var(--danger)' };
    hqWrap.innerHTML = hq.length ? `
      <div class="c-ey" style="margin-bottom:8px;">
        <div class="ey-d" style="background:var(--accelerate)"></div>Hedge Quality
      </div>
      <div style="display:flex;flex-wrap:wrap;gap:8px;">
        ${hq.map(h => `
          <div style="padding:8px 12px;border-radius:6px;background:var(--bg2);border:1px solid var(--bdr);min-width:140px;">
            <div style="font-size:12px;font-weight:600;">${h.instrument}</div>
            <div style="font-size:11px;margin-top:3px;display:flex;align-items:center;gap:6px;">
              <span style="font-family:var(--fm);font-size:15px;font-weight:700;color:${tierColor[h.hqs_tier] || 'var(--t2)'};">${h.hqs}</span>
              <span style="color:${tierColor[h.hqs_tier] || 'var(--t3)'};">Tier ${h.hqs_tier}</span>
              <span style="color:var(--t3);">${h.hedged ? '· hedged' : '· unhedged'}</span>
            </div>
            ${h.strategy ? `<div style="font-size:10px;color:var(--t3);margin-top:2px;">${h.strategy}${h.coverage_pct != null ? ' · ' + h.coverage_pct + '% coverage' : ''}</div>` : ''}
          </div>`).join('')}
      </div>` : '';
  }
}
