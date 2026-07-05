"""Unit tests for Feature 32 Phase 4 — outcome evaluation + backfill.

Covers the pure evaluator (build/parse, direction → verdict, maturity, not_evaluable),
recommendation capture, the repository helpers, and the end-to-end backfill service.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pandas as pd
import pytest

from rita.core.agent_outcomes import (
    build_recommendation,
    parse_recommendation,
    derive_recommendation,
    evaluate_outcome,
    EVAL_HORIZON_DAYS,
)
from rita.models.agent_performance import AgentPerformance
from rita.repositories.agent_performance import AgentPerformanceRepository
from rita.services.agent_outcome_backfill import backfill_agent_outcomes


def _price(closes, start="2020-01-01"):
    idx = pd.date_range(start=start, periods=len(closes), freq="B")
    return pd.DataFrame({"Close": closes}, index=idx)


# ── build / parse ─────────────────────────────────────────────────────────────

def test_build_parse_roundtrip():
    rec = build_recommendation("ASML", "up")
    assert parse_recommendation(rec) == {"instrument": "ASML", "dir": "up"}


def test_parse_tolerates_none_and_junk():
    assert parse_recommendation(None) == {}
    assert parse_recommendation("garbage") == {}


# ── evaluate_outcome: direction → verdict ─────────────────────────────────────

def test_bullish_call_matches_on_rise_misses_on_fall():
    h = EVAL_HORIZON_DAYS["trend_direction"]
    rising = _price([100 + i for i in range(h + 3)])
    falling = _price([100 - i for i in range(h + 3)])
    t0 = rising.index[0].to_pydatetime()
    assert evaluate_outcome("trend_direction", build_recommendation("X", "up"), t0, rising) == "match"
    assert evaluate_outcome("trend_direction", build_recommendation("X", "up"), t0, falling) == "miss"


def test_bearish_call_is_mirror_of_bullish():
    h = EVAL_HORIZON_DAYS["trend_direction"]
    falling = _price([100 - i for i in range(h + 3)])
    t0 = falling.index[0].to_pydatetime()
    assert evaluate_outcome("trend_direction", build_recommendation("X", "down"), t0, falling) == "match"


def test_flat_move_is_neutral_within_dead_band():
    h = EVAL_HORIZON_DAYS["trend_direction"]
    flat = _price([100.0] * (h + 3))
    t0 = flat.index[0].to_pydatetime()
    assert evaluate_outcome("trend_direction", build_recommendation("X", "up"), t0, flat) == "neutral"


def test_hedge_matches_on_decline_nohedge_mirrors():
    h = EVAL_HORIZON_DAYS["hedge_advice"]
    falling = _price([100 - i for i in range(h + 3)])
    t0 = falling.index[0].to_pydatetime()
    assert evaluate_outcome("hedge_advice", build_recommendation("X", "hedge"), t0, falling) == "match"
    assert evaluate_outcome("hedge_advice", build_recommendation("X", "nohedge"), t0, falling) == "miss"


# ── evaluate_outcome: maturity + not_evaluable ────────────────────────────────

def test_immature_row_returns_none_pending():
    h = EVAL_HORIZON_DAYS["trend_direction"]
    df = _price([100 + i for i in range(h + 3)])
    # created_at at the very last bar → no forward bars → still maturing.
    t_last = df.index[-1].to_pydatetime()
    assert evaluate_outcome("trend_direction", build_recommendation("X", "up"), t_last, df) is None


def test_not_evaluable_intent_and_dir_none():
    df = _price([100 + i for i in range(30)])
    t0 = df.index[0].to_pydatetime()
    # hypothetical intent → not_evaluable regardless of direction
    assert evaluate_outcome("stress_crash_20", build_recommendation("X", "up"), t0, df) == "not_evaluable"
    # evaluable intent but no captured direction → not_evaluable
    assert evaluate_outcome("trend_direction", build_recommendation("X", "none"), t0, df) == "not_evaluable"


# ── derive_recommendation ─────────────────────────────────────────────────────

def test_derive_directional_intents():
    df = _price([100 + i for i in range(70)])
    df["trend_score"] = 0.5
    df["rsi_14"] = 50.0
    assert parse_recommendation(derive_recommendation("trend_direction", "ASML", df))["dir"] == "up"
    assert parse_recommendation(derive_recommendation("return_1m", "ASML", df))["dir"] == "up"
    assert parse_recommendation(derive_recommendation("invest_now", "ASML", df))["dir"] == "buy"
    # hypothetical / report intents capture as not-evaluable
    assert parse_recommendation(derive_recommendation("market_sentiment", "ASML", df))["dir"] == "none"


def test_derive_hedge_flags_on_recent_drawdown():
    rising = _price([100 + i for i in range(70)])               # near highs → nohedge
    dropped = _price([100 + i for i in range(60)] + [120 - 8 * i for i in range(10)])  # recent dip
    assert parse_recommendation(derive_recommendation("hedge_advice", "X", rising))["dir"] == "nohedge"
    assert parse_recommendation(derive_recommendation("hedge_advice", "X", dropped))["dir"] == "hedge"


# ── repository helpers ────────────────────────────────────────────────────────

def _add(db, intent, rec, created, agent="Technical Analyst"):
    row = AgentPerformance(
        perf_id=str(uuid.uuid4()), agent_name=agent, intent=intent,
        recommendation=rec, outcome_status=None, created_at=created,
    )
    db.add(row)
    db.commit()
    return row.perf_id


def test_pending_outcomes_and_set_outcome(db_session):
    repo = AgentPerformanceRepository(db_session)
    pid = _add(db_session, "trend_direction", build_recommendation("X", "up"), datetime(2020, 1, 1))
    assert [r.perf_id for r in repo.pending_outcomes()] == [pid]
    assert repo.set_outcome(pid, "match") is True
    assert repo.pending_outcomes() == []            # no longer null
    assert repo.set_outcome("does-not-exist", "match") is False


# ── backfill end-to-end ───────────────────────────────────────────────────────

def test_backfill_scores_matured_leaves_immature_pending(db_session):
    h = EVAL_HORIZON_DAYS["trend_direction"]
    df = _price([100 + i for i in range(h + 50)])
    loader = lambda _inst: df

    matured = df.index[0].to_pydatetime()        # plenty of forward bars
    immature = df.index[-1].to_pydatetime()       # no forward bars
    _add(db_session, "trend_direction", build_recommendation("X", "up"), matured)
    _add(db_session, "stress_crash_20", build_recommendation("X", "none"), matured, agent="Scenario Analyst")
    _add(db_session, "trend_direction", build_recommendation("X", "up"), immature)

    tally = backfill_agent_outcomes(db_session, price_loader=loader)

    assert tally.get("match") == 1
    assert tally.get("not_evaluable") == 1
    assert tally.get("pending") == 1
    # the immature row is still NULL → resurfaces next run
    assert len(AgentPerformanceRepository(db_session).pending_outcomes()) == 1
