"""F44 P2 — multi-currency portfolios: location rules, currency derived server-side, D1 (one
active portfolio per user + location), legacy fallbacks, readers, MCP ``portfolio.get_holdings``.

DoD items covered here:
- save rejects out-of-location instruments (422); currency always from the location
- legacy rows read as EUR (``total_value ?? total_value_eur``, ``cash ?? cash_eur``)
- analytics / portfolio-hedge / hedge-history read ``total_value`` + ``currency`` (EUR fallback)
- MCP ``portfolio.get_holdings`` returns the P2 fields and takes ``location``

All data lives in in-memory / temp SQLite DBs — never the dev ``rita_output/rita.db``; the app is
called without its lifespan.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone

import jsonschema
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import rita.interfaces.mcp_tools as mt
from rita.auth import get_current_user, get_optional_user
from rita.database import Base, get_db
from rita.interfaces.mcp_client import McpCallError, identity_for, memory_client
from rita.interfaces.tools import set_session_factory
from rita.main import app
from rita.models.instrument import InstrumentModel
from rita.models.market_data import MarketDataCacheModel
from rita.models.user import UserModel
from rita.models.user_portfolio import UserPortfolioModel
from rita.schemas.user_portfolio import HoldingItem, UserPortfolioCreate
from rita.services.user_portfolio_service import (
    UserPortfolioService,
    holding_cash,
    location_for_country,
    portfolio_currency,
    portfolio_total,
)

NOW = datetime(2026, 10, 20, 12, 0, 0)
INSTRUMENTS = [  # (id, country, currency)
    ("NIFTY", "IN", None), ("RELIANCE", "IN", None), ("NVIDIA", "US", None),
    ("ASML", "NL", None), ("ATO", "FR", None), ("MM", "IN", "INR"), ("ODD", "ZZ", "USD"),
]


def _seed(db, *, fx: bool = True) -> None:
    for uid in ("alice", "bob"):
        db.add(UserModel(id=uid))
    for iid, cc, ccy in INSTRUMENTS:
        db.add(InstrumentModel(instrument_id=iid, name=iid, exchange="X", country_code=cc, currency=ccy,
                               is_available=True, created_at=NOW))
    if fx:
        for und, close in (("FX_EURINR", 91.0), ("FX_EURUSD", 1.10)):
            db.add(MarketDataCacheModel(cache_id=str(uuid.uuid4()), date=date(2026, 10, 17), underlying=und,
                                        open=close, high=close, low=close, close=close, recorded_at=NOW))
    db.commit()


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    _seed(session)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(db):
    state = {"user": UserModel(id="alice")}

    def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    app.dependency_overrides[get_optional_user] = lambda: state["user"]
    try:
        c = TestClient(app)  # no lifespan
        c.as_user = lambda uid: state.__setitem__("user", UserModel(id=uid))
        yield c
    finally:
        for dep in (get_db, get_current_user, get_optional_user):
            app.dependency_overrides.pop(dep, None)


def _india_body(**kw):
    body = {"name": "India", "location": "india", "total_value": 1_000_000,
            "holdings": [{"instrument_id": "NIFTY", "allocation_pct": 50, "shares": 2, "cash": 1500.0},
                         {"instrument_id": "RELIANCE", "allocation_pct": 50, "shares": 300, "cash": 20.0}]}
    body.update(kw)
    return body


# ── save: location rules + currency ────────────────────────────────────────────

def test_save_india_portfolio_currency_from_location(client):
    r = client.post("/api/v1/user-portfolio/", json=_india_body(currency="USD"))  # client currency ignored
    assert r.status_code == 201, r.text
    b = r.json()
    assert (b["location"], b["currency"], b["total_value"]) == ("india", "INR", 1_000_000)
    assert b["total_value_eur"] == pytest.approx(1_000_000 / 91.0)          # deprecated, via cached FX
    assert [h["cash"] for h in b["holdings"]] == [1500.0, 20.0]
    assert all(h["cash_eur"] is None for h in b["holdings"])                 # never mislabel INR as EUR


@pytest.mark.parametrize("location,currency,iid", [("us", "USD", "NVIDIA"), ("europe", "EUR", "ASML")])
def test_save_us_and_europe_currency(client, location, currency, iid):
    r = client.post("/api/v1/user-portfolio/", json={
        "location": location, "total_value": 1000, "holdings": [{"instrument_id": iid, "allocation_pct": 100}]})
    assert r.status_code == 201, r.text
    assert (r.json()["currency"], r.json()["location"]) == (currency, location)


@pytest.mark.parametrize("iid", ["NVIDIA", "ASML", "UNKNOWN"])
def test_save_out_of_location_instrument_is_422(client, iid):
    body = _india_body(holdings=[{"instrument_id": "NIFTY", "allocation_pct": 50},
                                 {"instrument_id": iid, "allocation_pct": 50}])
    r = client.post("/api/v1/user-portfolio/", json=body)
    assert r.status_code == 422
    assert r.json()["detail"] == f"instrument {iid} is not in location india"


def test_unknown_location_is_422(client):
    r = client.post("/api/v1/user-portfolio/", json=_india_body(location="mars"))
    assert r.status_code == 422


def test_instrument_location_from_country_then_currency(db):
    svc = UserPortfolioService(db)
    assert [svc.instrument_location(i) for i in ("nifty", "NVIDIA", "ATO", "MM", "ODD", "NOPE")] == [
        "india", "us", "europe", "india", "us", None]
    assert location_for_country("United States") == "us" and location_for_country("Netherlands") == "europe"


def test_legacy_save_without_location_is_eur(client):
    """Portfolio Builder (D2) saves with no location → legacy EUR portfolio."""
    r = client.post("/api/v1/user-portfolio/", json={
        "holdings": [{"instrument_id": "NIFTY", "allocation_pct": 60, "shares": 1, "cash_eur": 12.5},
                     {"instrument_id": "NVIDIA", "allocation_pct": 40, "shares": 2, "cash_eur": 3.0}],
        "total_value_eur": 50000})
    assert r.status_code == 201, r.text
    b = r.json()
    assert (b["currency"], b["location"], b["total_value"], b["total_value_eur"]) == ("EUR", None, 50000, 50000)
    assert [(h["cash"], h["cash_eur"]) for h in b["holdings"]] == [(12.5, 12.5), (3.0, 3.0)]


def test_save_without_fx_rate_leaves_eur_total_none(client, db):
    db.query(MarketDataCacheModel).delete()
    db.commit()
    b = client.post("/api/v1/user-portfolio/", json=_india_body()).json()
    assert b["total_value"] == 1_000_000 and b["total_value_eur"] is None   # no static fallback


def test_location_portfolio_from_legacy_eur_total_converts(client):
    b = client.post("/api/v1/user-portfolio/", json=_india_body(total_value=None, total_value_eur=10_000)).json()
    assert b["total_value"] == pytest.approx(910_000)
    assert b["total_value_eur"] == pytest.approx(10_000)


# ── D1: one active portfolio per (user, location) ──────────────────────────────

def test_one_active_portfolio_per_user_and_location(client, db):
    client.post("/api/v1/user-portfolio/", json={"holdings": [{"instrument_id": "ASML", "allocation_pct": 100}],
                                                 "total_value_eur": 5000})
    client.post("/api/v1/user-portfolio/", json=_india_body())
    client.post("/api/v1/user-portfolio/", json=_india_body(total_value=2_000_000))
    rows = db.query(UserPortfolioModel).all()
    active = {(r.location, r.total_value) for r in rows if r.is_active}
    assert active == {(None, 5000.0), ("india", 2_000_000.0)}
    assert len(rows) == 3

    india = client.get("/api/v1/experience/user-portfolio?location=india").json()
    assert (india["currency"], india["total_value"]) == ("INR", 2_000_000)
    assert client.get("/api/v1/user-portfolio/?location=india").json()["portfolio_id"] == india["portfolio_id"]
    assert client.get("/api/v1/experience/user-portfolio?location=us").status_code == 404
    assert client.get("/api/v1/experience/user-portfolio?location=mars").status_code == 422


def test_get_without_location_returns_most_recent_active(client, db):
    client.post("/api/v1/user-portfolio/", json=_india_body())
    client.post("/api/v1/user-portfolio/", json={"holdings": [{"instrument_id": "ASML", "allocation_pct": 100}],
                                                 "total_value_eur": 5000})
    # make the ordering explicit (func.now() has 1 s resolution in SQLite)
    for r in db.query(UserPortfolioModel).all():
        r.updated_at = NOW + (timedelta(hours=1) if r.location is None else timedelta(0))
    db.commit()
    assert client.get("/api/v1/experience/user-portfolio").json()["location"] is None
    assert client.get("/api/v1/user-portfolio/").json()["location"] is None


def test_users_do_not_share_portfolios(client):
    client.post("/api/v1/user-portfolio/", json=_india_body())
    client.as_user("bob")
    assert client.get("/api/v1/experience/user-portfolio?location=india").status_code == 404


# ── reader helpers ─────────────────────────────────────────────────────────────

class _Row:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_reader_helpers_fallbacks():
    from unittest.mock import MagicMock

    legacy = _Row(currency=None, total_value=None, total_value_eur=500.0, location=None)
    assert (portfolio_currency(legacy), portfolio_total(legacy)) == ("EUR", 500.0)
    inr = _Row(currency="INR", total_value=None, total_value_eur=500.0, location="india")
    assert portfolio_total(inr) is None                     # an EUR amount is never an INR total
    assert portfolio_total(_Row(currency="INR", total_value=9.0, total_value_eur=1.0)) == 9.0
    mock = MagicMock()
    mock.total_value_eur = 100.0                            # legacy test doubles keep working
    assert (portfolio_currency(mock), portfolio_total(mock)) == ("EUR", 100.0)
    assert holding_cash({"cash": 2.0, "cash_eur": 9.0}) == 2.0      # cash wins
    assert holding_cash({"cash_eur": 9.0}) == 9.0
    assert holding_cash(HoldingItem(instrument_id="X", allocation_pct=1, cash=None, cash_eur=None)) is None


def test_create_schema_has_no_currency_field():
    assert "currency" not in UserPortfolioCreate.model_fields


# ── readers: analytics, portfolio-hedge, hedge-plan history ────────────────────

def test_analytics_reads_inr_total_and_currency(client):
    client.post("/api/v1/user-portfolio/", json=_india_body())
    r = client.get("/api/v1/experience/fno/portfolio-analytics?mode=real")
    assert r.status_code == 200, r.text
    meta = r.json()["portfolio_meta"]
    assert (meta["currency"], meta["total_value"]) == ("INR", 1_000_000)
    assert meta["total_value_eur"] == pytest.approx(1_000_000 / 91.0)
    positions = {p["und"]: p["position_eur"] for p in r.json()["positions"]}
    assert positions == {"NIFTY": 500_000.0, "RELIANCE": 500_000.0}   # amounts in INR


def test_analytics_legacy_row_meta(client):
    client.post("/api/v1/user-portfolio/", json={"holdings": [{"instrument_id": "ASML", "allocation_pct": 100}],
                                                 "total_value_eur": 5000})
    meta = client.get("/api/v1/experience/fno/portfolio-analytics?mode=real").json()["portfolio_meta"]
    assert (meta["currency"], meta["total_value"], meta["total_value_eur"]) == ("EUR", 5000, 5000)


def test_analytics_mock_carries_currency(client):
    meta = client.get("/api/v1/experience/fno/portfolio-analytics?mode=mock").json()["portfolio_meta"]
    assert meta["currency"] == "EUR" and meta["total_value"] == meta["total_value_eur"]


def test_portfolio_hedge_uses_total_value_and_currency(client, db):
    client.post("/api/v1/user-portfolio/", json=_india_body())
    start = date(2026, 1, 1)
    for und, base in (("NIFTY", 24000.0), ("RELIANCE", 2500.0)):
        for i in range(120):
            c = base * (1 + 0.01 * ((i % 5) - 2))
            db.add(MarketDataCacheModel(cache_id=str(uuid.uuid4()), date=start + timedelta(days=i), underlying=und,
                                        open=c, high=c, low=c, close=c, recorded_at=NOW))
    db.commit()
    from unittest.mock import patch
    mod = "rita.api.experience.portfolio_hedge"
    with patch(f"{mod}.fetch_put_premium", return_value=None), patch(f"{mod}.put_premium_from_csv", return_value=None):
        r = client.get("/api/v1/experience/fno/portfolio-hedge?coverage=50")
        r2 = client.get("/api/v1/experience/fno/portfolio-hedge?coverage=50&total_value=2000000&total_value_eur=1")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["currency"] == "INR"
    assert {h["instrument_id"]: h["position_eur"] for h in b["holdings"]} == {"NIFTY": 500_000.0, "RELIANCE": 500_000.0}
    assert {h["position_eur"] for h in r2.json()["holdings"]} == {1_000_000.0}   # total_value wins


def test_hedge_history_portfolio_block_has_currency(db):
    from rita.services.hedge_plan_service import HedgePlanService

    UserPortfolioService(db).save("alice", [HoldingItem(instrument_id="NIFTY", allocation_pct=100, shares=1, cash=10.0)],
                                  location="india", total_value=100_000)
    pf = db.query(UserPortfolioModel).filter_by(is_active=True).one()
    block = HedgePlanService._portfolio_block(pf, 10.0, 1)
    assert block == {"total_value_eur": pytest.approx(100_000 / 91.0), "cash_eur": None, "n_holdings": 1,
                     "currency": "INR", "total_value": 100_000.0, "cash": 10.0}
    assert HedgePlanService._portfolio_block(None, 0.0, 0)["currency"] is None


def test_hedge_history_csv_has_portfolio_currency_columns():
    from rita.services.hedge_history_export import HEADER_COLUMNS, flatten_rows

    assert HEADER_COLUMNS[12:18] == ["total_value_eur", "cash_eur", "n_holdings",
                                     "portfolio_currency", "total_value", "cash"]
    row = _Row(history_id="h", saved_at=None, user_id="u", key_id="k", trigger="t", source="s", last_step=None,
               scenario_tab="pp", coverage=50, duration="1y", schema_version=1, app_version="x",
               portfolio={"currency": "INR", "total_value": 5.0, "cash": 1.0}, instruments=[{"instrument_id": "NIFTY", "currency": "INR"}])
    out = flatten_rows([row])[0]
    assert (out["portfolio_currency"], out["total_value"], out["cash"], out["currency"]) == ("INR", 5.0, 1.0, "INR")


# ── MCP portfolio.get_holdings ─────────────────────────────────────────────────

@pytest.fixture
def tool_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'tools.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine)
    s = maker()
    _seed(s)
    UserPortfolioService(s).save("alice", [HoldingItem(instrument_id="NIFTY", allocation_pct=100, shares=40, cash=99.0)],
                                 name="IN", location="india", total_value=1_000_000)
    UserPortfolioService(s).save("alice", [HoldingItem(instrument_id="ASML", allocation_pct=100, shares=1, cash_eur=4.0)],
                                 name="Legacy", total_value_eur=10_000)
    for r in s.query(UserPortfolioModel).all():  # legacy saved last
        r.updated_at = NOW + (timedelta(hours=1) if r.location is None else timedelta(0))
    s.commit()
    s.close()
    set_session_factory(maker)
    try:
        yield maker
    finally:
        set_session_factory(None)
        engine.dispose()


async def _call(user, name, args=None):
    async with memory_client(identity_for(user, "jarvis")) as c:
        return await c.call(name, args or {})


def test_mcp_get_holdings_p2_fields(tool_db):
    alice = UserModel(id="alice")
    india = asyncio.run(_call(alice, "portfolio.get_holdings", {"location": "india"})).structured
    jsonschema.validate(india, mt.REGISTRY["portfolio.get_holdings"].output_json_schema())
    assert (india["name"], india["currency"], india["location"], india["total_value"]) == ("IN", "INR", "india", 1_000_000)
    assert [(h["shares"], h["cash"]) for h in india["holdings"]] == [(40, 99.0)]

    latest = asyncio.run(_call(alice, "portfolio.get_holdings")).structured
    assert (latest["name"], latest["currency"], latest["location"], latest["total_value"]) == ("Legacy", "EUR", None, 10_000)
    assert latest["holdings"][0]["cash"] == 4.0                 # legacy cash_eur → cash

    with pytest.raises(McpCallError) as e:
        asyncio.run(_call(alice, "portfolio.get_holdings", {"location": "us"}))
    assert e.value.code == "not_found"
    with pytest.raises(McpCallError) as e:
        asyncio.run(_call(alice, "portfolio.get_holdings", {"location": "mars"}))
    assert e.value.code == "invalid_input"


def test_mcp_get_holdings_input_has_location_no_user_id():
    schema = mt.REGISTRY["portfolio.get_holdings"].input_model.model_json_schema()
    assert set(schema.get("properties", {})) == {"location"}
