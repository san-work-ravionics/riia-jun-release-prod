"""F39 exposure/save redesign — monthly σ math, hedge-impact numbers, shared charts and
the Exposure / Save step flow, driven through node (repo has no JS runner).

Golden vectors are computed here in Python from the documented formulas:
  monthly σ = ann_vol_pct / 100 / sqrt(12); level_k = price × (1 − k σ)
  hedge impact = hedgedPL(m) at m = −kσ·100 (existing pricing, unchanged).
Skipped when node is absent.
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_JS = _ROOT / "dashboard" / "js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _node(workdir: Path, source: str) -> object:
    script = workdir / "run.mjs"
    script.write_text(source, encoding="utf-8")
    out = subprocess.run(
        ["node", str(script)], capture_output=True, text=True, timeout=60, cwd=workdir
    )
    assert out.returncode == 0, out.stderr[-3000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def jsroot(tmp_path_factory) -> Path:
    dst = tmp_path_factory.mktemp("js")
    shutil.copytree(_JS, dst / "js")
    (dst / "js" / "package.json").write_text('{"type":"module"}', encoding="utf-8")
    return dst / "js"


def _calc(jsroot: Path, body: str) -> object:
    uri = (jsroot / "fno" / "hedge-calc.js").as_uri()
    return _node(jsroot, f"import * as calc from {json.dumps(uri)};\n{body}")


# ── monthly σ golden vectors ────────────────────────────────────────────────────────

def test_monthly_sigma_and_levels_golden(jsroot):
    r = _calc(jsroot, "console.log(JSON.stringify({s:calc.monthlySigma(30), l:calc.sigmaLevels(1000,30)}));")
    s = 30 / 100 / math.sqrt(12)
    assert r["s"] == pytest.approx(s, rel=1e-12)
    for lv, k in zip(r["l"], (1, 2, 3)):
        assert lv["k"] == k
        assert lv["sigmaPct"] == pytest.approx(s * k * 100)
        assert lv["down"] == pytest.approx(1000 * (1 - k * s))
        assert lv["up"] == pytest.approx(1000 * (1 + k * s))


def test_monthly_sigma_invalid_vol_is_null(jsroot):
    r = _calc(jsroot, "console.log(JSON.stringify([calc.monthlySigma(null),calc.monthlySigma(0),calc.monthlySigma('x'),calc.sigmaLevels(10,undefined)]));")
    assert r == [None, None, None, None]


def test_weighted_vol_matches_risk_page_formula_and_skips_missing(jsroot):
    r = _calc(jsroot, """console.log(JSON.stringify([
 calc.weightedVolPct([{allocation_pct:30,ann_vol_pct:18.4},{allocation_pct:20,ann_vol_pct:22.1},{allocation_pct:50,ann_vol_pct:null}]),
 calc.weightedVolPct([]), calc.weightedVolPct(null)]));""")
    assert r[0] == pytest.approx((30 * 18.4 + 20 * 22.1) / 50)
    assert r[1] is None and r[2] is None


def test_vol_map_precedence_and_portfolio_vol_fallback(jsroot):
    r = _calc(jsroot, """
const vm = calc.buildVolMap([{und:'A',ann_vol_pct:10}],[{und:'A',ann_vol_pct:99},{und:'B',ann_vol_pct:20}],{holdings:[{instrument_id:'C',ann_vol_pct:30},{instrument_id:'B',ann_vol_pct:77}]});
const pv = calc.portfolioVolPct([], [{instrument_id:'A',allocation_pct:50},{instrument_id:'Z',allocation_pct:50}], vm);
console.log(JSON.stringify({vm, pv}));""")
    assert r["vm"] == {"A": 10, "B": 20, "C": 30}
    assert r["pv"] == 10  # Z has no vol → ignored


# ── hedge impact golden vectors ─────────────────────────────────────────────────────

def _hedged_pl(m, tab, strike, cost):
    if tab == "pp":
        return max(m, strike) - cost
    if tab == "ps":
        lo, hi = strike, strike - 5
        if m > lo:
            return m - cost * 0.65
        if m > hi:
            return lo - cost * 0.65
        return m + (lo - hi) - cost * 0.65
    return max(min(m, 5), strike) - cost


@pytest.mark.parametrize("tab", ["pp", "ps", "collar"])
def test_hedge_impact_matches_hedged_pl_at_sigma_moves(jsroot, tab):
    r = _calc(jsroot, f"""
