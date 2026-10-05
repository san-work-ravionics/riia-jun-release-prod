// ── FnO Trade Analysis — analytics panels (F42 Phase 3) ──────────────────────────
// Fills the five panels on the Trade Analysis page (overtrading, build-up, market-turn, margin
// trap, suggestions) plus the reconciliation strip.  Six read-only Experience GETs run IN PARALLEL
// (Promise.allSettled); every panel renders independently and fails to "—" on its own.
//   GET /api/v1/experience/fno/trade-analysis/analytics/{foundation,overtrading,buildup,
//       market-turn,margin-trap,suggestions}
// PERSONAL DATA: the payloads are the caller's own rows.  Every server string goes through _esc;
// numbers go through _num / _pnl / _pct.  Descriptive wording only: no causal claims, no advice.

import { api } from './api.js';
import { setEl } from '../shared/utils.js';
import { mkChart, destroyChart } from '../shared/charts.js';
import { _esc, _num, _pnl, taGetFilters } from './trade-analysis.js';

const _BASE = '/api/v1/experience/fno/trade-analysis/analytics/';
const _DISCLAIMER = 'Observations from your own imported history, not investment advice or a forecast.';
const _REASONS = {
  no_data: 'Import your Console files on the Import panel first.',
  no_trades_in_scope: 'No option fills match the selected underlying, expiry and date filters.',
  no_ledger: 'No usable ledger cash history; cash metrics are omitted.',
  spot_unavailable: 'No spot price history for this underlying; the turn analysis is omitted.',
  no_pnl_sheet: 'No P&L sheet imported.',
  no_timestamps: 'Needs execution timestamps, which are missing in too many fills.',
};
const _PANELS = ['overtrading', 'buildup', 'marketturn', 'margintrap', 'suggestions'];
const _ENDPOINTS = {
  foundation: 'foundation', overtrading: 'overtrading', buildup: 'buildup',
  marketturn: 'market-turn', margintrap: 'margin-trap', suggestions: 'suggestions',
};

let _from = '';
let _estimate = null;   // null = server default; set once the user toggles the checkbox
let _seq = 0;

// ── tiny html helpers (all inputs escaped or numeric) ─────────────────────────────

const _pct = v => v == null ? '—' : `${_num(v, 2)}%`;
const _cls = v => v == null ? '' : (Number(v) >= 0 ? 'pos' : 'neg');
const _dash = v => (v == null || v === '') ? '—' : _esc(v);
const _badge = kind => `<span style="font-family:var(--fm);font-size:9px;padding:1px 6px;border-radius:8px;`
  + `margin-left:6px;background:${kind === 'estimated' ? 'rgba(146,72,10,.12)' : 'rgba(26,107,60,.12)'};`
  + `color:${kind === 'estimated' ? '#92480A' : '#1A6B3C'}">${_esc(kind)}</span>`;
const _kpi = (label, valueHtml, cls = '', sub = '') => `<div class="kpi"><div class="kpi-label">${_esc(label)}</div>`
  + `<div class="kpi-value ${cls}">${valueHtml}</div>${sub ? `<div class="kpi-sub">${sub}</div>` : ''}</div>`;
const _kpis = items => `<div class="kpi-row c4">${items.join('')}</div>`;
const _th = c => `<th style="padding:6px 8px;text-align:left;font-weight:700;white-space:nowrap">${_esc(c)}</th>`;
const _td = c => `<td style="padding:4px 8px;white-space:nowrap">${c}</td>`;
const _tbl = (title, cols, rows, empty = 'No data') => `<div style="margin:10px 0 4px;font-weight:700;font-size:12px">${_esc(title)}</div>`
  + `<div class="tbl-wrap" style="max-height:200px"><table style="width:100%;border-collapse:collapse;font-size:12px"><thead><tr>`
  + `${cols.map(_th).join('')}</tr></thead><tbody>`
  + (rows.length ? rows.map(r => `<tr>${r.map(_td).join('')}</tr>`).join('')
    : `<tr><td colspan="${cols.length}" style="color:var(--t3);text-align:center">${_esc(empty)}</td></tr>`)
  + '</tbody></table></div>';
