// Jarvis — instrument panel (A6): engine toggle (RITA / FnO σ / ASTA), price chart with entry / exit /
// derisk markers and level lines, the RITA sleeve-vs-SL chart, the levels table with each level's
// basis, the rationale panel (.reasoning-data-row layout, re-implemented — fno/ is not imported) and
// honest status texts. Every figure is a field of the A6 payload.
import { api } from '../shared/api.js';
import { mkChart, destroyChart, chartOpts, C } from '../shared/charts.js';
import { esc } from './esc.js?v=2';
import { t } from './copy.js?v=2';
import { fmtRate, fmtPp, fmtNum, fmtDate, isNum } from './format.js?v=2';
import { reasonText } from './chat.js?v=2';
import { engineStatusText } from './portfolio.js?v=2';

export function loadInstrument(location, instrument) {
  return api(`/api/v1/experience/jarvis/instrument?location=${encodeURIComponent(location)}&instrument=${encodeURIComponent(instrument)}`);
}

const ENGINE_ORDER = ['rita', 'fno', 'asta'];
const HAS_CHART = new Set(['ok', 'levels_only', 'no_recorded_window']);

export function pickDefaultEngine(data) {
  const by = Object.fromEntries((data.engines || []).map(e => [e.engine, e]));
  if (by.rita && by.rita.status === 'ok') return 'rita';
  if (by.fno && HAS_CHART.has(by.fno.status)) return 'fno';
  if (by.asta && HAS_CHART.has(by.asta.status)) return 'asta';
  return 'rita';
}

export function enginesToggleHtml(data, active) {
  const by = Object.fromEntries((data.engines || []).map(e => [e.engine, e]));
  return ENGINE_ORDER.filter(k => by[k]).map(k => {
    const e = by[k];
    const dim = HAS_CHART.has(e.status) ? '' : ' is-dim';
    return `<button type="button" class="jv-seg${k === active ? ' is-active' : ''}${dim}" data-engine="${esc(k)}" title="${esc(e.label)}">${esc(t(`inst.engine.${k}`))}</button>`;
  }).join('');
}

export function statusText(e, instrument) {
  if (!e) return '';
  if (e.status === 'excluded') {
    const r = e.method && e.method.excluded_reason;
    return t('engine.status.excluded', { reason: reasonText(r) });
  }
  return engineStatusText(e.status, { instrument });
}

function _levelVal(engine, key, lv) {
  if (!lv || !isNum(lv.value)) return '—';
  return engine === 'rita' && key === 'stop_loss' ? fmtNum(lv.value, 3) : fmtNum(lv.value, 2);
}

function _slNote(e, ctx) {
  if (e.engine === 'rita') return isNum(ctx.slLimit) ? t('inst.sl.rita', { limit: fmtRate(Math.abs(ctx.slLimit)) }) : '';
  if (e.engine === 'fno') return t('inst.sl.fno');
  if (e.engine === 'asta') return t('inst.sl.asta');
  return '';
}

export function levelsHtml(e, ctx = {}) {
  const lv = e.levels || {};
  const keys = ['entry', 'exit', 'stop_loss', 'target'];
  const rows = keys.map(k => {
    const l = lv[k];
    const note = k === 'stop_loss' && l ? _slNote(e, ctx) : '';
    return `<tr><td>${esc(t(`inst.level.${k}`))}</td><td class="num">${esc(_levelVal(e.engine, k, l))}</td>
      <td class="mono">${esc(l && l.date ? fmtDate(l.date) : '—')}</td>
      <td>${esc(l ? l.basis : '—')}${note ? `<div class="jv-muted">${esc(note)}</div>` : ''}</td></tr>`;
  }).join('');
  return `<table class="jv-table jv-table-sm"><tbody>${rows}</tbody></table>`;
}

function _kv(name, value) {
  return `<span class="reasoning-kpi"><strong>${esc(name)}:</strong> ${esc(value)}</span>`;
}

function _num(v) {
  if (!isNum(v)) return v === null || v === undefined ? '—' : String(v);
  return Math.abs(v) >= 100 ? fmtNum(v, 2) : String(Number(v.toPrecision(4)));
}