const rows=[{{id:'A',weight:60,strikePct:-10,costPct:1.2,protectedPct:60}},{{id:'B',weight:40,strikePct:-8,costPct:0.8,protectedPct:50}}];
console.log(JSON.stringify(calc.hedgeImpact(rows,null,'{tab}',30,100000)));""")
    cost = 1.2 * 0.6 + 0.8 * 0.4
    strike = -10 * 0.6 + -8 * 0.4
    s = 30 / math.sqrt(12)  # monthly σ in %
    assert r["premiumPct"] == pytest.approx(cost)
    assert r["premiumEur"] == pytest.approx(cost * 1000)
    assert r["monthlySigmaPct"] == pytest.approx(s)
    assert [x["label"] for x in r["scenarios"]] == ["Flat", "−1σ", "−2σ", "−3σ"]
    for sc, k in zip(r["scenarios"], (0, 1, 2, 3)):
        m = -s * k
        h = _hedged_pl(m, tab, strike, cost)
        assert sc["unhedgedPct"] == pytest.approx(m)
        assert sc["hedgedPct"] == pytest.approx(h)
        assert sc["protectedPct"] == pytest.approx(h - m)
        assert sc["unhedgedEur"] == pytest.approx(m * 1000)
        assert sc["protectedEur"] == pytest.approx((h - m) * 1000)
    # max drawdown: hedged = max(avgStrike - cost, -25); unhedged default -22
    assert r["agg"]["maxDdHedged"] == pytest.approx(max(strike - cost, -25))
    assert r["maxDdProtectedPct"] == pytest.approx(max(strike - cost, -25) + 22)


def test_hedge_impact_no_rows_null_and_no_vol_flat_only(jsroot):
    r = _calc(jsroot, """
const rows=[{id:'A',weight:100,strikePct:-10,costPct:1,protectedPct:60}];
console.log(JSON.stringify([calc.hedgeImpact([], null, 'pp', 20, 1), calc.hedgeImpact(rows, null, 'pp', null, null)]));""")
    assert r[0] is None
    assert [x["label"] for x in r[1]["scenarios"]] == ["Flat"]
    assert r[1]["scenarios"][0]["hedgedEur"] is None and r[1]["monthlySigmaPct"] is None


# ── shared chart module (pure parts) ────────────────────────────────────────────────

def test_monthly_candles_and_changes_pure(jsroot):
    uri = (jsroot / "fno" / "hedge-charts.js").as_uri()
    r = _node(jsroot, f"""
import * as ch from {json.dumps(uri)};
const d=[{{date:'2026-01-02',price:100}},{{date:'2026-01-20',price:110}},{{date:'2026-01-30',price:105}},
 {{date:'2026-02-03',price:104}},{{date:'2026-02-27',price:115.5}},{{date:'2026-03-31',price:99}}];
console.log(JSON.stringify({{c:ch.buildMonthlyCandles(d), m:ch.buildMonthlyChanges(d)}}));""")
    assert r["c"]["monthKeys"] == ["2026-01", "2026-02", "2026-03"]
    assert r["c"]["candles"][0] == {"o": 100, "h": 110, "l": 100, "c": 105}
    assert r["c"]["candles"][1] == {"o": 104, "h": 115.5, "l": 104, "c": 115.5}
    ch1, ch2 = (115.5 - 105) / 105 * 100, (99 - 115.5) / 115.5 * 100
    assert r["m"]["changes"] == pytest.approx([ch1, ch2])
    mean = (ch1 + ch2) / 2
    assert r["m"]["stdDev"] == pytest.approx(math.sqrt(((ch1 - mean) ** 2 + (ch2 - mean) ** 2) / 2))


# ── flow: Exposure + Save steps through the real module tree ───────────────────────

_PRELUDE = r"""
import { pathToFileURL } from 'node:url';
const store = {};
globalThis.window = globalThis;
globalThis.sessionStorage = { getItem:k=>store[k]??null, setItem:(k,v)=>{store[k]=String(v)}, removeItem:k=>{delete store[k]} };
globalThis.location = { hostname:'localhost', href:'http://localhost/' };
const els = {};
globalThis.document = { getElementById:(id)=> els[id] ??= { id, innerHTML:'', textContent:'', style:{}, dataset:{}, classList:{add(){}}, closest:()=>null, getContext:()=>({}) },
  querySelector:()=>null, querySelectorAll:()=>[], addEventListener(){} };