const _pnlCell = v => `<span class="${_cls(v)}">${_pnl(v)}</span>`;
const _list = items => `<ul style="margin:4px 0 4px 18px;padding:0">${(items || []).map(i => `<li>${_esc(i)}</li>`).join('')}</ul>`;
const _note = text => `<div class="kpi-sub" style="margin:6px 0">${_esc(text)}</div>`;
const _unavail = (d) => `<div class="kpi-sub">${_esc(d.message || _REASONS[d.reason] || 'Not available.')}</div>`;

function _quality(d) {
  const q = d.quality || {};
  return _note(`Fills in scope ${_num(q.fills_in_scope)} · timestamp coverage ${_pct(q.timestamp_coverage_pct)}`
    + ` · spot days missing ${_num(q.spot_days_missing)} · spot last ${_dash(q.spot_last_date)}`
    + ` · expiry-estimated lots ${_num(q.expiry_estimated_lots)} · expiry unknown lots ${_num(q.expiry_unknown_lots)}`);
}

function _infoBlock(label, b) {
  const x = (b && b.info) || b || {};
  if (!x.definition && !(x.assumptions || []).length) return '';
  return `<div style="margin:6px 0"><b>${_esc(label)}</b> ${_esc(x.definition || '')}${_list(x.assumptions)}</div>`;
}

function _defs(d, blocks) {
  const t = d.tags || {};
  return `<div class="kpi-sub" style="margin:6px 0 10px;padding:8px 10px;border:1px dashed var(--border);border-radius:6px">`
    + `<div>${_esc(d.definition || '')}</div>${_list(d.assumptions)}`
    + `<div>Measured: ${_esc((t.measured || []).join(', ') || '—')}</div>`
    + `<div>Estimated: ${_esc((t.estimated || []).join(', ') || '—')}</div>`
    + `${blocks.map(([l, b]) => _infoBlock(l, b)).join('')}</div>`;
}

function _setPanel(key, bodyHtml, defHtml) {
  setEl(`ta-an-${key}-body`, bodyHtml);
  setEl(`ta-an-${key}-def`, defHtml || '');
}

function _fail(key) {
  setEl(`ta-an-${key}-body`, '<div class="kpi-sub">— could not be loaded</div>');
  setEl(`ta-an-${key}-def`, '');
}

function _chart(id, cfg) {
  if (typeof Chart === 'undefined') return;
  destroyChart(id);
  if (cfg) mkChart(id, cfg);
}

const _axis = { grid: { color: 'rgba(0,0,0,.035)' }, ticks: { font: { family: 'IBM Plex Mono, monospace', size: 10 } } };
const _opts = (extra = {}) => ({ responsive: true, maintainAspectRatio: false, scales: { x: _axis, y: _axis }, ...extra });

// ── panels ──────────────────────────────────────────────────────────────────────────

