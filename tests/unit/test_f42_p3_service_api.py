"""F42 P3 — service + Experience API: empty states, isolation, read-only, config, schema, lots."""
from __future__ import annotations

import typing
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from rita.api.experience import fno_trade_analytics as router_mod
from rita.config import TradeAnalysisSettings
from rita.schemas import fno_trade_analytics as sch
from rita.services.fno_trade_analytics_service import (
    AnalyticsParams, FnoTradeAnalyticsService, lot_info_from_master,
)
from rita.services.kite_middleware_client import ClientResult
from tests.unit.f42_p3_helpers import fill, seed

TODAY = date(2026, 10, 12)
PANELS = ["foundation", "overtrading", "buildup", "market-turn", "margin-trap", "suggestions"]
BASE = "/api/v1/experience/fno/trade-analysis/analytics/"
P = AnalyticsParams()


def _book():
    fs = []
    for i, (d, sell) in enumerate([("2026-10-01", 12.0), ("2026-10-02", 8.0), ("2026-10-05", 14.0),
                                   ("2026-10-06", 9.0)]):
        fs += [fill("buy", 100, 10.0, d, "09:31"), fill("sell", 100, sell, d, "10:00")]
    fs.append(fill("buy", 100, 20.0, "2026-10-07", "10:00"))     # stays open
    return fs


SPOT = [("NIFTY", d, c) for d, c in [("2026-10-01", 24000.0), ("2026-10-02", 24400.0), ("2026-10-05", 24000.0),
                                     ("2026-10-06", 24100.0), ("2026-10-07", 24100.0)]]
LEDGER = [("2026-10-01", 0, 100000, 100000), ("2026-10-02", 30000, 0, 70000), ("2026-10-05", 30000, 0, 40000),
          ("2026-10-06", 10000, 0, 30000)]


def _svc(db):
    return FnoTradeAnalyticsService(db, today=TODAY)


def _fields(model):
    return model.model_fields


def _assert_keys_in_schema(data, model):
    """Every key the analytics emit is declared in the Pydantic model (nothing silently dropped)."""
    if not isinstance(data, dict):
        return
    extra = set(data) - set(_fields(model))
    assert not extra, f"{model.__name__}: undeclared keys {extra}"
    for k, v in data.items():
        ann = _fields(model)[k].annotation
        for t in [ann, *typing.get_args(ann)] + [a for x in typing.get_args(ann) for a in typing.get_args(x)]:
            if isinstance(t, type) and issubclass(t, BaseModel):
                for item in (v if isinstance(v, list) else [v]):
                    _assert_keys_in_schema(item, t)
                break


def test_empty_user_returns_no_data_on_all_six_panels(db_session):
    svc = _svc(db_session)
    for name, call in [("foundation", svc.foundation), ("overtrading", svc.overtrading), ("buildup", svc.buildup),
                       ("market-turn", svc.market_turn), ("margin-trap", svc.margin_trap),
                       ("suggestions", svc.suggestions)]:
        r = call("nobody", P)
        assert r.available is False and r.reason == "no_data", name
        assert "Import your Console files" in (r.message or "")
        assert r.definition and r.filter.date_from and r.as_of == TODAY.isoformat()


def test_per_user_isolation(db_session):
    seed(db_session, "user-a", _book(), SPOT, LEDGER)
    seed(db_session, "user-b", [fill("buy", 10, 10.0, "2026-10-01"), fill("sell", 10, 11.0, "2026-10-02")])
    svc = _svc(db_session)
    a = svc.overtrading("user-a", P)
    b = svc.overtrading("user-b", P)
    assert a.activity.fills_total == 9 and b.activity.fills_total == 2
    assert svc.overtrading("user-c", P).reason == "no_data"
    assert svc.margin_trap("user-b", P).ledger.available is False


