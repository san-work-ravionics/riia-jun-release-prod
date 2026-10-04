"""F40 Phase 2 — QA additions (gaps vs Architect edge cases / Code Review advisories).

Real in-memory SQLite via conftest ``client`` / ``db_session``; only auth overridden.
Reuses helpers from test_f40_hedge_plan_history.
"""
from __future__ import annotations

import csv
import io
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from rita.auth import get_current_user
from rita.main import app
from rita.models.user_hedge_plan import UserHedgePlanModel
from tests.unit.test_f40_hedge_plan_history import (
    EXPECTED_CSV_COLUMNS, EXPORT, HIST, URL, _as, _body, _cleanup, _rows, _seed_key, _seed_portfolio,
)

_ = _cleanup  # autouse fixture re-exported so dependency override is popped after each test


class TestSelectionsPreserveAdvisory2:
    """Code Review advisory #2: only a valid non-empty dict replaces stored selections."""

    def test_invalid_only_selections_preserve(self, client, db_session):
        _seed_key(db_session); _as("u1")
        client.put(URL, json=_body(selections={"ASML": "put_buy"}))
        r = client.put(URL, json=_body(selections={"ASML": "bogus", "TCS": 1}))
        assert r.json()["selections"] == {"ASML": "put_buy"}

    def test_empty_selections_preserve(self, client, db_session):
        _seed_key(db_session); _as("u1")
        client.put(URL, json=_body(selections={"ASML": "put_buy"}))
        r = client.put(URL, json=_body(selections={}))
        assert r.json()["selections"] == {"ASML": "put_buy"}

    def test_null_and_omitted_and_nondict_preserve(self, client, db_session):
        _seed_key(db_session); _as("u1")
        client.put(URL, json=_body(selections={"ASML": "put_buy"}))
        for sel in (None, "garbage", ["ASML"], 5):
            r = client.put(URL, json=_body(selections=sel))
            assert r.json()["selections"] == {"ASML": "put_buy"}, sel
        r = client.put(URL, json=_body())
        assert r.json()["selections"] == {"ASML": "put_buy"}

    def test_valid_nonempty_replaces(self, client, db_session):
        _seed_key(db_session); _as("u1")
        client.put(URL, json=_body(selections={"ASML": "put_buy"}))
        r = client.put(URL, json=_body(selections={"ASML": "call_sell", "TCS": "put_buy", "Z": "x"}))
        assert r.json()["selections"] == {"ASML": "call_sell", "TCS": "put_buy"}


class TestAppendAndTrigger:
    def test_identical_consecutive_autosaves_each_append_and_record_trigger_source(self, client, db_session):
        _seed_key(db_session); _as("u1")
        for _ in range(5):
            assert client.put(URL, json=_body(trigger="autosave", source="overview")).status_code == 200
        rows = _rows(db_session)
        assert len(rows) == 5
        assert {(r.trigger, r.source) for r in rows} == {("autosave", "overview")}
        assert len({r.history_id for r in rows}) == 5

    def test_history_row_snapshots_stored_plan_not_raw_body(self, client, db_session):
        """Overview-style PUT without last_step/selections: history row carries the preserved values."""
        _seed_key(db_session); _as("u1")
        client.put(URL, json=_body(last_step="save", trigger="explicit", selections={"ASML": "put_buy"}))
        client.put(URL, json=_body(coverage=33, source="overview"))
        newest = client.get(HIST).json()["items"][0]
        assert newest["last_step"] == "save" and newest["selections"] == {"ASML": "put_buy"}
        assert newest["coverage"] == 33 and newest["source"] == "overview"

    def test_hedged_id_not_in_portfolio_still_listed(self, client, db_session):
        _seed_key(db_session); _seed_portfolio(db_session); _as("u1")
        client.put(URL, json=_body(hedged_ids=["ASML", "GHOST"]))
        ids = [i["instrument_id"] for i in _rows(db_session)[0].instruments]
        assert "GHOST" in ids and ids.count("ASML") == 1


class TestContextNonObject:
    @pytest.mark.parametrize("ctx", [[1, 2], "str", 7, True])
    def test_non_object_context_is_422_and_no_side_effects(self, client, db_session, ctx):
        """Documented behaviour (Code Review advisory #3): non-object context -> 422, nothing written."""
        _seed_key(db_session); _as("u1")
        r = client.put(URL, json=_body(context=ctx))
        assert r.status_code == 422
        assert _rows(db_session) == []
        assert client.get(URL).json() is None

    def test_null_context_ok(self, client, db_session):
        _seed_key(db_session); _as("u1")
        assert client.put(URL, json=_body(context=None)).status_code == 200


class TestHistoryGetFilters:
    def test_trigger_filter_positive_limit_bounds_and_isolation(self, client, db_session):
        _seed_key(db_session, "u1", "k1"); _seed_key(db_session, "u2", "k2")
        _as("u1")
        client.put(URL, json=_body(trigger="autosave"))
        client.put(URL, json=_body(trigger="explicit", last_step="save"))
        client.put(URL, json=_body(trigger="autosave"))
        _as("u2")
        client.put(URL, json=_body(trigger="explicit"))
        _as("u1")
        assert client.get(HIST + "?trigger=explicit").json()["count"] == 1
        assert client.get(HIST + "?trigger=autosave").json()["count"] == 2
        assert client.get(HIST + "?limit=2").json()["count"] == 2
        assert client.get(HIST + "?limit=200").status_code == 200
        assert client.get(HIST + "?limit=201").status_code == 422
        # u2 sees only its own row, none of u1's
        _as("u2")
        j = client.get(HIST).json()
        assert j["count"] == 1 and j["items"][0]["trigger"] == "explicit"
        # user with no key -> empty (also with filter)
        _as("ghost")
        assert client.get(HIST + "?trigger=explicit").json()["count"] == 0

    def test_history_get_does_not_commit(self, client, db_session):
        _seed_key(db_session); _as("u1")
        client.put(URL, json=_body())
        with patch.object(db_session, "commit") as spy:
            client.get(HIST)
            client.get(URL)
        assert spy.call_count == 0


