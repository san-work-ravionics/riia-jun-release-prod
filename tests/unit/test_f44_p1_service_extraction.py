"""F44 P1 — route logic moved into services with no behaviour change (one parity test each).

- chat ``_get_df``          → ``services/market_analysis_service.get_indicator_df``
- fno hedge-plan GET        → ``HedgePlanService.get_for_user``
- optimal-allocation route  → ``OptimalAllocationService.allocate``
- ``RetirementPlanService.load_with_result`` gains ``location`` (default unchanged)

Each parity test compares the new path with the old inline logic (copied here verbatim) on the
same data.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from rita.auth import get_current_user
from rita.main import app
from rita.models.instrument import InstrumentModel
from rita.models.user import UserModel
from rita.models.user_hedge_plan import UserHedgePlanModel
from rita.models.user_portfolio_key import UserPortfolioKeyModel
from rita.repositories.user_hedge_plan import UserHedgePlanRepo
from rita.repositories.user_portfolio_key import UserPortfolioKeyRepo
from rita.schemas.portfolio_optimizer import OptimalAllocationResponse
from rita.schemas.user_hedge_plan import HedgePlanOut


# ── chat loader ────────────────────────────────────────────────────────────────

def test_chat_loader_is_the_service_function():
    from rita.api.v1.workflow import chat
    from rita.services.market_analysis_service import get_indicator_df

    assert chat._get_df is get_indicator_df


def test_indicator_df_parity_with_old_inline_loader():
    """The moved loader returns exactly what the old chat._get_df computed."""
    import os
    from pathlib import Path

    import pandas as pd

    from rita.config import get_settings
    from rita.core.data_loader import load_ohlcv_csv
    from rita.core.data_understanding import find_instrument_csv
    from rita.core.technical_analyzer import calculate_indicators
    from rita.services import market_analysis_service as svc

    try:
        primary = str(find_instrument_csv("NIFTY"))
    except FileNotFoundError:
        pytest.skip("no NIFTY price CSV in this checkout")
    assert os.path.exists(primary)

    # Old inline algorithm (chat.py before F44 P1)
    manual = Path(get_settings().data.input_dir) / "DAILY-DATA" / "nifty_manual.csv"
    raw = load_ohlcv_csv(primary)
    if manual.exists():
        raw = pd.concat([raw, load_ohlcv_csv(str(manual))])
        raw = raw[~raw.index.duplicated(keep="last")].sort_index()
    expected = calculate_indicators(raw)

    svc._market_signals_cache.pop("NIFTY", None)
    got = svc.get_indicator_df("nifty")
    pd.testing.assert_frame_equal(got, expected)
    assert svc.get_indicator_df("NIFTY") is got  # cached until a source mtime changes


# ── hedge-plan GET ─────────────────────────────────────────────────────────────

def _old_get_hedge_plan(user, db):
    """Old route body (fno_hedge_plan.py GET before F44 P1)."""
    key = UserPortfolioKeyRepo(db).find_by_user_id(user.id)
    if key is None:
        return None
    plan = UserHedgePlanRepo(db).find_by_key_id(key.key_id)
    if plan is None:
        return None
    return HedgePlanOut.model_validate(plan)


@pytest.fixture
def as_user():
    def _set(uid: str):
        app.dependency_overrides[get_current_user] = lambda: UserModel(id=uid)
    yield _set
    app.dependency_overrides.pop(get_current_user, None)


def test_hedge_plan_get_parity(client, db_session, as_user):
    from rita.services.hedge_plan_service import HedgePlanService

    db_session.add(UserModel(id="u1"))
    db_session.add(UserModel(id="u2"))
    db_session.add(UserPortfolioKeyModel(key_id="k1", user_id="u1"))
    db_session.add(UserHedgePlanModel(
        key_id="k1", hedged_ids=["ASML", "NIFTY"], coverage=70, scenario_tab="pp",
        duration="1y", last_step="save", selections={"ASML": "put"},
        updated_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    ))
    db_session.commit()

    for uid in ("u1", "u2", "nobody"):
        user = UserModel(id=uid)
        old = _old_get_hedge_plan(user, db_session)
        new = HedgePlanService(db_session).get_for_user(user)
        assert (old is None) == (new is None)
        if old is not None:
            assert new.model_dump() == old.model_dump()
        as_user(uid)
        resp = client.get("/api/v1/experience/fno/hedge-plan")
        assert resp.status_code == 200
        expected = None if old is None else old.model_dump(mode="json")
        assert resp.json() == expected


# ── optimal allocation ─────────────────────────────────────────────────────────

def _old_instrument_input(db):
    """Old route body (optimal_allocation.py before F44 P1) — the solver input it built."""
    from rita.repositories.instrument import InstrumentRepository

    return [
        {
            "instrument_id": inst.instrument_id,
            "name": inst.name,
            "ticker": inst.instrument_id,
            "yf_ticker": getattr(inst, "yf_ticker", inst.instrument_id),
        }
        for inst in InstrumentRepository(db).read_all()
        if getattr(inst, "is_available", True)
    ]


def test_optimal_allocation_parity(client, db_session):
    from rita.services.optimal_allocation_service import OptimalAllocationService

    now = datetime.now(timezone.utc)
    db_session.add_all([
        InstrumentModel(instrument_id="NIFTY", name="Nifty 50", exchange="NSE", country_code="IN",
                        is_available=True, yf_ticker="^NSEI", created_at=now),
        InstrumentModel(instrument_id="ASML", name="ASML", exchange="AMS", country_code="NL",
                        is_available=True, yf_ticker="ASML.AS", created_at=now),
        InstrumentModel(instrument_id="ATHER", name="Ather", exchange="NSE", country_code="IN",
                        is_available=False, created_at=now),
    ])
    db_session.commit()
    expected_input = _old_instrument_input(db_session)

    seen = []

    def fake_optimize(instruments, horizon):
        seen.append((instruments, horizon))
        return OptimalAllocationResponse(
            horizon=horizon, instrument_count=len(instruments), solver_status="OPTIMAL",
            estimated_sharpe=1.0, estimated_mdd_pct=-5.0, allocations=[],
        )

    with patch("rita.services.optimal_allocation_service.optimize_allocation", fake_optimize):
        direct = OptimalAllocationService(db_session).allocate("medium_term")
        resp = client.get("/api/v1/experience/rita/optimal-allocation?horizon=medium_term")

    assert resp.status_code == 200
    assert resp.json() == direct.model_dump(mode="json")
    assert seen[0] == (expected_input, "medium_term")
    assert seen[1] == (expected_input, "medium_term")
    assert {i["instrument_id"] for i in expected_input} == {"NIFTY", "ASML"}


def test_optimal_allocation_error_fallback_unchanged(db_session):
    from rita.services.optimal_allocation_service import OptimalAllocationService

    with patch("rita.services.optimal_allocation_service.optimize_allocation",
               side_effect=RuntimeError("boom")):
        out = OptimalAllocationService(db_session).allocate("short_term")
    assert out.solver_status == "ERROR"
    assert out.allocations == [] and out.instrument_count == 0


# ── retirement plan location ───────────────────────────────────────────────────

def test_load_with_result_location(db_session):
    from rita.services.retirement_plan_service import PlanValidationError, RetirementPlanService

    svc = RetirementPlanService(db_session)
    default = svc.load_with_result(None)
    assert svc.load_with_result(None, None).model_dump() == default.model_dump()
    india = svc.load_with_result(None, "india")
    assert india.location == "india" and india.currency == "INR"
    with pytest.raises(PlanValidationError):
        svc.load_with_result(None, "mars")
