"""F40 Phase 3 — position-value chart flow, driven through node against dashboard/js.

Covers: loadPositionValue URL/params + cache key (vol), renderPositionValue (title, ±1σ band
datasets/labels, non-ok message with no chart, bands-null note), node buildMonthlyCandles(daily)
== server candles (contract), full Exposure flow (position-value fetched with the Monthly σ
tile vol as ann_vol_pct override, candle card = position value, MoM chart stays on PRICE),
API failure keeps the rest of Exposure, instrument-switch race dropped, hwRefreshStep refetches,
and static guards (no old price-candle strings, no raw fetch / new Chart in the new module).
Skipped when node is absent.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_JS = _ROOT / "dashboard" / "js"
_FNO = _JS / "fno"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _node(workdir: Path, source: str) -> object:
    script = workdir / "run.mjs"
    script.write_text(source, encoding="utf-8")
    out = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60, cwd=workdir)
    assert out.returncode == 0, out.stderr[-3000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def jsroot(tmp_path_factory) -> Path:
    dst = tmp_path_factory.mktemp("js40p3")
    shutil.copytree(_JS, dst / "js")
    (dst / "js" / "package.json").write_text('{"type":"module"}', encoding="utf-8")
    return dst / "js"


_PRELUDE = r"""
import { pathToFileURL } from 'node:url';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const store = {};
globalThis.window = globalThis;
globalThis.sessionStorage = { getItem:k=>store[k]??null, setItem:(k,v)=>{store[k]=String(v)}, removeItem:k=>{delete store[k]} };
globalThis.location = { hostname:'localhost', href:'http://localhost/' };
const els = {};
const WATCH = new Set(['hw-exp-candle-title','hw-exp-candle-msg','hw-exp-candle-chart','hw-exp-change-chart','hw-exp-change-title',
  'hw-exp-latest-view','hw-exp-sigma-kpis','hw-exp-hqs-banner','hw-stepper']);
globalThis.document = {
  getElementById: (id) => WATCH.has(id) ? (els[id] ??= { id, innerHTML: '', style: {} }) : null,
  querySelector:()=>null, querySelectorAll:()=>[], addEventListener(){} };
const charts = [];
globalThis.Chart = class { constructor(ctx, cfg){ this.ctx = ctx; this.cfg = cfg; this.destroyed = false; charts.push(this); }
  destroy(){ this.destroyed = true; } update(){} static register(){} };
globalThis.Chart.defaults = { font: {} };
const live = (canvas) => charts.filter((c) => c.ctx.id === canvas && !c.destroyed);
const log = [];
const opts = { pv: 'ok', pvDelayRel: 0 };
function jr(body, status = 200) { return { ok: status < 400, status, statusText: 'x', json: async () => body }; }
const DAILY = [];
for (let m = 0; m < 4; m++) for (let d = 1; d <= 3; d++) DAILY.push({ date: `2026-0${m + 6}-0${d}`, value: 1000 + m * 100 + d * 7 });
const CANDLES = (() => { const by = {}; for (const x of DAILY) (by[x.date.slice(0, 7)] ??= []).push(x.value);
  return Object.keys(by).sort().map((k) => ({ month: k, open: by[k][0], high: Math.max(...by[k]), low: Math.min(...by[k]), close: by[k].at(-1) })); })();
