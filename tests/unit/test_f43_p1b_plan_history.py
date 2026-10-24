"""F43 Phase 1b — per-user plan result + append-only plan history.

GET /api/experience/invest-game/retirement-plan/result
GET /api/experience/invest-game/retirement-plan/history
GET /api/experience/invest-game/retirement-plan/history/{history_id}
PUT /api/v1/workflow/invest-game/retirement-plan  (now also appends a history row)
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from rita.auth import get_current_user, get_optional_user
from rita.main import app
from rita.models.user import UserModel
from rita.models.user_retirement_plan import UserRetirementPlanModel
from rita.models.user_retirement_plan_history import UserRetirementPlanHistoryModel

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "what_i_need_golden.json"
GOLDEN = json.loads(_FIXTURE.read_text(encoding="utf-8"))
DEFAULTS = GOLDEN["scenarios"]["defaults"]["input"]
DEFAULT_OUT = GOLDEN["scenarios"]["defaults"]["output"]

CALC = "/api/experience/invest-game/retirement-plan/calculate"
RESULT = "/api/experience/invest-game/retirement-plan/result"
HISTORY = "/api/experience/invest-game/retirement-plan/history"
SAVE = "/api/v1/workflow/invest-game/retirement-plan"


def _as(user_id: str | None):
    user = UserModel(id=user_id) if user_id else None
    app.dependency_overrides[get_optional_user] = lambda: user
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    else:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_optional_user, None)


def _inp(**kw) -> dict:
    d = copy.deepcopy(DEFAULTS)
    d.update(kw)
    return d


# ── result ───────────────────────────────────────────────────────────────────


def test_result_no_user_is_defaults_with_calculated_result(client):
    r = client.get(RESULT)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["saved"] is False
    assert d["inputs"]["need"] == DEFAULTS["need"]
    assert d["result"]["atRet"]["monthly"] == pytest.approx(DEFAULT_OUT["atRet"]["monthly"], abs=1e-6)
    assert d["result"]["portfolio"]["corpusOut"] == 119


def test_result_is_not_shadowed_by_game_result_route(client):
    # GET /{game_id}/result is declared later on the same router.
    d = client.get(RESULT).json()
    assert "result" in d and "inputs" in d


def test_result_uses_the_users_saved_plan(client):
    _as("u1")
    inp = _inp(need=2500, partial=0.4)
    assert client.put(SAVE, json=inp).status_code == 200
    d = client.get(RESULT).json()
    assert d["saved"] is True and d["inputs"]["need"] == 2500
    calc = client.post(CALC, json=inp).json()
    assert d["result"] == calc


def test_result_is_per_user(client):
    _as("u1")
    client.put(SAVE, json=_inp(need=1111))
    _as("u2")
    client.put(SAVE, json=_inp(need=2222))
    _as("u1")
    assert client.get(RESULT).json()["inputs"]["need"] == 1111
    _as("u3")
    assert client.get(RESULT).json()["saved"] is False


def test_result_never_writes(client, db_session):
    _as("u1")
    client.get(RESULT)
    assert db_session.query(UserRetirementPlanModel).count() == 0
    assert db_session.query(UserRetirementPlanHistoryModel).count() == 0


def test_result_falls_back_when_saved_plan_fails_current_checks(client, db_session):
    # e.g. a plan saved before the inflation guard existed
    db_session.add(UserRetirementPlanModel(
        user_id="u1", inputs=_inp(infl=-0.9), schema_version=1, location="europe",
    ))
    db_session.commit()
    _as("u1")
    r = client.get(RESULT)
    assert r.status_code == 200
    assert r.json()["saved"] is False and r.json()["inputs"]["infl"] == DEFAULTS["infl"]


# ── history written on save ──────────────────────────────────────────────────


def test_each_save_appends_history_with_key_figures(client, db_session):
    _as("u1")
    client.put(SAVE, json=DEFAULTS)
    client.put(SAVE, json=_inp(need=2200))
    rows = db_session.query(UserRetirementPlanHistoryModel).all()
    assert len(rows) == 2
    assert db_session.query(UserRetirementPlanModel).count() == 1  # current plan stays one row
    first = next(r for r in rows if r.inputs["need"] == DEFAULTS["need"])
    assert first.user_id == "u1" and first.retire_age == 55 and first.plan_until == 85
    assert first.monthly_at_retire == pytest.approx(DEFAULT_OUT["atRet"]["monthly"], abs=1e-6)
    assert first.need_at_retire == pytest.approx(DEFAULT_OUT["atRet"]["need"], abs=1e-6)
    assert first.corpus_at_retire == pytest.approx(DEFAULT_OUT["value"], abs=1e-6)
    assert first.sustainable_until == 55 and first.corpus_out_age == 119
    assert first.schema_version == 1 and first.app_version


def test_invalid_save_writes_no_history(client, db_session):
    _as("u1")
    assert client.put(SAVE, json=_inp(end=50)).status_code == 422
    assert db_session.query(UserRetirementPlanHistoryModel).count() == 0


def test_save_failure_rolls_back_plan_and_history(client, db_session, monkeypatch):
    from rita.repositories.user_retirement_plan_history import UserRetirementPlanHistoryRepo

    def boom(self, row):
        raise RuntimeError("history write failed")

    monkeypatch.setattr(UserRetirementPlanHistoryRepo, "append", boom)
    _as("u1")
    with pytest.raises(RuntimeError):
        client.put(SAVE, json=DEFAULTS)
    assert db_session.query(UserRetirementPlanModel).count() == 0
    assert db_session.query(UserRetirementPlanHistoryModel).count() == 0


# ── history endpoints ────────────────────────────────────────────────────────


def test_history_requires_auth(client):
    assert client.get(HISTORY).status_code in (401, 403)
    assert client.get(HISTORY + "/abc").status_code in (401, 403)


def test_history_newest_first_and_per_user(client):
    _as("u1")
    client.put(SAVE, json=_inp(need=2100))
    client.put(SAVE, json=_inp(need=2200))
    _as("u2")
    client.put(SAVE, json=_inp(need=9999))
    _as("u1")
    items = client.get(HISTORY).json()["items"]
    assert len(items) == 2
    assert items[0]["savedAt"] >= items[1]["savedAt"]
    keys = set(items[0])
    assert {"historyId", "savedAt", "retireAge", "planUntil", "needAtRetire", "monthlyAtRetire",
            "corpusAtRetire", "sustainableUntil", "corpusOutAge"} <= keys
    assert client.get(HISTORY, params={"limit": 1}).json()["items"][0]["historyId"] == items[0]["historyId"]


def test_history_entry_recalculates_result_from_saved_inputs(client):
    _as("u1")
    inp = _inp(need=2300, h2Mode="same")
    client.put(SAVE, json=inp)
    hid = client.get(HISTORY).json()["items"][0]["historyId"]
    d = client.get(f"{HISTORY}/{hid}").json()
    assert d["historyId"] == hid and d["inputs"]["need"] == 2300
    assert d["result"] == client.post(CALC, json=inp).json()
    assert d["monthlyAtRetire"] == pytest.approx(d["result"]["atRet"]["monthly"], abs=1e-9)


def test_history_entry_of_another_user_is_404(client):
    _as("u1")
    client.put(SAVE, json=DEFAULTS)
    hid = client.get(HISTORY).json()["items"][0]["historyId"]
    _as("u2")
    assert client.get(f"{HISTORY}/{hid}").status_code == 404
    assert client.get(f"{HISTORY}/does-not-exist").status_code == 404


def test_history_endpoints_never_write(client, db_session):
    _as("u1")
    client.put(SAVE, json=DEFAULTS)
    n = db_session.query(UserRetirementPlanHistoryModel).count()
    hid = client.get(HISTORY).json()["items"][0]["historyId"]
    client.get(f"{HISTORY}/{hid}")
    client.get(RESULT)
    assert db_session.query(UserRetirementPlanHistoryModel).count() == n


def test_experience_routes_still_have_no_commit():
    src = (Path(__file__).parent.parent.parent / "src" / "rita" / "api" / "experience" / "invest_game.py").read_text()
    assert ".commit(" not in src


def test_history_entry_with_unreadable_inputs_is_404_not_500(client, db_session):
    from datetime import datetime, timezone
    db_session.add(UserRetirementPlanHistoryModel(
        history_id="bad-1", user_id="u1", saved_at=datetime.now(timezone.utc), inputs={"need": "x"},
        location="europe", retire_age=55, plan_until=85, need_at_retire=1.0, monthly_at_retire=1.0,
        corpus_at_retire=1.0, schema_version=1, app_version="t",
    ))
    db_session.commit()
    _as("u1")
    assert client.get(f"{HISTORY}/bad-1").status_code == 404
    assert len(client.get(HISTORY).json()["items"]) == 1  # still listed with its key figures


def test_save_button_blocks_concurrent_saves():
    js = (Path(__file__).parent.parent.parent / "dashboard" / "js" / "investgame-app" / "what-i-need.js").read_text(encoding="utf-8")
    assert "if (!_restored || _saving) return;" in js
    save_fn = js.split("async function savePlan()")[1].split("let _flash")[0]
    assert "_saving = true;" in save_fn and "} finally {\n    _saving = false;" in save_fn
