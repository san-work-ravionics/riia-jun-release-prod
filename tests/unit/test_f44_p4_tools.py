"""F44 P4 — the six new MCP tools (16 → 22): journey.get_current, journey.save, portfolio.pnl,
portfolio.sleeve_trace, fno.sigma_levels, market.asta_trace.

Catalogue + schemas, no ``user_id`` input, auth exactly as designed (journey / pnl need a user;
sleeve_trace / asta_trace answer the system identity without ``require_user``; sigma_levels is
``none`` + stdio), allow-list logging (event / source values; goal amounts as bare keys), no
network, coded errors.
"""
# ruff: noqa: F811 — pytest fixtures imported from a sibling module are redefined as test params
from __future__ import annotations

import asyncio
import json
import socket
from unittest.mock import patch

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

import rita.interfaces.mcp_tools as mt
from rita.interfaces.mcp_auth import TRANSPORTS, McpIdentity, identity_scope
from rita.interfaces.tools import ToolContext
from rita.repositories.asta_artifact import AstaArtifactRepository

from .test_f44_p3_mcp_tools import ALICE, STDIO, SYSTEM, _call, _err, calls, fake_models, tool_db  # noqa: F401

P4_TOOLS = {"journey.get_current", "journey.save", "portfolio.pnl", "portfolio.sleeve_trace",
            "fno.sigma_levels", "market.asta_trace"}
AUTH = {
    "journey.get_current": {"user", "system"}, "journey.save": {"user", "system"},
    "portfolio.pnl": {"user", "system"}, "portfolio.sleeve_trace": {"user", "system"},
    "fno.sigma_levels": {"none"}, "market.asta_trace": {"user", "system"},
}
GOAL = {"saved": True, "plan_updated_at": "2026-03-01T10:00:00Z", "goal_return": 0.07675,
        "horizon_years": 13.0, "goal_value": 264804.0}


@pytest.fixture
def no_asta(tmp_path, monkeypatch):
    repo = AstaArtifactRepository(tmp_path / "models", tmp_path / "input", "rita_ddqn_asta_{inst}_*.zip",
                                  "asta_labeled_dataset.csv")
    monkeypatch.setattr(AstaArtifactRepository, "from_settings", classmethod(lambda cls: repo))
    return repo


def test_registry_has_22_tools():
    assert P4_TOOLS <= set(mt.REGISTRY) and mt.tools_registered() == 22
    for name in P4_TOOLS:
        spec = mt.REGISTRY[name]
        assert spec.output_json_schema() is not None
        assert spec.auth == frozenset(AUTH[name]), name
        assert spec.stdio is (name == "fno.sigma_levels")
        assert "user_id" not in json.dumps(spec.input_json_schema())
    assert "journey.explain_pick" not in mt.REGISTRY and "portfolio.analytics" not in mt.REGISTRY


def test_transports_have_no_sse():
    assert TRANSPORTS == ("memory", "http", "stdio")


def test_new_allow_list_keys_and_no_amount_keys():
    assert {"event", "source", "tolerance", "since", "entry_date", "detail", "expected_version"} <= mt.SAFE_ARG_KEYS
    for k in ("goal_return", "goal_value", "ytd_return", "text", "goal", "selection", "proposal"):
        assert k not in mt.SAFE_ARG_KEYS


def test_journey_tools_need_a_user(tool_db):
    assert _err(_call(SYSTEM, "journey.get_current", {"location": "europe"})) == "forbidden"
    assert _err(_call(SYSTEM, "journey.save", {"location": "europe", "event": "start", "goal": GOAL})) == "forbidden"
    assert _err(_call(ALICE, "journey.get_current", {"location": "europe"})) == "not_found"
    res = _call(ALICE, "journey.save", {"location": "europe", "event": "start", "goal": GOAL})
    assert not res.isError and res.structuredContent["state"] == "goal_loaded"
    res = _call(ALICE, "journey.get_current", {"location": "europe"})
    assert res.structuredContent["version"] == 1 and res.structuredContent["goal_return"] == 0.07675
    # restart on the same plan → invalid_input (B1)
    assert _err(_call(ALICE, "journey.save", {"location": "europe", "event": "start", "goal": GOAL})) == "invalid_input"
    # a user_id argument is refused
    assert _err(_call(ALICE, "journey.get_current", {"location": "europe", "user_id": "bob"})) == "invalid_input"


