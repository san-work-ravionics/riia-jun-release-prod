"""F44 P2 — frontend currency fix (D2: no ``pb-location`` selector; only the currency fix).

DoD items covered here:
- Portfolio Builder share count: the amount is converted into the instrument currency before the
  division (pins the old bug: an EUR amount ÷ an INR price gave ~91× too FEW shares)
- India portfolio of ₹10,00,000 at 50 % and price P → ``shares = floor(500000 / P)``
- every listed consumer shows amounts in the portfolio currency: no hardcoded ``€`` (grep), reads
  ``total_value ?? total_value_eur`` / ``cash ?? cash_eur`` through the shared helpers
- portfolio save + load go through ``api()`` (401 → ``ensureDevToken(true)`` → retry once) — no
  raw fetch / token-header ``apiFetch`` for the user portfolio (project.md §9)
- ``?v=`` cache-bust bumped where the page already has one (``portfolio-builder.js?v=5``)

The pure JS runs under node (same approach as the F39/F40 JS tests); the rest is static.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_JS = Path(__file__).resolve().parents[2] / "dashboard" / "js"

FNO_CONSUMERS = [
    "fno/portfolio-hedge.js", "fno/my-portfolio.js", "fno/hedge-workflow.js", "fno/hedge-workflow-save.js",
    "fno/hedge-workflow-whatif.js", "fno/hedge-workflow-recommendation.js", "fno/hedge-instrument-tiles.js",
    "fno/hedge-calc.js", "fno/risk_chart.js", "fno/stress.js", "fno/dashboard.js", "fno/state.js",
    "fno/app-init.js",
]
CONSUMERS = FNO_CONSUMERS + ["rita/portfolio-builder.js"]
CHANGED = CONSUMERS + ["shared/portfolio-currency.js", "shared/fx.js", "rita/main.js"]
# Modules that read the saved user portfolio
PORTFOLIO_LOADERS = ["fno/portfolio-hedge.js", "fno/my-portfolio.js", "fno/hedge-workflow.js",
                     "fno/app-init.js", "rita/portfolio-builder.js"]

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _src(rel: str) -> str:
    return (_JS / rel).read_text()


def _node(script: str) -> dict:
    r = subprocess.run(["node", "--input-type=module", "-e", script], cwd=_JS,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


_IMPORT = """
import { pathToFileURL } from 'node:url';
const base = pathToFileURL(process.cwd() + '/').href;
"""


# ── shares: the 91× bug ────────────────────────────────────────────────────────

def test_india_portfolio_shares_floor_500000_over_price():
    r = _node(_IMPORT + """
const m = await import(base + 'shared/portfolio-currency.js');
const P = 247.35;
console.log(JSON.stringify({
  india: m.sharesAndCash(1000000, 50, P, 1),
  eur:   m.sharesAndCash(10000, 50, 250, 91),
  usd:   m.sharesAndCash(10000, 50, 100, 1.1),
  noFx:  m.sharesAndCash(10000, 50, 250, null),
}));""")
    P = 247.35
    assert r["india"]["shares"] == int(500000 // P)
    assert r["india"]["cash"] == pytest.approx(500000 - int(500000 // P) * P)
    # legacy EUR portfolio, India instrument at ₹250, EURINR 91 → 5,000 € = ₹4,55,000 → 1820 shares
    assert r["eur"]["shares"] == 1820
    assert r["eur"]["cash"] == pytest.approx(0.0, abs=1e-9)
    old_bug = int(5000 // 250)                         # floor(allocEur / INR price) = 20
    assert r["eur"]["shares"] / old_bug == pytest.approx(91.0)
    assert r["usd"]["shares"] == 55                    # floor(5000 * 1.1 / 100)
    assert r["usd"]["cash"] == pytest.approx(5000 - 55 * 100 / 1.1)   # cash back in the portfolio currency
    assert r["noFx"] is None                           # no rate → no share count (never a static rate)


def test_compute_n_shares_converts_with_fx():
    r = _node(_IMPORT + """
