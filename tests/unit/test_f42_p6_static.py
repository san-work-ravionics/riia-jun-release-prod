"""F42 P6 — static contract: DOM ids, container-query CSS, renderer purity, schema parity of the fields read,
wording ban (with the mandatory disclaimer whitelisted), copy coverage, cache lifecycle order."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from rita.schemas import fno_trade_analytics as sch

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "dashboard/js/fno/trade-analytics.js").read_text()
MAIN = (ROOT / "dashboard/js/fno/main.js").read_text()
HTML = (ROOT / "dashboard/fno.html").read_text()
DISCLAIMER = "Observations from your own imported history, not investment advice or a forecast."


def _func(name: str) -> str:
    m = re.search(rf"^(?:export )?(?:async )?function {name}\(.*?\n}}\n", JS, re.S | re.M)
    assert m, name
    return m.group(0)


def _reads(body: str, var: str) -> set[str]:
    return set(re.findall(rf"(?<![\w.]){var}\.([a-z_0-9]+)\b", body))


# ── DOM ids (design 9.1) ──────────────────────────────────────────────────────────────────

NEW_IDS = (
    [f"ta-an-{k}-headline" for k in ("overtrading", "buildup", "margintrap", "suggestions")]
    + [f"ta-an-{k}-what" for k in ("overtrading", "buildup", "margintrap", "suggestions")]
    + [f"ta-an-{k}-how" for k in ("overtrading", "buildup", "margintrap", "suggestions")]
    + ["ta-cv-holding", "ta-an-overtrading-note", "ta-bu-chain-sel", "ta-an-buildup-glossary", "ta-an-margintrap-caveat",
       "ta-panel-details", "ta-an-detail-a", "ta-an-detail-b", "ta-an-fulltables", "ta-an-fulltables-body",
       "ta-an-sg-summary", "ta-an-sg-obs", "ta-an-sg-grid", "ta-an-sg-host", "ta-sg-expand-all", "ta-sg-collapse-all"])
KEPT_IDS = (["ta-panel-overtrading", "ta-panel-buildup", "ta-panel-margintrap", "ta-panel-suggestions", "ta-panel-marketturn",
             "ta-panel-spotpnl", "ta-cv-weekly", "ta-cv-buildup", "ta-cv-cash", "ta-an-recon", "ta-an-status", "ta-empty-cta",
             "ta-an-from", "ta-an-expiry-est"]
            + [f"ta-an-{k}-body" for k in ("overtrading", "buildup", "margintrap", "suggestions")]
            + [f"ta-an-{k}-def" for k in ("overtrading", "buildup", "margintrap", "suggestions")])


@pytest.mark.parametrize("i", NEW_IDS + KEPT_IDS)
def test_ids_exist_once(i):
    assert len(re.findall(rf'id="{re.escape(i)}"', HTML)) == 1, i


def test_panel_order_and_details_hosts():
    pos = [HTML.index(f'id="{i}"') for i in ("ta-panel-overtrading", "ta-panel-buildup", "ta-panel-margintrap",
                                             "ta-panel-details", "ta-an-fulltables")]
    assert pos == sorted(pos)
    assert 'data-ta-tab="behaviour"' in re.search(r'<[^>]*id="ta-panel-details"[^>]*>', HTML).group(0)
    assert 'data-ta-tab="suggestions"' in re.search(r'<[^>]*id="ta-panel-suggestions"[^>]*>', HTML).group(0)
    assert 'class="ta-cq"' in HTML and re.search(r'id="ta-an-sg-host" class="ta-cq"', HTML)
    ft = re.search(r'<details[^>]*id="ta-an-fulltables"[^>]*>', HTML).group(0)
    assert " open" not in ft and "taAnFullToggle(this.open)" in ft
    assert "Full data tables (11)" in HTML


def test_static_copy_present():
    assert "This describes what happened on the same days, not why." in HTML and "cannot say whether low cash kept you in a trade" in HTML
    assert "Position chain = one position from your first fill until it is fully closed" in HTML
    assert "not investment advice or a forecast" in HTML
    assert "Stop-loss what-if" in HTML


# ── CSS: container-based sizing (design 17.1; thresholds stated in N2) ─────────────────────────────

def _css() -> str:
    a = HTML.index("/* F42 P6")
    return HTML[a:HTML.index("/* Charts */", a) if "/* Charts */" in HTML[a:] else a + 6000]


def test_single_row_widgets_are_container_based():
    css = _css()
    assert ".ta-cq{container-type:inline-size" in css
    assert re.search(r"\.kpi-row\.ta-row1\{display:flex[^}]*overflow-x:auto", css)               # default: ONE row, scrolls sideways
    assert re.search(r"@container \(min-width:900px\)\{ \.kpi-row\.c8\{display:grid;grid-template-columns:repeat\(8,", css)
    assert re.search(r"@container \(max-width:479px\)\{ \.kpi-row\.ta-row1\{display:grid;grid-template-columns:repeat\(2,", css)
    assert re.search(r"@container \(min-width:700px\)\{ \.kpi-row\.c5\.ta-row1\{[^}]*repeat\(5,", css)
    assert re.search(r"@container \(min-width:560px\)\{ \.kpi-row\.c4\.ta-row1\{[^}]*repeat\(4,", css)
    assert sorted(set(re.findall(r"@container \(min-width:(\d+)px\)", css))) == ["560", "600", "700", "720", "900", "960"]
    assert re.findall(r"@container \(max-width:(\d+)px\)", css) == ["479"]
    assert not re.search(r"@media[^{]*\{[^}]*\.kpi-row\.c[458]", css)                              # nothing viewport-based
    assert re.search(r"\.kpi\.kpi-compact \.kpi-value\{[^}]*overflow:hidden;text-overflow:ellipsis", css)
    assert ".kpi .kpi-est{position:absolute" in css


def test_suggestion_grid_and_chart_rows_use_container_thresholds():
    css = _css()
    assert re.search(r"@container \(min-width:600px\)\{ \.ta-sg-grid\{[^}]*repeat\(2,", css)
    assert re.search(r"@container \(min-width:960px\)\{ \.ta-sg-grid\{[^}]*repeat\(3,", css)
    assert re.search(r"@container \(min-width:720px\)\{ \.ta-chart-row\{", css)
    assert re.search(r"@container \(min-width:900px\)\{ \.ta-two-col\{", css)
    assert ".ta-sg-grid{display:grid;grid-template-columns:minmax(0,1fr);gap:12px;align-items:start}" in css


def test_overtrading_uses_c8_and_only_overtrading():
    assert "'c8'" in _func("_renderOvertrading") and "'c8'" not in "".join(
        _func(f) for f in ("_renderBuildup", "_renderMarginTrap", "_renderSuggestions"))
    assert "'c5'" in _func("_renderMarginTrap") and "'c4'" in _func("_renderBuildup")


# ── renderer purity ───────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fn", ["_renderOvertrading", "_renderBuildup", "_renderMarginTrap", "_headlineOvertrading",
                                "_headlineBuildup", "_headlineMarginTrap", "_renderChainLadder", "_cashChartCfg"])
def test_panel_renderers_draw_no_tables(fn):
    assert "<table" not in _func(fn) and "_tbl(" not in _func(fn)


def test_margin_trap_no_longer_touches_stops():
    for fn in ("_renderMarginTrap", "_marginKpis", "_headlineMarginTrap", "_cashChartCfg"):
        assert "stops" not in _func(fn), fn
    assert "'Planned vs actual stops.'" not in _func("_renderMarginTrap")
    assert "'Planned vs actual stops.'" in _func("_renderSuggestions")
    assert len(re.findall(r"function _stopsTable\(", JS)) == 1


def test_charts_use_local_plugins_only():
    assert "Chart.register" not in JS
    assert "plugins: [_monthBandsPlugin]" in JS and "plugins: [_dayBandsPlugin]" in JS
    assert "id: 'taMonthBands'" in JS and "id: 'taDayBands'" in JS


# ── cache lifecycle order (design 17.3) ─────────────────────────────────────────────────────────

def test_cache_lifecycle_order_in_loader():
    body = _func("loadAnalyticsPanels")
    order = [body.index(s) for s in ("++_seq", "_cache[k] = null", "Promise.allSettled", "if (seq !== _seq) return",
                                     "_cache[key] =", "_RENDER[key](data)", "_renderBehaviourDetails()", "_renderFullTablesIfOpen()")]
    assert order == sorted(order) and len(set(order)) == len(order)
    assert "taSwitchTab" not in body


def test_cache_keys_and_scope_reset():
    assert re.search(r"const _cache = \{ overtrading: null, buildup: null, margintrap: null, suggestions: null \};", JS)
    r = _func("_renderSuggestions")
    assert "_sgScope !== scope" in r and "_sgOpen.clear()" in r and "_query()" in r
    for k in ("overtrading", "buildup", "margintrap", "suggestions"):
        assert f"_cache.{k} = d;" in _func(f"_render{k.capitalize() if k != 'margintrap' else 'MarginTrap'}")


# ── bindings ──────────────────────────────────────────────────────────────────────────────────

def test_p6_handlers_bound_exported_and_resolved():
    names = ["taAnChainPick", "taAnSgExpandAll", "taAnSgCollapseAll", "taAnSgToggle", "taAnFullToggle", "taAnDetailBToggle"]
    for n in names:
        assert re.search(rf"window\.{n} = {n};", MAIN), n
        assert re.search(rf"export function {n}\b", JS), n
    used = set(re.findall(r'on(?:click|toggle)="(taAn\w+)\(', HTML + JS))
    assert used <= set(re.findall(r"window\.(taAn\w+)\s*=", MAIN)), used


# ── schema parity: every field the new renderers read exists in the Pydantic models ──────────────

_MAP = {
    "_headlineBuildup": {"ct": [sch.ChainTotals], "w": [sch.ChainRow], "ev": [sch.EventCounts]},
    "_renderBuildup": {"av": [sch.AveragingBlock], "ct": [sch.ChainTotals], "lots": [sch.LotsBlock]},
    "_renderChainLadder": {"c": [sch.ChainRow], "s": [sch.ChainStep]},
    "_storyChains": {"c": [sch.ChainRow]},
    "_headlineMarginTrap": {"l": [sch.LedgerBlock], "c": [sch.CashBlock], "t": [sch.TrapBlock], "g": [sch.LossGrowth], "a": [sch.AddsOnLowCash]},
    "_marginKpis": {"l": [sch.LedgerBlock], "c": [sch.CashBlock], "t": [sch.TrapBlock], "a": [sch.AddsOnLowCash]},
    "_cashChartCfg": {"c": [sch.CashBlock], "r": [sch.CashPoint]},
    "_cashIdx": {},
    "_bandRanges": {"s": [sch.Streak]},
    "_renderMarginTrap": {"l": [sch.LedgerBlock], "ex": [sch.ExposureBlock]},
    "_headlineOvertrading": {"a": [sch.ActivityBlock], "c": [sch.ChurnBlock], "ch": [sch.ChargesBlock]},
    "_renderOvertrading": {"a": [sch.ActivityBlock], "w": [sch.WinLossBlock], "c": [sch.ChurnBlock], "ch": [sch.ChargesBlock],
                           "h": [sch.HoldingBlock], "b": [sch.BurstBlock], "fpd": [sch.FillsPerDay], "re": [sch.Reentry]},
    "_renderHoldingChart": {"h": [sch.HoldingBlock], "r": [sch.Bucket]},
    "_tableA": {"d": [sch.OvertradingResponse], "w": [sch.WinLossBlock], "mo": [sch.MeasuredOnly], "r": [sch.GroupRow, sch.WLGroup]},
    "_momentRows": {"ot": [sch.OvertradingResponse], "bu": [sch.BuildupResponse], "mt": [sch.MarginTrapResponse],
                    "c": [sch.ChainRow]},   # "r" is reused for the module-internal row objects (kind/when/basis)
    "_stopsTable": {"st": [sch.StopsBlock], "r": [sch.StopRow]},
    "_sgEffect": {"r": [sch.Rule], "w": [sch.WhatIf], "p": [sch.RuleParam], "smp": [sch.Sample]},
    "_sgBody": {"r": [sch.Rule], "w": [sch.WhatIf], "p": [sch.RuleParam], "e": [sch.Evidence], "v": [sch.Variant]},
    "_sgCard": {"r": [sch.Rule]},
    "_renderSuggestions": {"d": [sch.SuggestionsResponse], "cb": [sch.Combined], "cw": [sch.WhatIf], "smp": [sch.Sample],
                           "stop1": [sch.StopRow], "o": [sch.Observation], "r": [sch.Rule]},
}


@pytest.mark.parametrize("fn", sorted(_MAP))
def test_fields_read_exist_in_schema(fn):
    body = _func(fn)
    for var, models in _MAP[fn].items():
        have = set().union(*(set(m.model_fields) for m in models)) if models else set()
        got = _reads(body, var)
        assert got <= have, (fn, var, got - have)


# ── wording ban + lot-number ban on the new code (design A7) ───────────────────────────────────────

def _p6_text() -> str:
    code = re.sub(r"//[^\n]*", "", JS).replace(DISCLAIMER, "")
    seg = HTML[HTML.index('id="ta-panel-overtrading"'):HTML.index("<!-- /main -->")].replace(DISCLAIMER, "")
    return code + "\n" + seg


@pytest.mark.parametrize("word", ["should", "recommend", "recommended", "buy", "sell", "advice", "advise"])
def test_wording_ban_with_disclaimer_whitelist(word):
    assert not re.search(rf"\b{word}\b", _p6_text(), re.I), word


def test_disclaimer_present_and_whitelist_is_exact():
    assert DISCLAIMER in JS and "not investment advice or a forecast" in HTML
    assert len(re.findall(r"investment advice", JS)) == 1                      # the one mandatory sentence only


def test_no_hardcoded_lot_numbers_in_lot_context():
    txt = _p6_text()
    assert not re.search(r"(?i)lots?\W.{0,20}\b(25|75|30)\b|\b(25|75|30)\b.{0,20}lots?", txt)


# ── copy ───────────────────────────────────────────────────────────────────────────────────────

def test_rule_copy_titles_are_plain_and_complete():
    blk = re.search(r"const _RULE_COPY = \{(.*?)\n\};", JS, re.S).group(1)
    pairs = re.findall(r"^\s{2}([a-z_]+): \['((?:[^'\\]|\\.)*)', '((?:[^'\\]|\\.)*)'\]", blk, re.M)
    assert len(pairs) == 10 and all(t and w for _, t, w in pairs)
    assert "const _copy = r => _RULE_COPY[r.id] || [r.title, r.threshold_basis];" in JS