export function rationaleHtml(e) {
  const r = e.rationale;
  const parts = [];
  const a = e.asta;
  if (r) {
    parts.push(`<div class="jv-card-title">${esc(t('rationale.title', { date: fmtDate(r.date) }))}</div>`);
    if (e.engine === 'rita') parts.push(`<p class="jv-note">${esc(t('note.rita'))}</p>`);
    if (e.engine === 'fno') parts.push(`<p class="jv-note">${esc(t('note.fno', { lookback_returns: e.method && e.method.lookback_returns }))}</p>`);
    if (e.engine === 'asta' && a && a.last_signal) {
      parts.push(`<p class="jv-note">${esc(t('note.asta', { setup: a.last_signal.setup, confidence: _num(a.last_signal.confidence) }))}</p>`);
    }
    if (r.action || r.prev_action) parts.push(`<div class="reasoning-data-row">${_kv('action', `${r.prev_action || '—'} → ${r.action || '—'}`)}</div>`);
    if ((r.inputs || []).length) {
      parts.push(`<div class="reasoning-data-row">${r.inputs.map(i =>
        _kv(i.name, isNum(i.model_input) ? `${_num(i.raw)} → ${_num(i.model_input)}` : _num(i.raw))).join('')}</div>`);
    }
    if ((r.state || []).length) {
      parts.push(`<div class="reasoning-data-row">${r.state.map(s => _kv(s.name, _num(s.value))).join('')}</div>`);
    }
    if (r.note) parts.push(`<p class="jv-muted">${esc(r.note)}</p>`);
  }
  if (e.engine === 'rita' && e.tolerance_rule === 'p3_tau_rule_single_sleeve') parts.push(`<p class="jv-note">${esc(t('inst.tau_rule'))}</p>`);
  if (e.engine === 'asta' && a) {
    const w = a.window || {};
    const tr = a.training_record || {};
    const bt = a.pipeline_backtest || {};
    if (tr.run_id) {
      parts.push(`<p class="jv-note">${esc(t('asta.caveat', {
        test_start: fmtDate(w.test_start), test_end: fmtDate(w.test_end), run_id: String(tr.run_id).slice(0, 8),
        test_sharpe: isNum(tr.test_sharpe) ? tr.test_sharpe.toFixed(3) : null, test_return: fmtRate(tr.test_return),
        test_mdd: fmtRate(tr.test_mdd), test_trades: tr.test_trades,
        bt_run_id: bt.run_id ? String(bt.run_id).slice(0, 8) : null, bt_status: bt.status,
      }))}</p>`);
    }
    if (a.live_replay_note) parts.push(`<p class="jv-muted">${esc(a.live_replay_note)}</p>`);
  }
  return parts.join('');
}

export function performanceHtml(e) {
  const p = e.performance;
  if (!p) return '';
  const k = (label, v, cls = '') => `<div class="kpi kpi-sm"><div class="kpi-label">${esc(label)}</div><div class="kpi-value ${cls}">${esc(v)}</div></div>`;
  const sign = v => (isNum(v) ? (v >= 0 ? 'pos' : 'neg') : '');
  return k(t('engine.col.return'), fmtRate(p.return_since), sign(p.return_since))
    + k(t('engine.col.target'), fmtRate(p.target_to_date))
    + k(t('engine.col.gap'), fmtPp(p.gap), sign(p.gap));
}

// ── charts ─────────────────────────────────────────────────────────────────────
const MARK = {
  entry: { style: 'triangle', rot: 0, color: C.build },
  exit: { style: 'triangle', rot: 180, color: C.danger },
  derisk: { style: 'rectRot', rot: 0, color: C.warn },
  rerisk: { style: 'circle', rot: 0, color: C.run },
};

function _const(labels, from, value) {
  const f = from ? fmtDate(from) : labels[0];
  return labels.map(d => (d >= f ? value : null));
}

export function priceDatasets(e) {
  const labels = (e.prices || []).map(p => fmtDate(p.date));
  const ds = [{ label: e.label, data: (e.prices || []).map(p => p.close), borderColor: C.t3, borderWidth: 1.3, pointRadius: 0, order: 5 }];
  for (const kind of Object.keys(MARK)) {
    const ms = (e.markers || []).filter(m => m.kind === kind);
    if (!ms.length) continue;
    const by = Object.fromEntries(ms.map(m => [fmtDate(m.date), m.close]));
    const label = kind === 'entry' || kind === 'exit' ? t(`inst.level.${kind}`) : kind;
    ds.push({ label, data: labels.map(d => by[d] ?? null), showLine: false, pointStyle: MARK[kind].style,
              rotation: MARK[kind].rot, pointRadius: 6, pointHoverRadius: 7, borderColor: MARK[kind].color,
              backgroundColor: MARK[kind].color, order: 1 });
  }
  const lv = e.levels || {};
  if (e.engine === 'fno') {
    const s = e.series || {};
    if ((s.band_upper || []).length === labels.length) ds.push({ label: t('inst.level.target'), data: s.band_upper, stepped: true, borderColor: C.build, borderDash: [4, 3], borderWidth: 1.2, pointRadius: 0, spanGaps: false });
    if ((s.band_lower || []).length === labels.length) ds.push({ label: t('inst.level.stop_loss'), data: s.band_lower, stepped: true, borderColor: C.danger, borderDash: [4, 3], borderWidth: 1.2, pointRadius: 0, spanGaps: false });
    if (lv.entry && isNum(lv.entry.value) && labels.length) {
      const month = fmtDate(lv.entry.date).slice(0, 7);
      ds.push({ label: t('inst.level.entry'), data: labels.map(d => (d.slice(0, 7) === month ? lv.entry.value : null)), borderColor: C.run, borderWidth: 1.4, pointRadius: 0 });
    }
  } else if (e.engine === 'asta') {
    if (lv.stop_loss && isNum(lv.stop_loss.value)) ds.push({ label: t('inst.level.stop_loss'), data: _const(labels, lv.stop_loss.date, lv.stop_loss.value), borderColor: C.danger, borderDash: [4, 3], borderWidth: 1.2, pointRadius: 0 });
    if (lv.target && isNum(lv.target.value)) ds.push({ label: t('inst.level.target'), data: _const(labels, lv.target.date, lv.target.value), borderColor: C.build, borderDash: [4, 3], borderWidth: 1.2, pointRadius: 0 });
  }
  return { labels, datasets: ds };
}

