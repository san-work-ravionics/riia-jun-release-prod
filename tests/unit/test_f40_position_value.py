"""F40 Phase 3 — position-value endpoint (GET /api/v1/experience/fno/position-value).

Golden vectors (100 shares, ann_vol 24% -> monthly sigma 0.069282; close 50 -> V 5000,
bands 5346.41 / 4653.59), status matrix with exact message strings, route via the real
in-memory DB (only auth overridden), read-only guarantee, schema contract.

σ honesty: with constant shares the value σ equals the price σ (bands = price σ scaled by
shares); the σ window is fixed at the last 253 closes regardless of ``months``; the
``ann_vol_pct`` override takes precedence (vol_source == "override").
"""
from __future__ import annotations

import inspect
import math
from datetime import date, datetime, timedelta

import pytest

from rita.api.experience import fno_position_value as route_mod
from rita.auth import get_current_user
from rita.main import app
from rita.models.market_data import MarketDataCacheModel
from rita.models.user import UserModel
from rita.models.user_portfolio import UserPortfolioModel
from rita.models.user_portfolio_key import UserPortfolioKeyModel
from rita.repositories.market_data import MarketDataCacheRepository
from rita.schemas import position_value as schema_mod
from rita.schemas.position_value import PositionValueItem, PositionValueResponse
from rita.services import position_value_service as svc
from rita.services.position_value_service import (
    ann_vol_pct_from_closes,
    build_bands,
    monthly_candles,
    monthly_sigma,
    value_series,
    window_start,
)

URL = "/api/v1/experience/fno/position-value"
END = date(2026, 9, 30)


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _as(user_id="u1"):
    app.dependency_overrides[get_current_user] = lambda: UserModel(id=user_id, can_access_ops=False)


def _seed_closes(db, und, n_days=420, end=END, last_close=50.0, wiggle=True):
    """n_days consecutive calendar days ending at ``end``; last close == last_close."""
    for i in range(n_days):
        d = end - timedelta(days=n_days - 1 - i)
        close = last_close + (0.0 if i == n_days - 1 else (1.0 if (wiggle and i % 2) else -1.0) + (i % 7) * 0.1)
        db.add(MarketDataCacheModel(
            cache_id=f"{und}-{i}", date=d, underlying=und, open=close, high=close, low=close,
            close=close, recorded_at=datetime(2026, 9, 30),
        ))
    db.commit()


def _seed_portfolio(db, holdings, key_id="k1", user_id="u1"):
    db.add(UserPortfolioKeyModel(key_id=key_id, user_id=user_id))
    db.add(UserPortfolioModel(
        portfolio_id="p-" + key_id, key_id=key_id, name="t", is_active=True,
        total_value_eur=10000.0, holdings=holdings,
    ))
    db.commit()


def _get(client, **params):
    return client.get(URL, params=params)


# ── golden vectors (pure) ───────────────────────────────────────────────────
class TestGolden:
    def test_monthly_sigma_24pct(self):
        assert monthly_sigma(24.0) == pytest.approx(0.069282, abs=1e-6)

    def test_bands_100_shares_close_50(self):
        v = 100 * 50.0
        b = build_bands(v, END, 24.0)
        assert b.anchor_value == 5000.0
        assert b.plus_1sigma_value == pytest.approx(5346.41, abs=0.005)
        assert b.minus_1sigma_value == pytest.approx(4653.59, abs=0.005)
        assert b.plus_1sigma_pct == pytest.approx(6.9282, abs=1e-4)
        assert b.minus_1sigma_pct == pytest.approx(-6.9282, abs=1e-4)
        assert b.anchor_date == "2026-09-30"

    def test_value_sigma_equals_price_sigma(self):
        """Constant shares => value returns == price returns => identical σ."""
        closes = [100 + math.sin(i) * 5 + i * 0.1 for i in range(120)]
        pairs = [(date(2026, 1, 1) + timedelta(days=i), c) for i, c in enumerate(closes)]
        vals = [v for _, v in value_series(pairs, 100)]
        assert ann_vol_pct_from_closes(vals) == pytest.approx(ann_vol_pct_from_closes(closes), abs=1e-3)

    def test_vol_needs_30_closes(self):
        assert ann_vol_pct_from_closes([100.0 + i for i in range(29)]) is None
        assert ann_vol_pct_from_closes([100.0 + (i % 3) for i in range(30)]) is not None

    def test_window_start(self):
        assert window_start(date(2026, 9, 30), 12) == date(2025, 10, 1)
        assert window_start(date(2026, 1, 15), 1) == date(2026, 1, 1)
        assert window_start(date(2026, 2, 10), 3) == date(2025, 12, 1)

    def test_monthly_candles_ohlc(self):
        daily = [(date(2026, 1, 2), 10.0), (date(2026, 1, 3), 14.0), (date(2026, 1, 4), 8.0),
                 (date(2026, 1, 5), 12.0), (date(2026, 2, 1), 13.0)]
        c = monthly_candles(daily)
        assert [x.month for x in c] == ["2026-01", "2026-02"]
        assert (c[0].open, c[0].high, c[0].low, c[0].close) == (10.0, 14.0, 8.0, 12.0)
        assert c[1].open == c[1].close == 13.0


