"""F44 P4 — Jarvis routes A1–A6 over the real in-memory MCP stack (test DB, fake P3 models).

401 without a token, 422 on bad input, the **session-owner 404** (P1 Finding 2 class), payload ⇔
schema, the message's ``tool_calls`` ids resolve to logged ``mcp_calls`` rows, and the removed
SSE transport answers 404.
"""
# ruff: noqa: F811 — pytest fixtures imported from a sibling module are redefined as test params
from __future__ import annotations

import pytest

from rita.auth import create_access_token
from rita.core import journey_intents as ji
from rita.core.journey_intents import JourneyIntentResult
from rita.database import get_db
from rita.main import app
from rita.models.jarvis import JarvisMessageModel
from rita.models.user import UserModel
from rita.repositories.asta_artifact import AstaArtifactRepository
from rita.schemas.jarvis import InstrumentPageOut, MessageOut, PortfolioPageOut, SessionOut, StateOut, WarmupOut

from .test_f44_p3_mcp_tools import calls, fake_models, tool_db  # noqa: F401

A1, A2, A3 = "/api/v1/workflow/jarvis/warmup", "/api/v1/workflow/jarvis/session", "/api/v1/workflow/jarvis/message"
A4, A5, A6 = "/api/v1/experience/jarvis/state", "/api/v1/experience/jarvis/portfolio", "/api/v1/experience/jarvis/instrument"


