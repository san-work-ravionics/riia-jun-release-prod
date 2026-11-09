// Jarvis — instrument grid extras: Entry, Exit and Comments cells for each instrument row.
// Every value is a field of that instrument's A6 payload (default engine); nothing is computed here.
// Comments = "why the engine did this on <date>": the engine's rationale (date, action change, note).
import { esc } from './esc.js?v=3';
import { t } from './copy.js?v=21';
import { fmtNum, fmtDate, isNum } from './format.js?v=3';
import { actionText } from './chat.js?v=5';
import { pickDefaultEngine, modelEngines } from './instrument.js?v=6';

function _levelCell(l) {
  if (!l || !isNum(l.value)) return '—';
  const d = l.date ? `<div class="jv-muted">${esc(fmtDate(l.date))}</div>` : '';
  return `${esc(fmtNum(l.value, 2))}${d}`;
}

function _comment(e, instrumentId) {
  const r = e.rationale;
  if (!r) return '—';
  const head = r.date ? `<b>${esc(t('rationale.short', { date: fmtDate(r.date) }))}</b> · ` : '';
  let act = '';
  if (r.action && r.prev_action) act = ` ${esc(actionText(r.prev_action))} → ${esc(actionText(r.action))}`;
  else if (r.action || r.prev_action) act = ` ${esc(actionText(r.action || r.prev_action))}`;
  const note = r.note ? ` — ${esc(r.note)}` : '';
  return `${head}${esc(t(`inst.engine.${e.engine}`))}:${act}${note}`;
}

// {entry, exit, comment} as HTML strings for one A6 payload, or null when the payload has no engine.
export function rowCells(data) {
  const engines = data ? modelEngines(data) : [];
  if (!engines.length) return null;
  const key = pickDefaultEngine({ engines });
  const e = engines.find(x => x.engine === key) || engines[0];
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
