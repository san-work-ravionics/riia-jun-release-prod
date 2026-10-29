// Jarvis — plan view. Renders ONLY from the journey (JourneyOut, rev 1 B3) plus A4 live_holdings (rev 2
// N2: "Model today", "Invested now", next_reset). The journey selection is the selection-time
// snapshot and is labelled "at selection".
import { esc } from './esc.js?v=3';
import { t } from './copy.js?v=3';
import { fmtRate, fmtMoney, fmtDate, fmtYears, isNum } from './format.js?v=3';
import { actionText, reasonText } from './chat.js?v=3';

function _row(label, value) {
  return `<div class="jv-dl-row"><span>${esc(label)}</span><b>${esc(value)}</b></div>`;
}

function _window(w) {
  return w ? `${fmtDate(w.start)}–${fmtDate(w.end)}` : '—';
}

export function goalHtml(j) {
  return `<h3 class="jv-h3">${esc(t('plan.goal.title'))}</h3><div class="jv-dl">
    ${_row(t('plan.goal.return'), fmtRate(j.goal_return))}
    ${_row(t('plan.goal.horizon'), fmtYears(j.horizon_years))}
    ${_row(t('plan.goal.value'), fmtMoney(j.goal_value, j.currency))}
    ${_row(t('plan.goal.saved'), fmtDate(j.plan_updated_at))}</div>`;
}

// The mix the journey holds now: open segment, else the selection (closest when it can't reach).
function _mix(j) {
  const sel = j.selection;
  if (!sel) return { holdings: [], closest: false };
  if (sel.holdings && sel.holdings.length) return { holdings: sel.holdings, closest: false };
  if (sel.closest && sel.closest.holdings) return { holdings: sel.closest.holdings, closest: true };
  return { holdings: [], closest: false };
}

export function selectionHtml(j, live) {
  const sel = j.selection;
  if (!sel) return '';
  const { holdings, closest } = _mix(j);
  const liveBy = {};
  for (const h of live || []) liveBy[h.instrument_id] = h;
  const atSel = `<span class="jv-muted"> · ${esc(t('plan.selection.at_selection'))}</span>`;
  const rows = holdings.map(h => {
    const lv = liveBy[h.instrument_id];
    const liveOk = lv && lv.status === 'ok';
    const model = liveOk ? esc(actionText(lv.model_action)) : `${esc(actionText(h.model_action))}${atSel}`;
    const inv = liveOk
      ? esc(fmtRate(isNum(lv.invested_fraction) ? lv.invested_fraction * h.allocation_pct / 100 : null))
      : `${esc(isNum(h.invested_pct) ? `${h.invested_pct.toFixed(0)}%` : '—')}${atSel}`;
    const sl = liveOk
      ? `${esc(fmtRate(lv.sl_distance))}${lv.sl_hit ? ` <span class="jv-badge warn">${esc(t('plan.selection.col.sl'))}</span>` : ''}`
      : `${esc(fmtRate(h.sl_drawdown_limit))}${atSel}`;
    return `<tr><td class="mono">${esc(h.instrument_id)}</td><td class="num">${esc(`${h.allocation_pct}%`)}</td>
      <td>${model}</td><td class="num">${inv}</td><td class="num">${sl}</td></tr>`;
  }).join('');
  let status;
  if (closest || j.state === 'cant_reach') status = `<div class="jv-note warn">${esc(t('plan.selection.cant'))}</div>`;
  else if (sel.meets_goal) status = `<div class="jv-note ok">${esc(t('plan.selection.meets'))}</div>`;
  else status = `<div class="jv-note warn">${esc(t('plan.selection.short', { fit: _window(sel.fit_window), gap: fmtRate(sel.gap) }))}</div>`;
  return `<h3 class="jv-h3">${esc(t('plan.selection.title'))}</h3>${status}
    <table class="jv-table"><thead><tr><th>${esc(t('plan.selection.col.instrument'))}</th>
    <th class="num">${esc(t('plan.selection.col.weight'))}</th><th>${esc(t('plan.selection.col.model'))}</th>
    <th class="num">${esc(t('plan.selection.col.invested'))}</th><th class="num">${esc(t('plan.selection.col.sl'))}</th>
    </tr></thead><tbody>${rows}</tbody></table>`;
}

