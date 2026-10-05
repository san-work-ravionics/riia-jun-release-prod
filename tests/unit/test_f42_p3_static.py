"""F42 P3 — static contracts: JS field reads vs schema, DOM ids, bindings, imports, escaping,
tier compliance, read-only and logging hygiene of the new modules."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from rita.schemas import fno_trade_analytics as sch

ROOT = Path(__file__).resolve().parents[2]
JS_PATH = ROOT / "dashboard/js/fno/trade-analytics.js"
JS = JS_PATH.read_text()
TA = (ROOT / "dashboard/js/fno/trade-analysis.js").read_text()
MAIN = (ROOT / "dashboard/js/fno/main.js").read_text()
HTML = (ROOT / "dashboard/fno.html").read_text()
SRC = ROOT / "src/rita"
NEW_PY = [SRC / "services/fno_trade_fifo.py", SRC / "services/fno_trade_analytics.py",
          SRC / "services/fno_trade_suggestions.py", SRC / "services/fno_trade_analytics_service.py",
          SRC / "schemas/fno_trade_analytics.py", SRC / "api/experience/fno_trade_analytics.py"]
PANELS = ("overtrading", "buildup", "marketturn", "margintrap", "suggestions")


def _func(name: str) -> str:
    m = re.search(rf"^(?:export )?(?:async )?function {name}\(.*?\n}}\n", JS, re.S | re.M)
    assert m, name
    return m.group(0)


def _reads(body: str, var: str) -> set[str]:
    return set(re.findall(rf"(?<![\w.]){var}\.([a-z_0-9]+)\b", body))


def _fields(*models) -> set[str]:
    out: set[str] = set()
    for m in models:
        out |= set(m.model_fields)
    return out


# function -> {variable: candidate schema models}
_MAP = {
    "_renderOvertrading": {"d": [sch.OvertradingResponse], "a": [sch.ActivityBlock], "w": [sch.WinLossBlock],
                           "c": [sch.ChurnBlock], "ch": [sch.ChargesBlock], "h": [sch.HoldingBlock],
                           "b": [sch.BurstBlock], "fpd": [sch.FillsPerDay], "mo": [sch.MeasuredOnly],
                           "r": [sch.GroupRow, sch.Bucket, sch.BurstRow, sch.WeeklyRow, sch.WLGroup]},
    "_renderBuildup": {"d": [sch.BuildupResponse], "av": [sch.AveragingBlock], "ct": [sch.ChainTotals],
                       "ev": [sch.EventCounts], "lots": [sch.LotsBlock],
                       "r": [sch.ChainRow, sch.TimelineRow]},
    "_renderMarketTurn": {"d": [sch.MarketTurnResponse], "k": [sch.TurnKpis], "sp": [sch.SpotBlock],
                          "r": [sch.WorstDay, sch.TurnDay], "s": [sch.TurnSeries]},
    "_renderMarginTrap": {"d": [sch.MarginTrapResponse], "l": [sch.LedgerBlock], "c": [sch.CashBlock],
                          "t": [sch.TrapBlock], "st": [sch.StopsBlock], "ex": [sch.ExposureBlock],
                          "g": [sch.LossGrowth], "stop1": [sch.StopRow],
                          "r": [sch.Streak, sch.TrapDay, sch.StopRow, sch.CashPoint]},
    "_ruleCard": {"r": [sch.Rule], "w": [sch.WhatIf], "p": [sch.RuleParam], "e": [sch.Evidence],
                  "v": [sch.Variant]},
    "_renderSuggestions": {"d": [sch.SuggestionsResponse], "cb": [sch.Combined], "cw": [sch.WhatIf],
                           "smp": [sch.Sample], "o": [sch.Observation]},
    "_renderFoundation": {"d": [sch.FoundationResponse], "r": [sch.ReconBlock], "t": [sch.ReconTotals],
                          "x": [sch.ReconRow]},
    "_quality": {"d": [sch.AnalyticsEnvelope], "q": [sch.Quality]},
    "_defs": {"d": [sch.AnalyticsEnvelope], "t": [sch.Tags]},
}


@pytest.mark.parametrize("fn", sorted(_MAP))
def test_every_field_the_js_reads_is_in_the_schema(fn):
    body = _func(fn)
    for var, models in _MAP[fn].items():
        missing = _reads(body, var) - _fields(*models)
        assert not missing, f"{fn}: {var}.{missing} not in {[m.__name__ for m in models]}"
    assert any(_reads(body, v) for v in _MAP[fn])


def test_loader_reads_filter_fields_declared():
    body = _func("loadAnalyticsPanels")
    assert _reads(body, "data") <= _fields(sch.AnalyticsEnvelope)
    assert re.findall(r"data\.filter\.([a-z_]+)", body) and \
        set(re.findall(r"data\.filter\.([a-z_]+)", body)) <= set(sch.AnalyticsFilter.model_fields)
    for f in ("underlying", "expiry_months", "expiry_year", "date_from", "date_to", "include_expiry_estimate"):
        assert f in sch.AnalyticsFilter.model_fields


def test_dom_ids_used_by_js_exist_in_html():
    static = set(re.findall(r"""['"`](ta-(?:an|cv)-[a-z-]+)['"`]""", JS)) - {"ta-an-", "ta-cv-"}
    static = {i for i in static if "$" not in i}
    ids = static | {f"ta-an-{p}-{k}" for p in PANELS for k in ("body", "def")} | {f"ta-panel-{p}" for p in PANELS}
    ids |= {"ta-cv-weekly", "ta-cv-buildup", "ta-cv-turn", "ta-cv-cash", "ta-an-from", "ta-an-expiry-est",
            "ta-an-recon", "ta-an-status"}
    for i in ids:
        assert f'id="{i}"' in HTML, i
    assert len(re.findall(r'id="(ta-(?:an|cv|panel)-[a-z-]+)"', HTML)) == len(set(re.findall(r'id="(ta-(?:an|cv|panel)-[a-z-]+)"', HTML)))
    # JS builds per-panel ids from the key list: every key it uses is a real panel
    assert set(re.findall(r"_PANELS = \[([^\]]+)\]", JS)[0].replace("'", "").replace(" ", "").split(",")) == set(PANELS)