const charts = [];
globalThis.Chart = class { constructor(ctx, cfg){ this.cfg=cfg; this.id=ctx.id; charts.push(this); } destroy(){ this.destroyed=true; } update(){} static register(){} };
globalThis.Chart.defaults = { font: {} };
const log = [];
function jr(body, status = 200) { return { ok: status < 400, status, statusText: 'x', json: async () => body }; }
const daily = [];
for (let m = 1; m <= 6; m++) for (const d of ['02','15','28']) daily.push({ date: `2026-0${m}-${d}`, price: 2000 + m * 50 + Number(d) });
globalThis.fetch = async (url, o = {}) => {
  const method = (o.method || 'GET').toUpperCase();
  log.push(method + ' ' + url + (o.body ? ' ' + o.body : ''));
  if (url.includes('/user-portfolio')) return jr({ total_value_eur: 100000, holdings: [{ instrument_id: 'RELIANCE', allocation_pct: 60, shares: 10, cash_eur: 0 }] });
  if (url.includes('/geography-overview')) return jr({ regions: [{ region: 'India', instruments: [{ id: 'RELIANCE', close: 2500, currency: 'INR', daily_return_pct: 1.5, return_1y_pct: 12, risk_score: 4 }] }] });
  if (url.includes('/portfolio-analytics')) return jr({ positions: [{ und: 'NIFTY', exp: 'EQUITY', type: 'CE', qty: 1, ltp: 24000, avg: 24000, currency: 'INR', ann_vol_pct: 18 }],
    greeks: [{ und: 'RELIANCE', allocation_pct: 60, ann_vol_pct: 30, gamma: 0 }], net_greeks: {}, hedge_quality: { positions: [] } });
  if (url.includes('/equity-hedge-scenarios')) return jr({ portfolio: { currency: 'INR', n_shares: 10, daily }, hedge_scenarios: {} });
  if (url.includes('/portfolio-hedge')) return jr(null, 404);
  if (url.includes('/kite-live')) return jr({ available: false, source: 'fallback', lot_size: null, quote: null, margin: null });
  if (url.includes('/hedge-history')) return jr([]);
  if (url.includes('/hedge-plan')) return jr(null);
  return jr(null, 404);
};
const base = pathToFileURL(process.cwd() + '/').href;
const wf = await import(base + 'fno/hedge-workflow.js');
const { state } = await import(base + 'fno/state.js');
const hw = state.hedgeWorkflow;
"""


def test_exposure_step_renders_challenge_candles_and_no_holdings_table(jsroot):
    r = _node(jsroot, _PRELUDE + r"""
await wf.loadHedgeWorkflow();
await new Promise(r => setTimeout(r, 50));
const candle = charts.filter(c => c.id === 'hw-exp-candle-chart').at(-1);
const change = charts.filter(c => c.id === 'hw-exp-change-chart').at(-1);
console.log(JSON.stringify({
  inst: hw.instrumentId,
  tiles: document.getElementById('hw-exp-sigma-kpis').innerHTML,
  summary: document.getElementById('hw-exp-latest-view').innerHTML,
  oldSummary: 'hw-exp-challenge-summary' in els,
  yBegin: candle?.cfg.options.scales.y.beginAtZero,
  candleColors: candle?.cfg.data.datasets.slice(1).map(d => d.borderColor),
  changeColors: change?.cfg.data.datasets.slice(1).map(d => d.borderColor),
  changeLabels: change?.cfg.data.datasets.map(d => d.label),
  lastClose: daily.at(-1).price,
  holdingsTouched: 'hw-exp-holdings-table' in els,
  labels: candle?.cfg.data.datasets.map(d => d.label),
  bandVals: candle?.cfg.data.datasets.slice(1).map(d => d.data[0]),
  changeBars: change?.cfg.data.datasets[0].data.length,
  post: log.filter(l => l.includes('equity-hedge-scenarios')),
}));""")
    assert r["inst"] == "RELIANCE" and r["holdingsTouched"] is False
    s = 30 / 100 / math.sqrt(12)
    assert f"{-s * 100:.1f}%" in r["tiles"] and f"{-s * 300:.1f}%" in r["tiles"]
    # panels, not prose: .kpi tiles with label/value/sub; last price from the candle series
    assert r["summary"].count('class="kpi"') >= 4 and "Latest Price View" in r["summary"]
    assert "kpi-sub" in r["summary"] and "<strong" not in r["summary"]
    assert "₹2,328.00" in r["summary"] or "2,328.00" in r["summary"]
    assert "Portfolio monthly −1σ" in r["summary"] and "Portfolio monthly −3σ" in r["summary"]
    assert f"−€{100000 * s:,.0f}".replace("−€", "−€") in r["summary"]
    assert "Your current challenge" not in r["summary"] and r["oldSummary"] is False
    # ONE σ (±1σ dotted pair, no 2σ/3σ), anchored on the candle series' last close
    assert r["labels"][0] == "Body" and len(r["labels"]) == 3
    last = 2000 + 6 * 50 + 28
    assert r["lastClose"] == last
    assert r["bandVals"] == pytest.approx([last * (1 + s), last * (1 - s)], rel=1e-12)
    # +1σ blue, −1σ red (distinct), on both charts
    for cols in (r["candleColors"], r["changeColors"]):
        assert cols == ["#0056B8", "#9B1C1C"] and cols[0] != cols[1]
    assert r["yBegin"] is False  # candles must not be squashed against a zero baseline
    assert len(r["changeLabels"]) == 3 and r["changeLabels"][1].startswith("+1σ") and r["changeLabels"][2].startswith("−1σ")
    assert r["changeBars"] == 5
    assert len(r["post"]) == 1 and '"n_shares":10' in r["post"][0]


def test_exposure_option_only_instrument_uses_n_shares_1_and_notes_no_holding(jsroot):
    r = _node(jsroot, _PRELUDE + r"""