export function methodHtml(j) {
  const sel = j.selection;
  if (!sel) return '';
  return `<p class="jv-method">${esc(t('plan.method', { fit: _window(sel.fit_window), test: _window(sel.test_window) }))}</p>`;
}

export function excludedHtml(j) {
  const ex = (j.selection && j.selection.excluded) || [];
  if (!ex.length) return '';
  return `<h3 class="jv-h3">${esc(t('plan.excluded.title'))}</h3><ul class="jv-list">${ex.map(e =>
    `<li><span class="mono">${esc(e.instrument_id)}</span> — ${esc(reasonText(e.reason))}</li>`).join('')}</ul>`;
}

export function trackingHtml(j, live) {
  const tr = j.tracking || [];
  if (!tr.length) return '';
  const entry = tr.map(x => x.entry_date).filter(Boolean).sort()[0];
  const limits = tr.map(x => x.sl_drawdown_limit).filter(isNum);
  const limit = limits.length ? fmtRate(Math.abs(Math.max(...limits))) : '—';
  const resets = (live || []).map(h => h.next_reset).filter(Boolean).sort();
  return `<h3 class="jv-h3">${esc(t('plan.tracking.title', { date: fmtDate(j.plan_year_start || entry) }))}</h3>
    <p class="jv-note">${esc(t('plan.tracking.sl', { limit, next_reset: resets.length ? fmtDate(resets[0]) : '—' }))}</p>`;
}

export function proposalHtml(j) {
  if (j.state === 'reselect_proposed' && j.proposal) {
    const p = j.proposal;
    const hs = (p.proposal && p.proposal.holdings) || [];
    const mix = hs.map(h => `<span class="mono">${esc(h.instrument_id)}</span> ${esc(`${h.allocation_pct}%`)}`).join(', ');
    return `<h3 class="jv-h3">${esc(t('plan.proposal.title'))}</h3>
      <p class="jv-note">${esc(t('plan.proposal.text', { n: p.reselections_next, max: p.max_reselections }))}</p>
      ${mix ? `<p class="jv-note">${mix}</p>` : ''}`;
  }
  if (j.state === 'back_to_plan') {
    const p = j.proposal || {};
    const reason = j.back_to_plan_reason;
    const text = reason ? t(`bp.${reason}`, { required: fmtRate(p.required_return), cap_fit: fmtRate(p.cap_fit) }) : '';
    return `<h3 class="jv-h3">${esc(t('target.status.back_to_plan'))}</h3>
      ${text ? `<p class="jv-note warn">${esc(text)}</p>` : ''}
      <a class="btn btn-ghost btn-sm" href="investgame-app.html">${esc(t('link.whatineed'))}</a>`;
  }
  return '';
}

function _set(id, html) {
  const el = document.getElementById(id);
  if (!el) return;
  el.innerHTML = html;
  el.hidden = !html;
}

// state = A4 StateOut (journey may be replaced by a newer A3 reply journey).
export function renderPlan(state, journey) {
  const j = journey === undefined ? state && state.journey : journey;
  const live = (state && state.live_holdings) || [];
  const empty = !j || j.state === 'no_goal' || j.state === 'closed';
  let emptyHtml = empty ? esc(t('plan.empty')) : '';
  if (state && state.plan_stale && state.goal) {
    const notice = `<p class="jv-note warn">${esc(t('notice.plan_changed', { plan_updated_at: fmtDate(state.goal.plan_updated_at) }))}</p>`;
    emptyHtml = empty ? `${notice}${emptyHtml}` : notice;
  }
  _set('jv-plan-empty', emptyHtml);
  _set('jv-plan-goal', empty ? '' : goalHtml(j));
  _set('jv-plan-selection', empty ? '' : selectionHtml(j, live));
  _set('jv-plan-method', empty ? '' : methodHtml(j));
  _set('jv-plan-excluded', empty ? '' : excludedHtml(j));
  _set('jv-plan-tracking', empty ? '' : trackingHtml(j, live));
  _set('jv-plan-proposal', empty ? '' : proposalHtml(j));
}
