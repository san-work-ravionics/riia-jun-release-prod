"""F44 P2 — FX: rates only from ``market_data_cache`` (``services/fx_service``), the Experience
route ``GET /api/v1/experience/rita/fx``, MCP ``market.fx_rate``, the skill-only
``data_refresh.refresh_fx`` and the static FX table removed from ``core/portfolio_engine``.

DoD items covered here:
- FX: no network call from request code (test); ``/fx`` returns the cached rate with ``as_of``
- missing rate → 404 ``{"detail": "no fx rate"}``; never a static fallback
- ``refresh_fx`` is not called by ``refresh_all()`` (which a request can reach)
- ``core/portfolio_engine`` takes rates in (pure); no static FX table left

In-memory / temp SQLite only — never the dev ``rita_output/rita.db``.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import socket
import uuid
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import rita.interfaces.mcp_tools as mt
from rita.database import Base, get_db
from rita.interfaces.mcp_client import McpCallError, identity_for, memory_client
from rita.interfaces.tools import set_session_factory
from rita.main import app
from rita.models.market_data import MarketDataCacheModel
from rita.services.fx_service import FX_YF_TICKERS, FxService, fx_underlying

_SRC = Path(__file__).resolve().parents[2] / "src" / "rita"
NOW = datetime(2026, 10, 20, 12, 0, 0)


def _add(db, und: str, d: date, close: float) -> None:
    db.add(MarketDataCacheModel(cache_id=str(uuid.uuid4()), date=d, underlying=und,
                                open=close, high=close, low=close, close=close, recorded_at=NOW))


def _seed_fx(db) -> None:
    _add(db, "FX_EURINR", date(2026, 10, 15), 90.0)
    _add(db, "FX_EURINR", date(2026, 10, 17), 91.0)
    _add(db, "FX_EURUSD", date(2026, 10, 16), 1.10)
    db.commit()


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


@pytest.fixture
def client(db):
    def _db():
        yield db
    app.dependency_overrides[get_db] = _db
    try:
        yield TestClient(app)  # no lifespan
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def no_network(monkeypatch):
    """Any socket connect / yfinance download fails the test."""
    def _boom(*a, **k):
        raise AssertionError("network call from request code")
    monkeypatch.setattr(socket.socket, "connect", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)
    import yfinance
    monkeypatch.setattr(yfinance, "download", _boom, raising=False)  # yfinance may be a spec'd stub (test_data_refresh)


# ── service ───────────────────────────────────────────────────────────────────

def test_rate_latest_inverse_cross_and_identity(db):
    _seed_fx(db)
    fx = FxService(db)
    r = fx.rate("EUR", "INR")
    assert (r.rate, r.as_of, r.source) == (91.0, date(2026, 10, 17), "market_data_cache")
    assert fx.rate("INR", "EUR").rate == pytest.approx(1 / 91.0)
    cross = fx.rate("USD", "INR")
    assert cross.rate == pytest.approx(91.0 / 1.10)
    assert cross.as_of == date(2026, 10, 16)              # the older leg
    assert fx.rate("eur", "eur").rate == 1.0
    assert fx.rate("EUR", "INR", as_of=date(2026, 10, 16)).rate == 90.0
    assert fx.convert(910.0, "INR", "EUR") == pytest.approx(10.0)
    assert fx.eur_per_unit() == pytest.approx({"EUR": 1.0, "INR": 1 / 91.0, "USD": 1 / 1.10})


def test_missing_rate_is_none_never_static(db):
    fx = FxService(db)
    assert fx.rate("EUR", "INR") is None
    assert fx.convert(100.0, "EUR", "USD") is None
    assert fx.eur_per_unit() == {"EUR": 1.0}
    with pytest.raises(ValueError):
        fx.rate("EUR", "GBP")


def test_fx_service_has_no_network_imports():
    tree = ast.parse((_SRC / "services" / "fx_service.py").read_text())
    names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
             for a in (n.names if isinstance(n, ast.Import) else [ast.alias(n.module or "")])}
    assert not names & {"yfinance", "requests", "httpx", "urllib", "aiohttp", "socket"}


# ── route ─────────────────────────────────────────────────────────────────────

def test_fx_route_returns_cached_rate_without_network(client, db, no_network):
    _seed_fx(db)
    r = client.get("/api/v1/experience/rita/fx?base=EUR&quote=INR")
    assert r.status_code == 200, r.text
    assert r.json() == {"base": "EUR", "quote": "INR", "rate": 91.0, "as_of": "2026-10-17", "source": "market_data_cache"}
    assert client.get("/api/v1/experience/rita/fx?quote=USD").json()["base"] == "EUR"   # default base


def test_fx_route_missing_rate_404(client, no_network):
    r = client.get("/api/v1/experience/rita/fx?base=EUR&quote=INR")
    assert r.status_code == 404
    assert r.json()["detail"] == "no fx rate"


def test_fx_route_rejects_unknown_currency(client):
    assert client.get("/api/v1/experience/rita/fx?base=EUR&quote=GBP").status_code == 422


def test_fx_route_is_experience_tier_read_only():
    src = (_SRC / "api" / "experience" / "fx.py").read_text()
    assert "commit" not in src and "repositories" not in src
    assert 'prefix="/api/v1/experience"' in src and '"/rita/fx"' in src


def test_user_portfolio_save_makes_no_network_call(db, no_network):
    from rita.models.instrument import InstrumentModel
    from rita.models.user import UserModel
    from rita.schemas.user_portfolio import HoldingItem
    from rita.services.user_portfolio_service import UserPortfolioService

    _seed_fx(db)
    db.add(UserModel(id="u"))
    db.add(InstrumentModel(instrument_id="NIFTY", name="n", exchange="NSE", country_code="IN",
                           is_available=True, created_at=NOW))
    db.commit()
    out = UserPortfolioService(db).save("u", [HoldingItem(instrument_id="NIFTY", allocation_pct=100)],
                                        location="india", total_value=91_000)
    assert out.total_value_eur == pytest.approx(1000.0)


# ── refresh (skill run only) ──────────────────────────────────────────────────

def _fake_download(ticker, start, **kw):
    idx = pd.to_datetime(["2026-10-16", "2026-10-17"])
    close = {"EURINR=X": [90.5, 91.0], "EURUSD=X": [1.09, 1.10]}[ticker]
    cols = pd.MultiIndex.from_tuples([("Close", ticker), ("Open", ticker), ("High", ticker), ("Low", ticker)])
    return pd.DataFrame([[c, c, c, c] for c in close], index=idx, columns=cols)


def test_refresh_fx_inserts_rows_and_is_incremental(db):
    from rita.services.data_refresh import refresh_fx

    res = refresh_fx(db, downloader=_fake_download)
    assert [(r["pair"], r["status"], r["rows_inserted"]) for r in res] == [
        ("FX_EURINR", "ok", 2), ("FX_EURUSD", "ok", 2)]
    assert FxService(db).rate("EUR", "INR").rate == 91.0
    again = refresh_fx(db, downloader=_fake_download)        # same rows → nothing new
    assert all(r["rows_inserted"] == 0 for r in again)
    assert db.query(MarketDataCacheModel).count() == 4


def test_refresh_fx_records_errors(db):
    from rita.services.data_refresh import refresh_fx

    def bad(*a, **k):
        raise RuntimeError("offline")
    res = refresh_fx(db, downloader=bad)
    assert {r["status"] for r in res} == {"error"} and all("offline" in r["error"] for r in res)


def test_refresh_all_does_not_fetch_fx(db):
    """refresh_all() is reachable from a request (instrument_onboard) → it must not call refresh_fx."""
    from rita.services import data_refresh

    assert "refresh_fx" not in inspect.getsource(data_refresh.refresh_all)
    with patch.object(data_refresh, "refresh_fx") as fx, \
         patch.object(data_refresh, "YF_TICKER_MAP", {}):
        data_refresh.refresh_all(db)
    fx.assert_not_called()
    assert set(FX_YF_TICKERS) == {fx_underlying("INR"), fx_underlying("USD")}


def _code_names(path: Path) -> set[str]:
    """Identifiers used in code (imports, names, attributes) — docstrings/comments excluded."""
    out: set[str] = set()
    for n in ast.walk(ast.parse(path.read_text())):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
        elif isinstance(n, ast.alias):
            out.add(n.name.split(".")[-1])
    return out


def test_no_request_code_calls_refresh_fx():
    for root in ("api", "interfaces"):
        for path in (_SRC / root).rglob("*.py"):
            assert "refresh_fx" not in _code_names(path), path


# ── core/portfolio_engine: rates passed in ────────────────────────────────────

def test_portfolio_engine_has_no_static_fx_table():
    from rita.core import portfolio_engine

    assert not hasattr(portfolio_engine, "FX_EUR_PER_UNIT")
    src = (_SRC / "core" / "portfolio_engine.py").read_text()
    assert "1 / 91" not in src and "1 / 1.09" not in src
    assert "fx_eur_per_unit" in inspect.signature(portfolio_engine.portfolio_backtest).parameters


def _synthetic_df(price: float, n: int = 40) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.DataFrame({"Close": [price] * n}, index=idx)


@pytest.mark.parametrize("rates,expected_frac,missing", [
    ({"INR": 1 / 91.0}, 0.0, []),     # €250 into a ₹30,000 (≈ €330) share → 0 whole shares
    ({"INR": 1 / 200.0}, 0.6, []),    # ≈ €150/share → 1 share = €150 of €250
    ({}, 1.0, ["INR"]),               # no rate → constraint skipped, reported
])
def test_portfolio_backtest_uses_passed_rates(rates, expected_frac, missing):
    from rita.core import portfolio_engine as pe

    with patch.object(pe, "_load_with_indicators", return_value=_synthetic_df(30000.0)), \
         patch.object(pe, "_find_best_model", return_value=None):
        out = pe.portfolio_backtest(["NIFTY"], {"NIFTY": 250.0}, "2026-01-01", "2026-12-31",
                                    fx_eur_per_unit=rates)
    assert out["instruments"][0]["invested_frac"] == pytest.approx(expected_frac, abs=1e-4)
    assert out["fx_unavailable"] == missing


def test_portfolio_backtest_route_passes_cached_rates(client, db):
    _seed_fx(db)
    with patch("rita.core.portfolio_engine.portfolio_backtest", return_value={"ok": True}) as bt:
        r = client.post("/api/v1/portfolio/backtest", json={
            "instruments": ["NIFTY"], "allocations_eur": {"NIFTY": 1000},
            "start_date": "2026-01-01", "end_date": "2026-06-30"})
    assert r.status_code == 200, r.text
    assert bt.call_args.kwargs["fx_eur_per_unit"] == pytest.approx({"EUR": 1.0, "INR": 1 / 91.0, "USD": 1 / 1.10})


# ── MCP market.fx_rate ────────────────────────────────────────────────────────

@pytest.fixture
def tool_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'fx.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine)
    s = maker()
    _seed_fx(s)
    s.close()
    set_session_factory(maker)
    try:
        yield maker
    finally:
        set_session_factory(None)
        engine.dispose()


async def _call(name, args):
    async with memory_client(identity_for(None, "external")) as c:
        return await c.call(name, args)


def test_mcp_fx_rate(tool_db, no_network):
    import jsonschema

    r = asyncio.run(_call("market.fx_rate", {"base": "EUR", "quote": "INR"}))
    jsonschema.validate(r.structured, mt.REGISTRY["market.fx_rate"].output_json_schema())
    assert r.structured == {"base": "EUR", "quote": "INR", "rate": 91.0, "as_of": "2026-10-17", "source": "market_data_cache"}
    old = asyncio.run(_call("market.fx_rate", {"quote": "INR", "as_of": "2026-10-16"})).structured
    assert old["rate"] == 90.0 and old["as_of"] == "2026-10-15"
    with pytest.raises(McpCallError) as e:
        asyncio.run(_call("market.fx_rate", {"base": "EUR", "quote": "GBP"}))
    assert e.value.code == "invalid_input"


def test_mcp_fx_rate_missing_is_not_found(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    set_session_factory(sessionmaker(bind=engine))
    try:
        with pytest.raises(McpCallError) as e:
            asyncio.run(_call("market.fx_rate", {"quote": "USD"}))
        assert e.value.code == "not_found"
    finally:
        set_session_factory(None)
        engine.dispose()


def test_mcp_fx_rate_catalogue_entry():
    spec = mt.REGISTRY["market.fx_rate"]
    assert spec.auth == frozenset({"none"}) and spec.stdio is True
    props = set(spec.input_model.model_json_schema()["properties"])
    assert props == {"base", "quote", "as_of"}