function _renderOvertrading(d) {
  _chart('ta-cv-weekly', null);
  if (!d.available) { _setPanel('overtrading', _unavail(d)); return; }
  const a = d.activity || {}, w = d.winloss || {}, c = d.churn || {}, ch = d.charges || {}, h = d.holding || {};
  const b = d.bursts || {};
  const fpd = a.fills_per_day || {};
  const kp = _kpis([
    _kpi('Fills', _num(a.fills_total), '', `${_num(a.orders_total)} orders`),
    _kpi('Active days', _num(a.active_days), '', `of ${_num(a.market_days)} market days`),
    _kpi('Fills / active day', _num(fpd.median, 1), '', `mean ${_num(fpd.mean, 1)} · p90 ${_num(fpd.p90, 1)} · max ${_num(fpd.max)}`),
    _kpi('Same-day churn', _pct(c.churn_qty_pct), '', `${_num(c.same_day_trades)} trades · gross ${_pnl(c.churn_pnl)}`),
    _kpi('Charges % of gross', _pct(ch.pct_of_gross) + _badge('estimated'), '',
      ch.net_gross_negative ? 'gross P&L not positive' : `est. ${_pnl(ch.est_window)}`),
    _kpi('Trades to cover charges', _num(ch.breakeven_trades_needed), '', `per trade ${_pnl(ch.per_closed_trade)}`),
    _kpi('Win rate', _pct(w.win_rate), '', `${_num(w.wins)} W · ${_num(w.losses)} L · ${_num(w.scratch)} scratch`),
    _kpi('Payoff / expectancy', `${_num(w.payoff, 2)} / ${_pnl(w.expectancy)}`, _cls(w.expectancy),
      `breakeven win rate ${_pct(w.breakeven_win_rate)}`),
  ]);
  const byExp = _tbl('By expiry', ['Expiry', 'Fills', 'Closed', 'Win rate', 'P&L'],
    (d.by_expiry || []).map(r => [_esc(r.key), _num(r.fills), _num(r.closed_trades), _pct(r.win_rate), _pnlCell(r.pnl)]));
  const byUnd = _tbl('By underlying', ['Underlying', 'Fills', 'Closed', 'Win rate', 'P&L'],
    (d.by_underlying || []).map(r => [_esc(r.key), _num(r.fills), _num(r.closed_trades), _pct(r.win_rate), _pnlCell(r.pnl)]));
  const hold = _tbl(`Holding time${h.median_minutes != null ? ` (same-day median ${_num(h.median_minutes, 1)} min)` : ''}`,
    ['Bucket', 'Closed trades'], (h.buckets || []).map(r => [_esc(r.label), _num(r.count)]));
  const burst = b.available
    ? _tbl(`Bursts (${_num(b.count)}) · re-entries within window after a loss: ${_num((b.reentries_after_loss || {}).count)} `
      + `(P&L ${_pnl((b.reentries_after_loss || {}).pnl)})`,
    ['Date', 'Start', 'Fills', 'Symbols', 'P&L'],
    (b.top || []).map(r => [_esc(r.date), _dash(r.start), _num(r.fills), _num(r.symbols_count), _pnlCell(r.pnl)]), 'No bursts')
    : _note(`Bursts and re-entries: ${_REASONS[b.reason] || 'not available'}`);
  const week = _tbl('Per week', ['Week', 'Fills', 'Active days', 'Closed trades'],
    (d.weekly || []).map(r => [_esc(r.week), _num(r.fills), _num(r.active_days), _num(r.closed_trades)]));
  const side = _tbl('Win / loss by side', ['Side', 'Closed', 'Win rate', 'P&L'],
    (w.by_side || []).map(r => [_esc(r.key), _num(r.n), _pct(r.win_rate), _pnlCell(r.pnl)]));
  const mo = w.measured_only || {};
  const ext = _note(`Measured only (no expiry estimate): ${_num(mo.n)} trades · win rate ${_pct(mo.win_rate)} · P&L ${_pnl(mo.pnl)}`
    + ` · largest win ${_pnl(w.largest_win)} · largest loss ${_pnl(w.largest_loss)} · longest losing streak ${_num(w.max_loss_streak)}`);
  _setPanel('overtrading', _quality(d) + kp + ext + byExp + byUnd + hold + burst + week + side,
    _defs(d, [['Activity.', a], ['Holding time.', h], ['Churn.', c], ['Bursts and re-entries.', b], ['Charges (estimate).', ch], ['Win / loss.', w]]));
  const weeks = d.weekly || [];
  _chart('ta-cv-weekly', weeks.length ? {
    type: 'bar',
    data: { labels: weeks.map(r => r.week), datasets: [
      { label: 'Fills', data: weeks.map(r => r.fills), backgroundColor: 'rgba(0,86,184,.55)', borderRadius: 3 },
      { label: 'Closed trades', data: weeks.map(r => r.closed_trades), backgroundColor: 'rgba(26,107,60,.55)', borderRadius: 3 }] },
    options: _opts(),
  } : null);
}

