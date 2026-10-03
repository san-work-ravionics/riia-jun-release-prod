"""QA gap-fill — F39 Phase 4 (cleanup of the retired hedge pages), Tier A + Tier B.

(a) retired alias keys still resolve (static + node, no reference to a deleted function)
(b) relocated Greeks/stress/payoff ids exist once, inside #page-risk, beside the original cards
(c) nothing left in fno.html / dashboard/js/fno references a deleted id / function / state field
(d) node harness: boot chain + setUnderlying run with/without Risk-page ids and without the
    deleted pages; renderStdDevTable still runs when stress-row is missing
(e) i18n locale parity + none of the 39 removed keys
(f) specs no longer present removed modules as live (skipped if specs unreachable)
Node tests skip when node is absent.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_DASH = _ROOT / "dashboard"
_JS = _DASH / "js"
_FNO = _JS / "fno"
_HTML = _DASH / "fno.html"

_node_missing = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

# Ids lost from fno.html in Tier B (git show 0cd9ba6^:dashboard/fno.html vs HEAD). fno-geo-overview
# is deliberately excluded: dashboard.js keeps a guarded no-op lookup for it.
_DELETED_IDS = (
    "anchor-sub anchor-tbody budget-bars budget-summary eh-cc-breakeven eh-cc-desc eh-cc-max-value "
    "eh-cc-premium eh-cc-source-badge eh-cc-strike eh-kpi-date-range eh-kpi-end-price eh-kpi-hedge-return "
    "eh-kpi-lot eh-kpi-net-return eh-kpi-return eh-kpi-shares eh-kpi-start-price eh-kpi-vol eh-loading "
    "eh-monthly-change-chart eh-monthly-chart-title eh-overview-lot eh-portfolio-chart "
    "eh-portfolio-chart-title eh-pp-breakeven eh-pp-desc eh-pp-floor eh-pp-premium eh-pp-source-badge "
    "eh-pp-strike eh-results hedge-timeline-chart hist-content hist-day-tbody hist-kpis hist-loading "
    "hqs-alert-banner hqs-footer hqs-kpis hqs-tbody hqs-tier-card page-equity-hedge page-hedge "
    "page-portfolio-hedge reactive-summary reactive-tbody"
).split()
_DELETED_SYMBOLS = [
    "loadHedgeHistory", "renderHedgeHistory", "renderPortfolioHedgeRadar", "renderHedgeRadar",
    "injectAsmlToState", "loadEquityHedge", "renderEquityHedge",
    "hedgeHistoryLoaded", "hedgeHistory", "hedgeTimelineChart",
]
_RELOCATED_IDS = ["greeks-all-grid", "greeks-tbody", "greeks-footer", "greeks-table-sub",
                  "stress-row", "stress-card-sub", "payoff-charts-grid", "payoff-nifty-wrap",
                  "payoff-bnkn-wrap", "payoff-chart", "payoff-chart-bnkn"]
_ALIASES = {"hedge": "exposure", "hedge-advisor": "recommendation",
            "equity-hedge": "recommendation", "portfolio-hedge": "exposure"}


def _strip_js_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?m)(^|[^:\\'\"`])//.*$", r"\1", src)


def _strip_html_comments(src: str) -> str:
    return re.sub(r"<!--.*?-->", "", src, flags=re.S)


# ── (a) alias keys ────────────────────────────────────────────────────────────────────

def test_alias_keys_registered_in_nav_and_main_without_deleted_function_refs():
    nav = _strip_js_comments((_FNO / "nav.js").read_text(encoding="utf-8"))
    main = _strip_js_comments((_FNO / "main.js").read_text(encoding="utf-8"))
    for key, step in _ALIASES.items():
        assert re.search(rf"""['"]?{re.escape(key)}['"]?\s*:\s*'{step}'""", nav), f"nav.js alias {key}->{step}"
        assert re.search(rf"""_sectionLoaders\['{re.escape(key)}'\]\s*=\s*_hwAlias\('{step}'\)""", main), key
    for src_name, src in (("nav.js", nav), ("main.js", main)):
        for sym in _DELETED_SYMBOLS:
            assert not re.search(rf"\b{sym}\b", src), f"{src_name} references deleted {sym}"
    # alias branch must return before the page-<key> lookup (no #page-hedge etc. needed)
    i_alias = nav.index("HEDGE_WORKFLOW_ALIASES[page]")
    assert nav.index("return;", i_alias) < nav.index("getElementById('page-' + page)")


