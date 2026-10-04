"""F40 Phase 2 — hedge-plan save semantics + append-only history dataset.

Real in-memory SQLite (conftest ``client`` / ``db_session``); only auth is overridden.
Covers: preserve-on-omit (last_step, selections), selections round-trip, every PUT appends
(no dedupe), server-side market enrichment (not client-overridable), lenient context,
rollback on append failure, per-user isolation, history GET envelope, system export
(403 / JSON / CSV exact columns), pure CSV flattening.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest

from rita.auth import get_current_user
from rita.main import app
from rita.models.market_data import MarketDataCacheModel
from rita.models.user import UserModel
from rita.models.user_hedge_plan_history import UserHedgePlanHistoryModel
from rita.models.user_portfolio import UserPortfolioModel
from rita.models.user_portfolio_key import UserPortfolioKeyModel
from rita.services.hedge_history_export import HEADER_COLUMNS, flatten_rows, to_csv

URL = "/api/v1/experience/fno/hedge-plan"
HIST = URL + "/history"
EXPORT = "/api/v1/system/hedge-plan-history"

EXPECTED_CSV_COLUMNS = [
    "history_id", "saved_at", "user_id", "key_id", "trigger", "source", "last_step",
    "scenario_tab", "coverage", "duration", "schema_version", "app_version",
    "total_value_eur", "cash_eur", "n_holdings",
    "instrument_id", "hedged", "strategy", "shares", "allocation_pct", "currency",
    "spot", "spot_date", "position_value", "ann_vol_pct",
    "strike_pct", "strike_label", "premium_pct", "cost_source", "hedge_type",
    "risk_score", "protected_pct",
]


def _as(user_id: str, ops: bool = False):
    app.dependency_overrides[get_current_user] = lambda: UserModel(id=user_id, can_access_ops=ops)


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _seed_key(db, user_id="u1", key_id="k1"):
    db.add(UserPortfolioKeyModel(key_id=key_id, user_id=user_id))
    db.commit()


def _seed_portfolio(db, key_id="k1"):
    db.add(UserPortfolioModel(
        portfolio_id="p-" + key_id, key_id=key_id, name="t", is_active=True, total_value_eur=10000.0,
        holdings=[
            {"instrument_id": "ASML", "allocation_pct": 60.0, "shares": 10, "cash_eur": 12.5},
            {"instrument_id": "MYSTERY", "allocation_pct": 40.0, "shares": 5, "cash_eur": 1.0},
        ],
    ))
    # 40 deterministic closes for ASML
    for i in range(40):
        db.add(MarketDataCacheModel(
            cache_id=f"ASML-{i}", date=date(2026, 8, 1).fromordinal(date(2026, 8, 1).toordinal() + i),
            underlying="ASML", open=100.0, high=101.0, low=99.0,
            close=100.0 + i * (1 if i % 2 else -1), recorded_at=datetime(2026, 9, 30),
        ))
    db.commit()


def _body(**kw):
    b = {"hedged_ids": ["ASML"], "coverage": 60, "scenario_tab": "pp"}
    b.update(kw)
    return b


def _rows(db):
    return db.query(UserHedgePlanHistoryModel).order_by(UserHedgePlanHistoryModel.saved_at).all()


class TestSaveSemantics:
    def test_404_without_portfolio_key(self, client):
        _as("nokey")
        assert client.put(URL, json=_body()).status_code == 404

    def test_first_insert_defaults_last_step_exposure(self, client, db_session):
        _seed_key(db_session); _as("u1")
        r = client.put(URL, json=_body())
        assert r.status_code == 200 and r.json()["last_step"] == "exposure"
        assert r.json()["selections"] is None

    def test_first_insert_works_with_autoflush_off(self, client, db_session):
        """Regression (found by the isolated e2e): SessionLocal has autoflush=False, so the
        upserted-but-unflushed plan row must still be readable inside the same transaction."""
        db_session.autoflush = False
        _seed_key(db_session); _as("u1")
        r = client.put(URL, json=_body(selections={"ASML": "put_buy"}))
        assert r.status_code == 200 and r.json()["selections"] == {"ASML": "put_buy"}
        assert len(_rows(db_session)) == 1

    def test_omitted_or_unknown_last_step_preserves(self, client, db_session):
        _seed_key(db_session); _as("u1")
        client.put(URL, json=_body(last_step="save", trigger="explicit"))
        r = client.put(URL, json=_body(coverage=70))  # Overview-style: no last_step
        assert r.json()["last_step"] == "save" and r.json()["coverage"] == 70
        r = client.put(URL, json=_body(last_step="bogus"))
        assert r.json()["last_step"] == "save"

    def test_selections_round_trip_preserve_and_drop_invalid(self, client, db_session):
        _seed_key(db_session); _as("u1")
        r = client.put(URL, json=_body(selections={"ASML": "put_buy", "TCS": "call_sell", "X": "bogus"}))
        assert r.json()["selections"] == {"ASML": "put_buy", "TCS": "call_sell"}
        r = client.put(URL, json=_body(coverage=10))  # omitted -> preserved
        assert r.json()["selections"] == {"ASML": "put_buy", "TCS": "call_sell"}
        assert client.get(URL).json()["selections"] == {"ASML": "put_buy", "TCS": "call_sell"}
        r = client.put(URL, json=_body(selections={}))  # empty -> preserved (F40-QA-1)
        assert r.json()["selections"] == {"ASML": "put_buy", "TCS": "call_sell"}

    def test_duration_always_1y_and_single_commit(self, client, db_session):
        _seed_key(db_session); _as("u1")
        with patch.object(db_session, "commit", wraps=db_session.commit) as spy:
            r = client.put(URL, json=_body(duration="3m"))
        assert r.json()["duration"] == "1y"
        assert spy.call_count == 1


class TestHistoryAppend:
    def test_every_put_appends_no_dedupe(self, client, db_session):
        _seed_key(db_session); _as("u1")
        for _ in range(3):  # identical autosaves — user accepts duplicates
            client.put(URL, json=_body(trigger="autosave"))
        client.put(URL, json=_body(trigger="explicit", last_step="save"))
        rows = _rows(db_session)
        assert len(rows) == 4
        assert [r.trigger for r in rows] == ["autosave"] * 3 + ["explicit"]
        assert rows[-1].last_step == "save"
        assert all(r.schema_version == 1 and r.duration == "1y" for r in rows)

    def test_unknown_trigger_source_default(self, client, db_session):
        _seed_key(db_session); _as("u1")
        client.put(URL, json=_body(trigger="weird", source="elsewhere"))
        r = _rows(db_session)[0]
        assert (r.trigger, r.source) == ("autosave", "workflow")

    def test_overview_source_recorded(self, client, db_session):
        _seed_key(db_session); _as("u1")
        client.put(URL, json=_body(source="overview"))
        assert _rows(db_session)[0].source == "overview"

    def test_server_market_block_and_client_block(self, client, db_session):
        _seed_key(db_session); _seed_portfolio(db_session); _as("u1")
        ctx = {"instruments": [{
            "instrument_id": "ASML", "strike_pct": 95.0, "strike_label": "95%", "premium_pct": 0.4,
            "cost_source": "kite", "hedge_type": "put", "risk_score": 3.0, "protected_pct": 5.0,
            # client attempts to override server fields -> must be ignored
            "spot": 1.0, "currency": "XXX", "position_value": 1.0, "shares": 999,
        }], "margin": {"required": 1234}}
        client.put(URL, json=_body(trigger="explicit", selections={"ASML": "put_buy"}, context=ctx))
        row = _rows(db_session)[0]
        by_id = {i["instrument_id"]: i for i in row.instruments}
        a = by_id["ASML"]
        assert a["hedged"] is True and a["strategy"] == "put_buy"
        assert a["currency"] == "EUR" and a["shares"] == 10
        assert a["spot"] == 100.0 + 39 * 1 and a["spot_date"] == "2026-09-09"
        assert a["position_value"] == round(10 * a["spot"], 2)
        assert a["ann_vol_pct"] is not None  # explicit save computes vol
        assert (a["strike_pct"], a["cost_source"], a["protected_pct"]) == (95.0, "kite", 5.0)
        m = by_id["MYSTERY"]  # unmapped currency: no default, save still succeeds
        assert m["currency"] is None and m["position_value"] is None and m["hedged"] is False
        assert row.portfolio == {"total_value_eur": 10000.0, "cash_eur": 13.5, "n_holdings": 2}
        assert row.margin == {"required": 1234}

    def test_autosave_skips_ann_vol(self, client, db_session):
        _seed_key(db_session); _seed_portfolio(db_session); _as("u1")
        client.put(URL, json=_body(trigger="autosave"))
        a = {i["instrument_id"]: i for i in _rows(db_session)[0].instruments}["ASML"]
        assert a["ann_vol_pct"] is None and a["position_value"] is not None

    def test_context_never_422(self, client, db_session):
        _seed_key(db_session); _as("u1")
        big = {"instruments": [{"instrument_id": f"I{i}"} for i in range(80)]}
        assert client.put(URL, json=_body(context=big)).status_code == 200
        assert client.put(URL, json=_body(context={"instruments": "nope", "margin": 5})).status_code == 200
        assert client.put(URL, json=_body(context={"instruments": [{"strike_pct": 1}, 7]})).status_code == 200
        rows = _rows(db_session)
        # only hedged_ids (ASML) listed when no portfolio; context beyond 50 truncated
        assert all(len(r.instruments) <= 51 for r in rows)

    def test_rollback_when_append_fails(self, client, db_session):
        _seed_key(db_session); _as("u1")
        with patch("rita.services.hedge_plan_service.UserHedgePlanHistoryRepo.append",
                   side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                client.put(URL, json=_body())
        assert client.get(URL).json() is None  # plan upsert rolled back too
        assert _rows(db_session) == []


class TestHistoryGet:
    def test_envelope_newest_first_and_isolation(self, client, db_session):
        _seed_key(db_session, "u1", "k1"); _seed_key(db_session, "u2", "k2")
        _as("u1"); client.put(URL, json=_body(coverage=10)); client.put(URL, json=_body(coverage=20))
        _as("u2"); client.put(URL, json=_body(coverage=99))
        _as("u1")
        j = client.get(HIST).json()
        assert set(j) == {"items", "count", "limit"} and j["count"] == 2 and j["limit"] == 50
        assert [i["coverage"] for i in j["items"]] == [20, 10]
        item = j["items"][0]
        for f in ("history_id", "saved_at", "trigger", "source", "last_step", "scenario_tab", "coverage",
                  "duration", "hedged_ids", "selections", "instruments", "portfolio", "margin",
                  "schema_version", "app_version"):
            assert f in item
        assert "user_id" not in item
        assert client.get(HIST + "?limit=1").json()["count"] == 1
        assert client.get(HIST + "?limit=0").status_code == 422
        assert client.get(HIST + "?trigger=explicit").json()["count"] == 0

    def test_empty_without_key(self, client):
        _as("ghost")
        assert client.get(HIST).json() == {"items": [], "count": 0, "limit": 50}


class TestExport:
    def _seed(self, client, db):
        _seed_key(db); _seed_portfolio(db); _as("u1")
        client.put(URL, json=_body(trigger="explicit", selections={"ASML": "put_buy"}))

    def test_403_without_role_and_401_unauth(self, client, db_session):
        _seed_key(db_session); _as("u1", ops=False)
        assert client.get(EXPORT).status_code == 403
        app.dependency_overrides.pop(get_current_user, None)
        assert client.get(EXPORT).status_code in (401, 403)

    def test_json_envelope(self, client, db_session):
        self._seed(client, db_session); _as("ops", ops=True)
        j = client.get(EXPORT).json()
        assert set(j) == {"items", "count", "limit", "offset", "since", "until"}
        assert j["count"] == 1 and j["items"][0]["user_id"] == "u1" and j["items"][0]["key_id"] == "k1"

    def test_csv_exact_columns_one_row_per_instrument(self, client, db_session):
        self._seed(client, db_session); _as("ops", ops=True)
        r = client.get(EXPORT + "?format=csv")
        assert r.headers["content-type"].startswith("text/csv")
        rows = list(csv.reader(io.StringIO(r.text)))
        assert rows[0] == EXPECTED_CSV_COLUMNS
        assert len(rows) == 3  # header + ASML + MYSTERY

    def test_since_until_filter_and_bad_date(self, client, db_session):
        self._seed(client, db_session); _as("ops", ops=True)
        assert client.get(EXPORT + "?since=2999-01-01").json()["count"] == 0
        assert client.get(EXPORT + "?until=2999-01-01").json()["count"] == 1
        assert client.get(EXPORT + "?since=notadate").status_code == 422


class TestFlatten:
    def test_blank_instrument_row_and_header(self):
        class R:  # minimal row stand-in
            history_id = "h"; saved_at = datetime(2026, 10, 5, tzinfo=timezone.utc); user_id = "u"
            key_id = "k"; trigger = "autosave"; source = "workflow"; last_step = None
            scenario_tab = "pp"; coverage = 1; duration = "1y"; schema_version = 1; app_version = "v"
            portfolio = {}; instruments = []
        out = flatten_rows([R()])
        assert len(out) == 1 and out[0]["instrument_id"] is None
        assert HEADER_COLUMNS == EXPECTED_CSV_COLUMNS
        assert to_csv([R()]).splitlines()[0] == ",".join(EXPECTED_CSV_COLUMNS)