def test_all_panels_available_and_keys_match_schema(db_session):
    seed(db_session, "u", _book(), SPOT, LEDGER, pnl_lines=[("NIFTY26OCT24000CE", "NIFTY", "2026-10",
                                                          "2026-04-01", "2026-10-12", 600.0, 100, "Long")],
         charges=[("2026-04-01", "2026-10-12", "summary", "Charges", 90.0)])
    svc = _svc(db_session)
    out = svc.run_all("u", P)
    models = dict(zip(PANELS, [sch.FoundationResponse, sch.OvertradingResponse, sch.BuildupResponse,
                               sch.MarketTurnResponse, sch.MarginTrapResponse, sch.SuggestionsResponse]))
    for name, data in out.items():
        assert data["available"] is True, name
        assert data["quality"]["fills_in_scope"] == 9
        assert data["tags"]["measured"] is not None and data["assumptions"]
        models[name].model_validate(data)
    # keys emitted by the pure analyses are all declared in the schema
    ot = out["overtrading"]
    assert ot["activity"]["fills_total"] == 9 and ot["charges"]["est_window"] is not None
    assert out["suggestions"]["disclaimer"]


def test_pure_analysis_keys_are_declared_in_schema():
    from rita.services import fno_trade_analytics as an
    from rita.services.fno_trade_suggestions import suggestions
    from tests.unit.f42_p3_helpers import cfg, ctx, spot
    fs = _book() + [fill("sell", 100, 25.0, "2026-10-08", "10:00")]
    sp = spot(NIFTY=[(d, c) for _u, d, c in SPOT])
    cx = ctx(fs, sp=sp, date_from="2026-10-01", date_to="2026-10-12", c=cfg(suggestion_min_closed_trades=1))
    lots = an.LotInfo()
    ot, bu, mt = an.overtrading(cx, []), an.buildup(cx, lots), an.market_turn(cx)
    mg = an.margin_trap(cx, [an.LedgerRow(date.fromisoformat(d), a, b, c, i) for i, (d, a, b, c) in enumerate(LEDGER)], None)
    _assert_keys_in_schema(ot, sch.OvertradingResponse)
    _assert_keys_in_schema(bu, sch.BuildupResponse)
    _assert_keys_in_schema(mt, sch.MarketTurnResponse)
    _assert_keys_in_schema(mg, sch.MarginTrapResponse)
    _assert_keys_in_schema({k: v for k, v in suggestions(cx, ot, bu, mg, lots).items()}, sch.SuggestionsResponse)
    _assert_keys_in_schema(an.reconciliation(cx, []), sch.ReconBlock)


def test_expiry_month_outside_config_is_no_trades_in_scope(db_session):
    seed(db_session, "u", _book())
    r = _svc(db_session).overtrading("u", AnalyticsParams(expiry_month=2))
    assert r.available is False and r.reason == "no_trades_in_scope"
    r2 = _svc(db_session).overtrading("u", AnalyticsParams(expiry_month=11))
    assert r2.reason == "no_trades_in_scope"
    assert _svc(db_session).overtrading("u", AnalyticsParams(expiry_month=10)).available


def test_underlying_and_date_filters(db_session):
    seed(db_session, "u", _book())
    svc = _svc(db_session)
    assert svc.overtrading("u", AnalyticsParams(underlying="BANKNIFTY")).reason == "no_trades_in_scope"
    r = svc.overtrading("u", AnalyticsParams(date_from=date(2026, 10, 5)))
    assert r.activity.fills_total == 5          # window start filters fills; FIFO still saw earlier history
    assert svc.overtrading("u", AnalyticsParams(date_from=date(2026, 10, 9), date_to=date(2026, 10, 8))).reason == "no_trades_in_scope"


def test_estimate_toggle_param_overrides_config(db_session):
    fs = [fill("sell", 100, 50.0, "2026-10-01"), fill("buy", 10, 5.0, "2026-10-02", "11:00")]
    seed(db_session, "u", fs, [("NIFTY", "2026-10-27", 23800.0)])
    svc = FnoTradeAnalyticsService(db_session, today=date(2026, 10, 29))
    on = svc.overtrading("u", AnalyticsParams(include_expiry_estimate=True))
    off = svc.overtrading("u", AnalyticsParams(include_expiry_estimate=False))
    assert on.winloss.n == 2 and off.winloss.n == 1 and off.filter.include_expiry_estimate is False
    assert on.quality.expiry_estimated_lots == 1
    svc._cfg = TradeAnalysisSettings(expiry_settlement="off")
    assert svc.overtrading("u", P).winloss.n == 1