const BANDS = { anchor_value: 1300, anchor_date: '2026-09-03', plus_1sigma_value: 1390, minus_1sigma_value: 1210, plus_1sigma_pct: 6.9282, minus_1sigma_pct: -6.9282 };
function pvItem(id, over = {}) {
  return { instrument_id: id, status: 'ok', message: '', currency: 'INR', currency_symbol: '₹', shares: 10, months: 12,
    last_close: 130, last_value: 1300, ann_vol_pct: 24, vol_source: 'override', monthly_sigma_pct: 6.9282, bands: BANDS,
    candles: CANDLES, daily: DAILY, ...over };
}
globalThis.fetch = async (url, o = {}) => {
  const method = (o.method || 'GET').toUpperCase();
  log.push(method + ' ' + url);
  if (url.includes('/experience/fno/position-value')) {
    const id = new URL('http://x' + url).searchParams.get('instrument');
    if (id === 'RELIANCE' && opts.pvDelayRel) await sleep(opts.pvDelayRel);
    if (opts.pv === 'fail') return jr({ detail: 'boom' }, 500);
    if (opts.pv === 'nohold') return jr({ as_of: null, items: [{ instrument_id: id, status: 'no_holding', message: `No equity holding for ${id} (option exposure only). Position value needs shares held.`,
      currency: null, currency_symbol: '', shares: null, months: 12, candles: [], daily: [], bands: null }] });
    return jr({ as_of: '2026-09-03', items: [pvItem(id)] });
  }
  if (url.includes('/user-portfolio')) return jr({ total_value_eur: 100000, name: 'p', holdings: [
      { instrument_id: 'RELIANCE', allocation_pct: 60, shares: 10, cash_eur: 0 },
      { instrument_id: 'INFY', allocation_pct: 40, shares: 5, cash_eur: 0 }] });
  if (url.includes('/geography-overview')) return jr({ regions: [{ region: 'India', instruments: [
    { id: 'RELIANCE', close: 2500, daily_return_pct: 1.5, return_1y_pct: 12, risk_score: 4 },
    { id: 'INFY', close: 1500, daily_return_pct: 1, return_1y_pct: 8, risk_score: 3 }] }] });
  if (url.includes('/portfolio-analytics')) return jr({ positions: [], greeks: [{ und: 'RELIANCE', ann_vol_pct: 25, allocation_pct: 60 }, { und: 'INFY', ann_vol_pct: 30, allocation_pct: 40 }], net_greeks: {}, hedge_quality: { positions: [] } });
  if (url.includes('/equity-hedge-scenarios')) return jr({ portfolio: { currency: 'INR', daily: DAILY.map((d) => ({ date: d.date, price: d.value / 10 })) } });
  if (url.includes('/kite-live')) return jr({ instrument_id: 'RELIANCE', available: false, source: 'fallback', lot_size: 250, quote: null, margin: null, fetched_at: null });
  if (url.includes('/hedge-plan')) return jr(null);
  return jr(null, 404);
};
const base = pathToFileURL(process.cwd() + '/').href;
const wf = await import(base + 'fno/hedge-workflow.js');
const pvm = await import(base + 'fno/hedge-position-value.js');
const hc = await import(base + 'fno/hedge-charts.js');
const { state } = await import(base + 'fno/state.js');
const hw = state.hedgeWorkflow;
const pvCalls = () => log.filter((l) => l.includes('/position-value'));
"""


def _flow(jsroot: Path, body: str) -> object:
    return _node(jsroot, _PRELUDE + "\n" + body + "\nprocess.exit(0);")


def test_load_url_params_and_cache_key(jsroot):
    r = _flow(jsroot, r"""
const a = await pvm.loadPositionValue('RELIANCE', 25);
await pvm.loadPositionValue('RELIANCE', 25);          // cached
await pvm.loadPositionValue('RELIANCE', null);        // different key, no override param
await pvm.loadPositionValue('RELIANCE', 30);
console.log(JSON.stringify({ calls: pvCalls(), id: a.instrument_id, keys: Object.keys(hw.positionValue).sort() }));""")
    assert len(r["calls"]) == 3
    assert "instrument=RELIANCE" in r["calls"][0] and "months=12" in r["calls"][0] and "ann_vol_pct=25" in r["calls"][0]
    assert "ann_vol_pct" not in r["calls"][1]
    assert r["keys"] == ["RELIANCE|", "RELIANCE|25.0000", "RELIANCE|30.0000"]


def test_render_ok_title_bands_and_candle_contract(jsroot):
    r = _flow(jsroot, r"""
const item = pvItem('RELIANCE');
const ch = pvm.renderPositionValue('RELIANCE', item, null);
const cfg = ch.cfg;
const built = hc.buildMonthlyCandles(item.daily.map((d) => ({ date: d.date, price: d.value })));
const srv = item.candles.map((c) => ({ o: c.open, h: c.high, l: c.low, c: c.close }));
console.log(JSON.stringify({ title: els['hw-exp-candle-title'].innerHTML, msg: els['hw-exp-candle-msg'].innerHTML,
  labels: cfg.data.labels, nDs: cfg.data.datasets.length,
  bands: cfg.data.datasets.slice(1).map((d) => ({ l: d.label, v: d.data[0], dash: d.borderDash })),
  candlesMatch: JSON.stringify(built.candles) === JSON.stringify(srv),
  y0: cfg.options.scales.y.beginAtZero, fmt: cfg.options.scales.y.ticks.callback(1234.4),
  titles: pvm.positionValueBands(item).length }));""")
    assert r["title"] == "Position value — RELIANCE (shares × price, INR), 10 shares"
    assert r["msg"] == "" and r["nDs"] == 3 and len(r["labels"]) == 4
    assert r["bands"][0]["l"] == "+1σ monthly (+6.9%)" and r["bands"][0]["v"] == 1390 and r["bands"][0]["dash"] == [3, 3]
    assert r["bands"][1]["l"] == "−1σ monthly (−6.9%)" and r["bands"][1]["v"] == 1210
    assert r["candlesMatch"] is True and r["y0"] is False and r["fmt"] == "₹1,234"


def test_bands_null_note_and_non_ok_clears_chart(jsroot):
    r = _flow(jsroot, r"""
const ch = pvm.renderPositionValue('RELIANCE', pvItem('RELIANCE', { bands: null, ann_vol_pct: null }), null);
const noBands = { nDs: ch.cfg.data.datasets.length, msg: els['hw-exp-candle-msg'].innerHTML };
const before = charts.length;
const none = pvm.renderPositionValue('NIFTY', { instrument_id: 'NIFTY', status: 'no_holding',
  message: 'No equity holding for NIFTY (option exposure only). Position value needs shares held.', candles: [], daily: [], bands: null }, ch);
