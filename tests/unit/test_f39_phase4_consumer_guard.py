"""F39 Phase 4 — static consumer guard for the FnO dashboard (no node, no browser).

Protects the destructive Tier B commit (deleting hedge.js / equity_hedge.js and the
dead HTML sections) and passes today:

(a) no dashboard/js/** import resolves to a missing file;
(b) every inline on<event>="fn(...)" handler (fno.html + JS templates in dashboard/js/fno)
    has a window.* binding;
(c) manoeuvre.js imports nothing from the delete list {hedge.js, equity_hedge.js};
(d) 'null-guarded OR id exists': every getElementById('literal') that is dereferenced
    without a null guard (greeks.js, stress.js and every other fno module) names an id
    present in fno.html. Deleting a host section from fno.html without guarding its
    painters therefore fails here, not at browser boot.
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_DASH = _ROOT / "dashboard"
_JS = _DASH / "js"
_FNO = _JS / "fno"
_FNO_HTML = _DASH / "fno.html"

_DELETE_LIST = {"hedge.js", "equity_hedge.js"}

# ── (a) imports resolve ──────────────────────────────────────────────────────────────

_IMPORT_RE = re.compile(
    r"""(?:^|[;\s])(?:import|export)\s+(?:[^'"`;]*?\s+from\s+)?(['"])(\.{1,2}/[^'"]+)\1"""
    r"""|\bimport\(\s*(['"])(\.{1,2}/[^'"]+)\3\s*\)""",
    re.M,
)


def _imports(path: Path) -> list[str]:
    out = []
    for m in _IMPORT_RE.finditer(path.read_text(encoding="utf-8")):
        out.append((m.group(2) or m.group(4)).split("?")[0])  # drop cache-bust ?v=N
    return out


def test_no_dashboard_js_import_resolves_to_a_missing_file():
    files = sorted(_JS.rglob("*.js"))
    assert files, "no dashboard/js files found"
    checked, missing = 0, []
    for f in files:
        for spec in _imports(f):
            checked += 1
            if not (f.parent / spec).resolve().is_file():
                missing.append(f"{f.relative_to(_ROOT)} -> {spec}")
    assert checked > 50, f"import scan looks vacuous ({checked} imports)"
    assert not missing, "imports to missing files:\n" + "\n".join(missing)


# ── (b) inline handlers have window bindings ─────────────────────────────────────────

_ATTR_RE = re.compile(
    r"""\bon(?:click|input|change|keyup|keydown|submit|blur|focus|mouseover|mouseout)"""
    r"""\s*=\s*\\?(["'])(.*?)\\?\1""",
    re.S,
)
_NOT_FUNCS = {
    "this", "event", "document", "window", "if", "return", "function", "Number", "parseInt",
    "String", "JSON", "console", "setTimeout", "alert", "confirm", "stopPropagation",
    "encodeURIComponent",
}

# Pre-existing inline-handler gaps (handler name -> why). EMPTY at Tier A baseline
# (verified 2026-10-03: all 27 inline function names are bound). Add an entry ONLY for a
# pre-existing gap you cannot fix in the same change; a NEW gap must fail this test.
_UNBOUND_HANDLER_ALLOWLIST: dict[str, str] = {}


def _inline_handler_names() -> dict[str, set[str]]:
    sources = [_FNO_HTML] + sorted(_FNO.glob("*.js"))
    names: dict[str, set[str]] = {}
    for src in sources:
        text = src.read_text(encoding="utf-8")
        for m in _ATTR_RE.finditer(text):
            for fn in re.findall(r"(?<![\w.$])([A-Za-z_]\w*)\s*\(", m.group(2)):
                if fn not in _NOT_FUNCS:
                    names.setdefault(fn, set()).add(src.name)
    return names


def _window_bound_names() -> set[str]:
    text = "\n".join(p.read_text(encoding="utf-8") for p in _JS.rglob("*.js"))
    text += "\n" + _FNO_HTML.read_text(encoding="utf-8")
    bound = set(re.findall(r"window\.(\w+)\s*=", text))
    bound |= set(re.findall(r"""window\[\s*['"](\w+)['"]\s*\]\s*=""", text))
    for blk in re.findall(r"Object\.assign\(\s*window\s*,\s*\{(.*?)\}\s*\)", text, re.S):
        bound |= set(re.findall(r"\b(\w+)\b", blk))
    return bound


def test_every_inline_handler_function_has_a_window_binding():
    handlers = _inline_handler_names()
    assert len(handlers) >= 20, f"handler scan looks vacuous ({len(handlers)} names)"
    bound = _window_bound_names()
    gaps = {
        fn: sorted(srcs)
        for fn, srcs in handlers.items()
        if fn not in bound and fn not in _UNBOUND_HANDLER_ALLOWLIST
    }
    assert not gaps, f"inline handlers with no window.* binding: {gaps}"


def test_retained_workflow_and_overview_handlers_are_bound():
    """The handlers the Tier B deletion must never take with it."""
    bound = _window_bound_names()
    for fn in ("phSetCoverage", "phSetScenarioTab", "haSkipToVerdict", "hwGoToStep",
               "hwSetCoverage", "hwSave", "setExpiry"):
        assert fn in bound, fn


# ── (c) manoeuvre.js independence ────────────────────────────────────────────────────

def test_manoeuvre_imports_nothing_from_the_delete_list():
    specs = _imports(_FNO / "manoeuvre.js")
    assert specs, "manoeuvre.js import scan looks vacuous"
    bad = [s for s in specs if Path(s).name in _DELETE_LIST]
    assert not bad, bad


def test_hedge_workflow_modules_import_nothing_from_retired_modules():
    retired = _DELETE_LIST | {"portfolio-hedge.js"}
    for f in sorted(_FNO.glob("hedge-workflow*.js")) + [_FNO / "hedge-calc.js", _FNO / "hedge-charts.js",
                                                         _FNO / "hedge-instrument-tiles.js"]:
        bad = [s for s in _imports(f) if Path(s).name in retired]
        assert not bad, f"{f.name} imports {bad}"


# ── (d) getElementById: null-guarded OR id exists in fno.html ────────────────────────

_GET_RE = re.compile(r"""getElementById\(\s*(['"`])([^'"`$]+)\1\s*\)(\s*\?\.|\s*\.)?""")

# Pre-existing unguarded lookups whose id is NOT in fno.html (verified 2026-10-03).
# They sit in code paths that either never run on the FnO page (rita.html / ds.html ids)
# or are dead; out of scope for Phase 4 and baselined so only NEW gaps fail.
_UNGUARDED_MISSING_ID_BASELINE = {
    ("dashboard.js", "dash-kpis"),          # id lives in ds.html only
    ("dashboard.js", "daily-progress-wrap"),
    ("margin.js", "margin-kpis"),
    ("margin.js", "margin-util-card"),
    ("portfolio-builder.js", "pb-map-empty"),   # ids live in rita.html only
    ("portfolio-builder.js", "pb-table-empty"),
    ("portfolio-builder.js", "pb-status-msg"),
    ("positions.js", "pos-kpis"),
    ("positions.js", "pos-tbody"),
    ("positions.js", "pos-count-lbl"),
    ("positions.js", "pos-total"),
}


def _fno_html_ids() -> set[str]:
    return set(re.findall(r'\bid="([^"]+)"', _FNO_HTML.read_text(encoding="utf-8")))


def _is_guarded_assignment(lines: list[str], i: int, start: int) -> bool:
    """`const x = document.getElementById('id');` followed by a null check of x."""
    mv = re.search(r"(?:const|let|var)\s+(\w+)\s*=\s*(?:\w+\.)?\s*$", lines[i][:start])
    if not mv:
        return True  # value passed along / returned, not dereferenced here
    v = mv.group(1)
    ctx = "\n".join(lines[i:i + 25])
    return bool(re.search(
        rf"if\s*\(\s*!?{v}\b|\b{v}\s*\?\.|\b{v}\s*&&|!{v}\b|\b{v}\s*(?:===|!==|==|!=)\s*null|\b{v}\s*\?",
        ctx,
    ))


def _unguarded_lookups() -> tuple[int, list[tuple[str, int, str]]]:
    total, unguarded = 0, []
    for f in sorted(_FNO.glob("*.js")):
        lines = f.read_text(encoding="utf-8").split("\n")
        for i, line in enumerate(lines):
            for m in _GET_RE.finditer(line):
                total += 1
                suffix = (m.group(3) or "").strip()
                if suffix == "?.":
                    continue
                if suffix == "." or not _is_guarded_assignment(lines, i, m.start()):
                    unguarded.append((f.name, i + 1, m.group(2)))
    return total, unguarded


def test_unguarded_getelementbyid_ids_exist_in_fno_html():
    total, unguarded = _unguarded_lookups()
    assert total > 100, f"getElementById scan looks vacuous ({total} call sites)"
    ids = _fno_html_ids()
    new_gaps = [
        f"{f}:{ln} getElementById('{i}')"
        for f, ln, i in unguarded
        if i not in ids and (f, i) not in _UNGUARDED_MISSING_ID_BASELINE
    ]
    assert not new_gaps, (
        "unguarded getElementById on an id missing from fno.html (null-guard it or keep the id):\n"
        + "\n".join(new_gaps)
    )


def _section(html: str, section_id: str) -> str:
    start = html.index(f'id="{section_id}"')
    nxt = html.find('<div class="section"', start)
    return html[start: nxt if nxt != -1 else len(html)]


# ── Tier B (F39 Phase 4): retired modules gone, D2 blocks relocated to #page-risk ────

_RELOCATED_IDS = ["greeks-all-grid", "greeks-tbody", "greeks-footer", "greeks-table-sub",
                  "stress-row", "stress-card-sub", "payoff-charts-grid", "payoff-nifty-wrap",
                  "payoff-bnkn-wrap", "payoff-chart", "payoff-chart-bnkn"]


def test_relocated_greeks_stress_payoff_ids_live_inside_page_risk():
    html = _FNO_HTML.read_text(encoding="utf-8")
    risk = _section(html, "page-risk")
    for i in _RELOCATED_IDS:
        assert f'id="{i}"' in risk, f"{i} missing from #page-risk"
        assert html.count(f'id="{i}"') == 1, f"{i} duplicated"


def test_greeks_and_stress_have_no_unguarded_lookups_at_all():
    _, unguarded = _unguarded_lookups()
    assert [(f, i) for f, _, i in unguarded if f in ("greeks.js", "stress.js")] == []


def test_retired_modules_and_sections_are_gone_and_not_imported():
    for name in _DELETE_LIST:
        assert not (_FNO / name).exists(), name
    for f in sorted(_JS.rglob("*.js")):
        bad = [s for s in _imports(f) if Path(s).name in _DELETE_LIST]
        assert not bad, f"{f.name} imports retired module {bad}"
    html = _FNO_HTML.read_text(encoding="utf-8")
    for sid in ("page-hedge", "page-equity-hedge", "page-portfolio-hedge"):
        assert f'id="{sid}"' not in html, sid
    assert html.count('id="page-manoeuvre"') == 1
    assert (_FNO / "manoeuvre.js").is_file()
    assert (_FNO / "portfolio-hedge.js").is_file()      # Overview block retained (D1)