@_node_missing
def test_alias_loaders_resolve_at_runtime_with_no_deleted_page(tmp_path):
    """Load the real main.js alias block semantics: every alias loader calls loadHedgeWorkflow(step)."""
    main = (_FNO / "main.js").read_text(encoding="utf-8")
    m = re.search(r"function _hwAlias\(step\) \{.*?\n\}\n", main, re.S)
    assert m, "_hwAlias not found"
    calls = {k: re.search(rf"_sectionLoaders\['{k}'\] = _hwAlias\('(\w+)'\)", main).group(1) for k in _ALIASES}
    script = tmp_path / "a.mjs"
    script.write_text(
        "const seen=[]; function loadHedgeWorkflow(s){seen.push(s);return 1;}\n"
        "const _sectionLoaders={};\n" + m.group(0)
        + "\n".join(f"_sectionLoaders['{k}']=_hwAlias('{v}');" for k, v in calls.items())
        + "\nfor (const k of Object.keys(_sectionLoaders)) _sectionLoaders[k]();\n"
        "console.log(JSON.stringify(seen));\n", encoding="utf-8")
    out = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == [_ALIASES[k] for k in _ALIASES]


# ── (b) relocated ids ─────────────────────────────────────────────────────────────────

def _page_risk(html: str) -> str:
    start = html.index('id="page-risk"')
    nxt = html.find('<div class="section"', start)
    return html[start: nxt if nxt != -1 else len(html)]


def test_relocated_ids_exactly_once_inside_page_risk_and_original_cards_kept():
    html = _HTML.read_text(encoding="utf-8")
    risk = _page_risk(html)
    for i in _RELOCATED_IDS:
        assert len(re.findall(rf'\bid="{i}"', html)) == 1, f"{i} not unique in fno.html"
        assert f'id="{i}"' in risk, f"{i} not inside #page-risk"
    assert 'id="risk-stddev-card"' in risk, "original sigma card lost"
    chart_ids = re.findall(r'<canvas[^>]*\bid="(risk-[^"]+)"', risk)
    assert len(chart_ids) >= 2, f"instrument/portfolio chart canvases missing from #page-risk: {chart_ids}"
    # original cards come before the relocated block
    assert risk.index('id="risk-stddev-card"') < risk.index('id="greeks-all-grid"')
    assert html.count('id="page-risk"') == 1


# ── (c) no references to deleted ids / functions ──────────────────────────────────────

def test_no_remaining_reference_to_deleted_ids_or_symbols():
    html = _strip_html_comments(_HTML.read_text(encoding="utf-8"))
    js = {p.name: _strip_js_comments(p.read_text(encoding="utf-8")) for p in _FNO.glob("*.js")}
    assert len(js) > 15
    hits = []
    for i in _DELETED_IDS:
        pat = re.compile(rf"""(?<![\w-])(?:["'`#]|id=["']){re.escape(i)}(?![\w-])""")
        if pat.search(html):
            hits.append(f"fno.html -> {i}")
        hits += [f"{n} -> {i}" for n, s in js.items() if pat.search(s)]
    for sym in _DELETED_SYMBOLS:
        pat = re.compile(rf"\b{sym}\b")
        if pat.search(html):
            hits.append(f"fno.html -> {sym}")
        hits += [f"{n} -> {sym}" for n, s in js.items() if pat.search(s)]
    assert not hits, "dangling references:\n" + "\n".join(hits)


def test_fno_geo_overview_is_only_a_guarded_noop_lookup():
    for p in _FNO.glob("*.js"):
        text = _strip_js_comments(p.read_text(encoding="utf-8"))
        for m in re.finditer(r"getElementById\('fno-geo-overview'\)", text):
            tail = text[m.end(): m.end() + 200]
            assert re.search(r"if\s*\(\s*!\w+\s*\)\s*return|\?\.", tail) or "if (!" in text[max(0, m.start() - 120): m.start()], p.name


# ── (d) node boot harness ─────────────────────────────────────────────────────────────

