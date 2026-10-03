"""Agent Builds endpoint must tolerate both run-log formats of ``actual_tokens``.

Regression: run logs with a bare-int ``actual_tokens`` made AgentOut validation
raise and the whole /api/experience/ops/agent-builds endpoint return 500.
"""
import json
from pathlib import Path

import pytest

from rita.api.experience.ops import _normalize_actual_tokens
from rita.schemas.agent_builds import AgentOut

_RUNS = Path(__file__).resolve().parents[2] / "data" / "agent-ops" / "runs"


def test_dict_passes_through():
    raw = {"total_tokens": 100, "tool_uses": 3}
    assert _normalize_actual_tokens({"actual_tokens": raw}) == raw


def test_bare_int_becomes_dict_with_tool_uses():
    out = _normalize_actual_tokens({"actual_tokens": 55148, "tool_uses": 7})
    assert out == {"total_tokens": 55148, "tool_uses": 7}


def test_bare_int_without_tool_uses():
    assert _normalize_actual_tokens({"actual_tokens": 10}) == {"total_tokens": 10, "tool_uses": None}


@pytest.mark.parametrize("agent", [{}, {"actual_tokens": None}, {"actual_tokens": "x"}, {"actual_tokens": True}])
def test_missing_or_invalid_is_none(agent):
    assert _normalize_actual_tokens(agent) is None


def test_every_committed_run_log_validates_as_agentout():
    files = sorted(_RUNS.glob("run-*.json"))
    assert files, "no run logs found"
    for path in files:
        for agent in json.loads(path.read_text()).get("agents", []):
            AgentOut(
                role=agent["role"],
                status=agent.get("status", "unknown"),
                actual_tokens=_normalize_actual_tokens(agent),
            )