function _renderBuildup(d) {
  _chart('ta-cv-buildup', null);
  if (!d.available) { _setPanel('buildup', _unavail(d)); return; }
  const av = d.averaging || {}, ct = d.chain_totals || {}, ev = d.events || {}, lots = d.lots || {};
  const kp = _kpis([
    _kpi('Adverse adds', _num(av.adverse_add_fills), '', `${_pct(av.share_of_entries_pct)} of entries · ${_num(av.adverse_add_units)} units`),
    _kpi('Closed P&L of adverse adds', _pnl(av.adverse_add_closed_pnl), _cls(av.adverse_add_closed_pnl),
      `${_num(av.adverse_add_open_units)} units still open (unpriced)`),
    _kpi('Max adds in one chain', _num(ct.max_adds), '', `${_num(ct.with_adverse_add)} of ${_num(ct.count)} chains had an adverse add`),
    _kpi('Adds after adverse spot move', av.spot_adverse_adds == null ? '—' : _num(av.spot_adverse_adds), '', 'needs spot data'),
  ]);
  const chains = _tbl('Worst position chains (flat to flat)',
    ['Symbol', 'Expiry', 'Side', 'Opened', 'Closed', 'Peak qty', 'Adds', 'Adverse adds', 'P&L (measured)', 'Status'],
    (d.chains || []).map(r => [_esc(r.symbol), _dash(r.expiry_ym), _esc(r.side), _dash(r.open_date), _dash(r.close_date),
      _num(r.peak_qty), _num(r.adds), _num(r.adverse_adds), _pnlCell(r.pnl_measured),
      r.still_open ? 'open' : (r.pnl_estimated != null ? `expiry est. ${_pnl(r.pnl_estimated)}` : 'closed')]));
  const evt = _tbl('Fill classes', ['Open new', 'Scale in', 'Scale out', 'Close', 'Flip'],
    [[_num(ev.open_new), _num(ev.scale_in), _num(ev.scale_out), _num(ev.close), _num(ev.flip)]]);
  const lotNote = _note(lots.lots_available ? `Lots from the Kite master (${_esc(lots.lots_basis)}, ${_pct(lots.coverage_pct)} symbols)`
    : 'Lots unavailable (Kite master not reachable): quantities shown in units.');
  _setPanel('buildup', _quality(d) + kp + chains + evt + lotNote,
    _defs(d, [['Adverse adds.', av], ['Chains.', d.chains_info], ['Timeline.', d.timeline_info]]));
  const byDate = {};
  (d.timeline || []).forEach(r => {
    const x = byDate[r.date] || (byDate[r.date] = { l: 0, s: 0 });
    x.l += r.long_units || 0;
    x.s += r.short_units || 0;
  });
  const days = Object.keys(byDate).sort();
  _chart('ta-cv-buildup', days.length ? {
    type: 'bar',
    data: { labels: days, datasets: [
      { label: 'Long units (EOD)', data: days.map(k => byDate[k].l), backgroundColor: 'rgba(26,107,60,.6)' },
      { label: 'Short units (EOD)', data: days.map(k => -byDate[k].s), backgroundColor: 'rgba(155,28,28,.6)' }] },
    options: _opts({ scales: { x: { ..._axis, stacked: true }, y: { ..._axis, stacked: true } } }),
  } : null);
}

function _renderMarketTurn(d) {
  _chart('ta-cv-turn', null);
  if (!d.available) { _setPanel('marketturn', _unavail(d)); return; }
  const k = d.kpis || {}, sp = d.spot || {};
  const kp = _kpis([
    _kpi('Reversal days', _num(k.n_turn_days), '', `${_num(k.n_big_move_days)} big-move days`),
    _kpi('Adverse-exposed', _pct(k.adverse_exposed_pct), '', `${_num(k.n_adverse_exposed)} of ${_num(k.n_turn_days)} reversal days`),
    _kpi('Realised on adverse turns', _pnl(k.realised_pnl_turn_adverse), _cls(k.realised_pnl_turn_adverse),
      `carried in ${_pnl(k.realised_from_carried_in)} · opened that day ${_pnl(k.realised_from_opened_that_day)}`),
    _kpi('Avg realised, other days', _pnl(k.avg_realised_other_days), _cls(k.avg_realised_other_days)),
  ]);
  const worst = _tbl('Largest realised-loss days (drawdown days)', ['Date', 'Realised P&L', 'Open at end of day'],
    (d.worst_days || []).map(r => [_esc(r.date), _pnlCell(r.realised_pnl_day), _esc((r.open_symbols || []).join(', '))]), 'No loss days');
  let turn = '';
  if (sp.available) {
    turn = _tbl('Big-move days', ['Date', 'Underlying', 'Spot close', 'Move %', 'Reversal', 'Positioning in', 'Adverse', 'Realised P&L', 'Delta-1 bound (est.)', 'Open in'],
      (d.turn_days || []).map(r => [_esc(r.date), _esc(r.underlying), _num(r.spot_close, 2), _num(r.ret_pct, 2),
        r.is_reversal ? 'yes' : 'no', `${_esc(r.bias_label)} (${_num(r.bias_units_in)})`, r.adverse_exposed ? 'yes' : 'no',
        _pnlCell(r.realised_pnl_day), _pnlCell(r.delta1_bound_pnl), _esc((r.open_symbols_in || []).join(', '))]), 'No big-move days')
      + _note(d.delta1_note || '')
      + (sp.stale ? _note('Spot history looks stale: the last close is more than a few days old.') : '');
  } else {
    turn = _unavail({ reason: 'spot_unavailable' });
  }
  _setPanel('marketturn', _quality(d) + kp + turn + worst, _defs(d, [['Market turns.', d.info]]));
  const s = (d.series || [])[0];
  _chart('ta-cv-turn', s && s.dates.length ? {
    data: { labels: s.dates, datasets: [
      { type: 'line', label: s.underlying + ' close', data: s.spot_close, borderColor: '#0056B8', borderWidth: 1.5, pointRadius: 1, yAxisID: 'y', order: 1 },
      { type: 'bar', label: 'Positioning bias (units)', data: s.bias_units, backgroundColor: 'rgba(146,72,10,.45)', yAxisID: 'y1', order: 2 }] },
    options: _opts({ scales: { x: _axis, y: { ..._axis, position: 'left' }, y1: { ..._axis, position: 'right', grid: { drawOnChartArea: false } } } }),
  } : null);
}