# ── repository ──────────────────────────────────────────────────────────────
class TestFindCloses:
    def test_range_inclusive_oldest_first_upper(self, db_session):
        _seed_closes(db_session, "ASML", n_days=10, end=date(2026, 9, 10))
        rows = MarketDataCacheRepository(db_session).find_closes("asml", date(2026, 9, 3), date(2026, 9, 8))
        assert [d for d, _ in rows] == [date(2026, 9, d) for d in range(3, 9)]
        assert all(isinstance(c, float) for _, c in rows)

    def test_empty(self, db_session):
        assert MarketDataCacheRepository(db_session).find_closes("NOPE", date(2026, 1, 1), END) == []


# ── status matrix + exact messages ──────────────────────────────────────────
class TestStatusMatrix:
    def test_no_key_all_holdings_empty_items(self, client):
        _as("nokey")
        r = _get(client)
        assert r.status_code == 200 and r.json() == {"as_of": None, "items": []}

    def test_no_key_single_is_no_holding(self, client):
        _as("nokey")
        it = _get(client, instrument="asml").json()["items"][0]
        assert it["status"] == "no_holding" and it["instrument_id"] == "ASML"
        assert it["message"] == "No equity holding for ASML (option exposure only). Position value needs shares held."
        assert it["candles"] == [] and it["daily"] == [] and it["bands"] is None and it["last_value"] is None

    def test_option_only_not_held_no_price_fallback(self, client, db_session):
        _seed_portfolio(db_session, [{"instrument_id": "ASML", "allocation_pct": 100.0, "shares": 5}])
        _seed_closes(db_session, "NIFTY")
        _as()
        it = _get(client, instrument="NIFTY").json()["items"][0]
        assert it["status"] == "no_holding" and it["candles"] == []

    def test_cash(self, client, db_session):
        _seed_portfolio(db_session, [{"instrument_id": "CASH", "allocation_pct": 5.0, "shares": 3}])
        _as()
        it = _get(client, instrument="cash").json()["items"][0]
        assert it["status"] == "cash" and it["message"] == "Cash has no price history"

    @pytest.mark.parametrize("shares", [None, 0, -4])
    def test_no_shares(self, client, db_session, shares):
        _seed_portfolio(db_session, [{"instrument_id": "ASML", "allocation_pct": 100.0, "shares": shares}])
        _seed_closes(db_session, "ASML")
        _as()
        it = _get(client, instrument="ASML").json()["items"][0]
        assert it["status"] == "no_shares"
        assert it["message"] == "No share count stored for ASML. Position value needs shares held."
        assert it["candles"] == []

    def test_no_currency_held_unmapped(self, client, db_session):
        _seed_portfolio(db_session, [{"instrument_id": "MYSTERY", "allocation_pct": 100.0, "shares": 5}])
        _seed_closes(db_session, "MYSTERY")
        _as()
        it = _get(client, instrument="MYSTERY").json()["items"][0]
        assert it["status"] == "no_currency" and it["message"] == "Currency not configured for MYSTERY"
        assert it["currency"] is None and it["currency_symbol"] == ""

    def test_unmapped_not_held_is_no_holding(self, client, db_session):
        _seed_portfolio(db_session, [{"instrument_id": "ASML", "allocation_pct": 100.0, "shares": 5}])
        _as()
        assert _get(client, instrument="MYSTERY").json()["items"][0]["status"] == "no_holding"

    def test_no_price_data(self, client, db_session):
        _seed_portfolio(db_session, [{"instrument_id": "ASML", "allocation_pct": 100.0, "shares": 5}])
        _as()
        it = _get(client, instrument="ASML").json()["items"][0]
        assert it["status"] == "no_price_data"
        assert it["message"] == "No price data available for ASML"
        assert it["currency"] == "EUR" and it["shares"] == 5

    def test_insufficient_data_single_month(self, client, db_session):
        _seed_portfolio(db_session, [{"instrument_id": "ASML", "allocation_pct": 100.0, "shares": 5}])
        _seed_closes(db_session, "ASML", n_days=10, end=date(2026, 9, 28))
        _as()
        it = _get(client, instrument="ASML").json()["items"][0]
        assert it["status"] == "insufficient_data"
        assert it["message"] == "Not enough price history for ASML (needs at least 2 months of data)"
        assert it["candles"] == [] and it["daily"] == [] and it["bands"] is None

    def test_per_item_failure_is_no_price_data_batch_stays_200(self, client, db_session, monkeypatch):
        _seed_portfolio(db_session, [
            {"instrument_id": "ASML", "allocation_pct": 50.0, "shares": 5},
            {"instrument_id": "RELIANCE", "allocation_pct": 50.0, "shares": 7},
        ])
        _seed_closes(db_session, "RELIANCE")
        orig = MarketDataCacheRepository.find_latest

        def boom(self, und):
            if und.upper() == "ASML":
                raise RuntimeError("db hiccup")
            return orig(self, und)

        monkeypatch.setattr(MarketDataCacheRepository, "find_latest", boom)
        _as()
        r = _get(client)
        assert r.status_code == 200
        by = {i["instrument_id"]: i for i in r.json()["items"]}
        assert by["ASML"]["status"] == "no_price_data" and by["RELIANCE"]["status"] == "ok"

    def test_duplicate_holding_uses_first(self, client, db_session):
        _seed_portfolio(db_session, [
            {"instrument_id": "ASML", "allocation_pct": 50.0, "shares": 10},
            {"instrument_id": "ASML", "allocation_pct": 50.0, "shares": 99},
        ])
        _seed_closes(db_session, "ASML")
        _as()
        it = _get(client, instrument="ASML").json()["items"][0]
        assert it["status"] == "ok" and it["shares"] == 10