export function sleeveDatasets(e) {
  const s = e.series || {};
  const sv = s.sleeve_value || [];
  const prices = (e.prices || []).map(p => fmtDate(p.date));
  const labels = prices.length >= sv.length ? prices.slice(prices.length - sv.length) : sv.map((_v, i) => String(i));
  const starts = new Set((e.episode_starts || []).map(fmtDate));
  return {
    labels,
    datasets: [
      { label: t('inst.sleeve.title'), data: sv, borderColor: C.run, borderWidth: 1.5, pointRadius: labels.map(d => (starts.has(d) ? 4 : 0)), pointBackgroundColor: C.mon },
      { label: t('inst.level.stop_loss'), data: s.sl_line || [], borderColor: C.danger, borderDash: [4, 3], borderWidth: 1.2, pointRadius: 0 },
    ],
  };
}

function _wrap(id) {
  return document.getElementById(id)?.closest('.chart-wrap');
}

function _drawPrice(e) {
  const wrap = _wrap('jv-inst-chart');
  if (!(e.prices || []).length) {
    destroyChart('jv-inst-chart');
    if (wrap) wrap.hidden = true;
    return;
  }
  if (wrap) wrap.hidden = false;
  const { labels, datasets } = priceDatasets(e);
  const opts = chartOpts('', v => fmtNum(v, 0), labels);
  opts.plugins.legend.labels.filter = item => !['derisk', 'rerisk'].includes(item.text);
  mkChart('jv-inst-chart', { type: 'line', data: { labels, datasets }, options: opts });
}

function _drawSleeve(e) {
  const wrap = document.getElementById('jv-sleeve-wrap');
  if (e.engine !== 'rita' || !((e.series || {}).sleeve_value || []).length) {
    destroyChart('jv-sleeve-chart');
    if (wrap) wrap.hidden = true;
    return;
  }
  if (wrap) wrap.hidden = false;
  const { labels, datasets } = sleeveDatasets(e);
  mkChart('jv-sleeve-chart', { type: 'line', data: { labels, datasets }, options: chartOpts('', v => fmtNum(v, 2), labels) });
}

// ── DOM ────────────────────────────────────────────────────────────────────────
let _data = null;
let _ctx = {};

function _html(id, html) {
  const el = document.getElementById(id);
  if (el) { el.innerHTML = html; el.hidden = !html; }
}

export function renderInstrument(data, engineKey, ctx = {}) {
  _data = data;
  _ctx = ctx;
  const engine = engineKey || pickDefaultEngine(data);
  const e = (data.engines || []).find(x => x.engine === engine);
  const title = document.getElementById('jv-inst-title');
  if (title) title.textContent = `${data.instrument_id}${e ? ` · ${e.label}` : ''}${data.as_of ? ` · ${fmtDate(data.as_of)}` : ''}`;
  _html('jv-inst-engines', enginesToggleHtml(data, engine));
  const st = statusText(e, data.instrument_id);
  const status = document.getElementById('jv-inst-status');
  if (status) { status.textContent = st; status.hidden = !st; }
  _html('jv-inst-perf', e ? performanceHtml(e) : '');
  _html('jv-inst-levels', e && HAS_CHART.has(e.status) ? levelsHtml(e, ctx) : '');
  _html('jv-rationale', e ? rationaleHtml(e) : '');
  if (e) {
    _drawPrice(e);
    _drawSleeve(e);
  }
}

export function renderInstrumentError(message) {
  const status = document.getElementById('jv-inst-status');
  if (status) { status.textContent = t('err.load', { message }); status.hidden = false; }
}

// Delegated on the toggle container (data-engine).
export function initInstrument() {
  document.getElementById('jv-inst-engines')?.addEventListener('click', ev => {
    const b = ev.target.closest('button[data-engine]');
    if (!b || !_data) return;
    renderInstrument(_data, b.dataset.engine, _ctx);
  });
}
