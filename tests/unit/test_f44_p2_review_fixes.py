"""F44 P2 — Code Review advisories #2–#9 (task-brief-20261025-1150, run 20261025-1801).

#2  hedge-calc ``computeNShares``: no silent 10-share placeholder; callers show "FX rate unavailable"
#3  ``portfolio_backtest`` ``fx_unavailable`` shown on the screen that renders it (ds/scenarios.js)
#4  Portfolio Builder: "FX rate unavailable" notice; 'Other'-region instruments get a share count
    when their own currency is the portfolio currency (geography-overview now carries ``currency``)
#5  Experience ``/user-portfolio`` reads through ``UserPortfolioService`` (ADR-002)
#6  server strings escaped before ``innerHTML`` (stress.js currency, margin text)
#7  hedge-plan reads go through ``api()`` (401 → ensureDevToken(true) → retry once)
#8  "latest active portfolio" is deterministic (microsecond timestamps + portfolio_id tie-break)
#9  ``_EUROPE`` derived from the shared geography rule; unused ``authHeaders`` import removed
    (the Value Today behaviour test lives in test_f44_p2_js_currency.py)

All data lives in in-memory SQLite — never the dev ``rita_output/rita.db``; the app is called
without its lifespan. JS runs under node (skipped when node is missing).
"""
from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from rita.auth import get_current_user, get_optional_user
from rita.core.geography import EU_COUNTRY_CODES, EU_COUNTRY_NAMES, country_to_location, country_to_region
from rita.database import Base, get_db
from rita.main import app
from rita.models.instrument import InstrumentModel
from rita.models.user import UserModel
from rita.models.user_portfolio import UserPortfolioModel
from rita.repositories.user_portfolio import UserPortfolioRepo
from rita.repositories.user_portfolio_key import UserPortfolioKeyRepo
from rita.schemas.user_portfolio import HoldingItem
from rita.services.user_portfolio_service import UserPortfolioService, location_for_country

_ROOT = Path(__file__).resolve().parents[2]
_SRC = _ROOT / "src" / "rita"
_JS = _ROOT / "dashboard" / "js"
NOW = datetime(2026, 10, 20, 12, 0, 0)
_needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


# ── fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    for uid in ("alice", "bob"):
        session.add(UserModel(id=uid))
    for iid, cc, ccy in (("NIFTY", "IN", None), ("ASML", "NL", None), ("MM", "IN", "INR"), ("ODD", "ZZ", "EUR")):
        session.add(InstrumentModel(instrument_id=iid, name=iid, exchange="X", country_code=cc, currency=ccy,
                                    is_available=True, created_at=NOW))
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(db):
    def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: UserModel(id="alice")
    app.dependency_overrides[get_optional_user] = lambda: UserModel(id="alice")
    try:
        yield TestClient(app)  # no lifespan
    finally:
        for dep in (get_db, get_current_user, get_optional_user):
            app.dependency_overrides.pop(dep, None)


