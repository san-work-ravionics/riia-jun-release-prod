"""F44 P2 QA — multi-currency portfolios: gap tests on top of the Engineer's ``test_f44_p2_*``.

Covers:
- happy path end to end: India portfolio saved through the API, read back by both GET routes and
  by ``portfolio.get_holdings`` over the in-memory MCP client, all against one temp DB
- property: the currency always comes from the location (random bodies with client-sent currency
  junk); one active portfolio per (user, location) (random save sequences); share math
  (``floor(amount × rate / price)``, 0 <= cash < one share, missing rate → no count)
- property: no network from any portfolio / FX request path; ``refresh_fx`` unreachable
- legacy rows (location NULL, ``cash_eur`` only) round-trip unchanged through every reader
- migration up → down → up on a temp DB with legacy + P2 rows
- design contract: columns, API fields, FX route + 404 shape, ``market.fx_rate`` schema, 12 tools

Property tests use seeded ``random.Random`` (``hypothesis`` is not in the shared env), so they are
deterministic.  Every DB is in-memory or under ``tmp_path``; the dev ``rita_output/rita.db`` is only
opened read-only to check that its row counts do not change.
"""
from __future__ import annotations

import ast
import asyncio
import json
import math
import os
import random
import shutil
import socket
import sqlite3
import subprocess
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import jsonschema
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import rita.interfaces.mcp_tools as mt
from rita.auth import get_current_user, get_optional_user
from rita.config import get_settings
from rita.core.portfolio_engine import _invested_fraction
from rita.database import Base, get_db
from rita.interfaces.mcp_client import McpCallError, identity_for, memory_client
from rita.interfaces.tools import set_session_factory
from rita.main import app
from rita.models.instrument import InstrumentModel
from rita.models.market_data import MarketDataCacheModel
from rita.models.mcp_call import MCPCallModel
from rita.models.user import UserModel
from rita.models.user_portfolio import UserPortfolioModel
from rita.models.user_portfolio_key import UserPortfolioKeyModel
from rita.repositories.user_portfolio import UserPortfolioRepo
from rita.repositories.user_portfolio_key import UserPortfolioKeyRepo
from rita.schemas.user_portfolio import UserPortfolioCreate, UserPortfolioOut
from rita.services.user_portfolio_service import UserPortfolioService, holding_cash

_ROOT = Path(__file__).resolve().parents[2]
_SRC = _ROOT / "src" / "rita"
_JS = _ROOT / "dashboard" / "js"
_DEV_DB = _ROOT / "rita_output" / "rita.db"

NOW = datetime(2026, 10, 20, 12, 0, 0)
EURINR, EURUSD = 91.0, 1.10
RATE = {"EUR": 1.0, "INR": EURINR, "USD": EURUSD}        # units per 1 EUR
LOC_CCY = {None: "EUR", "europe": "EUR", "india": "INR", "us": "USD"}
LOC_INSTRUMENTS = {
    "india": ["NIFTY", "RELIANCE", "SBIN"],
    "us": ["NVIDIA", "MSFT"],
    "europe": ["ASML", "ATO"],
}
_COUNTRY = {"india": "IN", "us": "US", "europe": "NL"}
USERS = ("alice", "bob", "carol")


# ── dev DB guard ───────────────────────────────────────────────────────────────

def _dev_counts() -> dict[str, int] | None:
    if not _DEV_DB.exists():
        return None
    c = sqlite3.connect(f"file:{_DEV_DB}?mode=ro", uri=True)
    try:
        return {t: c.execute(f"select count(*) from {t}").fetchone()[0]
                for t in ("mcp_calls", "user_portfolios", "market_data_cache")}
    finally:
        c.close()


@pytest.fixture(scope="module", autouse=True)
def _dev_db_untouched():
    before = _dev_counts()
    yield
    assert _dev_counts() == before, "QA tests wrote to the dev rita_output/rita.db"


# ── fixtures ───────────────────────────────────────────────────────────────────

def _seed(db, *, fx: bool = True) -> None:
    for uid in USERS:
        db.add(UserModel(id=uid))
    for loc, ids in LOC_INSTRUMENTS.items():
        for iid in ids:
            db.add(InstrumentModel(instrument_id=iid, name=iid, exchange="X", country_code=_COUNTRY[loc],
                                   is_available=True, created_at=NOW))
    if fx:
        for und, close in (("FX_EURINR", EURINR), ("FX_EURUSD", EURUSD)):
            db.add(MarketDataCacheModel(cache_id=str(uuid.uuid4()), date=date(2026, 10, 17), underlying=und,
                                        open=close, high=close, low=close, close=close, recorded_at=NOW))
    db.commit()


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    _seed(s)
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _override(get_session, state):
    def _db():
        s = get_session()
        try:
            yield s
        finally:
            if s is not state.get("shared"):
                s.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    app.dependency_overrides[get_optional_user] = lambda: state["user"]
    c = TestClient(app)  # no lifespan
    c.as_user = lambda uid: state.__setitem__("user", UserModel(id=uid))
    return c


def _clear_overrides():
    for dep in (get_db, get_current_user, get_optional_user):
        app.dependency_overrides.pop(dep, None)