class TestExportQA:
    def test_unauth_is_401(self, client):
        app.dependency_overrides.pop(get_current_user, None)
        assert client.get(EXPORT).status_code == 401

    def test_ops_false_403_for_json_and_csv(self, client, db_session):
        _as("u1", ops=False)
        assert client.get(EXPORT).status_code == 403
        assert client.get(EXPORT + "?format=csv").status_code == 403

    def test_ops_200_json_and_csv(self, client, db_session):
        _seed_key(db_session); _as("u1")
        client.put(URL, json=_body())
        _as("ops", ops=True)
        assert client.get(EXPORT).status_code == 200
        assert client.get(EXPORT + "?format=csv").status_code == 200
        assert client.get(EXPORT + "?format=xml").status_code == 422

    def test_csv_row_count_is_saves_times_instruments_and_values_align_to_header(self, client, db_session):
        _seed_key(db_session); _seed_portfolio(db_session); _as("u1")
        client.put(URL, json=_body(trigger="explicit", selections={"ASML": "put_buy"}))  # 2 portfolio instruments
        client.put(URL, json=_body(trigger="autosave", hedged_ids=["ASML", "GHOST"]))     # +GHOST = 3
        _as("ops", ops=True)
        rows = list(csv.DictReader(io.StringIO(client.get(EXPORT + "?format=csv").text)))
        assert len(rows) == 2 + 3
        assert list(rows[0].keys()) == EXPECTED_CSV_COLUMNS
        asml = [r for r in rows if r["instrument_id"] == "ASML"]
        assert len(asml) == 2
        first = asml[0]  # oldest-first export order -> explicit save
        assert first["trigger"] == "explicit" and first["strategy"] == "put_buy"
        assert first["user_id"] == "u1" and first["key_id"] == "k1" and first["currency"] == "EUR"
        assert first["hedged"] == "True" and first["n_holdings"] == "2"
        ghost = [r for r in rows if r["instrument_id"] == "GHOST"][0]
        assert ghost["currency"] == "" and ghost["position_value"] == ""

    def test_save_with_no_instruments_gives_one_row(self, client, db_session):
        _seed_key(db_session); _as("u1")  # no portfolio
        client.put(URL, json=_body(hedged_ids=[]))
        _as("ops", ops=True)
        rows = list(csv.DictReader(io.StringIO(client.get(EXPORT + "?format=csv").text)))
        assert len(rows) == 1
        assert rows[0]["instrument_id"] == "" and rows[0]["history_id"] != ""
        assert rows[0]["coverage"] == "60"

    def test_limit_offset_paging_and_validation(self, client, db_session):
        _seed_key(db_session); _as("u1")
        for c in (1, 2, 3):
            client.put(URL, json=_body(coverage=c))
        _as("ops", ops=True)
        j = client.get(EXPORT + "?limit=2&offset=1").json()
        assert j["count"] == 2 and j["limit"] == 2 and j["offset"] == 1
        assert [i["coverage"] for i in j["items"]] == [2, 3]  # oldest-first
        assert client.get(EXPORT + "?limit=0").status_code == 422
        assert client.get(EXPORT + "?limit=10001").status_code == 422
        assert client.get(EXPORT + "?offset=-1").status_code == 422

    def test_export_spans_users(self, client, db_session):
        _seed_key(db_session, "u1", "k1"); _seed_key(db_session, "u2", "k2")
        _as("u1"); client.put(URL, json=_body())
        _as("u2"); client.put(URL, json=_body())
        _as("ops", ops=True)
        assert {i["user_id"] for i in client.get(EXPORT).json()["items"]} == {"u1", "u2"}


class TestRollbackQA:
    def test_append_failure_returns_500_and_existing_plan_unchanged(self, client, db_session):
        _seed_key(db_session); _as("u1")
        client.put(URL, json=_body(coverage=40, last_step="whatif", selections={"ASML": "put_buy"}))
        before_rows = len(_rows(db_session))
        with patch("rita.services.hedge_plan_service.UserHedgePlanHistoryRepo.append",
                   side_effect=RuntimeError("boom")):
            with TestClient(app, raise_server_exceptions=False) as c:
                r = c.put(URL, json=_body(coverage=99, last_step="save", selections={"ASML": "call_sell"}))
        assert r.status_code == 500
        db_session.expire_all()
        plan = db_session.query(UserHedgePlanModel).one()
        assert (plan.coverage, plan.last_step, plan.selections) == (40, "whatif", {"ASML": "put_buy"})
        assert len(_rows(db_session)) == before_rows
        assert client.get(URL).json()["coverage"] == 40

    def test_commit_failure_rolls_back(self, client, db_session):
        _seed_key(db_session); _as("u1")
        with patch.object(db_session, "commit", side_effect=RuntimeError("disk")):
            with TestClient(app, raise_server_exceptions=False) as c:
                assert c.put(URL, json=_body()).status_code == 500
        assert _rows(db_session) == []