def test_page_ids_and_placeholder_removed():
    assert 'id="page-trade-analysis"' in HTML and 'data-page="trade-analysis"' in HTML
    assert "Coming in Phase 3" not in HTML and "Coming in Phase 3" not in TA and "Coming in Phase 3" not in JS
    assert "_PLACEHOLDERS" not in TA
    assert "not investment advice or a forecast" in HTML       # disclaimer statically present on the panel
    assert "Observations from your own imported history" in JS


def test_bindings_and_inline_handlers():
    handlers = set(re.findall(r'on(?:click|change)="(taAn\w+)\(', HTML))
    bound = set(re.findall(r"window\.(taAn\w+)\s*=\s*\1;", MAIN))
    assert handlers == {"taAnFromChanged", "taAnToggleEstimate", "taAnRefresh", "taAnToggleInfo"} == bound
    for n in bound:
        assert re.search(rf"export (async )?function {n}\b", JS), n
    assert "from './trade-analytics.js'" in MAIN


def test_fc_imp_every_import_is_exported():
    for js_path, text in ((JS_PATH, JS), (ROOT / "dashboard/js/fno/trade-analysis.js", TA),
                          (ROOT / "dashboard/js/fno/main.js", MAIN)):
        for m in re.finditer(r"import \{([^}]+)\} from '([^']+)'", text):
            names = [n.strip().split(" as ")[0] for n in m.group(1).split(",")]
            src = (js_path.parent / m.group(2)).resolve()
            assert src.exists(), (m.group(2), "path depth")
            code = src.read_text()
            for n in names:
                assert re.search(rf"export\s+(async\s+)?(function|const)\s+{n}\b|export\s*\{{[^}}]*\b{n}\b", code), (n, m.group(2))
    # helpers are imported (not redefined)
    assert "import { _esc, _num, _pnl, taGetFilters } from './trade-analysis.js'" in JS
    assert not re.search(r"^(export )?(const|function) (_esc|_num|_pnl)\b", JS, re.M)
    for n in ("_esc", "_num", "_pnl", "taGetFilters"):
        assert re.search(rf"export (const|function) {n}\b", TA)
    assert "../shared/charts.js" in JS and (ROOT / "dashboard/js/shared/charts.js").exists()


def test_no_banned_patterns_and_parallel_independent_loading():
    for banned in ("localhost", "127.0.0.1", "KITE_API_BASE", "kiteFetch", "new Chart(", "document.write", "eval(", "fetch("):
        assert banned not in JS, banned
    assert not re.search(r"\b(75|30)\b", JS)
    assert "typeof Chart === 'undefined'" in JS and "mkChart(" in JS
    assert "Promise.allSettled" in JS
    for ep in ("foundation", "overtrading", "buildup", "market-turn", "margin-trap", "suggestions"):
        assert re.search(rf"[:']\s*'?{ep}'", JS), ep
    assert "/api/v1/experience/fno/trade-analysis/analytics/" in JS
    assert not re.search(r"api\([^)]*,\s*\{", JS)                                  # FC-API-SIG
    body = _func("loadAnalyticsPanels")
    assert "try {" in body and "catch" in body and "_fail(key)" in body
    # loaded alongside the import panel, fire-and-forget
    tb = TA[TA.index("export async function loadTradeAnalysis"):]
    assert "loadAnalyticsPanels()" in tb[:400] and "loadImportPanel()" in tb[:400]