console.log(JSON.stringify({ noBands, ret: none, destroyed: ch.destroyed, created: charts.length - before,
  title: els['hw-exp-candle-title'].innerHTML, msg: els['hw-exp-candle-msg'].innerHTML }));""")
    assert r["noBands"] == {"nDs": 1, "msg": "Volatility unavailable; ±1σ lines hidden."}
    assert r["ret"] is None and r["destroyed"] is True and r["created"] == 0
    assert r["title"] == "Position value — NIFTY"
    assert r["msg"] == "No equity holding for NIFTY (option exposure only). Position value needs shares held."


def test_message_is_html_escaped(jsroot):
    r = _flow(jsroot, r"""
pvm.renderPositionValue('X', { instrument_id: 'X<b>', status: 'no_holding', message: '<img src=x onerror=1>', candles: [], daily: [] }, null);
console.log(JSON.stringify({ t: els['hw-exp-candle-title'].innerHTML, m: els['hw-exp-candle-msg'].innerHTML }));""")
    assert "<" not in r["t"].replace("&lt;", "") and "<img" not in r["m"]


def test_exposure_flow_uses_tile_vol_and_keeps_price_mom_chart(jsroot):
    r = _flow(jsroot, r"""
await wf.hwGoToStep('exposure', false); await sleep(80);
const cand = live('hw-exp-candle-chart'), chg = live('hw-exp-change-chart');
console.log(JSON.stringify({ pv: pvCalls(), candN: cand.length, candDs: cand[0]?.cfg.data.datasets.length,
  chgN: chg.length, chgPrice: log.filter((l) => l.includes('/equity-hedge-scenarios')).length,
  title: els['hw-exp-candle-title'].innerHTML, msg: els['hw-exp-candle-msg'].innerHTML,
  chgTitle: els['hw-exp-change-title']?.textContent }));""")
    assert len(r["pv"]) == 1 and "instrument=RELIANCE" in r["pv"][0] and "ann_vol_pct=25" in r["pv"][0]
    assert r["candN"] == 1 and r["candDs"] == 3 and r["chgN"] == 1 and r["chgPrice"] == 1
    assert r["title"].startswith("Position value — RELIANCE") and r["msg"] == ""
    assert "Monthly Price Change" in (r["chgTitle"] or "")


def test_api_failure_shows_unavailable_and_mom_still_renders(jsroot):
    r = _flow(jsroot, r"""
opts.pv = 'fail';
await wf.hwGoToStep('exposure', false); await sleep(80);
console.log(JSON.stringify({ cand: live('hw-exp-candle-chart').length, chg: live('hw-exp-change-chart').length,
  msg: els['hw-exp-candle-msg'].innerHTML, title: els['hw-exp-candle-title'].innerHTML }));""")
    assert r["cand"] == 0 and r["chg"] == 1
    assert r["msg"] == "Position value unavailable for RELIANCE."


def test_option_only_message_no_chart_flow(jsroot):
    r = _flow(jsroot, r"""
opts.pv = 'nohold';
await wf.hwGoToStep('exposure', false); await sleep(80);
console.log(JSON.stringify({ cand: live('hw-exp-candle-chart').length, msg: els['hw-exp-candle-msg'].innerHTML }));""")
    assert r["cand"] == 0 and r["msg"].startswith("No equity holding for RELIANCE (option exposure only)")


def test_instrument_switch_race_drops_stale_and_refresh_refetches(jsroot):
    r = _flow(jsroot, r"""
opts.pvDelayRel = 150;
const p = wf.hwGoToStep('exposure', false);
await sleep(30);
wf.hwSelectInstrument('INFY');
await p; await sleep(300);
const afterSwitch = { title: els['hw-exp-candle-title'].innerHTML, cand: live('hw-exp-candle-chart').length };
const n0 = pvCalls().length;
await wf.hwRefreshStep(); await sleep(150);
console.log(JSON.stringify({ afterSwitch, refetched: pvCalls().length > n0 }));""")
    assert "INFY" in r["afterSwitch"]["title"] and r["afterSwitch"]["cand"] == 1
    assert r["refetched"] is True


def test_static_guards():
    mod = (_FNO / "hedge-position-value.js").read_text(encoding="utf-8")
    assert "fetch(" not in re.sub(r"//.*", "", mod).replace("apiFetch", "")
    assert "new Chart" not in mod and "window." not in mod
    wfsrc = (_FNO / "hedge-workflow.js").read_text(encoding="utf-8")
    assert "showing the instrument price" not in wfsrc and "latest price vs monthly 1σ" not in wfsrc
    assert "renderMonthlyCandles" not in wfsrc  # candle card delegated
    assert "renderMonthlyChange" in wfsrc        # MoM chart stays on price
    html = (_ROOT / "dashboard" / "fno.html").read_text(encoding="utf-8")
    assert "Monthly OHLC of position value · dotted = ±1σ" in html
    assert "positionValue: {}" in (_FNO / "state.js").read_text(encoding="utf-8")
