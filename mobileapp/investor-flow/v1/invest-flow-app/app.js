// Tiny vanilla helpers — no framework.
// 1. Calculation logic
// 2. Slider / input live updates on results page
// 3. Choice button toggling
// 4. Accordion

(function () {
  // ───── Math ─────
  function fv(monthly, months, annualRate) {
    if (monthly <= 0 || months <= 0) return 0;
    const rm = Math.pow(1 + annualRate, 1 / 12) - 1;
    if (Math.abs(rm) < 1e-9) return monthly * months;
    return monthly * ((Math.pow(1 + rm, months) - 1) / rm);
  }
  function requiredRate(monthly, months, target) {
    if (monthly <= 0 || months <= 0) return null;
    let lo = -0.5, hi = 1.0;
    const f = (r) => fv(monthly, months, r) - target;
    for (let i = 0; i < 80; i++) {
      const mid = (lo + hi) / 2;
      if (f(mid) > 0) hi = mid; else lo = mid;
    }
    return (lo + hi) / 2;
  }
  const fmtEur = (n) => {
    if (n == null || isNaN(n)) return '€—';
    const abs = Math.abs(n);
    if (abs >= 1_000_000) return '€' + (n / 1_000_000).toFixed(1).replace(/\.0$/, '') + 'M';
    if (abs >= 10_000) return '€' + Math.round(n / 1000) + 'k';
    if (abs >= 1_000) return '€' + (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k';
    return '€' + Math.round(n);
  };
  const fmtPct = (r) =>
    r == null || isNaN(r) ? '—%' : (r * 100).toFixed(1).replace(/\.0$/, '') + '%';

  // ───── Choice toggling (single-select buttons) ─────
  document.querySelectorAll('[data-choice-group]').forEach((group) => {
    group.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-choice]');
      if (!btn || !group.contains(btn)) return;
      group.querySelectorAll('[data-choice]').forEach((b) => b.classList.remove('selected'));
      btn.classList.add('selected');
      // Enable continue if there's a gated nav button
      const nav = group.closest('.phone')?.querySelector('[data-gate]');
      if (nav) nav.disabled = false;
    });
  });

  // ───── Tabs (segmented) ─────
  document.querySelectorAll('[data-tabs]').forEach((wrap) => {
    wrap.addEventListener('click', (e) => {
      const tab = e.target.closest('.tab');
      if (!tab) return;
      wrap.querySelectorAll('.tab').forEach((t) => t.classList.remove('active'));
      tab.classList.add('active');
      const tabId = tab.dataset.tab;
      const pane = wrap.closest('.phone')?.querySelectorAll('[data-tab-pane]');
      if (pane) {
        pane.forEach((p) => {
          p.style.display = p.dataset.tabPane === tabId ? '' : 'none';
        });
      }
      // Recalculate on tab change for results page
      if (window.recalc) window.recalc();
    });
  });

  // ───── Accordion ─────
  document.querySelectorAll('[data-accordion]').forEach((acc) => {
    const head = acc.querySelector('.accordion-head');
    const body = acc.querySelector('.accordion-body');
    head.addEventListener('click', () => {
      const open = head.classList.toggle('open');
      body.style.display = open ? '' : 'none';
    });
  });

  // ───── Stepper buttons ─────
  document.querySelectorAll('[data-stepper]').forEach((wrap) => {
    const numEl = wrap.querySelector('.num');
    const minus = wrap.querySelector('[data-step="minus"]');
    const plus = wrap.querySelector('[data-step="plus"]');
    const step = parseFloat(wrap.dataset.stepBy || '0.1');
    const min = parseFloat(wrap.dataset.min || '0');
    const suffix = wrap.dataset.suffix || '%';
    let val = parseFloat(wrap.dataset.value || '0');
    const render = () => {
      numEl.textContent = val.toFixed(1).replace(/\.0$/, '') + suffix;
      wrap.dataset.value = String(val);
      if (window.recalc) window.recalc();
    };
    minus.addEventListener('click', () => {
      val = Math.max(min, +(val - step).toFixed(2));
      render();
    });
    plus.addEventListener('click', () => {
      val = +(val + step).toFixed(2);
      render();
    });
    render();
  });

  // ───── Toggle switches ─────
  document.querySelectorAll('.toggle').forEach((t) => {
    t.addEventListener('click', () => t.classList.toggle('on'));
  });

  // ───── Slider live label ─────
  document.querySelectorAll('input[type=range][data-bind]').forEach((sl) => {
    const target = document.querySelector(sl.dataset.bind);
    const update = () => {
      if (target) target.textContent = sl.value;
      const riskBadge = document.querySelector('[data-risk-badge]');
      if (riskBadge) {
        const v = +sl.value;
        riskBadge.classList.remove('good', 'warn', 'bad');
        if (v < 5) {
          riskBadge.classList.add('bad');
          riskBadge.textContent = 'Aggressive';
        } else if (v < 15) {
          riskBadge.classList.add('warn');
          riskBadge.textContent = 'Balanced';
        } else {
          riskBadge.classList.add('good');
          riskBadge.textContent = 'Growth + compound';
        }
      }
      if (window.recalc) window.recalc();
    };
    sl.addEventListener('input', update);
    update();
  });

  // ───── Number inputs trigger recalc ─────
  document.querySelectorAll('input[type=number][data-recalc]').forEach((inp) => {
    inp.addEventListener('input', () => window.recalc && window.recalc());
  });

  // ───── Goal hint (Step 2A) ─────
  document.querySelectorAll('[data-goal-hint]').forEach((h) => {
    const group = h.closest('.phone').querySelector('[data-choice-group="goal"]');
    if (!group) return;
    group.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-choice]');
      if (!btn) return;
      const hint = btn.dataset.hint;
      const title = btn.dataset.title;
      h.style.display = '';
      h.querySelector('[data-goal-title]').textContent = title;
      h.querySelector('[data-goal-text]').textContent = hint;
    });
  });

  // ───── Horizon chip select (Step 3+4 B) ─────
  document.querySelectorAll('[data-chip-group]').forEach((group) => {
    group.addEventListener('click', (e) => {
      const chip = e.target.closest('.chip');
      if (!chip) return;
      group.querySelectorAll('.chip').forEach((c) => c.classList.remove('selected'));
      chip.classList.add('selected');
      const slider = group.closest('.phone').querySelector('input[type=range][data-bind]');
      if (slider) {
        slider.value = chip.dataset.value;
        slider.dispatchEvent(new Event('input'));
      }
    });
  });

  // ───── Expose helpers globally for results page ─────
  window.invest = { fv, requiredRate, fmtEur, fmtPct };
})();