def test_journey_is_per_user(tool_db):
    _call(ALICE, "journey.save", {"location": "europe", "event": "start", "goal": GOAL})
    bob = McpIdentity(transport="memory", caller="jarvis", user_id="bob")
    assert _err(_call(bob, "journey.get_current", {"location": "europe"})) == "not_found"


def test_pnl_needs_a_user_and_not_found_without_portfolio(tool_db):
    assert _err(_call(SYSTEM, "portfolio.pnl", {"location": "europe"})) == "forbidden"
    assert _err(_call(ALICE, "portfolio.pnl", {"location": "europe"})) == "not_found"
    assert _err(_call(ALICE, "portfolio.pnl", {"location": "europe", "source": "cash"})) == "invalid_input"


def test_sleeve_and_asta_answer_the_system_identity_without_require_user(tool_db, fake_models, no_asta):
    def refuse(self):
        raise AssertionError("must not call require_user")

    with patch.object(ToolContext, "require_user", refuse):
        st = _call(SYSTEM, "portfolio.sleeve_trace", {"location": "europe", "instrument": "E1", "detail": True})
        ex = _call(SYSTEM, "portfolio.sleeve_trace", {"location": "europe", "instrument": "E3"})
        at = _call(SYSTEM, "market.asta_trace", {"instrument": "NIFTY"})
    assert not st.isError, st.structuredContent
    o = st.structuredContent
    assert o["status"] == "ok" and o["tolerance_rule"] == "p3_tau_rule_single_sleeve"
    assert o["method"]["sl"].endswith("(config input, not a model output)")
    assert o["detail"]["rationale"] is not None and len(o["detail"]["dates"]) == len(o["detail"]["sleeve_value"])
    assert ex.structuredContent["status"] == "excluded" and ex.structuredContent["excluded_reason"] == "no_model"
    assert at.structuredContent["status"] == "no_model"


def test_sleeve_trace_outside_location_is_invalid_input(tool_db, fake_models):
    assert _err(_call(ALICE, "portfolio.sleeve_trace", {"location": "europe", "instrument": "U1"})) == "invalid_input"
    assert _err(_call(ALICE, "portfolio.sleeve_trace", {"location": "europe", "instrument": "../x"})) == "invalid_input"


def test_sigma_levels_is_on_stdio_and_open(tool_db):
    async def go():
        with identity_scope(STDIO):
            async with create_connected_server_and_client_session(mt.server) as s:
                return {t.name for t in (await s.list_tools()).tools}
    names = asyncio.run(go())
    assert "fno.sigma_levels" in names and not ((P4_TOOLS - {"fno.sigma_levels"}) & names)
    res = _call(STDIO, "fno.sigma_levels", {"instrument": "E1"})
    assert not res.isError and res.structuredContent["status"] == "no_price_data"
    assert res.structuredContent["method"].endswith("(statistical, not a model)")
    assert _err(_call(STDIO, "journey.get_current", {"location": "europe"})) == "forbidden"


def test_logging_holds_events_not_amounts(tool_db, calls):
    _call(ALICE, "journey.save", {"location": "europe", "event": "start", "goal": GOAL})
    row = calls[-1]
    assert row["args_summary"] == "location=europe, event=start, goal"
    assert row["result_summary"] == "state=goal_loaded version=1"
    for leak in ("0.07675", "264804", "264,804", "13.0"):
        assert leak not in row["args_summary"] + row["result_summary"]


def test_no_network_on_any_p4_tool(tool_db, fake_models, no_asta, monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("network access")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    for name, args in (
        ("journey.save", {"location": "europe", "event": "start", "goal": GOAL}),
        ("journey.get_current", {"location": "europe"}),
        ("portfolio.sleeve_trace", {"location": "europe", "instrument": "E2"}),
        ("fno.sigma_levels", {"instrument": "E1"}),
        ("market.asta_trace", {"instrument": "NIFTY"}),
    ):
        res = _call(ALICE, name, args)
        assert not res.isError, (name, res.structuredContent)


def test_health_reports_22_tools_and_jarvis(client):
    body = client.get("/health").json()
    assert body["mcp"] == {"tools_registered": 22, "auth": "on", "transports": ["http", "memory"]}
    assert body["jarvis"]["intents"] == 12 and body["jarvis"]["chat_model"] in ("ready", "not_loaded")