_HARNESS = r"""
import { pathToFileURL } from 'node:url';
const ABSENT = new Set(JSON.parse(process.env.ABSENT_IDS));
const made = {};
function el(id) {
  return made[id] ??= { id, style: {}, dataset: {}, innerHTML: '', textContent: '', value: '',
    classList: { add(){}, remove(){}, toggle(){}, contains(){return false} },
    children: [], appendChild(){}, addEventListener(){}, setAttribute(){}, getContext(){return null},
    querySelector(){return null}, querySelectorAll(){return []}, getBoundingClientRect(){return {width:0,height:0}} };
}
globalThis.window = globalThis;
globalThis.sessionStorage = { getItem(){return null}, setItem(){}, removeItem(){} };
globalThis.localStorage = globalThis.sessionStorage;
globalThis.location = { hostname: 'localhost', href: 'http://localhost/', search: '' };
globalThis.document = {
  getElementById: (id) => ABSENT.has(id) ? null : el(id),
  querySelector: () => null, querySelectorAll: () => [], addEventListener(){},
  createElement: () => el('x' + Math.random()), body: el('body'),
};
globalThis.Chart = class { constructor(){} destroy(){} update(){} static register(){} };
globalThis.Chart.defaults = { font: {}, plugins: { legend: { labels: {} } } };
globalThis.fetch = async () => ({ ok: false, status: 404, json: async () => null });
const base = pathToFileURL(process.cwd() + '/').href;
const { state } = await import(base + 'fno/state.js');
const nav = await import(base + 'fno/nav.js');
const greeks = await import(base + 'fno/greeks.js');
const stress = await import(base + 'fno/stress.js');
await import(base + 'fno/app-init.js');          // links: no 'is not exported' for deleted modules
state.currentUnd = 'ALL'; state.currentExpiry = 'ALL';
state.positions = [{ und: 'NIFTY', exp: 'W1', type: 'CE', side: 'SELL', qty: 1, strike: 24000, ltp: 10, pnl: 5, ann_vol_pct: 15 }];
state.greeksData = [{ und: 'NIFTY', exp: 'W1', type: 'CE', side: 'SELL', delta: -0.3, gamma: 0, theta: 2, vega: -3, full: 'NIFTY CE' }];
state.marketData = { NIFTY: { close: 24000 } };
const out = {};
"""


def _run_harness(tmp_path: Path, absent: list[str], body: str) -> dict:
    dst = tmp_path / "js"
    shutil.copytree(_JS, dst)
    (dst / "package.json").write_text('{"type":"module"}', encoding="utf-8")
    (dst / "run.mjs").write_text(_HARNESS + body + "\nconsole.log(JSON.stringify(out));\nprocess.exit(0);\n", encoding="utf-8")
    r = subprocess.run(["node", "run.mjs"], capture_output=True, text=True, timeout=60, cwd=dst,
                       env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "ABSENT_IDS": json.dumps(absent)})
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


_CHAIN = r"""
const steps = {};
for (const [n, f] of [['greeksCards', greeks.renderGreeksCards], ['greeksTable', greeks.renderGreeksTable],
    ['riskSections', greeks.updateRiskSections], ['stress', stress.renderStressScenarios],
    ['stdDev', stress.renderStdDevTable]]) {
  try { f(); steps[n] = 'ok'; } catch (e) { steps[n] = 'THROW ' + e.message; }
}
out.steps = steps;
"""


@_node_missing
def test_boot_chain_without_deleted_pages_but_risk_ids_present(tmp_path):
    absent = ["page-hedge", "page-equity-hedge", "page-portfolio-hedge", "fno-geo-overview",
              "hqs-kpis", "hqs-tbody", "eh-results", "hist-content"]
    r = _run_harness(tmp_path, absent, _CHAIN + r"""
out.greeksPainted = (document.getElementById('greeks-all-grid').innerHTML || '').length > 0;
out.stressPainted = (document.getElementById('stress-row').innerHTML || '').length > 0;
""")
    assert set(r["steps"].values()) == {"ok"}, r
    assert r["greeksPainted"] and r["stressPainted"], "Risk-page ids must still be painted"


@_node_missing
def test_boot_chain_with_risk_ids_also_absent_is_guarded(tmp_path):
    absent = _RELOCATED_IDS + ["page-hedge", "page-equity-hedge", "fno-geo-overview"]
    r = _run_harness(tmp_path, absent, _CHAIN)
    assert set(r["steps"].values()) == {"ok"}, r