def _node(script: str):
    r = subprocess.run(["node", "--input-type=module", "-e", script], cwd=_JS,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


_IMPORT = """
import { pathToFileURL } from 'node:url';
const base = pathToFileURL(process.cwd() + '/').href;
"""


def _src(rel: str) -> str:
    return (_JS / rel).read_text()


# ── #2 computeNShares: no silent placeholder ───────────────────────────────────

@_needs_node
def test_n_shares_info_reports_missing_fx_instead_of_ten():
    r = _node(_IMPORT + """
const c = await import(base + 'fno/hedge-calc.js');
const h = {shares: null, allocation_pct: 50};
console.log(JSON.stringify({
  ok: c.nSharesInfo(h, {close: 250}, 10000, 91),
  fx: c.nSharesInfo(h, {close: 250}, 10000, null),
  fx0: c.nSharesInfo(h, {close: 250}, 10000, 0),
  inputs: c.nSharesInfo(h, {close: null}, 10000, 91),
  saved: c.nSharesInfo({shares: 7, allocation_pct: 50}, {close: 250}, 10000, null),
  n: c.computeNShares(h, {close: 250}, 10000, null),
  noticeFx: c.sharesNotice(c.nSharesInfo(h, {close: 250}, 10000, null)),
  noticeIn: c.sharesNotice(c.nSharesInfo(h, {}, 10000, 91)),
  noticeOk: c.sharesNotice(c.nSharesInfo(h, {close: 250}, 10000, 91)),
  label: c.FX_UNAVAILABLE,
}));""")
    assert r["ok"] == {"shares": 1820, "reason": None}
    assert r["fx"] == {"shares": None, "reason": "fx"} and r["fx0"] == {"shares": None, "reason": "fx"}
    assert r["inputs"] == {"shares": None, "reason": "inputs"}
    assert r["saved"] == {"shares": 7, "reason": None}            # builder shares need no FX
    assert r["n"] is None                                         # was 10
    assert r["label"] == "FX rate unavailable"
    assert r["noticeFx"].startswith("FX rate unavailable") and r["noticeOk"] is None
    assert "unavailable" in r["noticeIn"]


def test_hedge_callers_surface_the_notice():
    rec = _src("fno/hedge-workflow-recommendation.js")
    wi = _src("fno/hedge-workflow-whatif.js")
    wf = _src("fno/hedge-workflow.js")
    # Recommendation: caveat line shows the notice for a held instrument without a share count
    assert "setEl('hw-rec-note', _recNote(id));" in rec
    assert "sharesNotice(info)" in rec and "_esc(notice)" in rec
    # What-if: the equity leg says why there are no scenarios
    assert "const notice = sharesNotice(_sharesInfoFor(id));" in wi
    assert "Equity-leg scenarios for ${_esc(id)} — ${_esc(notice)}." in wi
    # history: price series only (share-count independent) → 1, never 10
    assert "fxForInstrument(getPortfolioCurrency(), hw.instruments[id])) : null) ?? 1;" in wf
    for s in (rec, wi, wf):
        assert "fxForRegion" not in s
        assert "return 10" not in s


# ── #3 fx_unavailable on the backtest screen ───────────────────────────────────

@_needs_node
def test_backtest_screen_shows_fx_unavailable():
    r = _node(_IMPORT + """
globalThis.window = globalThis;
const m = await import(base + 'ds/scenarios.js');
console.log(JSON.stringify({
  inr: m.fxUnavailableNotice({fx_unavailable: ['INR']}),
  esc: m.fxUnavailableNotice({fx_unavailable: ['<b>X</b>']}),
  none: m.fxUnavailableNotice({fx_unavailable: []}),
  legacy: m.fxUnavailableNotice({}),
}));""")
    assert 'id="sc-fx-unavailable"' in r["inr"] and "FX rate unavailable (INR)" in r["inr"]
    assert "&lt;b&gt;X&lt;/b&gt;" in r["esc"] and "<b>" not in r["esc"]
    assert r["none"] == "" and r["legacy"] == ""
    assert "${fxUnavailableNotice(d)}" in _src("ds/scenarios.js")


def test_portfolio_engine_still_reports_fx_unavailable():
    s = (_SRC / "core" / "portfolio_engine.py").read_text()
    assert '"fx_unavailable":             fx_unavailable' in s


# ── #4 Portfolio Builder ───────────────────────────────────────────────────────

@_needs_node
def test_instrument_currency_and_fx_for_other_region():
    r = _node(_IMPORT + """
globalThis.window = globalThis;
globalThis.sessionStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.location = { hostname: 'example.test' };
globalThis.fetch = async (url) => url.includes('quote=INR')
  ? { ok: true, status: 200, json: async () => ({ rate: 91 }) }
  : { ok: false, status: 404, statusText: 'x', json: async () => ({ detail: 'no fx rate' }) };
const pc = await import(base + 'shared/portfolio-currency.js');
const fx = await import(base + 'shared/fx.js');
const quotes = fx.fxQuotesFor([{id: 'A', currency: 'GBP'}, {id: 'B'}, {id: 'C', currency: 'INR'}], ['INR', 'USD', 'EUR']);
await fx.preloadFx('EUR', quotes);
console.log(JSON.stringify({
  ccy: [pc.instrumentCurrency({region: 'India'}), pc.instrumentCurrency({region: 'Other', currency: 'EUR'}),
        pc.instrumentCurrency({currency: 'GBP'}, 'Other'), pc.instrumentCurrency({region: 'Other'}),
        pc.instrumentCurrency({region: 'US', currency: 'EUR'})],
  quotes,
  otherEur: fx.fxForInstrument('EUR', {region: 'Other', currency: 'EUR'}),
  otherGbp: fx.fxForInstrument('EUR', {region: 'Other', currency: 'GBP'}),
  otherNone: fx.fxForInstrument('EUR', {region: 'Other'}),
  india: fx.fxForInstrument('EUR', {region: 'India'}),
  usdMissing: fx.fxForInstrument('EUR', {region: 'US'}),
  shares: pc.sharesAndCash(10000, 50, 100, fx.fxForInstrument('EUR', {region: 'Other', currency: 'EUR'})),
}));""")
    assert r["ccy"] == ["INR", "EUR", "GBP", None, "USD"]          # region first, then own currency
    assert sorted(r["quotes"]) == ["EUR", "GBP", "INR", "USD"]
    assert r["otherEur"] == 1                                        # same currency: no rate needed
    assert r["otherGbp"] is None and r["otherNone"] is None and r["usdMissing"] is None
    assert r["india"] == 91
    assert r["shares"]["shares"] == 50                               # 'Other' EUR instrument sized again


def test_portfolio_builder_fx_unavailable_notice():
    s = _src("rita/portfolio-builder.js")
    assert "const _FX_UNAVAILABLE = 'FX rate unavailable';" in s
    assert "return instrumentCurrency(inst, r.region);" in s          # 'Other' → instrument currency
    assert "_fxNoticeHtml(id)" in s                                   # basket chip
    assert 'id="pb-fx-unavailable"' in s                              # region summary
    assert "fxMissingSave.push(h.instrument_id)" in s and "saved without a share count" in s
    assert "fxMissing ? `<span style=\"color:#b45309\">${_FX_UNAVAILABLE}</span>`" in s   # pbSetAlloc
    assert "regionCurrency(r.region)" not in s


def test_geography_overview_carries_instrument_currency(client):
    r = client.get("/api/v1/experience/rita/geography-overview")
    assert r.status_code == 200, r.text
    insts = {i["id"]: i for reg in r.json()["regions"] for i in reg["instruments"]}
    assert insts["MM"]["currency"] == "INR"
    assert insts["ODD"]["currency"] == "EUR"
    assert insts["NIFTY"]["currency"] is None
    other = next(reg for reg in r.json()["regions"] if reg["region"] == "Other")
    assert [i["id"] for i in other["instruments"]] == ["ODD"]


# ── #5 Experience route reads through the service ──────────────────────────────

def test_experience_user_portfolio_route_uses_service_not_repo():
    tree = ast.parse((_SRC / "api" / "experience" / "user_portfolio.py").read_text())
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert "UserPortfolioService" in imported
    assert not {"UserPortfolioRepo", "UserPortfolioKeyRepo"} & imported


def test_experience_user_portfolio_route_calls_service(client, monkeypatch):
    calls = []
    real_get = UserPortfolioService.get

    def spy(self, user_id, location=None):
        calls.append((user_id, location))
        return real_get(self, user_id, location)

    monkeypatch.setattr(UserPortfolioService, "get", spy)
    assert client.get("/api/v1/experience/user-portfolio").status_code == 404
    client.post("/api/v1/user-portfolio/", json={"location": "india", "total_value": 1000,
                                                 "holdings": [{"instrument_id": "NIFTY", "allocation_pct": 100}]})
    r = client.get("/api/v1/experience/user-portfolio?location=india")
    assert r.status_code == 200 and r.json()["currency"] == "INR"
    assert calls == [("alice", None), ("alice", "india")]


# ── #6 escaping ────────────────────────────────────────────────────────────────

def test_server_strings_escaped_before_inner_html():
    stress = _src("fno/stress.js")
    assert "allocation-weighted vol in ${_esc(getPortfolioCurrency())}" in stress
    assert "${getPortfolioCurrency()}" not in stress
    assert "${_esc(inst.full)}" in stress and 'data-inst="${_esc(inst.id)}"' in stress
    assert "${_esc(s.ref_label)}" in stress
    save = _src("fno/hedge-workflow-save.js")
    assert "${_esc(m.currency || '')}" in save and "${_esc(m.instrumentId)}" in save
    # no P2-changed file interpolates the raw portfolio currency into markup
    for rel in ("fno/stress.js", "fno/portfolio-hedge.js", "fno/my-portfolio.js", "fno/dashboard.js",
                "fno/risk_chart.js", "fno/hedge-workflow.js", "fno/hedge-workflow-save.js",
                "fno/hedge-workflow-whatif.js", "fno/hedge-workflow-recommendation.js",
                "fno/hedge-instrument-tiles.js", "rita/portfolio-builder.js"):
        assert "${getPortfolioCurrency()}" not in _src(rel), rel


@_needs_node
def test_stress_esc_escapes_markup():
    r = _node(_IMPORT + """
const src = (await import('node:fs')).readFileSync('fno/stress.js', 'utf8');
const body = src.match(/function _esc\\(v\\) \\{([\\s\\S]*?)\\n\\}/)[1];
const _esc = new Function('v', body);
console.log(JSON.stringify([_esc('<img src=x onerror=1>'), _esc('a"b&c'), _esc(null), _esc('INR')]));""")
    assert r == ["&lt;img src=x onerror=1&gt;", "a&quot;b&amp;c", "", "INR"]


# ── #7 hedge-plan reads through api() ──────────────────────────────────────────

@pytest.mark.parametrize("rel", ["fno/hedge-workflow-save.js", "fno/portfolio-hedge.js", "fno/hedge-workflow.js"])
def test_hedge_plan_reads_go_through_api(rel):
    s = _src(rel)
    assert not re.search(r"apiFetch\(\s*'/api/v1/experience/fno/hedge-plan'", s), rel
    assert "api('/api/v1/experience/fno/hedge-plan').catch(() => null)" in s, rel


@_needs_node
def test_hedge_plan_stale_token_recovers_via_ensure_dev_token():
    r = _node(_IMPORT + """
const store = { auth_token: 'stale' };
globalThis.window = globalThis;
globalThis.sessionStorage = { getItem:k=>store[k]??null, setItem:(k,v)=>{store[k]=String(v)}, removeItem:k=>{delete store[k]} };
globalThis.location = { hostname:'localhost', href:'http://localhost/' };
const log = [];
const jr = (body, status = 200) => ({ ok: status < 400, status, statusText: 'x', json: async () => body });
globalThis.fetch = async (url, o = {}) => {
  const auth = (o.headers || {}).Authorization || '';
  log.push(`${o.method || 'GET'} ${url} ${auth}`);
  if (url === '/auth/token') return jr({ access_token: 'fresh' });
  if (auth !== 'Bearer fresh') return jr({ detail: 'expired' }, 401);
  return jr({ coverage: 70, hedged_ids: ['NIFTY'] });
};
const { api } = await import(base + 'shared/api.js');
const plan = await api('/api/v1/experience/fno/hedge-plan').catch(() => null);
console.log(JSON.stringify({ plan, log }));""")
    assert r["plan"] == {"coverage": 70, "hedged_ids": ["NIFTY"]}
    assert r["log"] == ["GET /api/v1/experience/fno/hedge-plan Bearer stale", "POST /auth/token ",
                        "GET /api/v1/experience/fno/hedge-plan Bearer fresh"]


# ── #8 deterministic "latest active portfolio" ─────────────────────────────────

def _row(key_id, pid, location=None, ts=NOW):
    return UserPortfolioModel(portfolio_id=pid, key_id=key_id, name=pid, holdings=[], currency="EUR",
                              location=location, created_at=ts, updated_at=ts, is_active=True)


def test_latest_active_tie_breaks_on_portfolio_id(db):
    key = UserPortfolioKeyRepo(db).find_or_create("alice")
    for pid, loc in (("p-b", "india"), ("p-c", None), ("p-a", "us")):   # identical timestamps
        db.add(_row(key.key_id, pid, loc))
    db.commit()
    repo = UserPortfolioRepo(db)
    picks = {repo.find_active_by_key_id(key.key_id).portfolio_id for _ in range(5)}
    assert picks == {"p-c"}                                              # highest portfolio_id wins
    assert UserPortfolioService(db).get("alice").portfolio_id == "p-c"


def test_same_second_saves_return_the_last_save(db):
    """Two saves in the same second (func.now() would tie) → GET without location = the last one."""
    svc = UserPortfolioService(db)
    first = svc.save("alice", [HoldingItem(instrument_id="NIFTY", allocation_pct=100)], location="india",
                     total_value=1000)
    second = svc.save("alice", [HoldingItem(instrument_id="ASML", allocation_pct=100)], total_value_eur=500)
    rows = {r.portfolio_id: r for r in db.query(UserPortfolioModel).all()}
    assert rows[second.portfolio_id].updated_at > rows[first.portfolio_id].updated_at   # microseconds
    assert svc.get("alice").portfolio_id == second.portfolio_id
    third = svc.save("alice", [HoldingItem(instrument_id="MM", allocation_pct=100)], location="india",
                     total_value=2000)
    assert svc.get("alice").portfolio_id == third.portfolio_id


def test_repo_orders_by_updated_created_then_portfolio_id():
    s = (_SRC / "repositories" / "user_portfolio.py").read_text()
    assert "UserPortfolioModel.portfolio_id.desc()" in s
    assert s.count(".order_by(*_LATEST_FIRST)") == 2
    assert "rowid" not in s.split('"""', 2)[2]                             # portable (PostgreSQL v2)


# ── #9 hygiene ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("code", sorted(EU_COUNTRY_CODES) + sorted(EU_COUNTRY_NAMES))
def test_europe_location_follows_geography_buckets(code):
    from rita.api.experience.rita import _country_to_region
    assert _country_to_region(code) == "EU"
    assert location_for_country(code) == "europe" == country_to_location(code)


@pytest.mark.parametrize("country,region,location", [
    ("IN", "India", "india"), ("India", "India", "india"), ("US", "US", "us"), ("USA", "US", "us"),
    ("United States of America", "US", "us"), ("ZZ", "Other", None), ("", "Other", None), (None, "Other", None),
])
def test_country_rule_single_source(country, region, location):
    assert country_to_region(country) == region
    assert location_for_country(country) == location


def test_no_copied_country_sets():
    svc = (_SRC / "services" / "user_portfolio_service.py").read_text()
    rita = (_SRC / "api" / "experience" / "rita.py").read_text()
    assert "_EUROPE" not in svc and '"NETHERLANDS"' not in svc
    assert "from rita.core.geography import country_to_location" in svc
    assert "_EU_COUNTRY_CODES = frozenset" not in rita and "from rita.core.geography import country_to_region" in rita


def test_recommendation_has_no_unused_auth_headers_import():
    s = _src("fno/hedge-workflow-recommendation.js")
    assert "authHeaders" not in s
