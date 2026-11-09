// Jarvis — instrument grid extras: Entry, Exit and Comments cells for each instrument row.
// Every value is a field of that instrument's A6 payload (default engine); nothing is computed here.
// Comments = "why the engine did this on <date>": the engine's rationale (date, action change, note).
import { esc } from './esc.js?v=3';
import { t } from './copy.js?v=21';
import { fmtNum, fmtDate, isNum } from './format.js?v=3';
import { actionText } from './chat.js?v=5';
import { pickDefaultEngine, statusText } from './instrument.js?v=4';

function _levelCell(l) {
  if (!l || !isNum(l.value)) return '—';
  const d = l.date ? `<div class="jv-muted">${esc(fmtDate(l.date))}</div>` : '';
  return `${esc(fmtNum(l.value, 2))}${d}`;
}

function _comment(e, instrumentId) {
  const r = e.rationale;
  if (!r) return esc(statusText(e, instrumentId) || '—');
  const act = r.action || r.prev_action
    ? ` ${esc(actionText(r.prev_action))} → ${esc(actionText(r.action))}` : '';
  const note = r.note ? ` — ${esc(r.note)}` : '';
  return `<b>${esc(t('rationale.short', { date: fmtDate(r.date) }))}</b> · ${esc(t(`inst.engine.${e.engine}`))}:${act}${note}`;
}

// {entry, exit, comment} as HTML strings for one A6 payload, or null when the payload has no engine.
export function rowCells(data) {
  if (!data || !(data.engines || []).length) return null;
  const key = pickDefaultEngine(data);
  const e = data.engines.find(x => x.engine === key) || data.engines[0];
  const lv = e.levels || {};
  return { entry: _levelCell(lv.entry), exit: _levelCell(lv.exit), comment: _comment(e, data.instrument_id) };
}

// Write the three cells into one grid row (the row exists once renderPortfolio has drawn the grid).
export function fillRowCells(instrumentId, cells) {
  if (!cells) return;
  const tr = document.querySelector(`#jv-grid-body tr[data-inst="${CSS.escape(instrumentId)}"]`);
  if (!tr) return;
  for (const k of ['entry', 'exit', 'comment']) {
    const td = tr.querySelector(`td[data-cell="${k}"]`);
    if (td) td.innerHTML = cells[k];
  }
}