_SAFE = ("_esc", "_num", "_pnl", "_pct", "_cls", "_dash", "_badge", "_kpi", "_kpis", "_tbl", "_pnlCell",
         "_list", "_note", "_unavail", "_quality", "_infoBlock", "_defs", "_ruleCard", "_th", "_td")


def _template_exprs(js: str) -> list[str]:
    out, i = [], 0
    while True:
        i = js.find("${", i)
        if i < 0:
            return out
        depth, j = 1, i + 2
        while depth and j < len(js):
            depth += {"{": 1, "}": -1}.get(js[j], 0)
            j += 1
        out.append(js[i + 2:j - 1])
        i += 2


def _strip_safe_calls(expr: str) -> str:
    changed = True
    while changed:
        changed = False
        for name in _SAFE:
            k = expr.find(name + "(")
            while k >= 0:
                if k and (expr[k - 1].isalnum() or expr[k - 1] == "_"):
                    k = expr.find(name + "(", k + 1)
                    continue
                depth, j = 0, k + len(name)
                while j < len(expr):
                    depth += {"(": 1, ")": -1}.get(expr[j], 0)
                    j += 1
                    if depth == 0:
                        break
                expr = expr[:k] + "_X_" + expr[j:]
                changed = True
                k = expr.find(name + "(")
    return expr


def test_every_template_interpolation_is_escaped_or_numeric():
    code = re.sub(r"//[^\n]*", "", JS)
    exprs = _template_exprs(code)
    assert len(exprs) > 100
    for e in exprs:
        rest = _strip_safe_calls(e)
        rest = re.sub(r"_REASONS\[[^\]]+\]", "_STATIC_", rest)                    # static text keyed by a server code
        rest = re.sub(r"'[^']*'", "''", rest)                                    # string literals
        rest = re.sub(r"\(\w+\.\w+ \|\| \[\]\)\.map\(|\b\w+\.\w+\.map\(|\(\w+\.\w+ \|\| \[\]\)", "_ARR_", rest)
        rest = re.sub(r"\b[a-z_]\w*\.[A-Za-z_]\w*\s*(?:!=|==|===|!==)\s*(?:null|'')\s*\?|\b[a-z_]\w*\.[A-Za-z_]\w*\s*\?", "_COND_ ?", rest)  # ternary conditions print nothing
        rest = re.sub(r"\.(join|map|replace|length)\b", "", rest)
        assert not re.search(r"\b[a-z_]\w*\.[A-Za-z_]\w*", rest), f"unescaped server value in template: {e[:120]}"
    for m in re.finditer(r"innerHTML\s*=", code):
        pytest.fail("direct innerHTML assignment; use setEl with escaped html")


def test_tier_read_only_and_logging_hygiene_of_new_python_modules():
    router = (SRC / "api/experience/fno_trade_analytics.py").read_text()
    assert "Repo" not in router and "repositories" not in router and "commit" not in router.replace("no commit", "")
    assert "kite_middleware_client as kmc" in router and router.count("kmc.fetch_instrument_master_nfo") == 1
    svc = (SRC / "services/fno_trade_analytics_service.py").read_text()
    assert "kite_middleware_client" not in svc and "kmc" not in svc
    for p in NEW_PY:
        t = p.read_text()
        assert "print(" not in t, p.name
        assert not re.search(r"\b(db|_db|session|self\._\w+)\.(commit|rollback|flush|add|add_all|delete|merge|bulk_insert_mappings)\(", t), p.name
        assert "settings.instruments" not in t and "lot_size_default" not in t, p.name
        assert "localhost" not in t and "LLM" not in t.replace("no LLM", "").replace("No LLM", "")
    for p in (SRC / "services/fno_trade_fifo.py", SRC / "services/fno_trade_analytics.py",
              SRC / "services/fno_trade_suggestions.py"):
        t = p.read_text()
        assert not re.search(r"^(from|import) (sqlalchemy|rita\.(config|database|repositories|models))", t, re.M), p.name
    # logs carry counts/codes only
    allowed = {"panel", "fills", "segments", "est_segments", "error_type"}
    for p in NEW_PY:
        for m in re.finditer(r"log\.\w+\(\s*\"[\w.]+\"((?:,\s*\w+=[^,)]+)*)", p.read_text()):
            assert set(re.findall(r"(\w+)=", m.group(1))) <= allowed, (p.name, m.group(0))
    repo = (SRC / "repositories/fno_import.py").read_text()
    for name in ("fills_for_analysis", "turnover", "unparsed_count", "lines_for_scope", "charge_summary", "series", "last_before"):
        m = re.search(rf"def {name}\(self, user_id: str", repo)
        assert m, name
        assert "user_id" in repo[m.start():m.start() + 700]
    assert "commit" not in repo[repo.index("F42 Phase 3 analytics reads"):repo.index("def purge(self, user_id: str) -> int:\n        return self._db.execute(delete(Trade)")]