function _renderMarginTrap(d) {
  _chart('ta-cv-cash', null);
  if (!d.available) { _setPanel('margintrap', _unavail(d)); return; }
  const l = d.ledger || {}, c = d.cash || {}, t = d.trap || {}, st = d.stops || {}, ex = d.exposure || {};
  const worst = (d.debit_streaks || []).reduce((m, r) => Math.max(m, r.days || 0), 0);
  const g = t.loss_growth_est;
  const stop1 = (st.rows || [])[0] || {};
  const cashKpis = l.available ? [
    _kpi('Lowest cash', _pnl(c.min), _cls(c.min), `on ${_esc(c.min_date || '—')}`),
    _kpi('Low-cash days', _num(c.days_below_threshold), '', `below ${_num(c.threshold)} · ${_num(c.days_negative)} negative`),
    _kpi('Worst debit streak', `${_num(worst)} days`, '', `${_num((d.debit_streaks || []).length)} streaks`),
    _kpi('Low-cash days with open losers (proxy)', _num(t.days) + _badge('estimated'), '',
      g ? `loss ${_pnl(g.loss_at_first_trap_est)} at first such day, ${_pnl(g.final_closed_pnl)} when closed` : 'no loss-growth sample'),
  ] : [];
  const kp = _kpis([...cashKpis, _kpi('Stop what-if saving', _pnl(stop1.saved_if_stopped) + _badge('estimated'), '',
    `at ${_num(stop1.multiple, 2)}x premium · ${_num(stop1.n_exceeded)} trades`)]);
  const ledgerNote = l.available
    ? _note(`Cash is MEASURED from the ledger (account-wide, settled cash only; sign auto-detected, match ${_pct(l.balance_sign_match_pct)}). `
      + `${_num(l.ledger_gap_days)} carried-forward days · ${_num(l.ordering_ambiguous_days)} ambiguous-order days. `
      + `Exposure proxy covers in-scope symbols only: peak short notional ${_pnl(ex.peak_short_notional_proxy)} (estimate, not margin).`)
    : _unavail(d);
  const streaks = l.available ? _tbl('Debit streaks', ['From', 'To', 'Days', 'Net outflow', 'Cash at end'],
    (d.debit_streaks || []).map(r => [_esc(r.start), _esc(r.end), _num(r.days), _pnl(r.net_outflow), _pnl(r.cash_at_end)]), 'No streaks') : '';
  const traps = l.available ? _tbl('Low-cash days with open losers (proxy; no causal claim)',
    ['Date', 'Cash', 'Open losers', 'Short notional proxy', 'Proxy / cash', 'Known loss (est.)'],
    (t.days_list || []).map(r => [_esc(r.date), _pnl(r.cash), _num(r.open_losers_count), _num(r.short_notional_proxy),
      _num(r.proxy_to_cash_ratio, 2), _pnlCell(r.known_loss_est)]), 'No such days') : '';
  const stops = _tbl('Planned vs actual: stop at a multiple of premium (closed short trades)',
    ['Multiple', 'Trades beyond', 'Loss beyond stop', 'Saved if stopped (est.)', '% of total loss', 'Open beyond (est.)'],
    (st.rows || []).map(r => [`${_num(r.multiple, 2)}x`, _num(r.n_exceeded), _pnl(r.realised_loss_exceeding),
      _pnlCell(r.saved_if_stopped), _pct(r.share_of_total_loss_pct), `${_num(r.open_beyond_n)} · ${_pnl(r.open_beyond_excess_est)}`]))
    + _note(`${_num(st.long_closed_excluded)} closed long trades are excluded (loss bounded by premium). One-sided: whipsaw stops and slippage cannot be seen.`);
  _setPanel('margintrap', _quality(d) + kp + ledgerNote + streaks + traps + stops,
    _defs(d, [['Cash and streaks.', c], ['Low-cash days with open losers.', t], ['Planned vs actual stops.', st]]));
  const cs = d.cash_series || [];
  _chart('ta-cv-cash', l.available && cs.length ? {
    type: 'line',
    data: { labels: cs.map(r => r.date), datasets: [
      { label: 'Ledger cash', data: cs.map(r => r.cash), borderColor: '#0056B8', borderWidth: 1.5, pointRadius: 1, fill: false },
      { label: 'Low-cash threshold', data: cs.map(() => c.threshold), borderColor: '#9B1C1C', borderWidth: 1, borderDash: [6, 4], pointRadius: 0, fill: false }] },
    options: _opts(),
  } : null);
}

