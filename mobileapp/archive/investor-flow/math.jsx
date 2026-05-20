// Investment math + central state hook.
// Implements: FV = P × ((1+r)^n − 1) / r  (monthly compounding for SIP)
// Real return = (1 + market) / (1 + inflation) − 1; then minus tax + costs.

function computeProjection(s) {
  const {
    monthly, target,
    horizon,                   // years
    grossReturn,               // annual % (e.g. 8)
    inflation, tax, costs,     // annual %
  } = s;

  // Net annual return after costs, tax (on gains), and inflation
  const r_gross = grossReturn / 100;
  const r_costs = costs / 100;
  const r_tax   = tax / 100;
  const r_infl  = inflation / 100;

  // After costs
  const r_after_costs = r_gross - r_costs;
  // After tax (rough: tax applied to nominal returns)
  const r_after_tax   = r_after_costs * (1 - r_tax);
  // After inflation (real return)
  const r_real = (1 + r_after_tax) / (1 + r_infl) - 1;

  const months = horizon * 12;

  const fv = (rateAnnual) => {
    const rm = Math.pow(1 + rateAnnual, 1/12) - 1;
    if (Math.abs(rm) < 1e-9) return monthly * months;
    return monthly * ((Math.pow(1 + rm, months) - 1) / rm);
  };

  // Required real return to hit target with given monthly + horizon
  // Solve for r in: target = monthly * ((1+r/12)^months - 1) / (r/12)
  const requiredReal = (() => {
    if (monthly <= 0 || months <= 0) return null;
    // bisection 0..30%
    let lo = -0.5, hi = 1.0;
    const f = (r) => {
      const rm = Math.pow(1 + r, 1/12) - 1;
      if (Math.abs(rm) < 1e-9) return monthly * months - target;
      return monthly * ((Math.pow(1 + rm, months) - 1) / rm) - target;
    };
    for (let i = 0; i < 80; i++) {
      const mid = (lo + hi) / 2;
      if (f(mid) > 0) hi = mid; else lo = mid;
    }
    return (lo + hi) / 2;
  })();

  const totalContrib = monthly * months;
  const fv_gross   = fv(r_gross);
  const fv_net     = fv(r_after_tax);
  const fv_real    = fv(r_real);

  // Status: how requiredReal compares to what user can realistically achieve
  let status = 'good';
  if (requiredReal == null) status = 'warn';
  else if (requiredReal > 0.10) status = 'bad';
  else if (requiredReal > 0.06) status = 'warn';

  return {
    months, totalContrib,
    r_gross, r_after_costs, r_after_tax, r_real, r_infl,
    fv_gross, fv_net, fv_real,
    requiredReal, status,
    shortfall: target - fv_real,
  };
}

const fmtEur = (n) => {
  if (n == null || isNaN(n)) return '€—';
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return '€' + (n/1_000_000).toFixed(1).replace(/\.0$/,'') + 'M';
  if (abs >= 10_000) return '€' + Math.round(n/1000) + 'k';
  if (abs >= 1_000) return '€' + (n/1000).toFixed(1).replace(/\.0$/,'') + 'k';
  return '€' + Math.round(n);
};
const fmtPct = (r) => (r == null || isNaN(r)) ? '—%' : (r*100).toFixed(1).replace(/\.0$/,'') + '%';
const fmtPctDelta = (r) => (r >= 0 ? '−' : '+') + Math.abs(r*100).toFixed(1).replace(/\.0$/,'') + '%';

// Default state used by every artboard (the same plan flows across screens
// so users see consistent numbers when stepping through).
const DEFAULT_PLAN = {
  investorType: 'goal',     // 'short' | 'goal' | 'long'
  goal: 'retire',           // edu | retire | buy | travel | wealth
  horizon: 12,              // years
  monthly: 250,             // €
  target: 75000,            // €
  grossReturn: 8,           // %
  inflation: 2.5,
  tax: 25,
  costs: 1.2,
};

function usePlan(initial = DEFAULT_PLAN) {
  const [plan, setPlan] = useState(initial);
  const set = (k, v) => setPlan((p) => ({ ...p, [k]: v }));
  const proj = useMemo(() => computeProjection(plan), [plan]);
  return { plan, set, setPlan, proj };
}

Object.assign(window, { computeProjection, fmtEur, fmtPct, fmtPctDelta, DEFAULT_PLAN, usePlan });
