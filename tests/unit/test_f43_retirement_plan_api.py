"""F43 Phase 1 — retirement plan endpoints (calculate / load / save).

Real in-memory SQLite (conftest ``client`` / ``db_session``); only auth is overridden.
"""
from __future__ import annotations

import ast
import copy
import json
import math
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from rita.auth import get_current_user, get_optional_user
from rita.config import get_settings
from rita.database import Base, get_db
from rita.main import app
from rita.models.user import UserModel
from rita.models.user_retirement_plan import UserRetirementPlanModel
from rita.schemas.retirement_plan import RetirementPlanInputs

CALC = "/api/experience/invest-game/retirement-plan/calculate"
LOAD = "/api/experience/invest-game/retirement-plan"
SAVE = "/api/v1/workflow/invest-game/retirement-plan"

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "what_i_need_golden.json"
GOLDEN = json.loads(_FIXTURE.read_text(encoding="utf-8"))
DEFAULTS = GOLDEN["scenarios"]["defaults"]["input"]
_SRC = Path(__file__).parent.parent.parent / "src" / "rita"


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


# ── calculate ────────────────────────────────────────────────────────────────


def test_calculate_defaults_200_headline(client):
    r = client.post(CALC, json=DEFAULTS)
    assert r.status_code == 200
    d = r.json()
    assert d["maxAge"] == 120
    assert d["startYear"] == date.today().year
    assert abs(d["byAge"][0]["monthly"] - 1987.518) < 0.01
    assert abs(d["byAge"][3]["monthly"] - 7703.30) < 0.01
    assert d["withInvesting"]["savingsOut"] == 55 and d["withoutInvesting"]["savingsOut"] == 59
    assert d["withInvesting"]["portfolioOut"] == 119
    assert d["withoutInvesting"]["portfolioOut"] is None
    # events present on points, JS formats the copy
    assert {e["kind"] for x in d["withInvesting"]["points"] for e in x["events"]} == {"house", "saving", "expense"}


def test_calculate_years_use_server_year(client):
    d = client.post(CALC, json=DEFAULTS).json()
    today = date.today().year
    assert all(y["year"] == today + y["age"] - DEFAULTS["now"] for y in d["years"])


@pytest.mark.parametrize("name", sorted(GOLDEN["scenarios"]))
def test_calculate_end_to_end_matches_golden(client, name):
    sc = GOLDEN["scenarios"][name]
    d = client.post(CALC, json=sc["input"]).json()

    def walk(g, a, path):
        if isinstance(g, dict):
            for k, v in g.items():
                walk(v, a[k], f"{path}.{k}")
        elif isinstance(g, list):
            assert len(a) == len(g), path
            for i, (x, y) in enumerate(zip(g, a)):
                walk(x, y, f"{path}[{i}]")
        elif g is None or isinstance(g, (bool, str)):
            assert a == g, path
        elif path.endswith(".year"):
            pass  # labelled with the server year (A4)
        else:
            assert math.isclose(a, g, rel_tol=1e-9, abs_tol=1e-6), f"{path}: {a} != {g}"

    walk(sc["output"], d, name)


def test_calculate_422_mock_message_string(client):
    r = client.post(CALC, json=_inp(ret=30))
    assert r.status_code == 422
    assert r.json()["detail"] == "Retirement must be after current age"


def test_calculate_null_field_gives_fill_in_message(client):
    r = client.post(CALC, json=_inp(need=None))
    assert r.status_code == 422
    assert r.json()["detail"] == "Fill in every field"


def test_calculate_null_event_gives_event_message(client):
    inp = _inp()
    inp["sv"][0]["amt"] = None
    r = client.post(CALC, json=inp)
    assert r.status_code == 422
    assert r.json()["detail"] == "Fill in every one time event (use 0 for none)"


def test_calculate_extreme_values_422_not_500(client):
    for bad in (_inp(now=-1e12), _inp(hSell=1e9), _inp(idxRate=50), _inp(need=1e300)):
        r = client.post(CALC, json=bad)
        assert r.status_code == 422, bad
        assert isinstance(r.json()["detail"], str)


def test_calculate_structural_error_is_list_detail(client):
    r = client.post(CALC, json=_inp(h2Mode="rent"))
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], list)


def test_calculate_needs_no_auth(client):
    app.dependency_overrides.pop(get_current_user, None)
    assert client.post(CALC, json=DEFAULTS).status_code == 200


# ── load ────────────────────────────────────────────────────────────────────


def test_load_no_auth_returns_defaults(client):
    r = client.get(LOAD)  # no token at all → get_optional_user → None
    assert r.status_code == 200
    d = r.json()
    assert d["saved"] is False and d["updatedAt"] is None
    assert d["location"] == "europe" and d["currency"] == "EUR"
    assert d["inputs"] == RetirementPlanInputs.model_validate(DEFAULTS).model_dump(mode="json", by_alias=True)