function _ruleCard(r) {
  const w = r.what_if;
  const p = r.parameter;
  const status = r.status === 'applicable' ? '' : ' (' + r.status.replace('_', ' ') + ')';  // escaped at use
  const wi = w ? `<div>Had this applied: baseline ${_pnl(w.baseline_pnl)} → ${_pnl(w.whatif_pnl)} `
    + `(<span class="${_cls(w.delta)}">${_pnl(w.delta)}</span>) · ${_num(w.trades_removed)} entries removed · `
    + `${_num(w.units_removed, 0)} units · ${_num(w.closed_trades_affected)} closed trades affected`
    + ` · ${_num(w.open_units_vetoed, 0)} open units vetoed</div>` : '';
  const ev = (r.evidence || []).map(e => `<li>${_esc(e.label)}: ${_dash(e.value)} <span style="color:var(--t3)">(${_esc(e.source)})</span></li>`).join('');
  const vs = (r.variants || []).length ? _tbl('Other stop multiples', ['Multiple', 'Trades beyond', 'Saved (est.)'],
    r.variants.map(v => [`${_num(v.multiple, 2)}x`, _num(v.n_exceeded), _pnlCell(v.saved_if_stopped)])) : '';
  return `<div class="kpi" style="margin:10px 0"><div class="kpi-label">${_esc(r.title)}${_esc(status)}</div>`
    + `${p ? `<div class="kpi-sub">Parameter: ${_esc(p.name)} = ${_dash(p.value)} ${_esc(p.unit)}${p.lots != null ? ` (~${_num(p.lots, 1)} lots)` : ''}</div>` : ''}`
    + `<div class="kpi-sub">Basis: ${_esc(r.threshold_basis)}</div>${wi}`
    + `<ul style="margin:4px 0 4px 18px;padding:0;font-size:12px">${ev}</ul>${vs}`
    + `<div class="kpi-sub">${_list(r.caveats)}</div></div>`;
}

function _renderSuggestions(d) {
  const disc = `<div class="kpi-sub" style="font-weight:700;margin-bottom:8px">${_esc(d.disclaimer || _DISCLAIMER)}</div>`;
  if (!d.available) { _setPanel('suggestions', disc + _unavail(d)); return; }
  const cb = d.combined || {};
  const cw = cb.what_if || {};
  const smp = d.sample || {};
  const kp = _kpis([
    _kpi('Baseline closed P&L', _pnl(d.baseline_pnl), _cls(d.baseline_pnl), `${_num(smp.closed_trades)} closed trades (min ${_num(smp.min_required)})`),
    _kpi('Combined entry what-if', _pnl(cw.delta), _cls(cw.delta), `would give ${_pnl(cw.whatif_pnl)} · rules: ${_esc((cb.rules_included || []).join(', ') || '—')}`),
    _kpi('Stop what-if add-on', _pnl(cb.stop_addon) + _badge('estimated'), '', `combined with stop ${_pnl(cb.combined_with_stop)}`),
  ]);
  const obs = (d.observations || []).length
    ? `<div style="margin:8px 0"><b>Observations</b><ul style="margin:4px 0 4px 18px;padding:0">${(d.observations || []).map(o => `<li>${_esc(o.text)}</li>`).join('')}</ul></div>` : '';
  _setPanel('suggestions', disc + _quality(d) + kp + obs + (d.rules || []).map(_ruleCard).join(''),
    _defs(d, [['Combined.', cb]]));
}