const c = await import(base + 'fno/hedge-calc.js');
console.log(JSON.stringify([
  c.computeNShares({shares: null, allocation_pct: 50}, {close: 250}, 10000, 91),
  c.computeNShares({shares: null, allocation_pct: 50}, {close: 250}, 10000),
  c.computeNShares({shares: null, allocation_pct: 50}, {close: 250}, 10000, null),
  c.computeNShares({shares: 7, allocation_pct: 50}, {close: 250}, 10000, 91),
]));""")
    assert r == [1820, 20, 10, 7]   # fx; default fx=1 (same currency); no rate → 10 fallback; saved shares win


def test_portfolio_builder_uses_fx_before_dividing():
    s = _src("rita/portfolio-builder.js")
    assert "Math.floor(allocEur / price)" not in s
    assert "sharesAndCash(totalEur, allocPct, price, fxRateSync(_PB_CURRENCY, _ccyForId(id)))" in s
    assert "await preloadFx(_PB_CURRENCY, Object.values(REGION_CCY));" in s
    # every call site passes the instrument id (for its currency)
    calls = re.findall(r"_sharesAndCash\(([^)]*)\)", s)
    assert calls and all(c.rstrip().endswith(("id", "h.instrument_id")) for c in calls), calls


def test_portfolio_builder_save_contract():
    s = _src("rita/portfolio-builder.js")
    assert "pb-location" not in s                                   # D2: selector dropped
    assert ("api('/api/v1/user-portfolio/', 'POST', { name, holdings, total_value: totalValueEur, "
            "total_value_eur: totalValueEur })") in s
    assert "cash, cash_eur: cash" in s
    assert "location" not in re.search(r"api\('/api/v1/user-portfolio/', 'POST'[^\n]*", s).group(0)


# ── consumers: currency + fallbacks ────────────────────────────────────────────

@pytest.mark.parametrize("rel", CONSUMERS)
def test_no_hardcoded_euro_symbol(rel):
    s = _src(rel)
    assert "€" not in s and "\\u20ac" not in s.lower(), rel
    assert "'EUR ' +" not in s and "(EUR $" not in s, rel


@pytest.mark.parametrize("rel", CONSUMERS)
def test_no_direct_eur_field_reads(rel):
    """``total_value_eur`` / ``cash_eur`` only via the shared fallbacks (query strings + the PB legacy
    save keys are the only other uses)."""
    s = _src(rel)

    def ctx(m):
        start = s.rfind("\n", 0, m.start()) + 1
        return s[start: s.find("\n", m.end())], "//" in s[start: m.start()]   # (line, inside a comment)

    for m in re.finditer(r"total_value_eur", s):
        line, comment = ctx(m)
        assert comment or "&total_value_eur=" in line or "total_value_eur: totalValueEur" in line, (rel, line)
    for m in re.finditer(r"cash_eur", s):
        line, comment = ctx(m)
        assert comment or "cash_eur: cash" in line, (rel, line)


def test_shared_fallbacks():
    r = _node(_IMPORT + """