@pytest.fixture
def client(db):
    state = {"user": UserModel(id="alice"), "shared": db}
    try:
        yield _override(lambda: db, state)
    finally:
        _clear_overrides()


@pytest.fixture
def file_db(tmp_path):
    """One temp file DB shared by the API (``get_db``) and the MCP tools (``set_session_factory``)."""
    engine = create_engine(f"sqlite:///{tmp_path / 'qa.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine)
    s = maker()
    _seed(s)
    s.close()
    set_session_factory(maker)
    state = {"user": UserModel(id="alice")}
    try:
        yield maker, _override(maker, state)
    finally:
        _clear_overrides()
        set_session_factory(None)
        engine.dispose()


async def _mcp(user, name, args=None):
    async with memory_client(identity_for(user, "jarvis")) as c:
        return await c.call(name, args or {})


# ── 1. happy path end to end ──────────────────────────────────────────────────

def test_e2e_india_portfolio_api_then_mcp(file_db):
    maker, client = file_db
    body = {
        "name": "India core", "location": "india", "total_value": 1_000_000, "currency": "USD",
        "holdings": [
            {"instrument_id": "NIFTY", "allocation_pct": 60, "shares": 24, "cash": 1234.5},
            {"instrument_id": "RELIANCE", "allocation_pct": 40, "shares": 160, "cash": 87.25},
        ],
    }
    r = client.post("/api/v1/user-portfolio/", json=body)
    assert r.status_code == 201, r.text
    saved = r.json()
    assert (saved["currency"], saved["location"], saved["total_value"]) == ("INR", "india", 1_000_000)
    assert saved["total_value_eur"] == pytest.approx(1_000_000 / EURINR)

    expected_holdings = [("NIFTY", 60.0, 24, 1234.5), ("RELIANCE", 40.0, 160, 87.25)]
    for url in ("/api/v1/user-portfolio/?location=india", "/api/v1/user-portfolio/",
                "/api/v1/experience/user-portfolio?location=india", "/api/v1/experience/user-portfolio"):
        got = client.get(url)
        assert got.status_code == 200, (url, got.text)
        g = got.json()
        assert g["portfolio_id"] == saved["portfolio_id"], url
        assert (g["currency"], g["location"], g["total_value"]) == ("INR", "india", 1_000_000), url
        assert [(h["instrument_id"], h["allocation_pct"], h["shares"], h["cash"]) for h in g["holdings"]] \
            == expected_holdings, url
        assert all(h["cash_eur"] is None for h in g["holdings"]), url   # no EUR cash on an INR portfolio

    alice = UserModel(id="alice")
    res = asyncio.run(_mcp(alice, "portfolio.get_holdings", {"location": "india"}))
    out = res.structured
    jsonschema.validate(out, mt.REGISTRY["portfolio.get_holdings"].output_json_schema())
    assert (out["portfolio_id"], out["currency"], out["location"], out["total_value"]) == \
        (saved["portfolio_id"], "INR", "india", 1_000_000)
    assert [(h["instrument_id"], h["allocation_pct"], h["shares"], h["cash"]) for h in out["holdings"]] \
        == expected_holdings
    latest = asyncio.run(_mcp(alice, "portfolio.get_holdings")).structured
    assert latest["portfolio_id"] == saved["portfolio_id"]

    with maker() as s:   # the MCP calls were logged into the temp DB, as the signed-in user
        rows = s.query(MCPCallModel).filter(MCPCallModel.tool_name == "portfolio.get_holdings").all()
        assert len(rows) == 2 and {r.user_id for r in rows} == {"alice"} and {r.transport for r in rows} == {"memory"}
        stored = s.query(UserPortfolioModel).one()
        assert (stored.currency, stored.location, stored.total_value) == ("INR", "india", 1_000_000)


# ── 2. property: currency always from the location ─────────────────────────────

_JUNK_CCY = ["USD", "INR", "EUR", "GBP", "", None, 123, "usd", {"x": 1}]
_SPLITS = [[100], [50, 50], [25, 75], [20, 30, 50]]


def _random_body(rng: random.Random) -> tuple[dict, str | None]:
    loc = rng.choice([None, "europe", "india", "us"])
    pool = [i for ids in LOC_INSTRUMENTS.values() for i in ids] if loc is None else LOC_INSTRUMENTS[loc]
    split = rng.choice([s for s in _SPLITS if len(s) <= len(pool)])
    ids = rng.sample(pool, len(split))
    holdings = []
    for iid, pct in zip(ids, split):
        h = {"instrument_id": iid, "allocation_pct": pct, "shares": rng.randint(0, 500),
             "cash": round(rng.uniform(0, 900), 2)}
        if rng.random() < 0.5:
            h["currency"] = rng.choice(_JUNK_CCY)          # client junk on the holding
        holdings.append(h)
    body: dict = {"holdings": holdings, "name": f"p{rng.randint(0, 9999)}"}
    if loc is not None or rng.random() < 0.5:
        body["location"] = loc
    if rng.random() < 0.8:
        body["currency"] = rng.choice(_JUNK_CCY)           # client junk on the body
    if rng.random() < 0.7:
        body["total_value"] = round(rng.uniform(1_000, 5_000_000), 2)
    if rng.random() < 0.5:
        body["total_value_eur"] = round(rng.uniform(1_000, 500_000), 2)
    return body, loc


@pytest.mark.parametrize("seed", [11, 22, 33])
def test_property_currency_always_from_location(client, db, seed):
    rng = random.Random(seed)
    presets = {k: v.currency for k, v in get_settings().retirement_plan.locations.items()}
    assert presets == {"europe": "EUR", "india": "INR", "us": "USD"}
    for _ in range(40):
        body, loc = _random_body(rng)
        user = rng.choice(USERS)
        client.as_user(user)
        r = client.post("/api/v1/user-portfolio/", json=body)
        assert r.status_code == 201, (body, r.text)
        out = r.json()
        ccy = LOC_CCY[loc]
        assert (out["currency"], out["location"]) == (ccy, loc), body
        row = db.get(UserPortfolioModel, out["portfolio_id"])
        assert (row.currency, row.location) == (ccy, loc), body

        tv, tv_eur = body.get("total_value"), body.get("total_value_eur")
        if loc is None:
            native = tv if tv is not None else tv_eur
            assert row.total_value == native and row.total_value_eur == native
        else:
            native = tv if tv is not None else (tv_eur * RATE[ccy] if tv_eur is not None else None)
            assert row.total_value == pytest.approx(native) if native is not None else row.total_value is None
            if native is None:
                assert row.total_value_eur is None
            else:
                assert row.total_value_eur == pytest.approx(native / RATE[ccy])
        for h in row.holdings:   # stored holdings never carry the client's currency key
            assert set(h) == {"instrument_id", "allocation_pct", "shares", "cash", "cash_eur"}
            assert h["cash_eur"] == (h["cash"] if ccy == "EUR" else None)
        if loc is not None:
            got = client.get(f"/api/v1/user-portfolio/?location={loc}").json()
            assert got["portfolio_id"] == out["portfolio_id"] and got["currency"] == ccy
    # an invalid location is rejected, never stored under a client currency
    n = db.query(UserPortfolioModel).count()
    for bad in ("mars", "INDIA", "", "INR"):
        r = client.post("/api/v1/user-portfolio/", json={"location": bad, "currency": "INR",
                                                         "holdings": [{"instrument_id": "NIFTY", "allocation_pct": 100}]})
        assert r.status_code == 422, bad
    assert db.query(UserPortfolioModel).count() == n


# ── 3. property: one active portfolio per (user, location) ─────────────────────

def _active_by_bucket(db) -> dict[tuple[str, str | None], list[str]]:
    out: dict[tuple[str, str | None], list[str]] = {}
    keys = {k.key_id: k.user_id for k in db.query(UserPortfolioKeyModel).all()}
    for r in db.query(UserPortfolioModel).filter(UserPortfolioModel.is_active.is_(True)).all():
        out.setdefault((keys[r.key_id], r.location), []).append(r.portfolio_id)
    return out


@pytest.mark.parametrize("seed", [5, 6, 7])
def test_property_one_active_portfolio_per_user_and_location(client, db, seed):
    rng = random.Random(seed)
    last_by_bucket: dict[tuple[str, str | None], str] = {}
    last_by_user: dict[str, str] = {}
    saves = 0
    for _ in range(60):
        user = rng.choice(USERS)
        loc = rng.choice([None, "europe", "india", "us"])
        iid = rng.choice(LOC_INSTRUMENTS[loc] if loc else LOC_INSTRUMENTS[rng.choice(list(LOC_INSTRUMENTS))])
        client.as_user(user)
        body = {"location": loc, "total_value": 10_000, "holdings": [{"instrument_id": iid, "allocation_pct": 100}]}
        r = client.post("/api/v1/user-portfolio/", json=body)
        assert r.status_code == 201, r.text
        saves += 1
        pid = r.json()["portfolio_id"]
        last_by_bucket[(user, loc)] = pid
        last_by_user[user] = pid

        active = _active_by_bucket(db)
        assert {k: v for k, v in active.items()} == {k: [v] for k, v in last_by_bucket.items()}
        assert db.query(UserPortfolioModel).count() == saves          # soft replace: nothing deleted

    for user in USERS:
        client.as_user(user)
        for loc in ("europe", "india", "us"):
            want = last_by_bucket.get((user, loc))
            for url in (f"/api/v1/user-portfolio/?location={loc}", f"/api/v1/experience/user-portfolio?location={loc}"):
                r = client.get(url)
                if want is None:
                    assert r.status_code == 404, url
                else:
                    assert r.json()["portfolio_id"] == want, url
        key = UserPortfolioKeyRepo(db).find_by_user_id(user)
        legacy = UserPortfolioRepo(db).find_active_by_key_and_location(key.key_id, None) if key else None
        assert (legacy.portfolio_id if legacy else None) == last_by_bucket.get((user, None))
        if user in last_by_user:   # no location → the user's most recent save of any location
            assert client.get("/api/v1/user-portfolio/").json()["portfolio_id"] == last_by_user[user]
            assert client.get("/api/v1/experience/user-portfolio").json()["portfolio_id"] == last_by_user[user]


# ── 4. property: share math ────────────────────────────────────────────────────

def _node(script: str) -> dict:
    r = subprocess.run(["node", "--input-type=module", "-e", script], cwd=_JS,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def _share_cases(seed: int, n: int = 250) -> list[dict]:
    rng = random.Random(seed)
    cases = []
    for _ in range(n):
        ccy = rng.choice(["EUR", "INR", "USD"])               # portfolio currency
        inst = rng.choice(["EUR", "INR", "USD"])              # instrument currency
        fx = RATE[inst] / RATE[ccy] * rng.uniform(0.8, 1.25)  # instrument units per portfolio unit
        cases.append({
            "total": round(rng.uniform(500, 5_000_000), 2),
            "pct": rng.choice([5, 10, 12.5, 20, 25, 33.3, 50, 100, rng.uniform(0.5, 100)]),
            "price": round(rng.uniform(0.5, 60_000), 2),
            "fx": 1.0 if inst == ccy else fx,
        })
    return cases


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("seed", [101, 202])
def test_property_share_math_js(seed):
    cases = _share_cases(seed)
    r = _node(f"""
import {{ pathToFileURL }} from 'node:url';
const base = pathToFileURL(process.cwd() + '/').href;
const pc = await import(base + 'shared/portfolio-currency.js');
const hc = await import(base + 'fno/hedge-calc.js');
const cases = {json.dumps(cases)};
const out = cases.map(c => ({{
  sc: pc.sharesAndCash(c.total, c.pct, c.price, c.fx),
  info: hc.nSharesInfo({{ allocation_pct: c.pct, shares: null }}, {{ close: c.price }}, c.total, c.fx),
}}));
const missing = [null, 0].map(fx => ({{
  sc: pc.sharesAndCash(100000, 50, 250, fx),
  info: hc.nSharesInfo({{ allocation_pct: 50, shares: null }}, {{ close: 250 }}, 100000, fx),
  n: hc.computeNShares({{ allocation_pct: 50, shares: null }}, {{ close: 250 }}, 100000, fx),
}}));
console.log(JSON.stringify({{ out, missing }}));""")
    for c, o in zip(cases, r["out"]):
        alloc = c["total"] * c["pct"] / 100
        want = math.floor((alloc * c["fx"]) / c["price"])      # floor(amount × rate / native price)
        sc = o["sc"]
        assert sc["shares"] == want, c
        one_share = c["price"] / c["fx"]                       # one share in the portfolio currency
        assert sc["cash"] >= -1e-9 * alloc, c                  # never negative
        assert sc["cash"] < one_share + 1e-9 * alloc, c        # less than one share price
        assert sc["cash"] == pytest.approx(alloc - want * one_share, rel=1e-9, abs=1e-6)
        # hedge workflow: same count (pre-existing rule: a zero count is shown as 1 share)
        assert o["info"] == {"shares": want or 1, "reason": None}, c
    for m in r["missing"]:          # a missing FX rate → no share count, never a static rate / 10 shares
        assert m["sc"] is None
        assert m["info"] == {"shares": None, "reason": "fx"}
        assert m["n"] is None


@pytest.mark.parametrize("seed", [7, 8])
def test_property_core_whole_share_fraction(seed):
    """core/portfolio_engine whole-share constraint with a passed-in rate (EUR per unit)."""
    rng = random.Random(seed)
    for _ in range(500):
        alloc = rng.uniform(1, 200_000)
        price_native = rng.uniform(0.5, 60_000)
        eur_per_unit = rng.choice([1.0, 1 / EURINR, 1 / EURUSD]) * rng.uniform(0.8, 1.25)
        price_eur = price_native * eur_per_unit
        frac = _invested_fraction(alloc, price_eur)
        n = math.floor(alloc / price_eur)
        assert 0.0 <= frac <= 1.0
        assert frac == pytest.approx(min(n * price_eur / alloc, 1.0))
        assert alloc * (1 - frac) < price_eur * (1 + 1e-9)    # uninvested cash < one share


# ── 5. property: no network; refresh_fx unreachable ───────────────────────────

@pytest.fixture
def net_guard(monkeypatch):
    """Record (and refuse) every socket connect / yfinance download / refresh_fx call.

    Recording, not only raising: a broad ``except`` in request code cannot hide the attempt.
    """
    calls: list[str] = []

    def _rec(kind):
        def _boom(*a, **k):
            calls.append(kind)
            raise OSError(f"network disabled in test: {kind}")
        return _boom

    monkeypatch.setattr(socket.socket, "connect", _rec("socket.connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", _rec("socket.connect_ex"))
    monkeypatch.setattr(socket, "create_connection", _rec("socket.create_connection"))
    monkeypatch.setattr(socket, "getaddrinfo", _rec("socket.getaddrinfo"))
    import yfinance

    from rita.services import data_refresh
    monkeypatch.setattr(yfinance, "download", _rec("yfinance.download"), raising=False)  # yfinance may be a spec'd stub (test_data_refresh)
    monkeypatch.setattr(yfinance, "Ticker", _rec("yfinance.Ticker"), raising=False)
    monkeypatch.setattr(data_refresh, "refresh_fx", _rec("refresh_fx"))
    return calls


def _seed_prices(db, ids, n=90):
    start = date(2026, 6, 1)
    for k, iid in enumerate(ids):
        for i in range(n):
            c = (100.0 + 50 * k) * (1 + 0.01 * ((i % 7) - 3))
            db.add(MarketDataCacheModel(cache_id=str(uuid.uuid4()), date=start + timedelta(days=i), underlying=iid,
                                        open=c, high=c, low=c, close=c, recorded_at=NOW))
    db.commit()


def test_property_no_network_on_any_portfolio_or_fx_path(client, db, net_guard):
    _seed_prices(db, ["NIFTY", "RELIANCE", "ASML", "NVIDIA"])
    mod = "rita.api.experience.portfolio_hedge"
    statuses = {}
    # the Kite middleware put-premium read on portfolio-hedge is pre-P2 and not a portfolio/FX read
    with patch(f"{mod}.fetch_put_premium", return_value=None), patch(f"{mod}.put_premium_from_csv", return_value=None):
        for loc, ids, tv in (("india", ["NIFTY", "RELIANCE"], 1_000_000), ("us", ["NVIDIA"], 20_000),
                             (None, ["ASML", "NIFTY"], 30_000)):
            body = {"location": loc, "total_value": tv,
                    "holdings": [{"instrument_id": i, "allocation_pct": 100 / len(ids)} for i in ids]}
            statuses[f"POST {loc}"] = client.post("/api/v1/user-portfolio/", json=body).status_code
        statuses["POST 422"] = client.post("/api/v1/user-portfolio/", json={
            "location": "india", "holdings": [{"instrument_id": "ASML", "allocation_pct": 100}]}).status_code
        for url in ["/api/v1/user-portfolio/", "/api/v1/experience/user-portfolio",
                    *[f"/api/v1/user-portfolio/?location={x}" for x in ("europe", "india", "us")],
                    *[f"/api/v1/experience/user-portfolio?location={x}" for x in ("europe", "india", "us")],
                    *[f"/api/v1/experience/rita/fx?base={b}&quote={q}" for b in RATE for q in RATE],
                    "/api/v1/experience/rita/fx?quote=GBP",
                    "/api/v1/experience/fno/portfolio-analytics?mode=real",
                    "/api/v1/experience/fno/portfolio-analytics?mode=mock",
                    "/api/v1/experience/fno/portfolio-hedge?coverage=50",
                    "/api/v1/experience/fno/portfolio-hedge?coverage=50&total_value=50000"]:
            statuses[url] = client.get(url).status_code
    assert net_guard == [], net_guard
    assert statuses["POST 422"] == 422 and statuses["/api/v1/experience/rita/fx?quote=GBP"] == 422
    assert all(v in (200, 201, 404) for k, v in statuses.items() if k not in ("POST 422", "/api/v1/experience/rita/fx?quote=GBP")), statuses
    assert statuses["/api/v1/experience/rita/fx?base=INR&quote=USD"] == 200
    assert statuses["/api/v1/experience/user-portfolio?location=europe"] == 404


def test_property_no_network_on_mcp_portfolio_and_fx_tools(file_db, net_guard):
    maker, client = file_db
    assert client.post("/api/v1/user-portfolio/", json={
        "location": "us", "total_value": 5000, "holdings": [{"instrument_id": "NVIDIA", "allocation_pct": 100}],
    }).status_code == 201
    alice = UserModel(id="alice")
    for loc in (None, "us"):
        assert asyncio.run(_mcp(alice, "portfolio.get_holdings", {"location": loc} if loc else {})).structured["currency"] == "USD"
    for b in RATE:
        for q in RATE:
            out = asyncio.run(_mcp(None, "market.fx_rate", {"base": b, "quote": q})).structured
            assert out["rate"] == pytest.approx(RATE[q] / RATE[b])
    with pytest.raises(McpCallError) as e:
        asyncio.run(_mcp(None, "market.fx_rate", {"quote": "INR", "as_of": "2020-01-01"}))
    assert e.value.code == "not_found"
    assert net_guard == [], net_guard


def _references(name: str) -> list[str]:
    """Every code reference (name / attribute / import alias) to ``name`` in ``src/rita`` except its def."""
    hits = []
    for path in _SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if (isinstance(node, ast.Name) and node.id == name) or \
               (isinstance(node, ast.Attribute) and node.attr == name) or \
               (isinstance(node, ast.alias) and node.name.split(".")[-1] == name):
                hits.append(f"{path.relative_to(_SRC)}:{node.lineno}")
            elif isinstance(node, ast.Constant) and node.value == name:   # getattr(mod, "refresh_fx")
                hits.append(f"{path.relative_to(_SRC)}:{node.lineno} (string)")
    return hits


def test_refresh_fx_has_no_caller_anywhere_in_src():
    """Stronger than the api/interfaces scan: nothing in src/rita (services, core, main, scheduler)
    references ``refresh_fx`` — so neither ``refresh_all()`` nor any route can reach it."""
    assert _references("refresh_fx") == []
    defs = [p for p in _SRC.rglob("*.py")
            if any(isinstance(n, ast.FunctionDef) and n.name == "refresh_fx" for n in ast.walk(ast.parse(p.read_text())))]
    assert [p.relative_to(_SRC).as_posix() for p in defs] == ["services/data_refresh.py"]


def test_refresh_all_never_calls_refresh_fx_at_runtime(db, net_guard):
    from rita.services import data_refresh

    with patch.object(data_refresh, "YF_TICKER_MAP", {"NIFTY": "^NSEI"}):
        try:
            data_refresh.refresh_all(db)
        except Exception:  # noqa: BLE001 — the instrument download is refused; only refresh_fx matters
            pass
    assert "refresh_fx" not in net_guard


# ── 6. legacy rows round-trip unchanged ────────────────────────────────────────

_LEGACY_HOLDINGS = [
    {"instrument_id": "ASML", "allocation_pct": 60.0, "shares": 3, "cash_eur": 12.5},
    {"instrument_id": "NIFTY", "allocation_pct": 40.0, "shares": 0, "cash_eur": 400.0},
]


def _insert_legacy(db, *, total_value) -> str:
    key = UserPortfolioKeyRepo(db).find_or_create("alice")
    pid = str(uuid.uuid4())
    # raw SQL as a pre-P2 writer would leave it: no currency (server default), no location, no `cash`
    db.execute(text(
        "insert into user_portfolios (portfolio_id, key_id, name, holdings, total_value_eur, total_value, "
        "created_at, updated_at, is_active) values (:p, :k, 'Legacy', :h, 5000.0, :tv, :t, :t, 1)"),
        {"p": pid, "k": key.key_id, "h": json.dumps(_LEGACY_HOLDINGS), "tv": total_value, "t": NOW})
    db.commit()
    return pid


def _raw(db, pid):
    return db.execute(text("select name, holdings, total_value_eur, total_value, currency, location, is_active, "
                           "updated_at from user_portfolios where portfolio_id = :p"), {"p": pid}).one()


@pytest.mark.parametrize("backfilled", [True, False], ids=["backfilled", "total_value_null"])
def test_legacy_row_round_trips_unchanged_through_every_reader(client, db, backfilled):
    from rita.services.hedge_history_export import flatten_rows
    from rita.services.hedge_plan_service import HedgePlanService

    pid = _insert_legacy(db, total_value=5000.0 if backfilled else None)
    before = _raw(db, pid)
    assert (before.currency, before.location) == ("EUR", None)

    def _check_out(o: dict, where: str):
        assert (o["portfolio_id"], o["currency"], o["location"]) == (pid, "EUR", None), where
        assert (o["total_value"], o["total_value_eur"]) == (5000.0, 5000.0), where
        assert [(h["instrument_id"], h["allocation_pct"], h["shares"], h["cash"], h["cash_eur"]) for h in o["holdings"]] \
            == [("ASML", 60.0, 3, 12.5, 12.5), ("NIFTY", 40.0, 0, 400.0, 400.0)], where

    _check_out(UserPortfolioService(db).get("alice").model_dump(), "service.get()")
    for url in ("/api/v1/user-portfolio/", "/api/v1/experience/user-portfolio"):
        _check_out(client.get(url).json(), url)
    for url in ("/api/v1/user-portfolio/?location=europe", "/api/v1/experience/user-portfolio?location=europe"):
        assert client.get(url).status_code == 404, url        # a legacy row has no location

    # MCP portfolio.get_holdings (temp file DB view of the same row: share the in-memory engine)
    set_session_factory(sessionmaker(bind=db.get_bind()))
    try:
        mcp = asyncio.run(_mcp(UserModel(id="alice"), "portfolio.get_holdings")).structured
    finally:
        set_session_factory(None)
    assert (mcp["currency"], mcp["location"], mcp["total_value"]) == ("EUR", None, 5000.0)
    assert [(h["shares"], h["cash"]) for h in mcp["holdings"]] == [(3, 12.5), (0, 400.0)]

    meta = client.get("/api/v1/experience/fno/portfolio-analytics?mode=real").json()["portfolio_meta"]
    assert (meta["currency"], meta["total_value"], meta["total_value_eur"]) == ("EUR", 5000.0, 5000.0)

    _seed_prices(db, ["ASML", "NIFTY"])
    mod = "rita.api.experience.portfolio_hedge"
    with patch(f"{mod}.fetch_put_premium", return_value=None), patch(f"{mod}.put_premium_from_csv", return_value=None):
        ph = client.get("/api/v1/experience/fno/portfolio-hedge?coverage=50").json()
    assert ph["currency"] == "EUR"
    assert {h["instrument_id"]: h["position_eur"] for h in ph["holdings"]} == {"ASML": 3000.0, "NIFTY": 2000.0}

    row = db.get(UserPortfolioModel, pid)
    cash_total = sum(holding_cash(h) or 0.0 for h in row.holdings)
    block = HedgePlanService._portfolio_block(row, cash_total, len(row.holdings))
    assert block == {"total_value_eur": 5000.0, "cash_eur": 412.5, "n_holdings": 2,
                     "currency": "EUR", "total_value": 5000.0, "cash": 412.5}
    flat = flatten_rows([type("R", (), dict(
        history_id="h", saved_at=None, user_id="alice", key_id="k", trigger="t", source="s", last_step=None,
        scenario_tab="pp", coverage=50, duration="1y", schema_version=1, app_version="x",
        portfolio=block, instruments=[]))()])[0]
    assert (flat["total_value_eur"], flat["cash_eur"], flat["portfolio_currency"], flat["total_value"]) == \
        (5000.0, 412.5, "EUR", 5000.0)

    db.expire_all()
    assert _raw(db, pid) == before                         # no reader wrote to the row
    assert json.loads(before.holdings) == _LEGACY_HOLDINGS


def test_legacy_out_schema_never_upgrades_eur_cash_on_non_eur_rows():
    """``cash_eur`` → ``cash`` and ``total_value_eur`` → ``total_value`` only for EUR portfolios."""
    base = dict(portfolio_id="p", key_id="k", name="n", created_at=NOW, updated_at=NOW, is_active=True,
                total_value_eur=100.0, holdings=[{"instrument_id": "NIFTY", "allocation_pct": 100, "cash_eur": 5.0}])
    inr = UserPortfolioOut.model_validate({**base, "currency": "INR", "location": "india"})
    assert inr.total_value is None and inr.holdings[0].cash is None
    eur = UserPortfolioOut.model_validate({**base, "currency": None})
    assert eur.currency == "EUR" and eur.total_value == 100.0 and eur.holdings[0].cash == 5.0


# ── 7. migration on a temp DB ──────────────────────────────────────────────────

_PRIOR = "20261026_f44p1_mcp_calls_caller"
_HEAD = "20261026_f44p2_user_portfolio_currency"


def _alembic(dbp: Path, *args: str) -> str:
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{dbp}", "RITA_ENV": "development"}
    r = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=_ROOT, env=env,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, (r.stdout + r.stderr)[-2000:]
    return r.stdout + r.stderr


def _q(dbp: Path, sql: str, params=()) -> list:
    c = sqlite3.connect(dbp)
    try:
        out = c.execute(sql, params).fetchall()
        c.commit()
        return out
    finally:
        c.close()


def test_migration_up_down_up_preserves_legacy_and_p2_rows(tmp_path):
    dbp = tmp_path / "mig.db"
    _alembic(dbp, "upgrade", _PRIOR)
    tables = {r[0] for r in _q(dbp, "select name from sqlite_master where type='table'")}
    if "user_portfolios" not in tables:  # pragma: no cover
        pytest.skip("user_portfolios not created by the migration chain")
    _q(dbp, "PRAGMA foreign_keys=OFF")
    legacy = json.dumps(_LEGACY_HOLDINGS)
    for pid, tv, active in (("L1", 5000.0, 1), ("L2", None, 0), ("L3", 0.0, 1)):
        _q(dbp, "insert into user_portfolios (portfolio_id, key_id, name, holdings, total_value_eur, is_active) "
                "values (?, 'k1', 'n', ?, ?, ?)", (pid, legacy, tv, active))
    legacy_before = _q(dbp, "select portfolio_id, key_id, name, holdings, total_value_eur, is_active "
                            "from user_portfolios order by portfolio_id")

    _alembic(dbp, "upgrade", _HEAD)
    schema_1 = _q(dbp, "PRAGMA table_info(user_portfolios)")
    assert _q(dbp, "select portfolio_id, currency, location, total_value from user_portfolios order by portfolio_id") == \
        [("L1", "EUR", None, 5000.0), ("L2", "EUR", None, None), ("L3", "EUR", None, 0.0)]
    # a P2 row written after the upgrade
    p2 = json.dumps([{"instrument_id": "NIFTY", "allocation_pct": 100, "shares": 40, "cash": 99.0, "cash_eur": None}])
    _q(dbp, "insert into user_portfolios (portfolio_id, key_id, name, holdings, total_value_eur, currency, location, "
            "total_value, is_active) values ('P2', 'k1', 'IN', ?, 10989.01, 'INR', 'india', 1000000.0, 1)", (p2,))
    all_before = _q(dbp, "select portfolio_id, key_id, name, holdings, total_value_eur, is_active "
                         "from user_portfolios order by portfolio_id")

    _alembic(dbp, "downgrade", _PRIOR)
    assert not ({"currency", "location", "total_value"} & {r[1] for r in _q(dbp, "PRAGMA table_info(user_portfolios)")})
    # every row (legacy and P2) keeps its pre-P2 columns; only the three P2 columns are dropped
    assert _q(dbp, "select portfolio_id, key_id, name, holdings, total_value_eur, is_active "
                   "from user_portfolios order by portfolio_id") == all_before

    _alembic(dbp, "upgrade", _HEAD)
    assert _q(dbp, "PRAGMA table_info(user_portfolios)") == schema_1
    assert _q(dbp, "select portfolio_id, key_id, name, holdings, total_value_eur, is_active "
                   "from user_portfolios where portfolio_id like 'L%' order by portfolio_id") == legacy_before
    assert _q(dbp, "select version_num from alembic_version") == [(_HEAD,)]
    # documented loss: after a downgrade the P2 row's location/currency are gone; re-upgrade treats it
    # as legacy EUR with total_value = its EUR value (consistent, not an INR amount labelled EUR)
    assert _q(dbp, "select currency, location, total_value from user_portfolios where portfolio_id='P2'") == \
        [("EUR", None, 10989.01)]


# ── 8. design-contract check ───────────────────────────────────────────────────

def test_contract_user_portfolios_columns():
    cols = {c.name: c for c in UserPortfolioModel.__table__.columns}
    assert set(cols) == {"portfolio_id", "key_id", "name", "holdings", "total_value_eur", "currency",
                         "location", "total_value", "created_at", "updated_at", "is_active"}
    assert cols["currency"].nullable is False and cols["currency"].server_default.arg == "EUR"
    assert cols["location"].nullable is True and cols["total_value"].nullable is True
    assert cols["total_value_eur"].nullable is True          # deprecated, kept one release


def test_contract_api_fields_and_routes():
    assert set(UserPortfolioCreate.model_fields) == {"name", "holdings", "location", "total_value", "total_value_eur"}
    assert {"currency", "location", "total_value", "total_value_eur"} <= set(UserPortfolioOut.model_fields)
    from rita.schemas.user_portfolio import HoldingItem
    assert {"cash", "cash_eur", "shares"} <= set(HoldingItem.model_fields)

    spec = app.openapi()
    paths = spec["paths"]
    for p in ("/api/v1/user-portfolio/", "/api/v1/experience/user-portfolio"):
        params = {x["name"]: x for x in paths[p]["get"].get("parameters", [])}
        assert "location" in params and not params["location"].get("required", False), p
    assert "post" in paths["/api/v1/user-portfolio/"]
    fx = {x["name"]: x for x in paths["/api/v1/experience/rita/fx"]["get"]["parameters"]}
    assert set(fx) == {"base", "quote"} and fx["quote"]["required"] is True
    assert fx["base"]["schema"].get("default") == "EUR"
    assert "/api/v1/workflow/rita/fx" not in paths and "post" not in paths["/api/v1/experience/rita/fx"]


def test_contract_fx_route_shape_and_404(client, db):
    r = client.get("/api/v1/experience/rita/fx?base=EUR&quote=INR")
    assert r.status_code == 200
    assert r.json() == {"base": "EUR", "quote": "INR", "rate": EURINR, "as_of": "2026-10-17", "source": "market_data_cache"}
    db.query(MarketDataCacheModel).filter(MarketDataCacheModel.underlying == "FX_EURUSD").delete()
    db.commit()
    miss = client.get("/api/v1/experience/rita/fx?base=INR&quote=USD")
    # the app-wide error handler adds ``trace_id`` to every error body; ``detail`` is the contract
    assert miss.status_code == 404 and miss.json()["detail"] == "no fx rate"
    assert set(miss.json()) <= {"detail", "trace_id"}


def test_contract_mcp_fx_rate_schema_and_catalogue():
    spec = mt.REGISTRY["market.fx_rate"]
    assert spec.auth == frozenset({"none"}) and spec.stdio is True
    inp = spec.input_model.model_json_schema()
    assert set(inp["properties"]) == {"base", "quote", "as_of"} and inp["required"] == ["quote"]
    assert inp["properties"]["base"]["enum"] == ["EUR", "INR", "USD"] and inp["properties"]["base"]["default"] == "EUR"
    assert inp.get("additionalProperties") is False
    out = spec.output_json_schema()
    assert set(out["properties"]) == {"base", "quote", "rate", "as_of", "source"}
    assert set(out["required"]) == {"base", "quote", "rate", "as_of", "source"}

    gh = mt.REGISTRY["portfolio.get_holdings"]
    assert set(gh.input_model.model_json_schema()["properties"]) == {"location"}
    assert {"currency", "location", "total_value"} <= set(gh.output_json_schema()["properties"])

    assert set(mt.REGISTRY) == {
        "whatineed.get_plan", "portfolio.get_holdings", "portfolio.optimal_allocation", "fno.position_value",
        "fno.get_hedge_plan", "market.overview", "market.ask", "market.fx_rate", "market.monitor",
        "ask_rita", "rita_market_overview", "rita_monitor",
        # F44 P3
        "whatineed.get_goal", "portfolio.select_for_goal", "portfolio.required_return",
        "portfolio.model_runs",
        # F44 P4 (Jarvis)
        "journey.get_current", "journey.save", "portfolio.pnl", "portfolio.sleeve_trace",
        "fno.sigma_levels", "market.asta_trace",
    }
    assert mt.tools_registered() == 22   # F44 P4: +6 Jarvis tools
    health = TestClient(app).get("/health").json()
    assert health["mcp"]["tools_registered"] == 22