function _renderFoundation(d) {
  if (!d.available) { setEl('ta-an-recon', _unavail(d)); return; }
  const r = d.reconciliation || {};
  const t = r.totals || {};
  const head = `<div>Reconciliation: ${_num(t.n_symbols_ok)} of ${_num(t.symbols)} symbols within tolerance; total gap ${_pnl(t.gap_measured)}`
    + ` (expiry estimate explains ${_pnl(t.expiry_estimate_explains)})</div>`;
  const rows = (r.rows || []).map(x => [_esc(x.symbol), _pnl(x.fifo_measured), _pnl(x.fifo_expiry_estimate), _pnl(x.sheet_realised),
    _pnlCell(x.gap_measured), _pnlCell(x.gap_with_estimate), _num(x.fifo_open_qty), _dash(x.sheet_open_qty),
    _num(x.intrinsic_px, 2), _num(x.sheet_implied_px, 2), _esc((x.causes || []).join(', '))]);
  setEl('ta-an-recon', head + `<details><summary style="cursor:pointer">Show per-symbol reconciliation</summary>`
    + _tbl('FIFO vs P&L sheet (gaps are shown, never hidden)',
      ['Symbol', 'FIFO measured', 'FIFO expiry est.', 'Sheet realised', 'Gap', 'Gap after estimate', 'FIFO open', 'Sheet open', 'Intrinsic px', 'Sheet-implied px', 'Causes'], rows)
    + `${_infoBlock('Reconciliation.', r)}</details>`);
}

const _RENDER = {
  foundation: _renderFoundation, overtrading: _renderOvertrading, buildup: _renderBuildup,
  marketturn: _renderMarketTurn, margintrap: _renderMarginTrap, suggestions: _renderSuggestions,
};

function _query() {
  const f = taGetFilters();
  const qs = new URLSearchParams({ underlying: f.underlying || 'ALL' });
  if (f.month) qs.set('expiry_month', f.month);
  if (_from) qs.set('date_from', _from);
  if (_estimate !== null) qs.set('include_expiry_estimate', String(_estimate));
  return qs.toString();
}

// Loads all six endpoints in parallel; each panel renders (or fails) on its own.
export async function loadAnalyticsPanels() {
  const seq = ++_seq;
  const qs = _query();
  const keys = Object.keys(_ENDPOINTS);
  const results = await Promise.allSettled(keys.map(k => api(`${_BASE}${_ENDPOINTS[k]}?${qs}`)));
  if (seq !== _seq) return;  // a newer load superseded this one
  let ok = 0;
  results.forEach((res, i) => {
    const key = keys[i];
    try {
      if (res.status !== 'fulfilled' || !res.value) throw new Error('no data');
      const data = res.value;
      _RENDER[key](data);
      ok += 1;
      const est = document.getElementById('ta-an-expiry-est');
      if (est && _estimate === null && data.filter) est.checked = !!data.filter.include_expiry_estimate;
      const from = document.getElementById('ta-an-from');
      if (from && !_from && data.filter && data.filter.date_from) from.value = data.filter.date_from;
    } catch (e) {
      if (key === 'foundation') setEl('ta-an-recon', '— could not be loaded');
      else _fail(key);
    }
  });
  setEl('ta-an-status', ok === keys.length ? '' : `${_num(keys.length - ok)} of ${_num(keys.length)} analytics panels could not be loaded`);
}

export function taAnRefresh() {
  return loadAnalyticsPanels();
}

export function taAnFromChanged(v) {
  _from = v || '';
  return loadAnalyticsPanels();
}

export function taAnToggleEstimate(flag) {
  _estimate = !!flag;
  return loadAnalyticsPanels();
}

export function taAnToggleInfo(panelId) {
  if (!_PANELS.includes(panelId)) return;
  const el = document.getElementById(`ta-an-${panelId}-def`);
  if (el) el.style.display = el.style.display === 'none' ? '' : 'none';
}
