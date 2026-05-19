// ── Chart expand modal ─────────────────────────────────────
export function openChartModal(canvasId, title) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const img = document.getElementById('chart-modal-img');
  img.src = canvas.toDataURL('image/png');
  document.getElementById('chart-modal-title').textContent = title || '';
  const modal = document.getElementById('chart-modal');
  modal.style.display = 'flex';
}

export function closeChartModal() {
  document.getElementById('chart-modal').style.display = 'none';
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') closeChartModal(); });