const m = await import(base + 'shared/portfolio-currency.js');
const out = {
  t1: m.portfolioTotal({total_value: 5, total_value_eur: 9}), t2: m.portfolioTotal({total_value_eur: 9}),
  t3: m.portfolioTotal(null), c1: m.holdingCash({cash: 1, cash_eur: 2}), c2: m.holdingCash({cash_eur: 2}),
  c3: m.holdingCash({cash: 0, cash_eur: 2}), ccy1: m.portfolioCurrency({currency: 'INR'}), ccy2: m.portfolioCurrency({}),
  sym0: m.pSym(),
};
m.setPortfolioCurrency('INR'); out.sym1 = m.pSym(); out.cur = m.getPortfolioCurrency();
m.setPortfolioCurrency(null); out.sym2 = m.pSym();
out.region = [m.regionCurrency('India'), m.regionCurrency('US'), m.regionCurrency('EU'), m.regionCurrency('Other')];
console.log(JSON.stringify(out));""")
    assert (r["t1"], r["t2"], r["t3"]) == (5, 9, None)
    assert (r["c1"], r["c2"], r["c3"]) == (1, 2, 0)            # cash wins, even when 0
    assert (r["ccy1"], r["ccy2"]) == ("INR", "EUR")
    assert (r["sym0"], r["sym1"], r["cur"], r["sym2"]) == ("€", "₹", "INR", "€")
    assert r["region"] == ["INR", "USD", "EUR", None]


@pytest.mark.parametrize("rel", PORTFOLIO_LOADERS)
def test_portfolio_loaders_set_currency_and_use_fallbacks(rel):
    s = _src(rel)
    if rel != "rita/portfolio-builder.js":   # PB is always a legacy EUR portfolio (D2)
        assert "setPortfolioCurrency(portfolioCurrency(" in s, rel
    if rel in ("fno/portfolio-hedge.js", "fno/my-portfolio.js", "fno/hedge-workflow.js"):
        assert "portfolioTotal(portfolio)" in s, rel


def test_value_today_converts_instrument_prices():
    s = _src("fno/portfolio-hedge.js")
    assert "liveValue += h.shares * inst.close / fx" in s
    assert "'FX rate unavailable'" in s
    assert "liveValue += (holdingCash(h) ?? 0);" in s


def test_analytics_meta_consumers_use_portfolio_total():
    for rel in ("fno/dashboard.js", "fno/risk_chart.js", "fno/stress.js"):
        assert "portfolioTotal(state.portfolioMeta)" in _src(rel), rel
    assert "setPortfolioCurrency(portfolioCurrency(state.portfolioMeta))" in _src("fno/app-init.js")


def test_portfolio_hedge_requests_send_total_value():
    for rel in ("fno/portfolio-hedge.js", "fno/hedge-workflow-save.js", "fno/hedge-workflow-whatif.js",
                "fno/hedge-workflow-recommendation.js"):
        s = _src(rel)
        assert "&total_value=${" in s and "&total_value_eur=${" in s, rel   # both until total_value_eur is retired


# ── auth: api() for the user portfolio, no raw fetch ──────────────────────────

@pytest.mark.parametrize("rel", PORTFOLIO_LOADERS)
def test_user_portfolio_reads_go_through_api(rel):
    s = _src(rel)
    assert "api('/api/v1/experience/user-portfolio')" in s, rel
    assert not re.search(r"apiFetch\(\s*'/api/v1/experience/user-portfolio'", s), rel
    assert not re.search(r"fetch\(\s*apiBase\(\)\s*\+\s*'/api/v1/experience/user-portfolio'", s), rel


def test_app_init_analytics_through_api_no_raw_fetch():
    s = _src("fno/app-init.js")
    assert "await api('/api/v1/experience/fno/portfolio-analytics?mode=' + mode)" in s
    raw = [ln.strip() for ln in s.splitlines() if re.search(r"(?<![\w.])fetch\(", ln)]
    assert raw == ["const r = await fetch(apiBase() + '/health');"], raw   # only the public health ping stays raw


def test_portfolio_hedge_reads_through_api():
    for rel in ("fno/portfolio-hedge.js", "fno/hedge-workflow-save.js", "fno/hedge-workflow-whatif.js",
                "fno/hedge-workflow-recommendation.js"):
        s = _src(rel)
        for m in re.finditer(r"portfolio-hedge\?coverage", s):
            if "//" in s[s.rfind("\n", 0, m.start()) + 1: m.start()]:
                continue   # header comment
            window = s[m.start(): m.start() + 400]
            assert "api(u" in window or "api(url" in window, rel
            assert "apiFetch(u" not in window and "apiFetch(url" not in window, rel


_STALE = """
import { pathToFileURL } from 'node:url';
const store = { auth_token: 'stale' };
globalThis.window = globalThis;
globalThis.sessionStorage = { getItem:k=>store[k]??null, setItem:(k,v)=>{store[k]=String(v)}, removeItem:k=>{delete store[k]} };
globalThis.location = { hostname:'localhost', href:'http://localhost/' };
const log = [];
const jr = (body, status = 200) => ({ ok: status < 400, status, statusText: 'x', json: async () => body });
globalThis.fetch = async (url, o = {}) => {
  const auth = (o.headers || {}).Authorization || '';
  log.push(`${(o.method || 'GET')} ${url} ${auth}`);
  if (url === '/auth/token') return jr({ access_token: 'fresh' });
  if (auth !== 'Bearer fresh') return jr({ detail: 'expired' }, 401);
  if (url.startsWith('/api/v1/experience/rita/fx')) return url.includes('quote=INR') ? jr({ rate: 91 }) : jr({ detail: 'no fx rate' }, 404);
  if (url === '/api/v1/experience/user-portfolio') return jr({ currency: 'INR', total_value: 5 });
  if (url === '/api/v1/user-portfolio/') return jr({ portfolio_id: 'p1' });
  return jr(null, 404);
};
const base = pathToFileURL(process.cwd() + '/').href;
"""


def test_stale_token_save_and_load_recover_via_ensure_dev_token():
    """Localhost: a stale token → 401 → ensureDevToken(true) mints a fresh one → retry once."""
    r = _node(_STALE + """
