"""QA gap-fill — F39 Phase 3 backend: kite client edge cases, kite-live route mapping,
hedge-plan last_step handling. Mocked HTTP / repos only (no live fno-margin-fetch).
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest

from rita.services import kite_middleware_client as kmc
from rita.services.kite_middleware_client import fetch_kite_quote

_HTTP = "rita.services.kite_middleware_client.httpx.request"
_ROUTE_CLIENT = "rita.api.experience.fno_kite_live.fetch_kite_quote"
_KEY_REPO = "rita.api.experience.fno_hedge_plan.UserPortfolioKeyRepo"
_PLAN_REPO = "rita.api.experience.fno_hedge_plan.UserHedgePlanRepo"


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    kmc._reset_cache()


def _resp(status: int = 200, body: object = None) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body
    return r


def _quote_body(key: str = "NSE:NIFTY 50", **q: object) -> dict:
    return {"success": True, "data": {key: q}}


def _by_route(instruments: object, quotes: object):
    def _side(method, url, **kw):
        return instruments if url.endswith("/api/instruments") else quotes
    return _side


# ── kite_middleware_client edge cases (every failure -> None via one path) ───────────

class TestKiteClientFallbacks:
    @pytest.mark.parametrize(
        "effect",
        [
            httpx.ConnectError("refused"),
            httpx.ReadTimeout("slow"),
            httpx.ConnectTimeout("slow"),
            httpx.RemoteProtocolError("bad"),
        ],
    )
    def test_transport_errors_return_none(self, effect) -> None:
        with patch(_HTTP, side_effect=effect):
            assert fetch_kite_quote("NIFTY") is None

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 500, 502, 503])
    def test_non_2xx_returns_none(self, status) -> None:
        with patch(_HTTP, return_value=_resp(status, {"success": True})):
            assert fetch_kite_quote("NIFTY") is None

    @pytest.mark.parametrize("body", [None, [], "text", 42, {}, {"success": "true"}, {"success": 1}])
    def test_non_dict_or_non_true_success_returns_none(self, body) -> None:
        with patch(_HTTP, return_value=_resp(200, body)):
            assert fetch_kite_quote("NIFTY") is None

    def test_empty_instrument_list_no_quote_returns_none(self) -> None:
        side = _by_route(_resp(200, {"success": True, "instruments": []}), _resp(200, {"success": True, "data": {}}))
        with patch(_HTTP, side_effect=side):
            assert fetch_kite_quote("NIFTY") is None

    def test_instruments_key_missing_or_null_does_not_raise(self) -> None:
        for inst_body in ({"success": True}, {"success": True, "instruments": None}):
            kmc._reset_cache()
            side = _by_route(_resp(200, inst_body), _resp(200, _quote_body(last_price=10.0)))
            with patch(_HTTP, side_effect=side):
                r = fetch_kite_quote("NIFTY")
            assert r == {"lot_size": None, "ltp": 10.0, "bid": None, "ask": None}

    def test_malformed_instrument_entries_ignored(self) -> None:
        body = {"success": True, "instruments": ["x", None, 3, {"name": "NIFTY", "lot_size": 75}]}
        side = _by_route(_resp(200, body), _resp(200, {"success": False}))
        with patch(_HTTP, side_effect=side):
            assert fetch_kite_quote("NIFTY")["lot_size"] == 75

    @pytest.mark.parametrize("bad", [0, -75, "75", 75.0, True, None])
    def test_invalid_lot_size_values_rejected(self, bad) -> None:
        body = {"success": True, "instruments": [{"name": "NIFTY", "lot_size": bad}]}
        side = _by_route(_resp(200, body), _resp(200, _quote_body(last_price=1.0)))
        with patch(_HTTP, side_effect=side):
            assert fetch_kite_quote("NIFTY")["lot_size"] is None

    def test_ambiguous_lot_size_not_cached(self) -> None:
        body = {"success": True, "instruments": [{"name": "NIFTY", "lot_size": 75}, {"name": "NIFTY", "lot_size": 25}]}
        side = _by_route(_resp(200, body), _resp(200, _quote_body(last_price=1.0)))
        with patch(_HTTP, side_effect=side) as m:
            fetch_kite_quote("NIFTY")
            fetch_kite_quote("NIFTY")
        assert sum(c.args[1].endswith("/api/instruments") for c in m.call_args_list) == 2

    def test_other_instrument_contracts_do_not_make_lot_ambiguous(self) -> None:
        body = {"success": True, "instruments": [
            {"name": "NIFTY", "lot_size": 75}, {"name": "BANKNIFTY", "lot_size": 30}]}
        side = _by_route(_resp(200, body), _resp(200, {"success": False}))
        with patch(_HTTP, side_effect=side):
            assert fetch_kite_quote("NIFTY")["lot_size"] == 75

    def test_quote_missing_depth_gives_none_bid_ask(self) -> None:
        side = _by_route(_resp(200, {"success": True, "instruments": []}), _resp(200, _quote_body(last_price=5.5)))
        with patch(_HTTP, side_effect=side):
            assert fetch_kite_quote("NIFTY") == {"lot_size": None, "ltp": 5.5, "bid": None, "ask": None}

    @pytest.mark.parametrize("depth", [{"buy": [], "sell": []}, {"buy": None}, "junk", []])
    def test_quote_odd_depth_shapes_do_not_raise(self, depth) -> None:
        side = _by_route(
            _resp(200, {"success": True, "instruments": []}),
            _resp(200, _quote_body(last_price=5.5, depth=depth)),
        )
        with patch(_HTTP, side_effect=side):
            r = fetch_kite_quote("NIFTY")
        assert r is not None and r["ltp"] == 5.5

    def test_quote_entry_not_a_dict_returns_none(self) -> None:
        side = _by_route(_resp(200, {"success": True, "instruments": []}),
                         _resp(200, {"success": True, "data": {"NSE:NIFTY 50": "bad"}}))
        with patch(_HTTP, side_effect=side):
            assert fetch_kite_quote("NIFTY") is None

    def test_unexpected_exception_is_swallowed(self) -> None:
        with patch(_HTTP, side_effect=RuntimeError("boom")):
            assert fetch_kite_quote("NIFTY") is None

    def test_settings_failure_is_swallowed(self) -> None:
        with patch("rita.services.kite_middleware_client.get_settings", side_effect=RuntimeError("cfg")):
            assert fetch_kite_quote("NIFTY") is None

    def test_never_returns_margin_keys_even_if_server_sends_them(self) -> None:
        q = _quote_body(last_price=1.0, margin={"required": 99})
        side = _by_route(_resp(200, {"success": True, "instruments": [{"name": "NIFTY", "lot_size": 75}]}), _resp(200, q))
        with patch(_HTTP, side_effect=side):
            r = fetch_kite_quote("NIFTY", strike=24000, option_type="PE", quantity=75, transaction_type="BUY")
        assert set(r) == {"lot_size", "ltp", "bid", "ask"}

    def test_timeout_value_is_short(self) -> None:
        side = _by_route(_resp(200, {"success": True, "instruments": []}), _resp(200, {"success": False}))
        with patch(_HTTP, side_effect=side) as m:
            fetch_kite_quote("NIFTY")
        assert all(c.kwargs["timeout"] <= 2.0 for c in m.call_args_list)

    def test_banknifty_uses_index_quote_key(self) -> None:
        side = _by_route(_resp(200, {"success": True, "instruments": []}),
                         _resp(200, _quote_body("NSE:NIFTY BANK", last_price=50000.0)))
        with patch(_HTTP, side_effect=side) as m:
            r = fetch_kite_quote("BANKNIFTY")
        assert r["ltp"] == 50000.0
        post = [c for c in m.call_args_list if c.args[1].endswith("/api/quotes")][0]
        assert post.kwargs["json"] == {"instruments": ["NSE:NIFTY BANK"]}


# ── fno_kite_live route ────────────────────────────────────────────────────────────

@pytest.fixture
def _auth(client):
    from rita.auth import get_current_user
    from rita.main import app
    user = MagicMock()
    user.id = "qa-user"
    app.dependency_overrides[get_current_user] = lambda: user
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.usefixtures("_auth")
class TestKiteLiveRoute:
    def _get(self, client, raw, **params):
        with patch(_ROUTE_CLIENT, return_value=raw) as m:
            resp = client.get("/api/v1/experience/fno/kite-live", params={"instrument_id": "NIFTY", **params})
        return resp, m

    def test_all_none_values_from_client_still_available_but_no_quote_or_margin(self, client) -> None:
        resp, _ = self._get(client, {"lot_size": None, "ltp": None, "bid": None, "ask": None})
        b = resp.json()
        assert resp.status_code == 200
        assert b["available"] is True and b["source"] == "kite"
        assert b["lot_size"] is None and b["quote"] is None and b["margin"] is None

    def test_empty_dict_from_client_does_not_raise(self, client) -> None:
        resp, _ = self._get(client, {})
        assert resp.status_code == 200 and resp.json()["quote"] is None

    def test_partial_quote_only_bid(self, client) -> None:
        resp, _ = self._get(client, {"lot_size": 75, "ltp": None, "bid": 1.5, "ask": None})
        assert resp.json()["quote"] == {"ltp": None, "bid": 1.5, "ask": None}

    def test_margin_partial_keys(self, client) -> None:
        resp, _ = self._get(client, {"lot_size": 75, "span": 1000.0})
        assert resp.json()["margin"] == {"required": None, "span": 1000.0, "exposure": None}

    def test_order_params_forwarded_to_client(self, client) -> None:
        _, m = self._get(client, None, strike=24000.0, option_type="PE", quantity=75, transaction_type="BUY")
        _, kw = m.call_args
        assert (kw["strike"], kw["option_type"], kw["quantity"], kw["transaction_type"]) == (24000.0, "PE", 75, "BUY")

    def test_client_none_is_fallback_with_null_fetched_at(self, client) -> None:
        resp, _ = self._get(client, None)
        b = resp.json()
        assert b["available"] is False and b["source"] == "fallback" and b["fetched_at"] is None

    def test_route_surfaces_margin_unchanged_currency_decision_is_client_side(self, client) -> None:
        # Route does not know the currency: it returns margin.required as-is. The
        # "INR only" rule lives in hedge-workflow-whatif.js (covered by the node flow test).
        resp, _ = self._get(client, {"lot_size": 75, "required": 5000.0})
        assert resp.json()["margin"]["required"] == 5000.0


# ── hedge-plan last_step ───────────────────────────────────────────────────────────

_NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


def _plan(last_step="exposure"):
    p = MagicMock()
    p.key_id, p.hedged_ids, p.coverage = "k", ["RELIANCE"], 40
    p.scenario_tab, p.duration, p.last_step, p.updated_at = "pp", "1y", last_step, _NOW
    return p


@pytest.mark.usefixtures("_auth")
class TestHedgePlanLastStep:
    def _put(self, client, db_session, body):
        with (
            patch(_KEY_REPO) as key_cls,
            patch(_PLAN_REPO) as plan_cls,
            patch.object(db_session, "commit", wraps=db_session.commit) as commit,
        ):
            key_cls.return_value.find_by_user_id.return_value = MagicMock(key_id="k")
            plan_cls.return_value.find_by_key_id.return_value = _plan()
            resp = client.put("/api/v1/experience/fno/hedge-plan", json=body)
            saved = plan_cls.return_value.upsert.call_args
        return resp, commit, saved

    @pytest.mark.parametrize("step", ["exposure", "recommendation", "whatif", "save"])
    def test_every_known_step_persisted_verbatim(self, client, db_session, step) -> None:
        resp, commit, saved = self._put(
            client, db_session, {"hedged_ids": ["A"], "coverage": 10, "scenario_tab": "ps", "last_step": step})
        assert resp.status_code == 200
        assert saved.args[0].last_step == step and commit.call_count == 1

    @pytest.mark.parametrize("bad", ["", "SAVE", "Save ", "history", "0"])
    def test_unknown_or_miscased_step_coerced_to_exposure_not_422(self, client, db_session, bad) -> None:
        resp, _, saved = self._put(
            client, db_session, {"hedged_ids": [], "coverage": 0, "scenario_tab": "pp", "last_step": bad})
        assert resp.status_code == 200
        assert saved.args[0].last_step == "exposure"

    def test_null_last_step_defaults_exposure(self, client, db_session) -> None:
        resp, _, saved = self._put(
            client, db_session, {"hedged_ids": [], "coverage": 0, "scenario_tab": "pp", "last_step": None})
        assert resp.status_code == 200 and saved.args[0].last_step == "exposure"

    def test_non_string_last_step_is_422(self, client, db_session) -> None:
        resp, _, _ = self._put(
            client, db_session, {"hedged_ids": [], "coverage": 0, "scenario_tab": "pp", "last_step": 5})
        assert resp.status_code == 422

    def test_coverage_out_of_range_still_422(self, client, db_session) -> None:
        resp, _, _ = self._put(
            client, db_session, {"hedged_ids": [], "coverage": 101, "scenario_tab": "pp", "last_step": "save"})
        assert resp.status_code == 422

    def test_put_no_portfolio_key_404_no_commit(self, client, db_session) -> None:
        with patch(_KEY_REPO) as key_cls, patch.object(db_session, "commit", wraps=db_session.commit) as c:
            key_cls.return_value.find_by_user_id.return_value = None
            resp = client.put("/api/v1/experience/fno/hedge-plan",
                              json={"hedged_ids": [], "coverage": 5, "scenario_tab": "pp", "last_step": "save"})
        assert resp.status_code == 404 and c.call_count == 0

    def test_get_saved_last_step_save(self, client) -> None:
        with patch(_KEY_REPO) as key_cls, patch(_PLAN_REPO) as plan_cls:
            key_cls.return_value.find_by_user_id.return_value = MagicMock(key_id="k")
            plan_cls.return_value.find_by_key_id.return_value = _plan("save")
            resp = client.get("/api/v1/experience/fno/hedge-plan")
        assert resp.json()["last_step"] == "save"

    def test_get_legacy_row_with_null_last_step(self, client) -> None:
        p = _plan()
        p.last_step = None
        with patch(_KEY_REPO) as key_cls, patch(_PLAN_REPO) as plan_cls:
            key_cls.return_value.find_by_user_id.return_value = MagicMock(key_id="k")
            plan_cls.return_value.find_by_key_id.return_value = p
            resp = client.get("/api/v1/experience/fno/hedge-plan")
        assert resp.status_code == 200 and resp.json()["last_step"] is None

    def test_get_null_body_when_no_plan_and_when_no_key_never_commits(self, client, db_session) -> None:
        with patch(_KEY_REPO) as key_cls, patch(_PLAN_REPO) as plan_cls, \
                patch.object(db_session, "commit", wraps=db_session.commit) as c:
            key_cls.return_value.find_by_user_id.return_value = MagicMock(key_id="k")
            plan_cls.return_value.find_by_key_id.return_value = None
            r1 = client.get("/api/v1/experience/fno/hedge-plan")
            key_cls.return_value.find_by_user_id.return_value = None
            r2 = client.get("/api/v1/experience/fno/hedge-plan")
        assert r1.status_code == r2.status_code == 200
        assert r1.json() is None and r2.json() is None and c.call_count == 0