await wf.loadHedgeWorkflow();
wf.hwSelectInstrument('NIFTY');
await new Promise(r => setTimeout(r, 50));
console.log(JSON.stringify({ msg: document.getElementById('hw-exp-candle-msg').innerHTML,
  post: log.filter(l => l.includes('equity-hedge-scenarios')).at(-1) }));""")
    assert "No equity holding for NIFTY" in r["msg"]
    assert '"instrument":"NIFTY"' in r["post"] and '"n_shares":1' in r["post"]
    assert '"ann_vol_pct":18' in r["post"]


def test_exposure_history_failure_degrades_with_message(jsroot):
    r = _node(jsroot, _PRELUDE + r"""
const orig = globalThis.fetch;
globalThis.fetch = async (u, o = {}) => u.includes('/equity-hedge-scenarios') ? jr({ detail: 'x' }, 422) : orig(u, o);
await wf.loadHedgeWorkflow();
await new Promise(r => setTimeout(r, 50));
console.log(JSON.stringify({ msg: document.getElementById('hw-exp-candle-msg').innerHTML,
  tiles: document.getElementById('hw-exp-sigma-kpis').innerHTML.length > 0 }));""")
    assert "Price history unavailable" in r["msg"] and r["tiles"] is True


def test_save_step_shows_impact_table_chart_and_keeps_save_button(jsroot):
    r = _node(jsroot, _PRELUDE + r"""
await wf.loadHedgeWorkflow('save');
await new Promise(r => setTimeout(r, 50));
const imp = document.getElementById('hw-save-impact-table').innerHTML;
const ch = charts.filter(c => c.id === 'hw-save-impact-chart').at(-1);
console.log(JSON.stringify({ step: hw.step, imp, kpis: document.getElementById('hw-save-impact-kpis').innerHTML,
  labels: ch?.cfg.data.labels, summary: document.getElementById('hw-save-summary').innerHTML.length > 0 }));""")
    assert r["step"] == "save" and r["summary"] is True
    assert r["labels"] == ["Flat", "−1σ", "−2σ", "−3σ"]
    assert "Unhedged P&amp;L" in r["imp"] and "Protected" in r["imp"]
    assert "Max drawdown" in r["kpis"] and "Premium cost" in r["kpis"]


def test_sigma_line_within_candle_value_range_scale_and_equity_chart_unchanged(jsroot):
    """The σ line is lastClose×(1−σ) on the candle series itself, so it can never sit in a
    different unit scale; the Equity Hedge page keeps its original zero-based axis + ±1σ."""
    uri = (jsroot / "fno" / "hedge-charts.js").as_uri()
    r = _node(jsroot, _PRELUDE.split("const base")[0] + f"""