def test_thresholds_come_from_config(db_session):
    seed(db_session, "u", _book(), SPOT)
    svc = _svc(db_session)
    hi = svc.market_turn("u", P)
    svc._cfg = TradeAnalysisSettings(turn_threshold_pct=5.0)
    lo = svc.market_turn("u", P)
    assert hi.kpis.n_big_move_days > 0 and lo.kpis.n_big_move_days == 0


def test_service_does_not_commit_or_write(db_session, monkeypatch):
    seed(db_session, "u", _book(), SPOT, LEDGER)

    def boom(*a, **k):
        raise AssertionError("write attempted on a read-only analytics path")

    for attr in ("commit", "add", "add_all", "delete", "bulk_insert_mappings", "merge"):
        monkeypatch.setattr(Session, attr, boom)
    out = _svc(db_session).run_all("u", P)
    assert all(v["available"] for v in out.values())


# ── API ──────────────────────────────────────────────────────────────────────


@pytest.fixture()
def user(client, db_session):
    from rita.auth import get_current_user
    from rita.main import app

    u = MagicMock()
    u.id = "u-api"
    app.dependency_overrides[get_current_user] = lambda: u
    app.dependency_overrides[router_mod._get_service] = lambda: FnoTradeAnalyticsService(db_session, today=TODAY)
    yield u
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(router_mod._get_service, None)


def test_requires_auth(client):
    for p in PANELS:
        assert client.get(BASE + p).status_code == 401


def test_six_routes_registered_experience_get_only():
    from rita.main import app
    paths = {r.path: r.methods for r in app.routes if getattr(r, "path", "").startswith(BASE.rstrip("/"))}
    assert set(paths) == {BASE + p for p in PANELS} | {BASE + "spot-vs-pnl"}   # F42 P4 adds the 7th route
    assert all(m == {"GET"} for m in paths.values())


def test_api_empty_state_and_bad_underlying(client, user):
    for p in PANELS:
        r = client.get(BASE + p)
        assert r.status_code == 200 and r.json()["reason"] == "no_data" and r.json()["available"] is False
    assert client.get(BASE + "overtrading?underlying=FINNIFTY").status_code == 422
    assert client.get(BASE + "overtrading?expiry_month=13").status_code == 422


def test_api_responses_validate_and_no_commit(client, user, db_session, monkeypatch):
    seed(db_session, "u-api", _book(), SPOT, LEDGER)
    monkeypatch.setattr(router_mod.kmc, "fetch_instrument_master_nfo", lambda: ClientResult(None, "middleware_unreachable"))
    monkeypatch.setattr(Session, "commit", MagicMock(side_effect=AssertionError("commit on GET")))
    models = dict(zip(PANELS, [sch.FoundationResponse, sch.OvertradingResponse, sch.BuildupResponse,
                               sch.MarketTurnResponse, sch.MarginTrapResponse, sch.SuggestionsResponse]))
    for p in PANELS:
        r = client.get(BASE + p)
        assert r.status_code == 200, p
        body = r.json()
        assert body["available"] is True
        models[p].model_validate(body)


