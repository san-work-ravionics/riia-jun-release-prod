"""Unit tests for Feature 32 — agent-performance endpoint + instrumentation hook.

Covers:
- GET /api/v1/experience/rita/agent-performance happy path (exactly 7 agents).
- Empty table edge case: 7 agents, invocation_count_30d=0, outcome_match_rate=None
  (NOT 0.0) so the dashboard renders a dash, not a misleading 0%.
- Rows present but all outcome_status NULL → rate stays None (no divide-by-zero).
- Fire-and-forget hook: record_agent_performance never raises (unmapped intent,
  bad input) and the background worker swallows DB write failures.
- INTENT_TO_AGENT mapping: mapped intents resolve to one of the 7 canonical
  names; an unmapped intent yields no agent (skip).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from rita.core.classifier import (
    CANONICAL_AGENTS,
    INTENT_TO_AGENT,
    Intent,
    IntentResult,
    _agent_perf_worker,
    record_agent_performance,
)
from rita.models.agent_performance import AgentPerformance

_NOW = datetime.now(timezone.utc)
_ENDPOINT = "/api/v1/experience/rita/agent-performance"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add_row(db, agent_name, intent="return_1m", outcome_status=None, age_days=1):
    import uuid

    row = AgentPerformance(
        perf_id=str(uuid.uuid4()),
        agent_name=agent_name,
        intent=intent,
        recommendation=None,
        outcome_status=outcome_status,
        training_run_id=None,
        created_at=_NOW - timedelta(days=age_days),
    )
    db.add(row)
    db.commit()
    return row


def _intent_result(intent_name: str) -> IntentResult:
    return IntentResult(
        intent=Intent(name=intent_name, seeds=[], handler="return_estimates"),
        confidence=0.9,
        low_confidence=False,
    )


# ---------------------------------------------------------------------------
# Endpoint — happy path
# ---------------------------------------------------------------------------

def test_endpoint_returns_exactly_seven_agents(client):
    resp = client.get(_ENDPOINT)
    assert resp.status_code == 200
    agents = resp.json()["agents"]
    assert len(agents) == 7
    names = [a["agent_name"] for a in agents]
    assert names == CANONICAL_AGENTS


def test_endpoint_counts_recorded_invocations(client, db_session):
    _add_row(db_session, "Financial Goal")
    _add_row(db_session, "Financial Goal")
    _add_row(db_session, "Sentiment Analyst")

    resp = client.get(_ENDPOINT)
    assert resp.status_code == 200
    by_name = {a["agent_name"]: a for a in resp.json()["agents"]}

    assert by_name["Financial Goal"]["invocation_count_30d"] == 2
    assert by_name["Sentiment Analyst"]["invocation_count_30d"] == 1
    # Agents with no rows still present with 0.
    assert by_name["Technical Analyst"]["invocation_count_30d"] == 0


# ---------------------------------------------------------------------------
# Endpoint — empty-table edge case (key contract requirement)
# ---------------------------------------------------------------------------

def test_empty_table_all_seven_with_null_rate_not_zero(client):
    """Empty agent_performance → 7 agents, count 0, rate None (NOT 0.0)."""
    resp = client.get(_ENDPOINT)
    assert resp.status_code == 200
    agents = resp.json()["agents"]
    assert len(agents) == 7
    for a in agents:
        assert a["invocation_count_30d"] == 0
        assert a["outcome_match_rate"] is None  # never 0.0
        assert a["outcome_match_rate"] != 0.0
        assert a["trend_vs_prior_30d"] is None
        assert a["gap_status"]  # static label present


def test_rows_with_no_outcome_keep_rate_none(client, db_session):
    """Rows exist but outcome_status all NULL → rate None, not 0.0 (no div-by-zero)."""
    _add_row(db_session, "Outcome Analyst", outcome_status=None)
    _add_row(db_session, "Outcome Analyst", outcome_status=None)

    resp = client.get(_ENDPOINT)
    by_name = {a["agent_name"]: a for a in resp.json()["agents"]}
    assert by_name["Outcome Analyst"]["invocation_count_30d"] == 2
    assert by_name["Outcome Analyst"]["outcome_match_rate"] is None


# ---------------------------------------------------------------------------
# Fire-and-forget hook — must never raise
# ---------------------------------------------------------------------------

def test_record_agent_performance_unmapped_intent_skips_silently():
    """Unmapped intent → no thread spawned, no exception."""
    with patch("rita.core.classifier.threading.Thread") as mock_thread:
        record_agent_performance(_intent_result("nonexistent_intent"))
    mock_thread.assert_not_called()


def test_record_agent_performance_mapped_intent_spawns_worker_with_correct_agent():
    """Mapped intent → background thread started with the correct canonical agent."""
    with patch("rita.core.classifier.threading.Thread") as mock_thread:
        record_agent_performance(_intent_result("return_1m"))
    mock_thread.assert_called_once()
    args = mock_thread.call_args.kwargs["args"]
    assert args[0] == "Financial Goal"   # resolved agent_name
    assert args[1] == "return_1m"        # intent name
    assert mock_thread.call_args.kwargs["daemon"] is True
    mock_thread.return_value.start.assert_called_once()


def test_record_agent_performance_bad_input_does_not_raise():
    """Garbage / None input must be swallowed — fire-and-forget never propagates."""
    # result=None → AttributeError inside, must be swallowed.
    record_agent_performance(None)  # type: ignore[arg-type]
    # result with no .intent.name attribute path.
    record_agent_performance(MagicMock(intent=MagicMock(name="x", spec=[])))


def test_worker_swallows_db_write_failure():
    """The background worker must swallow a failing DB write and never raise."""
    failing_repo = MagicMock()
    failing_repo.return_value.record.side_effect = RuntimeError("db boom")
    mock_session = MagicMock()

    with patch(
        "rita.repositories.agent_performance.AgentPerformanceRepository",
        failing_repo,
    ), patch("rita.database.SessionLocal", return_value=mock_session):
        # Must not raise despite record() blowing up.
        _agent_perf_worker("Financial Goal", "return_1m", None, None)

    failing_repo.return_value.record.assert_called_once()
    mock_session.close.assert_called_once()  # session always closed in finally


# ---------------------------------------------------------------------------
# INTENT_TO_AGENT mapping
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "intent_name,expected_agent",
    [
        ("return_1m", "Financial Goal"),
        ("market_sentiment", "Sentiment Analyst"),
        ("rsi_reading", "Technical Analyst"),
        ("allocation_level", "Strategy Analyst"),
        ("stress_crash_20", "Scenario Analyst"),
        ("invest_now", "Execution Analyst"),
        ("backtest_performance", "Outcome Analyst"),
    ],
)
def test_mapped_intent_resolves_to_canonical_agent(intent_name, expected_agent):
    resolved = INTENT_TO_AGENT.get(intent_name)
    assert resolved == expected_agent
    assert resolved in CANONICAL_AGENTS


def test_unmapped_intent_yields_no_agent():
    assert INTENT_TO_AGENT.get("nonexistent_intent") is None


def test_all_mapping_targets_are_canonical():
    """Every right-hand value in the map is one of the 7 canonical names."""
    assert set(INTENT_TO_AGENT.values()).issubset(set(CANONICAL_AGENTS))
    assert len(CANONICAL_AGENTS) == 7
