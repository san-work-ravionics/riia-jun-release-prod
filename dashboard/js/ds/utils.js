// ── DS-local color palette (extends shared C with ds-specific colors) ──────
// Note: shared/charts.js C is NOT imported here because ds.html used its own
// local C object which differs from the shared one. We define DS_C directly.
export const DS_C = {
  build:'#1A6B3C', buildBg:'rgba(26,107,60,.12)',
  run:'#0056B8',   runBg:'rgba(0,86,184,.12)',
  mon:'#6B2FA0',   monBg:'rgba(107,47,160,.12)',
  warn:'#92480A',  warnBg:'rgba(146,72,10,.12)',
  danger:'#9B1C1C',dangerBg:'rgba(155,28,28,.12)',
  ds:'#0E7490',    dsBg:'rgba(14,116,144,.12)',
  t2:'#4A4640', t3:'#8C877A', grid:'rgba(0,0,0,.05)'
};

// ── mkTbl — verbatim from ds.html ──────────────────────────────────────────
export function mkTbl(rows, cols) {
  if (!rows||!rows.length) return '<div class="empty">No data.</div>';
  const ths = cols.map(c=>`<th${c.right?' style="text-align:right"':''}>${c.label}</th>`).join('');
  const trs = rows.map(r=>{
    const tds = cols.map(c=>{
      const v = r[c.key]??'—';
      if (c.badge) {
        const s = String(v).toLowerCase();
        const cls = s==='ok'?'ok':s==='warn'||s==='warning'?'warn':s==='err'||s==='error'||s==='fail'||s==='failed'?'err':'neu';
        return `<td><span class="badge ${cls}">${v}</span></td>`;
      }
      return `<td${c.mono?' class="td-mono"':''}${c.right?' style="text-align:right"':''}>${v}</td>`;
    }).join('');
    return `<tr>${tds}</tr>`;
  }).join('');
  return `<table><thead><tr>${ths}</tr></thead><tbody>${trs}</tbody></table>`;
}

// ── fmtPctRaw — verbatim from ds.html ──────────────────────────────────────
export function fmtPctRaw(v, dec=1) {
  if (v==null||v==='') return '—';
  const n = parseFloat(v);
  return isNaN(n) ? String(v) : n.toFixed(dec)+'%';
}

// ── openChartModal / closeChartModal — ds-specific image-based modal ────────
// These are NOT the same as shared/charts.js modal. They render chart to PNG
// and display in a simple <img> modal (#chart-modal + #chart-modal-img).
export function openChartModal(id, title) {
  const canvas = document.getElementById(id);
  if (!canvas) return;
  document.getElementById('chart-modal-title').textContent = title || '';
  document.getElementById('chart-modal-img').src = canvas.toDataURL('image/png');
  document.getElementById('chart-modal').style.display = 'flex';
}

export function closeChartModal() {
  document.getElementById('chart-modal').style.display = 'none';
}