def test_kite_master_down_gives_lots_unavailable_rest_unchanged(client, user, db_session, monkeypatch):
    seed(db_session, "u-api", _book(), SPOT, LEDGER)
    monkeypatch.setattr(router_mod.kmc, "fetch_instrument_master_nfo", lambda: ClientResult(None, "middleware_unreachable"))
    down = client.get(BASE + "buildup").json()
    assert down["lots"]["lots_available"] is False and down["lots"]["lots_basis"] == "unknown"
    assert all(r["long_lots"] is None for r in down["timeline"])
    master = {"NIFTY26OCT24000CE": {"name": "NIFTY", "expiry": "2026-10-27", "lot_size": 20}}
    monkeypatch.setattr(router_mod.kmc, "fetch_instrument_master_nfo", lambda: ClientResult(master))
    up = client.get(BASE + "buildup").json()
    assert up["lots"]["lots_available"] is True and up["lots"]["lots_basis"] == "kite_master"
    assert any(r["long_lots"] for r in up["timeline"])
    assert up["averaging"] == down["averaging"] and up["chains"] == down["chains"]
    monkeypatch.setattr(router_mod.kmc, "fetch_instrument_master_nfo", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert client.get(BASE + "suggestions").json()["available"] is True
    called = []
    monkeypatch.setattr(router_mod.kmc, "fetch_instrument_master_nfo", lambda: called.append(1) or ClientResult(None, "x"))
    client.get(BASE + "buildup?include_lots=false")
    client.get(BASE + "overtrading")
    assert called == []                          # master only fetched for buildup/suggestions with include_lots


def test_lot_info_from_master_shapes():
    assert lot_info_from_master(None).available is False
    assert lot_info_from_master(ClientResult(None, "x")).available is False
    m = ClientResult({"A": {"name": "NIFTY", "expiry": "2026-10-27", "lot_size": 20},
                      "B": {"name": "NIFTY", "expiry": "2026-11-24", "lot_size": 25},
                      "C": {"name": "BANKNIFTY", "expiry": "2026-10-27", "lot_size": None}})
    li = lot_info_from_master(m)
    assert li.by_symbol == {"A": 20, "B": 25} and li.by_underlying == {"NIFTY": 20}
    assert li.lot_size("A", "NIFTY") == (20, "kite_master")
    assert li.lot_size("Z", "NIFTY") == (20, "underlying_current")
    assert li.lot_size("Z", "BANKNIFTY") == (None, "unknown")


# ── config ───────────────────────────────────────────────────────────────────


def test_base_yaml_keys_equal_model_fields_and_extra_forbidden():
    root = Path(__file__).resolve().parents[2]
    y = yaml.safe_load((root / "config/base.yaml").read_text())["trade_analysis"]
    assert set(y) == set(TradeAnalysisSettings.model_fields)
    with pytest.raises(ValidationError):
        TradeAnalysisSettings(not_a_key=1)


@pytest.mark.parametrize("kw", [
    {"expiry_settlement": "other"}, {"analytics_min_timestamp_coverage": 1.5},
    {"analytics_min_timestamp_coverage": -0.1}, {"cooling_off_min_minutes": 200, "cooling_off_max_minutes": 100},
    {"burst_min_fills": 0}, {"debit_streak_min_days": 0}, {"analytics_max_rows": 0},
    {"suggestion_percentile": 0}, {"suggestion_percentile": 100}, {"stop_loss_multiples": [0.0]},
    {"stop_loss_multiples": []}, {"turn_threshold_pct": -1.0}, {"low_cash_threshold_inr": -5.0},
])
def test_config_validators_reject(kw):
    with pytest.raises(ValidationError):
        TradeAnalysisSettings(**kw)


def test_config_defaults_valid():
    c = TradeAnalysisSettings()
    assert c.expiry_settlement == "spot_intrinsic" and c.stop_loss_multiples == [1.0, 1.5, 2.0]
    assert TradeAnalysisSettings(expiry_settlement="off").expiry_settlement == "off"


def test_randomised_book_runs_end_to_end_and_is_deterministic(db_session):
    import json
    import random
    rng = random.Random(7)
    days = [f"2026-10-{d:02d}" for d in (1, 2, 5, 6, 7, 8, 9)]
    fs = []
    for _ in range(120):
        k = rng.choice([24000, 24100, 24200])
        typ = rng.choice(["CE", "PE"])
        fs.append(fill(rng.choice(["buy", "sell"]), rng.choice([10, 20, 25]), float(rng.randint(5, 40)),
                       rng.choice(days), f"{rng.randint(9, 14):02d}:{rng.randint(0, 59):02d}",
                       symbol=f"NIFTY26OCT{k}{typ}", itype=typ, strike=float(k)))
    spot_rows = [("NIFTY", d, 24000.0 + 150 * ((i * 7) % 5 - 2)) for i, d in enumerate(days)]
    led, bal = [], 100000.0
    for d in days:
        bal -= 12000.0
        led.append((d, 12000.0, 0, bal))
    seed(db_session, "u", fs, spot_rows, led)
    svc = _svc(db_session)
    a, b = svc.run_all("u", P), svc.run_all("u", P)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert all(v["available"] for v in a.values())
    assert a["foundation"]["reconciliation"]["totals"]["symbols"] > 0
