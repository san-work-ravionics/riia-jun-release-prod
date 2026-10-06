"""F42 P4 — Spot vs P&L card: static contract + (node, when available) lazy-load behaviour."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from rita.schemas import fno_trade_analytics as sch

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "dashboard/js/fno/trade-analytics.js").read_text()
MAIN = (ROOT / "dashboard/js/fno/main.js").read_text()
HTML = (ROOT / "dashboard/fno.html").read_text()


def _func(name: str) -> str:
    m = re.search(rf"^(?:export )?(?:async )?function {name}\(.*?\n}}\n", JS, re.S | re.M)
    assert m, name
    return m.group(0)


def _reads(body: str, var: str) -> set[str]:
    return set(re.findall(rf"(?<![\w.]){var}\.([a-z_0-9]+)\b", body))


_MAP = {
    "_spotVerdictLine": {"u": [sch.SpotPnlUnderlying], "al": [sch.Alignment], "ad": [sch.CorrBlock]},
    "_spotRelationHtml": {"u": [sch.SpotPnlUnderlying], "rel": [sch.Relationship], "al": [sch.Alignment],
                          "tt": [sch.SpotPnlTotals], "sn": [sch.UnrealisedSnapshot]},
    "_spotChart": {"u": [sch.SpotPnlUnderlying], "s": [sch.SpotPnlSeries], "sn": [sch.UnrealisedSnapshot]},
    "_renderSpotPnl": {"d": [sch.SpotVsPnlResponse], "u": [sch.SpotPnlUnderlying]},
    "_spotRulesHtml": {"im": [sch.Improvement], "r": [sch.RelatedLink]},
    "_spotObsHtml": {"d": [sch.SpotVsPnlResponse], "u": [sch.SpotPnlUnderlying], "o": [sch.Observation]},
    "_corrRow": {"c": [sch.CorrBlock]},
    "_bucketRows": {"b": [sch.SpotBucket]},
}


@pytest.mark.parametrize("fn", sorted(_MAP))
def test_fields_read_exist_in_schema(fn):
    body = _func(fn)
    for var, models in _MAP[fn].items():
        have = set().union(*(set(m.model_fields) for m in models))
        assert _reads(body, var) <= have, (fn, var, _reads(body, var) - have)
    assert "truncated" in JS and "dropped_days" in sch.SpotPnlSeries.model_fields


def test_ids_exist_in_html_and_card_is_closed_by_default():
    ids = ["ta-panel-spotpnl", "ta-an-spotpnl-body", "ta-an-spotpnl-def", "ta-an-spotpnl-grid", "ta-an-spotpnl-obs",
           "ta-an-spotpnl-rules"] + [f"ta-an-spotpnl-{k}-{i}" for k in ("slot", "title", "rel") for i in (0, 1)] \
        + [f"ta-cv-spot-{i}" for i in (0, 1)]
    for i in ids:
        assert f'id="{i}"' in HTML, i
    tag = re.search(r'<details[^>]*id="ta-panel-spotpnl"[^>]*>', HTML).group(0)
    assert " open" not in tag and 'ontoggle="taAnSpotToggle(this.open)"' in tag
    assert HTML.index('id="ta-panel-marketturn"') < HTML.index('id="ta-panel-spotpnl"') < HTML.index('id="ta-panel-margintrap"')
    for k in ("ta-an-spotpnl-body", "ta-an-spotpnl-def", "ta-an-spotpnl-obs", "ta-an-spotpnl-rules"):
        assert k in JS
    assert "ta-cv-spot-" in JS and "ta-an-spotpnl-slot-" in JS


def test_binding_loader_isolation_and_wording():
    assert "window.taAnSpotToggle = taAnSpotToggle" in MAIN and "taAnSpotToggle" in MAIN.split("trade-analytics.js")[0]
    assert re.search(r"export function taAnSpotToggle\b", JS)
    assert "spot-vs-pnl" not in re.search(r"const _ENDPOINTS = \{.*?\};", JS, re.S).group(0)
    assert _func("loadAnalyticsPanels").count("spot-vs-pnl") == 0
    assert "'spotpnl'" in JS
    assert "`${_BASE}spot-vs-pnl?${qs}`" in _func("loadSpotPnl")
    new = JS[JS.index("F42 P4: Spot vs P&L"):JS.index("const _RENDER = {")]
    for banned in ("should", "recommend", "buy", "sell", "localhost"):
        assert not re.search(rf"\b{banned}\b", new, re.I), banned
    assert not re.search(r"\b(75|30)\b", new)
    assert "typeof Chart === 'undefined'" in JS and "destroyChart" in JS
    for v in ("_spotLoaded", "_spotStale", "_spotSeq", "_spotKey"):
        assert f"let {v}" in JS
    assert "Observed, not a prediction" in new and "mostly positioned with the market" in JS
    assert "_ruleCard" in _func("_spotRulesHtml") and "illustrative" in _func("_ruleCard")


NODE = shutil.which("node")

HARNESS = r"""
import { taAnSpotToggle, taAnRefresh, loadAnalyticsPanels } from './js/fno/trade-analytics.js';
const g = globalThis.__t;
const log = (...a) => g.out.push(a.join(' '));
const spotCalls = () => g.calls.filter(u => u.includes('spot-vs-pnl')).length;
await loadAnalyticsPanels();                       // page load, card closed
log('closed_fetch', spotCalls());
await taAnSpotToggle(true); await new Promise(r => setTimeout(r, 5));
log('first_open', spotCalls());
taAnSpotToggle(false); await taAnSpotToggle(true); await new Promise(r => setTimeout(r, 5));
log('reopen_same_key', spotCalls());
g.filters.underlying = 'NIFTY'; taAnSpotToggle(false);
await loadAnalyticsPanels();                       // filter changed while closed: stale only
log('changed_closed', spotCalls());
await taAnSpotToggle(true); await new Promise(r => setTimeout(r, 5));
log('reopen_after_change', spotCalls());
await taAnRefresh(); await new Promise(r => setTimeout(r, 5));
log('refresh_open', spotCalls());
log('urls', g.calls.filter(u => u.includes('spot-vs-pnl')).map(u => u.includes('underlying=NIFTY')).join(','));
log('charts_guard', g.charts);
"""


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_lazy_card_fetches_once_per_filter_key(tmp_path):
    (tmp_path / "package.json").write_text('{"type":"module"}')
    fno = tmp_path / "js/fno"
    shared = tmp_path / "js/shared"
    fno.mkdir(parents=True)
    shared.mkdir(parents=True)
    (fno / "trade-analytics.js").write_text(JS)
    (fno / "api.js").write_text(
        "export async function api(u){ const g=globalThis.__t; g.calls.push(u);"
        " return {available:false, reason:'no_data', underlyings:[], filter:{}}; }")
    (shared / "utils.js").write_text("export function setEl(id,h){ globalThis.__t.els[id]=h; }")
    (shared / "charts.js").write_text("export function mkChart(id){ globalThis.__t.charts++; }"
                                      " export function destroyChart(id){}")
    (fno / "trade-analysis.js").write_text(
        "export const _esc=s=>String(s); export const _num=v=>v==null?'—':String(v); export const _pnl=_num;"
        " export const taGetFilters=()=>globalThis.__t.filters;")
    (tmp_path / "run.mjs").write_text(
        "globalThis.__t={calls:[],els:{},out:[],charts:0,filters:{underlying:'ALL',month:''}};"
        "globalThis.document={getElementById:()=>({style:{},checked:false,value:''})};"
        "globalThis.Chart=function(){};"
        "await import('./harness.mjs');console.log(JSON.stringify(globalThis.__t.out));")
    (tmp_path / "harness.mjs").write_text(HARNESS)
    r = subprocess.run([NODE, "run.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = dict(x.split(" ", 1) for x in json.loads(r.stdout.strip().splitlines()[-1]))
    assert out["closed_fetch"] == "0" and out["first_open"] == "1"
    assert out["reopen_same_key"] == "1" and out["changed_closed"] == "1"
    assert out["reopen_after_change"] == "2" and out["refresh_open"] == "3"
    assert out["urls"] == "false,true,true"
