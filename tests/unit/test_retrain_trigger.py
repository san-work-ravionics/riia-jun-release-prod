"""Unit tests for Feature 32 Phase 4.1 — risk-adjusted (Sortino) retrain trigger."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pandas as pd
import pytest

from rita.core.agent_outcomes import advised_return, build_recommendation, EVAL_HORIZON_DAYS
from rita.models.agent_performance import AgentPerformance
from rita.services.retrain_trigger import _sortino, evaluate_retrain_trigger

_AGENT = "Execution Analyst"
_INTENT = "hedge_advice"
_H = EVAL_HORIZON_DAYS[_INTENT]


# ── pure metric ───────────────────────────────────────────────────────────────

def test_sortino_basic_and_edge_cases():
    assert _sortino([0.03, 0.03, -0.02, 0.03]) > 0      # net positive, some downside
    assert _sortino([-0.02, -0.02, -0.02]) < 0          # net negative → negative Sortino
    assert _sortino([0.01, 0.02, 0.03]) is None         # no downside → undefined
    assert _sortino([0.01]) is None                     # < 2 points


def test_advised_return_hedge_caps_downside_nohedge_full():
    # 6 business days, −10% over the horizon
    idx = pd.date_range("2025-01-01", periods=_H + 1, freq="B")
    down = pd.DataFrame({"Close": [100.0] * _H + [90.0]}, index=idx)
    t0 = idx[0].to_pydatetime()
    nohedge = advised_return(_INTENT, build_recommendation("X", "nohedge"), t0, down)
    hedge = advised_return(_INTENT, build_recommendation("X", "hedge"), t0, down)
    assert nohedge == pytest.approx(-0.10, abs=1e-9)     # full downside exposure
    assert hedge == pytest.approx(-0.10 * 0.4, abs=1e-9)  # 60% of the loss removed
    assert hedge > nohedge                                # hedging hurt less


# ── trigger integration ───────────────────────────────────────────────────────

def _price_from_fwd_returns(fwd_returns):
    """Build a price frame so row k (at bar k·H) realises forward return fwd_returns[k]."""
    closes = [100.0]
    for f in fwd_returns:
        base = closes[-1]
        closes += [base] * (_H - 1)        # filler bars (irrelevant to non-overlapping rows)
        closes.append(base * (1.0 + f))
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=len(closes))
    df = pd.DataFrame({"Close": closes}, index=idx)
    dates = [idx[k * _H].to_pydatetime() for k in range(len(fwd_returns))]
    return df, dates


def _seed(db, dates):
    for d in dates:
        db.add(AgentPerformance(
            perf_id=str(uuid.uuid4()), agent_name=_AGENT, intent=_INTENT,
            recommendation=build_recommendation("X", "nohedge"),
            outcome_status="match", created_at=d,   # any evaluated verdict → row is "scored"
        ))
    db.commit()


def test_trigger_insufficient_samples(db_session):
    df, dates = _price_from_fwd_returns([0.02])
    _seed(db_session, dates)
    d = evaluate_retrain_trigger(db_session, window_days=400, min_samples=5,
                                 price_loader=lambda _i: df)
    assert d["should_retrain"] is False
    assert "insufficient samples" in d["reason"]


def test_trigger_fires_when_recs_lose_risk_adjusted(db_session):
    # Six no-hedge calls into a falling market → negative advised returns → Sortino < 0.
    df, dates = _price_from_fwd_returns([-0.03] * 6)
    _seed(db_session, dates)
    d = evaluate_retrain_trigger(db_session, window_days=400, min_samples=5,
                                 sortino_floor=0.0, price_loader=lambda _i: df)
    assert d["current_sortino"] < 0
    assert d["should_retrain"] is True
    assert "below floor" in d["reason"]


def test_trigger_quiet_when_risk_adjusted_healthy(db_session):
    # Mostly-up with a little downside → positive Sortino → no retrain.
    df, dates = _price_from_fwd_returns([0.03, 0.03, 0.03, 0.03, -0.02, 0.03])
    _seed(db_session, dates)
    d = evaluate_retrain_trigger(db_session, window_days=400, min_samples=5,
                                 sortino_floor=0.0, price_loader=lambda _i: df)
    assert d["current_sortino"] > 0
    assert d["should_retrain"] is False
    assert "healthy" in d["reason"]
