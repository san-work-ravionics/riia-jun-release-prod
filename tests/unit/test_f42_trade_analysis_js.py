"""F42 P1 — static contract: every field trade-analysis.js reads exists in the Pydantic
schema; section/nav/loader/window bindings registered; no banned Kite/localhost usage."""
from __future__ import annotations

import re
from pathlib import Path

from rita.schemas.fno_trade_analysis import (
    ExcludedCounts, ExpirySummary, OrderRow, PositionRow, SnapshotInfo,
    TradeAnalysisLiveResponse, TradeFilter, TradeKpis, TradeRow,
)

ROOT = Path(__file__).resolve().parents[2] / "dashboard"
JS = (ROOT / "js/fno/trade-analysis.js").read_text()
MAIN = (ROOT / "js/fno/main.js").read_text()
HTML = (ROOT / "fno.html").read_text()

# variable prefix used in trade-analysis.js -> schema model it reads
_PREFIXES = {
    "data": TradeAnalysisLiveResponse, "k": TradeKpis, "v": TradeKpis, "o": OrderRow, "t": TradeRow,
    "p": PositionRow, "b": ExpirySummary, "s": SnapshotInfo, "x": ExcludedCounts,
}


def _reads(prefix: str) -> set[str]:
    return set(re.findall(rf"(?<![\w.]){prefix}\.([a-z_]+)\b", JS))


def test_every_field_js_reads_is_in_schema():
    for prefix, model in _PREFIXES.items():
        missing = _reads(prefix) - set(model.model_fields)
        assert not missing, f"{prefix}.* not in {model.__name__}: {missing}"
    assert {"available", "reason", "message", "kpis", "orders", "trades", "positions",
            "by_expiry", "snapshot", "excluded", "history_note", "as_of_date"} <= _reads("data")
    assert "expiry_months" in set(TradeFilter.model_fields)


def test_dom_ids_used_by_js_exist_in_html():
    ids = set(re.findall(r"""['"`](ta-[a-z-]+)""", JS))
    ids |= {f"ta-panel-{p}" for p in ("overtrading", "buildup", "marketturn", "margintrap", "suggestions")}
    ids -= {"ta-panel-"}
    for i in ids:
        assert f'id="{i}"' in HTML, i


def test_section_nav_loader_and_bindings():
    assert 'id="page-trade-analysis"' in HTML
    assert 'data-page="trade-analysis"' in HTML and "Trade Analysis" in HTML
    assert '<div class="page-title">Trade Analysis</div>' in HTML
    assert "_sectionLoaders['trade-analysis'] = loadTradeAnalysis" in MAIN
    for name in ("loadTradeAnalysis", "taSetUnderlying", "taSetExpiryMonth", "taRefresh"):
        assert f"window.{name} = {name}" in MAIN
        assert re.search(rf"export (async )?function {name}\b", JS)
    for handler in ("taSetUnderlying", "taSetExpiryMonth", "taRefresh"):
        assert f"{handler}(" in HTML


def test_imports_resolve_and_no_banned_patterns():
    for m in re.finditer(r"import \{([^}]+)\} from '([^']+)'", JS):
        names = [n.strip() for n in m.group(1).split(",")]
        src = (ROOT / "js/fno" / m.group(2)).resolve().read_text()
        for n in names:
            assert re.search(rf"export\s+(async\s+)?(function|const)\s+{n}\b|export\s*\{{[^}}]*\b{n}\b", src), (n, m.group(2))
    for banned in ("kiteFetch", "KITE_API_BASE", "kiteBase", "localhost", "127.0.0.1", "new Chart("):
        assert banned not in JS
    assert "/api/v1/experience/fno/trade-analysis/live" in JS
    assert "try {" in JS and "catch" in JS