def test_load_invalid_token_returns_defaults_not_401(client):
    r = client.get(LOAD, headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 200
    assert r.json()["saved"] is False


def test_load_user_without_plan_defaults(client):
    _as("u-none")
    d = client.get(LOAD).json()
    assert d["saved"] is False


def test_config_defaults_equal_golden_defaults():
    cfg = get_settings().retirement_plan
    assert cfg.default_location == "europe"
    europe = cfg.locations["europe"]
    assert europe.currency == "EUR"
    a = RetirementPlanInputs.model_validate(europe.defaults).model_dump()
    b = RetirementPlanInputs.model_validate(DEFAULTS).model_dump()
    assert a == b


# ── save ────────────────────────────────────────────────────────────────────


def test_save_requires_auth(client):
    r = client.put(SAVE, json=DEFAULTS)
    assert r.status_code in (401, 403)


def test_save_load_round_trip(client, db_session):
    _as("u1")
    inp = _inp(need=2500, h2Mode="same", partial=0.4)
    r = client.put(SAVE, json=inp)
    assert r.status_code == 200, r.text
    assert r.json()["saved"] is True and r.json()["updatedAt"] is not None
    d = client.get(LOAD).json()
    assert d["saved"] is True
    assert d["inputs"] == RetirementPlanInputs.model_validate(inp).model_dump(mode="json", by_alias=True)
    assert d["updatedAt"] is not None


def test_save_twice_keeps_one_row(client, db_session):
    _as("u1")
    client.put(SAVE, json=_inp(need=2100))
    client.put(SAVE, json=_inp(need=2200))
    rows = db_session.query(UserRetirementPlanModel).all()
    assert len(rows) == 1 and rows[0].inputs["need"] == 2200
    assert rows[0].schema_version == 1 and rows[0].location == "europe"


def test_save_per_user_isolation(client):
    _as("u1")
    client.put(SAVE, json=_inp(need=1111))
    _as("u2")
    assert client.get(LOAD).json()["saved"] is False
    client.put(SAVE, json=_inp(need=2222))
    _as("u1")
    assert client.get(LOAD).json()["inputs"]["need"] == 1111


def test_save_invalid_plan_422_not_stored(client, db_session):
    _as("u1")
    r = client.put(SAVE, json=_inp(end=50))
    assert r.status_code == 422
    assert r.json()["detail"] == "Plan until must be after retirement"
    assert db_session.query(UserRetirementPlanModel).count() == 0


def test_corrupt_saved_row_falls_back_to_defaults(client, db_session):
    db_session.add(UserRetirementPlanModel(user_id="u1", inputs={"need": "x"}, schema_version=1, location="europe"))
    db_session.commit()
    _as("u1")
    d = client.get(LOAD).json()
    assert d["saved"] is False and d["inputs"]["need"] == DEFAULTS["need"]
    assert db_session.query(UserRetirementPlanModel).count() == 1  # row not deleted
    assert client.put(SAVE, json=_inp(need=3000)).status_code == 200
    assert client.get(LOAD).json()["inputs"]["need"] == 3000


def test_unknown_schema_version_falls_back(client, db_session):
    db_session.add(UserRetirementPlanModel(user_id="u1", inputs=DEFAULTS, schema_version=99, location="europe"))
    db_session.commit()
    _as("u1")
    assert client.get(LOAD).json()["saved"] is False


def test_save_with_foreign_keys_enforced_for_existing_user():
    """A1: with PRAGMA foreign_keys=ON a save works for a user present in users,
    and is rejected for a user that is not (what PostgreSQL will do for rita-dev)."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _rec):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(UserModel(id="rita-dev"))
    session.commit()

    def _db():
        yield session

    app.dependency_overrides[get_db] = _db
    try:
        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            _as("rita-dev")
            assert c.put(SAVE, json=DEFAULTS).status_code == 200
            assert c.get(LOAD).json()["saved"] is True
            _as("ghost")
            with pytest.raises(Exception):
                c.put(SAVE, json=DEFAULTS)
            session.rollback()
        assert session.query(UserRetirementPlanModel).count() == 1
        # Phase 1b: the history row is FK-bound to the real user too; the ghost save left none
        from rita.models.user_retirement_plan_history import UserRetirementPlanHistoryModel
        hist = session.query(UserRetirementPlanHistoryModel).all()
        assert len(hist) == 1 and hist[0].user_id == "rita-dev"
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


# ── tier gates ───────────────────────────────────────────────────────────────


def test_experience_router_has_no_writes():
    src = (_SRC / "api" / "experience" / "invest_game.py").read_text(encoding="utf-8")
    for bad in (".commit(", ".upsert(", ".delete(", ".add(", ".save("):
        assert bad not in src, bad


def test_calculate_route_has_no_db_dependency():
    tree = ast.parse((_SRC / "api" / "experience" / "invest_game.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "calculate_retirement_plan")
    assert [a.arg for a in fn.args.args] == ["body"]


def test_save_only_in_workflow_tier():
    routes = {(r.path, m) for r in app.routes for m in getattr(r, "methods", set())}
    assert (SAVE, "PUT") in routes
    assert (LOAD, "PUT") not in routes and (LOAD, "POST") not in routes
    assert (CALC, "POST") in routes and (LOAD, "GET") in routes


def test_c2_calculate_near_minus_100_inflation_is_422_not_500(client):
    r = client.post(CALC, json=_inp(infl=-0.9999999999))
    assert r.status_code == 422
    assert r.json()["detail"] == "Inflation must be between −50% and 100%"


def test_c2_save_near_minus_100_inflation_is_422(client, db_session):
    _as("u1")
    r = client.put(SAVE, json=_inp(infl=-0.9999999999))
    assert r.status_code == 422
    assert db_session.query(UserRetirementPlanModel).count() == 0


def test_c3_restore_skips_write_when_dirty():
    js = (Path(__file__).parent.parent.parent / "dashboard" / "js" / "investgame-app" / "what-i-need.js").read_text(encoding="utf-8")
    assert "let _dirty = false;" in js
    assert "addEventListener('input', () => { if (!_restored) _dirty = true; })" in js
    assert "if (plan && plan.inputs && !_dirty) {" in js
    # Phase 1b: saving is explicit (Save button) and still blocked until the restore finished
    assert "if (!_restored || _saving) return;" in js
    assert "document.getElementById('wn-save').addEventListener('click', () => savePlan());" in js
    assert "savePlan(" not in js.split("async function calculate()")[1].split("let _bound")[0]
