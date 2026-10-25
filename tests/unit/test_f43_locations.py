"""F43 — India (INR) and US (USD) location presets for "What I Need".

GET ``…/retirement-plan?location=`` and PUT ``…/retirement-plan?location=``; one current plan
per user (saving another location replaces it), history keeps the location of every save.
Real in-memory SQLite (conftest ``client`` / ``db_session``); only auth is overridden.
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from rita.auth import get_current_user, get_optional_user
from rita.config import get_settings
from rita.main import app
from rita.models.user import UserModel
from rita.models.user_retirement_plan import UserRetirementPlanModel
from rita.models.user_retirement_plan_history import UserRetirementPlanHistoryModel
from rita.schemas.retirement_plan import RetirementPlanInputs
from rita.services.retirement_plan_service import calculate

LOAD = "/api/experience/invest-game/retirement-plan"
RESULT = "/api/experience/invest-game/retirement-plan/result"
SAVE = "/api/v1/workflow/invest-game/retirement-plan"
_JS = Path(__file__).parent.parent.parent / "dashboard" / "js" / "investgame-app" / "what-i-need.js"
_HTML = Path(__file__).parent.parent.parent / "dashboard" / "investgame-app.html"


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


def _preset(loc: str) -> dict:
    return copy.deepcopy(get_settings().retirement_plan.locations[loc].defaults)


# ── presets ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("loc,ccy", [("europe", "EUR"), ("india", "INR"), ("us", "USD")])
def test_preset_exists_and_calculates(loc, ccy):
    cfg = get_settings().retirement_plan.locations[loc]
    assert cfg.currency == ccy
    r = calculate(RetirementPlanInputs.model_validate(cfg.defaults))
    # every preset shows a gap at retirement (the page's point) but is a sane plan
    assert 0.3 < r.at_ret.share < 1.0
    assert r.value > 0


def test_default_location_still_europe(client):
    d = client.get(LOAD).json()
    assert d["location"] == "europe" and d["currency"] == "EUR"


@pytest.mark.parametrize("loc,ccy", [("india", "INR"), ("us", "USD")])
def test_load_location_preset_signed_out(client, loc, ccy):
    r = client.get(LOAD, params={"location": loc})
    assert r.status_code == 200
    d = r.json()
    assert d["saved"] is False and d["location"] == loc and d["currency"] == ccy
    assert d["inputs"] == RetirementPlanInputs.model_validate(_preset(loc)).model_dump(mode="json", by_alias=True)


def test_load_unknown_location_422(client):
    r = client.get(LOAD, params={"location": "mars"})
    assert r.status_code == 422 and r.json()["detail"] == "Unknown location"


# ── save ─────────────────────────────────────────────────────────────────────


def test_save_india_round_trip(client, db_session):
    _as("u1")
    inp = _preset("india") | {"need": 90000}
    r = client.put(SAVE, params={"location": "india"}, json=inp)
    assert r.status_code == 200, r.text
    assert r.json()["location"] == "india" and r.json()["currency"] == "INR"
    # no location → default (europe) → no europe plan → preset, saved=False
    d = client.get(LOAD).json()
    assert d["saved"] is False and d["location"] == "europe"
    # with ?location=india → the saved india plan
    d = client.get(LOAD, params={"location": "india"}).json()
    assert d["saved"] is True and d["location"] == "india" and d["inputs"]["need"] == 90000
    row = db_session.query(UserRetirementPlanModel).one()
    assert row.location == "india"
    hist = db_session.query(UserRetirementPlanHistoryModel).one()
    assert hist.location == "india"


def test_saved_plan_for_other_location_not_returned(client):
    _as("u1")
    client.put(SAVE, json=_preset("europe") | {"need": 2500})  # no location → europe
    d = client.get(LOAD, params={"location": "us"}).json()
    assert d["saved"] is False and d["location"] == "us"
    assert d["inputs"]["need"] == _preset("us")["need"]
    d = client.get(LOAD, params={"location": "europe"}).json()
    assert d["saved"] is True and d["inputs"]["need"] == 2500


def test_saving_per_location_independent_history_keeps_both(client, db_session):
    _as("u1")
    client.put(SAVE, json=_preset("europe"))
    client.put(SAVE, params={"location": "us"}, json=_preset("us"))
    # per-location PK: both rows kept independently
    locs_db = sorted(r.location for r in db_session.query(UserRetirementPlanModel).all())
    assert locs_db == ["europe", "us"]
    locs = sorted(h.location for h in db_session.query(UserRetirementPlanHistoryModel).all())
    assert locs == ["europe", "us"]
    # RESULT with no location → default (europe) → saved europe plan
    d = client.get(RESULT).json()
    assert d["location"] == "europe" and d["currency"] == "EUR"


def test_save_unknown_location_422_nothing_stored(client, db_session):
    _as("u1")
    r = client.put(SAVE, params={"location": "mars"}, json=_preset("europe"))
    assert r.status_code == 422 and r.json()["detail"] == "Unknown location"
    assert db_session.query(UserRetirementPlanModel).count() == 0
    assert db_session.query(UserRetirementPlanHistoryModel).count() == 0


# ── page ─────────────────────────────────────────────────────────────────────


def test_page_location_pills_enabled():
    html = _HTML.read_text(encoding="utf-8")
    for loc in ("europe", "india", "us"):
        assert f'data-loc="{loc}"' in html
    assert "Coming later" not in html


def test_js_sends_location_and_formats_currency():
    js = _JS.read_text(encoding="utf-8")
    assert "SAVE_PATH + '?location=' + _loc" in js
    assert "PLAN_PATH + '?location=' + loc" in js
    assert "'en-IN'" in js and "'₹'" in js and "'$'" in js
    assert "'€' + v.toLocaleString" not in js        # no hardcoded euro formatting left