const { api } = await import(base + 'shared/api.js');
const load = await api('/api/v1/experience/user-portfolio').catch(e => 'ERR ' + e.message);
store.auth_token = 'stale';
const save = await api('/api/v1/user-portfolio/', 'POST', { holdings: [] }).catch(e => 'ERR ' + e.message);
console.log(JSON.stringify({ load, save, token: store.auth_token, log }));""")
    assert r["load"] == {"currency": "INR", "total_value": 5}
    assert r["save"] == {"portfolio_id": "p1"}
    assert r["token"] == "fresh"
    assert sum("/auth/token" in line for line in r["log"]) == 2
    assert r["log"][:3] == ["GET /api/v1/experience/user-portfolio Bearer stale", "POST /auth/token ",
                            "GET /api/v1/experience/user-portfolio Bearer fresh"]


def test_fx_cache_through_api():
    r = _node(_STALE + """
const fx = await import(base + 'shared/fx.js');
const a = await fx.fxRate('EUR', 'INR');
const b = await fx.fxRate('EUR', 'USD');
const same = await fx.fxRate('INR', 'INR');
await fx.preloadFx('EUR', ['INR', 'USD', 'EUR']);
const calls = log.filter(l => l.includes('/rita/fx')).length;
console.log(JSON.stringify({ a, b, same, sync: fx.fxRateSync('EUR', 'INR'), syncMissing: fx.fxRateSync('EUR', 'USD'),
  region: fx.fxForRegion('EUR', 'India'), other: fx.fxForRegion('EUR', 'Other'), calls }));""")
    assert (r["a"], r["b"], r["same"]) == (91, None, 1)            # 404 "no fx rate" → null
    assert (r["sync"], r["syncMissing"], r["region"], r["other"]) == (91, None, 91, None)
    assert r["calls"] == 3   # INR (stale 401 + retry) + USD once — cached afterwards


# ── syntax + cache-bust ────────────────────────────────────────────────────────

@pytest.mark.parametrize("rel", CHANGED)
def test_node_check(rel):
    r = subprocess.run(["node", "--check", str(_JS / rel)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr


def test_cache_bust_bumped():
    s = _src("rita/main.js")
    assert "./portfolio-builder.js?v=5'" in s and "?v=4'" not in s


def test_fno_portfolio_builder_untouched_and_unloaded():
    """fno/portfolio-builder.js is not loaded by any page (Architect table: confirm and leave)."""
    assert "portfolio-builder" not in _src("fno/main.js")
    html = (_JS.parent / "fno.html").read_text()
    assert "portfolio-builder.js" not in html