# ── ok path via the route ───────────────────────────────────────────────────
class TestOkPath:
    def _setup(self, db_session, shares=100):
        _seed_portfolio(db_session, [
            {"instrument_id": "ASML", "allocation_pct": 60.0, "shares": shares},
            {"instrument_id": "RELIANCE", "allocation_pct": 40.0, "shares": 7},
        ])
        _seed_closes(db_session, "ASML", last_close=50.0)
        _seed_closes(db_session, "RELIANCE", last_close=2500.0)

    def test_golden_override_24pct(self, client, db_session):
        self._setup(db_session)
        _as()
        it = _get(client, instrument="asml", ann_vol_pct=24).json()["items"][0]
        assert it["status"] == "ok" and it["currency"] == "EUR" and it["currency_symbol"] == "€"
        assert it["shares"] == 100 and it["last_close"] == 50.0 and it["last_value"] == 5000.0
        assert it["vol_source"] == "override" and it["ann_vol_pct"] == 24.0
        assert it["monthly_sigma_pct"] == pytest.approx(6.9282, abs=1e-4)
        b = it["bands"]
        assert b["anchor_value"] == 5000.0 and b["anchor_date"] == "2026-09-30"
        assert b["plus_1sigma_value"] == pytest.approx(5346.41, abs=0.005)
        assert b["minus_1sigma_value"] == pytest.approx(4653.59, abs=0.005)
        assert len(it["candles"]) >= 12 and it["candles"][-1]["close"] == 5000.0
        assert it["daily"][-1] == {"date": "2026-09-30", "value": 5000.0}

    def test_override_takes_precedence_over_computed(self, client, db_session):
        self._setup(db_session)
        _as()
        comp = _get(client, instrument="ASML").json()["items"][0]
        ovr = _get(client, instrument="ASML", ann_vol_pct=10).json()["items"][0]
        assert comp["vol_source"] == "computed" and ovr["vol_source"] == "override"
        assert ovr["ann_vol_pct"] == 10.0 and comp["ann_vol_pct"] != 10.0

    def test_computed_vol_matches_price_sigma_and_ignores_months(self, client, db_session):
        """Value σ == price σ; σ window is the last 253 closes whatever ``months`` is."""
        self._setup(db_session)
        _as()
        repo = MarketDataCacheRepository(db_session)
        price_sigma = ann_vol_pct_from_closes(repo.find_recent_closes("ASML", 253))
        a = _get(client, instrument="ASML", months=3).json()["items"][0]
        b = _get(client, instrument="ASML", months=24).json()["items"][0]
        assert a["ann_vol_pct"] == b["ann_vol_pct"] == price_sigma
        assert a["vol_source"] == "computed"
        assert len(a["candles"]) < len(b["candles"])
        # shares scale amounts only: percentages equal the price-σ percentages
        assert a["bands"]["plus_1sigma_pct"] == pytest.approx(price_sigma / math.sqrt(12), abs=1e-4)

    def test_short_history_hides_bands(self, client, db_session):
        _seed_portfolio(db_session, [{"instrument_id": "ASML", "allocation_pct": 100.0, "shares": 5}])
        # 29 closes across two months -> candles ok, vol unavailable
        _seed_closes(db_session, "ASML", n_days=29, end=date(2026, 9, 10))
        _as()
        it = _get(client, instrument="ASML").json()["items"][0]
        assert it["status"] == "ok" and it["bands"] is None and it["vol_source"] is None
        assert it["ann_vol_pct"] is None and it["monthly_sigma_pct"] is None
        assert len(it["candles"]) == 2

    def test_all_holdings_default_and_as_of(self, client, db_session):
        self._setup(db_session)
        _as()
        r = _get(client).json()
        assert [i["instrument_id"] for i in r["items"]] == ["ASML", "RELIANCE"]
        assert r["as_of"] == "2026-09-30"
        rel = r["items"][1]
        assert rel["currency"] == "INR" and rel["currency_symbol"] == "₹" and rel["last_value"] == 17500.0

    def test_window_anchored_on_latest_row_not_today(self, client, db_session):
        _seed_portfolio(db_session, [{"instrument_id": "ASML", "allocation_pct": 100.0, "shares": 5}])
        _seed_closes(db_session, "ASML", n_days=120, end=date(2024, 3, 31))
        _as()
        it = _get(client, instrument="ASML").json()["items"][0]
        assert it["status"] == "ok" and it["daily"][-1]["date"] == "2024-03-31"

    @pytest.mark.parametrize("q", [{"months": 0}, {"months": 37}, {"ann_vol_pct": 0}, {"ann_vol_pct": -3}])
    def test_query_validation(self, client, q):
        _as()
        assert _get(client, **q).status_code == 422