def _h(user: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


@pytest.fixture
def api(tool_db, fake_models, calls, tmp_path, monkeypatch):
    db = tool_db()
    db.add(UserModel(id="bob"))
    db.commit()
    db.close()

    def _get_db():
        s = tool_db()
        try:
            yield s
        finally:
            s.close()

    def classify(text, threshold):
        known = {"use my goal": "take_goal", "hi": "help"}
        if text in known:
            return JourneyIntentResult(intent=known[text], confidence=0.9, low_confidence=False)
        return JourneyIntentResult(intent="help", confidence=0.1, low_confidence=True)

    monkeypatch.setattr(ji, "classify_journey", classify)
    repo = AstaArtifactRepository(tmp_path / "m", tmp_path / "i", "rita_ddqn_asta_{inst}_*.zip", "x.csv")
    monkeypatch.setattr(AstaArtifactRepository, "from_settings", classmethod(lambda cls: repo))
    app.dependency_overrides[get_db] = _get_db
    from fastapi.testclient import TestClient
    try:
        yield TestClient(app), tool_db, calls
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.parametrize("method,path", [("post", A1), ("post", A2), ("post", A3),
                                         ("get", A4 + "?location=europe"), ("get", A5 + "?location=europe"),
                                         ("get", A6 + "?location=europe&instrument=E1")])
def test_401_without_token(api, method, path):
    client, _, _ = api
    r = client.post(path, json={}) if method == "post" else client.get(path)
    assert r.status_code == 401


@pytest.mark.parametrize("method,path,body", [
    ("post", A2, {"location": "mars"}),
    ("post", A2, {"location": "europe", "user_id": "bob"}),
    ("post", A3, {"session_id": "s", "text": "", "location": "europe"}),
    ("post", A3, {"session_id": "s", "text": "x" * 501, "location": "europe"}),
    ("get", A4 + "?location=mars", None),
    ("get", A5, None),
    ("get", A6 + "?location=europe&instrument=..%2Fetc", None),
    ("get", A6 + "?location=europe&instrument=" + "A" * 33, None),
])
def test_422_on_bad_input(api, method, path, body):
    client, _, _ = api
    kw = {"json": body} if method == "post" else {}
    assert getattr(client, method)(path, headers=_h("alice"), **kw).status_code == 422


def test_warmup_ready_and_503(api, monkeypatch):
    client, _, _ = api
    monkeypatch.setattr(ji, "build_index", lambda: 12)
    r = client.post(A1, headers=_h("alice"))
    assert r.status_code == 200 and WarmupOut(**r.json()).intents == 12

    def boom():
        raise OSError("no model")

    monkeypatch.setattr(ji, "build_index", boom)
    r = client.post(A1, headers=_h("alice"))
    assert r.status_code == 503 and r.json()["detail"] == "chat model unavailable"


def test_session_owner_404_and_message_flow(api):
    client, maker, calls = api
    r = client.post(A2, json={"location": "europe"}, headers=_h("alice"))
    assert r.status_code == 200
    sid = SessionOut(**r.json()).session_id
    # another user's session id → 404, never a reply
    r = client.post(A3, json={"session_id": sid, "text": "hi", "location": "europe"}, headers=_h("bob"))
    assert r.status_code == 404 and r.json()["detail"] == "session not found"
    r = client.post(A3, json={"session_id": "missing", "text": "hi", "location": "europe"}, headers=_h("alice"))
    assert r.status_code == 404
    # the owner
    r = client.post(A3, json={"session_id": sid, "text": "use my goal", "location": "europe"}, headers=_h("alice"))
    assert r.status_code == 200, r.text
    out = MessageOut(**r.json())
    assert out.reply.template_id == "take_goal.no_plan.v1" and out.journey.state == "no_goal"
    ids = [c.mcp_call_id for c in out.reply.tool_calls]
    logged = {row["call_id"] for row in calls}
    assert ids and set(ids) <= logged                     # tool_calls resolve to mcp_calls rows
    assert all(row["caller"] == "jarvis" for row in calls if row["call_id"] in ids)
    db = maker()
    rows = db.query(JarvisMessageModel).filter_by(session_id=sid).all()
    db.close()
    assert len(rows) == 2 and any(r.tool_calls for r in rows)
    # bob cannot read alice's state either: his own A4 has no session, no journey
    st = StateOut(**client.get(A4 + "?location=europe", headers=_h("bob")).json())
    assert st.session is None and st.journey is None
    st = StateOut(**client.get(A4 + "?location=europe", headers=_h("alice")).json())
    assert st.session.session_id == sid and len(st.messages) == 2 and st.journey.state == "no_goal"
    assert st.currency == "EUR" and st.location_name == "Europe"


def test_low_confidence_calls_no_tool(api):
    client, _, calls = api
    sid = client.post(A2, json={"location": "europe"}, headers=_h("alice")).json()["session_id"]
    calls.clear()
    r = client.post(A3, json={"session_id": sid, "text": "blorp", "location": "europe"}, headers=_h("alice"))
    out = MessageOut(**r.json())
    assert out.reply.low_confidence and out.reply.tool_calls == [] and calls == []


def test_portfolio_and_instrument_payloads(api):
    client, _, _ = api
    r = client.get(A5 + "?location=europe", headers=_h("alice"))
    assert r.status_code == 200, r.text
    pf = PortfolioPageOut(**r.json())
    assert pf.pnl_source == "none" and pf.perf is None and pf.required is None
    assert {e.engine for e in pf.engines} >= {"rita", "asta", "fno"}
    r = client.get(A6 + "?location=europe&instrument=e1", headers=_h("alice"))
    assert r.status_code == 200, r.text
    inst = InstrumentPageOut(**r.json())
    assert inst.instrument_id == "E1" and [e.engine for e in inst.engines] == ["rita", "fno", "asta"]
    rita = inst.engines[0]
    assert rita.status == "ok" and rita.model_based and rita.prices and rita.series.sleeve_value
    assert rita.levels.target is None and rita.levels.stop_loss is not None
    assert inst.engines[2].status == "no_model"
    assert client.get(A6 + "?location=europe&instrument=U1", headers=_h("alice")).status_code == 404


@pytest.mark.parametrize("path", ["/mcp/sse", "/mcp/messages/"])
def test_sse_transport_is_gone(api, path):
    client, _, _ = api
    assert client.get(path, headers=_h("alice")).status_code == 404
    assert client.post(path, headers=_h("alice"), json={}).status_code in (404, 405)