import * as ch from {json.dumps(uri)};
const bands = [{{label:'b', value: daily.at(-1).price*(1-0.05)}}];
const c1 = ch.renderMonthlyCandles('x', daily, {{ bands, beginAtZero:false }});
const c2 = ch.renderMonthlyCandles('y', daily, {{}});
const c3 = ch.renderMonthlyChange('z', daily, {{}});
const lows = c1.cfg.data.datasets[0].data.map(d=>d[0]);
console.log(JSON.stringify({{ line: c1.cfg.data.datasets[1].data[0], minLow: Math.min(...lows), maxHigh: Math.max(...c1.cfg.data.datasets[0].data.map(d=>d[1])),
  eqUp: c3.cfg.data.datasets[1].borderColor,
  zeroDefault: c2.cfg.options.scales.y.beginAtZero, nLines: c2.cfg.data.datasets.length, mom: c3.cfg.data.datasets.length }}));""")
    assert 0.5 * r["minLow"] < r["line"] < r["maxHigh"]
    assert r["eqUp"] == "#9B1C1C"  # Equity Hedge keeps its original red ±1σ
    assert r["zeroDefault"] is True and r["nLines"] == 1 and r["mom"] == 4


def test_recommendation_step_renders_original_advisor_screen_and_selection_table(jsroot):
    r = _node(jsroot, _PRELUDE + r"""
const orig = globalThis.fetch;
const steps = ['REGIME','TECHNICAL','SENTIMENT','ALLOC','VOL','GOAL','HEDGE_ADVISOR'].map((a, i) => ({ agent: a, title: 't'+i, narrative: 'n'+i, verdict: 'Bullish', data: i === 6 ? { primary_recommendation: 'call_sell', call_sell: {}, put_buy: {} } : {} }));
globalThis.fetch = async (u, o = {}) => u.includes('/hedge-reasoning')
  ? jr({ steps, recommendation: 'call_sell', confidence: 'High', spot_price: 2500, data_source: 'x', timestamp: null })
  : orig(u, o);
await wf.loadHedgeWorkflow('recommendation');
await new Promise(r => setTimeout(r, 4000));
const rec = await import(base + 'fno/hedge-workflow-recommendation.js');
console.log(JSON.stringify({
  step: hw.step, sel: hw.selections['RELIANCE'],
  res: els['ha-results'].style.display, s0: els['ha-step-0-narrative'].textContent, s6: els['ha-step-6-verdict'].textContent,
  detail: els['hw-rec-detail'].innerHTML, step6data: els['ha-step-6-data'].innerHTML, table: els['hw-rec-selection-table'].innerHTML.includes('Hedged?'),
  oldCard: 'hw-rec-verdict-card' in els || 'hw-rec-cascade' in els,
}));""")
    assert r["step"] == "recommendation" and r["sel"] == "call_sell"
    assert r["res"] == "" and r["s0"] == "n0" and r["s6"] == "Bullish"
    d = r["detail"]
    assert d.count('class="kpi"') == 6 and "CALL SELL" in d and "High" in d
    assert all(k in d for k in ("Recommendation", "Confidence", "Spot", "Data source", "Call sell", "Put buy"))
    assert r["step6data"] == "" and "reasoning-card" not in r["step6data"]  # no duplicate call/put cards
    assert "&#9733; Call sell" in d and "&#9733; Put buy" not in d  # ★ on the recommended leg only
    assert r["table"] is True and r["oldCard"] is False


def test_advisor_markup_six_up_row_then_separate_hedge_advisor_row():
    html = (_ROOT / "dashboard" / "fno.html").read_text(encoding="utf-8")
    a = html.index('id="hw-step-recommendation"')
    seg = html[a: html.index('id="hw-step-whatif"')]
    grid1 = seg.index('class="ha-steps-grid"')
    grid2 = seg.index('id="hw-rec-advisor-row"')
    for i in range(6):
        assert grid1 < seg.index(f'id="ha-step-{i}"') < grid2
    assert seg.index('id="ha-step-6"') > grid2
    assert seg.count('id="ha-step-6"') == 1 and 'id="ha-final-verdict"' not in seg
    # ONE row: narrative panel (#ha-step-6) and the summary panels share #hw-rec-advisor-row
    row_end = seg.index('<!-- /hw-rec-advisor-row -->')
    assert grid2 < seg.index('id="ha-step-6"') < seg.index('id="hw-rec-detail"') < row_end < seg.index('id="hw-rec-selection-table"')
    assert 'id="ha-step-6-verdict" style="display:none' in seg  # no separate 7th-panel verdict heading
    assert seg.index('id="hw-rec-selection-table"') < seg.index('id="hw-rec-next-btn"')
    assert "repeat(6,minmax(0,1fr))" in html and "ha-steps-grid--row2{grid-template-columns:minmax(0,1fr)" in html