@_node_missing
@pytest.mark.parametrize("absent_risk", [False, True])
def test_set_underlying_chain_runs_without_throwing(tmp_path, absent_risk):
    """nav.setUnderlying drives the same render chain (+ renderDashboard/renderScenarios/initManoeuvre)."""
    absent = ["page-hedge", "page-equity-hedge", "page-portfolio-hedge", "fno-geo-overview"]
    if absent_risk:
        absent += _RELOCATED_IDS
    r = _run_harness(tmp_path, absent, r"""
const res = {};
for (const und of ['NIFTY', 'BANKNIFTY', 'ALL']) {
  try { nav.setUnderlying(und); res[und] = 'ok'; } catch (e) { res[und] = 'THROW ' + e.message; }
}
out.res = res;
""")
    assert set(r["res"].values()) == {"ok"}, r


@_node_missing
def test_render_std_dev_table_runs_when_stress_row_missing(tmp_path):
    r = _run_harness(tmp_path, ["stress-row", "stress-card-sub"], r"""
let err = null;
try { stress.renderStressScenarios(); } catch (e) { err = e.message; }
out.err = err;
out.cardTouched = document.getElementById('risk-stddev-card').innerHTML.length > 0;
""")
    assert r["err"] is None, r
    assert r["cardTouched"], "renderStdDevTable must still paint #risk-stddev-card"


# ── (e) i18n ──────────────────────────────────────────────────────────────────────────

_REMOVED_KEYS = ["nav.hedge", "nav.equity_hedge"] + [
    f"hedge.{k}" for k in (
        "days_analysed reactive_score budget_peak anchor_positions anchor_sub none_detected near_atm "
        "mid_otm far_otm reactive_desc down_day_ctx calm_ctx no_new_pos avg_budget peak_label "
        "days_over_5pct premium_deployed lottery_pct avg_delta low_delta_warn acceptable_range hedge_pnl "
        "quality_distribution tier_lottery tier_watch tier_good tier_lottery_pct tier_watch_pct "
        "tier_good_pct total_premium_deployed lottery_premium net_hedge_pnl anchor_held_sub no_anchor "
        "alert_lottery_positions alert_watch_positions alert_all_ok").split()
]


def _keys(lang: str) -> list[str]:
    return re.findall(r"^\s*'([^']+)'\s*:", (_JS / "locales" / f"{lang}.js").read_text(encoding="utf-8"), re.M)


def test_removed_key_list_is_the_39_keys():
    assert len(_REMOVED_KEYS) == 39 and len(set(_REMOVED_KEYS)) == 39


@pytest.mark.parametrize("lang", ["en", "nl", "fr"])
def test_locale_has_no_removed_key_and_no_duplicates(lang):
    keys = _keys(lang)
    assert len(keys) > 200
    assert len(keys) == len(set(keys)), "duplicate keys"
    assert not [k for k in _REMOVED_KEYS if k in set(keys)]
    assert not [k for k in keys if k.startswith("hedge.")]


def test_locale_key_sets_identical_across_en_nl_fr():
    en, nl, fr = (set(_keys(x)) for x in ("en", "nl", "fr"))
    assert en == nl == fr, {"nl-en": sorted(nl ^ en)[:10], "fr-en": sorted(fr ^ en)[:10]}


# ── (f) specs ─────────────────────────────────────────────────────────────────────────

_SPECS = _ROOT.parent / "riia-agentic-firm" / "project-office" / "specs"


@pytest.mark.xfail(
    strict=True,
    reason="KNOWN spec drift found by QA: Spec_RITA_App.md still lists `hedge.js` (hedge-history row) and "
           "`equity_hedge.js` (shares+cash note) as live consumers. Remove this marker once the spec is fixed.",
)
def test_specs_do_not_present_removed_modules_as_live():
    if not _SPECS.is_dir():
        pytest.skip(f"specs not reachable from worktree ({_SPECS})")
    pat = re.compile(r"(?<![-\w])(hedge\.js|equity_hedge\.js|loadEquityHedge|renderHedgeRadar|renderPortfolioHedgeRadar|"
                     r"loadHedgeHistory|renderHedgeHistory|injectAsmlToState|page-equity-hedge|page-portfolio-hedge)\b")
    retired_word = re.compile(r"deleted|retired|removed|no longer|dropped|gone|former|was |previously|legacy|dormant|empty", re.I)
    bad = []
    for spec in sorted(_SPECS.glob("Spec_*.md")):
        for n, line in enumerate(spec.read_text(encoding="utf-8").splitlines(), 1):
            if pat.search(line) and not retired_word.search(line):
                bad.append(f"{spec.name}:{n}: {line.strip()[:140]}")
    assert not bad, "specs still describe removed modules as live:\n" + "\n".join(bad)