# ── read-only / tier / schema contract ──────────────────────────────────────
class TestReadOnlyAndContract:
    def test_get_only_and_no_commit_in_code(self):
        methods = {m for r in route_mod.router.routes for m in r.methods}
        assert methods == {"GET"}
        for mod in (route_mod, svc):
            src = inspect.getsource(mod)
            assert ".commit(" not in src and ".add(" not in src and ".rollback(" not in src
        assert ".commit(" not in inspect.getsource(MarketDataCacheRepository.find_closes)

    def test_no_commit_or_pending_writes_at_runtime(self, client, db_session, monkeypatch):
        _seed_portfolio(db_session, [{"instrument_id": "ASML", "allocation_pct": 100.0, "shares": 5}])
        _seed_closes(db_session, "ASML")
        calls = []
        monkeypatch.setattr(db_session, "commit", lambda: calls.append("commit"))
        _as()
        assert _get(client, instrument="ASML").status_code == 200
        assert calls == []
        assert not db_session.new and not db_session.dirty and not db_session.deleted

    def test_requires_auth(self, client):
        assert _get(client).status_code in (401, 403)

    def test_schema_contract_fields_js_reads(self):
        item_fields = set(PositionValueItem.model_fields)
        assert {"instrument_id", "status", "message", "currency", "currency_symbol", "shares", "months",
                "last_close", "last_value", "ann_vol_pct", "vol_source", "monthly_sigma_pct",
                "bands", "candles", "daily"} <= item_fields
        assert set(PositionValueResponse.model_fields) == {"as_of", "items"}
        assert set(schema_mod.PositionValueBands.model_fields) == {
            "anchor_value", "anchor_date", "plus_1sigma_value", "minus_1sigma_value",
            "plus_1sigma_pct", "minus_1sigma_pct"}
        assert set(schema_mod.PositionValueCandle.model_fields) == {"month", "open", "high", "low", "close"}
        assert set(schema_mod.PositionValueDaily.model_fields) == {"date", "value"}

    def test_response_keys_match_schema(self, client, db_session):
        _seed_portfolio(db_session, [{"instrument_id": "ASML", "allocation_pct": 100.0, "shares": 5}])
        _seed_closes(db_session, "ASML")
        _as()
        it = _get(client, instrument="ASML").json()["items"][0]
        assert set(it) == set(PositionValueItem.model_fields)
        assert set(it["bands"]) == set(schema_mod.PositionValueBands.model_fields)
