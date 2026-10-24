"""F43 Phase 1 — QA: acceptance (independent hand calculation) + property tests.

Complements test_f43_retirement_plan_core.py / _api.py:
- Phase-1 acceptance: defaults match an independent hand calculation within EUR 1
  (closed-form / month-by-month loops written here, not the core's code path).
- Properties: partial up => income at retirement up; same house => no release and
  no house event (h2 fields still validated); zero tax => withdrawnNet == profitM*partial;
  panels before current age are off.
- Persistence: save -> load -> calculate is identical to calculating the original
  inputs; real JWT path (no dependency override) for save/load; invalid / expired
  token => PUT 401 and GET 200 defaults with the stored plan untouched.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from jose import jwt

from rita.auth import create_access_token, get_current_user, get_optional_user
from rita.config import get_settings
from rita.core.retirement_plan import calc, to_params, validate_plan
from rita.main import app
from rita.models.user import UserModel
from rita.models.user_retirement_plan import UserRetirementPlanModel
from rita.schemas.retirement_plan import RetirementPlanInputs
from rita.services.retirement_plan_service import (
    PlanValidationError,
    RetirementPlanService,
    calculate,
)

CALC = "/api/experience/invest-game/retirement-plan/calculate"
LOAD = "/api/experience/invest-game/retirement-plan"
SAVE = "/api/v1/workflow/invest-game/retirement-plan"

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "what_i_need_golden.json"
GOLDEN = json.loads(_FIXTURE.read_text(encoding="utf-8"))
DEFAULTS = GOLDEN["scenarios"]["defaults"]["input"]
EUR = 1.0  # Phase-1 acceptance tolerance


@pytest.fixture(autouse=True)
def _cleanup():
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_optional_user, None)
    yield
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_optional_user, None)


def _inp(**kw) -> dict:
    d = copy.deepcopy(DEFAULTS)
    d.update(kw)
    return d


def _calc(inp: dict):
    return calculate(RetirementPlanInputs.model_validate(inp), start_year=GOLDEN["start_year"])


def _bearer(sub: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(sub)}"}


def _expired_bearer(sub: str) -> dict:
    s = get_settings().security
    tok = jwt.encode(
        {"sub": sub, "exp": datetime.now(timezone.utc) - timedelta(minutes=5)},
        s.jwt_secret.get_secret_value(), algorithm=s.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {tok}"}


# ── Phase-1 acceptance: independent hand calculation (defaults) ───────────────


def test_hand_calc_need_at_retirement():
    r = _calc(DEFAULTS)
    need55 = 2000 * 1.025 ** 20  # EUR 2000 today, 2.5 % for 20 years (35 -> 55)
    assert abs(r.need_ret - need55) < EUR
    assert abs(r.years[0].monthly - need55) < EUR
    assert abs(r.at_ret.need - need55) < EUR
    assert r.years[0].age == 55 and r.years[-1].age == 84 and len(r.years) == 30


def test_hand_calc_plain_sum_total_closed_form():
    # 12 * 2000 * 1.025**(a-35) for a in 55..84  ==  geometric series
    total = 12 * 2000 * 1.025 ** 20 * (1.025 ** 30 - 1) / 0.025
    r = _calc(DEFAULTS)
    assert abs(r.total - total) < EUR
    assert abs(r.years[-1].cum - total) < EUR
    assert abs(r.need_all - (total + 600_000)) < EUR


def test_hand_calc_index_fund_future_value_month_by_month():
    # EUR 1000/month into 7 % p.a. (monthly compounding) for 20 years, end-of-month deposit
    m = 1.07 ** (1 / 12) - 1
    bal = 0.0
    for _ in range(240):
        bal = bal * (1 + m) + 1000
    r = _calc(DEFAULTS)
    idx = next(a for a in r.assets if a.key == "idx")
    assert idx.put == 240_000
    assert abs(idx.value - bal) < EUR
    assert abs(idx.gain - (bal - 240_000)) < EUR
    assert abs(idx.profit_m - bal * m) < EUR
    assert abs(idx.withdrawn_net - bal * m * 0.5 * 0.7) < EUR
    # the year-by-year simulation reaches the same index balance at retirement
    p55 = next(x for x in r.portfolio.points if x.age == 55)
    assert abs(p55.bal[0] - bal) < EUR and p55.basis[0] == pytest.approx(240_000)


def test_hand_calc_all_assets_and_portfolio_totals():
    r = _calc(DEFAULTS)
    exp = {}
    for key, monthly, rate in (("idx", 1000, 0.07), ("eq", 700, 0.10), ("com", 150, 0.04), ("alt", 150, 0.05)):
        m = (1 + rate) ** (1 / 12) - 1
        exp[key] = monthly * ((1 + m) ** 240 - 1) / m
    got = {a.key: a.value for a in r.assets}
    for k, v in exp.items():
        assert abs(got[k] - v) < EUR, k
    assert abs(r.value - (exp["idx"] + exp["eq"] + exp["com"] + exp["alt"])) < EUR
    assert r.monthly == 2000 and r.put == 2000 * 240


def test_hand_calc_house_and_target():
    r = _calc(DEFAULTS)
    v60 = 400_000 * 1.03 ** 25
    gain = v60 - 400_000
    tax = gain * 0.3
    net = v60 - tax
    h2 = 250_000 * 1.03 ** 25
    release = net - h2
    total = 12 * 2000 * 1.025 ** 20 * (1.025 ** 30 - 1) / 0.025
    for got, want in ((r.h_value_at, v60), (r.h_gain, gain), (r.h_tax_amt, tax),
                      (r.h_net, net), (r.h2_at, h2), (r.house_release, release)):
        assert abs(got - want) < EUR
    assert r.big_expenses == 600_000 and r.savings == 300_000
    assert abs(r.target - max(0.0, total + 600_000 - 300_000 - release)) < EUR


def test_hand_calc_from_pot_at_retirement():
    # fromPot = pot / sum_{a=55}^{84} 12 * 1.025**(a-55)
    r = _calc(DEFAULTS)
    months = 12 * (1.025 ** 30 - 1) / 0.025
    pot55 = next(x for x in r.portfolio.points if x.age == 55).pot
    assert abs(r.at_ret.from_pot - pot55 / months) < EUR


# ── Properties ───────────────────────────────────────────────────────────────


def test_property_partial_up_income_at_retirement_up():
    incomes = [_calc(_inp(partial=x)).at_ret.income for x in (0.0, 0.2, 0.5, 0.8, 1.0)]
    assert incomes[0] == 0.0
    assert all(b > a for a, b in zip(incomes, incomes[1:])), incomes
    # income at ret is linear in partial (no sale before exit age)
    assert incomes[2] == pytest.approx(incomes[4] * 0.5, rel=1e-12)


def test_property_partial_up_byage_retirement_cell_income_up():
    def cell(partial):
        r = _calc(_inp(partial=partial))
        return next(c for c in r.by_age if c.age == 55)
    assert cell(0.3).income < cell(0.6).income < cell(0.9).income


def test_property_same_house_no_release_no_event_and_target():
    r = _calc(_inp(h2Mode="same"))
    assert r.house_release == 0.0
    assert all(e.kind != "house" for x in r.portfolio.points + r.portfolio0.points for e in x.events)
    assert r.target == pytest.approx(max(0.0, r.total + r.big_expenses - r.savings))
    # house value / tax are still reported for the KPI cards
    assert r.h_value_at > 400_000 and r.h_net > 0


def test_property_same_house_h2_fields_still_validated():
    with pytest.raises(PlanValidationError, match="Check house values and tax %"):
        _calc(_inp(h2Mode="same", h2Price=-5))


@pytest.mark.parametrize("partial", [0.0, 0.25, 0.5, 1.0])
def test_property_zero_tax_withdrawn_net_equals_profit_times_partial(partial):
    r = _calc(_inp(tax=0, partial=partial))
    for a in r.assets:
        assert a.withdrawn_net == pytest.approx(a.profit_m * partial, rel=1e-12, abs=1e-12)


@pytest.mark.parametrize("now,ret,h_sell,ev_ages,off_ages", [
    (50, 55, 60, (50, 55, 60), set()),
    (57, 60, 60, (57, 60, 65), {55}),
    (62, 65, 63, (62, 65, 70), {55, 60}),
])
def test_property_panels_before_current_age_are_off(now, ret, h_sell, ev_ages, off_ages):
    inp = _inp(now=now, ret=ret, hSell=h_sell)
    for g in ("sv", "bx"):
        for ev, age in zip(inp[g], ev_ages):
            ev["age"] = age
    r = _calc(inp)
    off = {c.age for c in r.by_age if c.off}
    assert off == off_ages
    for c in r.by_age:
        if c.off:
            assert c.monthly is None and c.share is None and c.need is None
        else:
            assert c.monthly is not None and c.monthly >= 0
    assert r.portfolio.points[0].age == now


def test_property_c2_regression_present():
    # C2 (code review) — the near −100 % inflation divide-by-zero is a 422 guard
    raw = RetirementPlanInputs.model_validate(_inp(infl=-0.9999999999)).model_dump()
    assert validate_plan(raw) == "Inflation must be between −50% and 100%"


def test_property_all_monthly_zero_corpus_never_out():
    r = _calc(_inp(idxMonthly=0, eqMonthly=0, comMonthly=0, altMonthly=0))
    assert r.portfolio.corpus_out is None and r.portfolio0.corpus_out is None
    assert r.value == 0.0 and all(a.withdrawn_net == 0.0 for a in r.assets)


# ── Persistence round-trip ───────────────────────────────────────────────────


def test_save_load_calculate_identical_to_original(client, db_session):
    db_session.add(UserModel(id="qa-user"))
    db_session.commit()
    hdr = _bearer("qa-user")
    inp = _inp(need=2750, infl=0.021, partial=0.35, tax=0.26, h2Mode="same", idxRate=0.065)
    inp["sv"][2]["amt"] = 12345.67
    assert client.put(SAVE, json=inp, headers=hdr).status_code == 200
    loaded = client.get(LOAD, headers=hdr).json()
    assert loaded["saved"] is True
    a = client.post(CALC, json=inp).json()
    b = client.post(CALC, json=loaded["inputs"]).json()
    assert a == b


def test_service_level_round_trip_identical(db_session):
    svc = RetirementPlanService(db_session)
    inp = RetirementPlanInputs.model_validate(_inp(need=1800, exit=75))
    svc.save("svc-user", inp)
    out = svc.load("svc-user")
    assert out.saved is True and out.inputs == inp
    assert calculate(out.inputs, 2026) == calculate(inp, 2026)


def test_real_jwt_save_then_load(client, db_session):
    db_session.add(UserModel(id="qa-user"))
    db_session.commit()
    hdr = _bearer("qa-user")
    r = client.put(SAVE, json=_inp(need=3100), headers=hdr)
    assert r.status_code == 200 and r.json()["saved"] is True
    d = client.get(LOAD, headers=hdr).json()
    assert d["saved"] is True and d["inputs"]["need"] == 3100


def test_put_without_token_rejected(client, db_session):
    r = client.put(SAVE, json=DEFAULTS)
    assert r.status_code in (401, 403)  # HTTPBearer: 401 on newer FastAPI, 403 on older
    assert db_session.query(UserRetirementPlanModel).count() == 0


@pytest.mark.parametrize("hdr", [
    {"Authorization": "Bearer not-a-jwt"},
    "expired",
])
def test_put_invalid_or_expired_token_401(client, db_session, hdr):
    if hdr == "expired":
        db_session.add(UserModel(id="qa-user"))
        db_session.commit()
        hdr = _expired_bearer("qa-user")
    r = client.put(SAVE, json=DEFAULTS, headers=hdr)
    assert r.status_code == 401
    assert db_session.query(UserRetirementPlanModel).count() == 0


def test_get_invalid_or_expired_token_200_defaults_and_plan_untouched(client, db_session):
    db_session.add(UserModel(id="qa-user"))
    db_session.commit()
    assert client.put(SAVE, json=_inp(need=4444), headers=_bearer("qa-user")).status_code == 200
    for hdr in ({"Authorization": "Bearer not-a-jwt"}, _expired_bearer("qa-user")):
        r = client.get(LOAD, headers=hdr)
        assert r.status_code == 200
        d = r.json()
        assert d["saved"] is False and d["inputs"]["need"] == DEFAULTS["need"]
    # stored plan untouched — still restored with a valid token
    assert client.get(LOAD, headers=_bearer("qa-user")).json()["inputs"]["need"] == 4444
    assert db_session.query(UserRetirementPlanModel).count() == 1


def test_load_never_writes(client, db_session):
    for _ in range(3):
        assert client.get(LOAD).status_code == 200
    db_session.add(UserModel(id="qa-user"))
    db_session.commit()
    assert client.get(LOAD, headers=_bearer("qa-user")).json()["saved"] is False
    assert db_session.query(UserRetirementPlanModel).count() == 0


def test_validation_error_never_pydantic_list_for_any_null_field(client):
    for key in ("need", "infl", "now", "ret", "end", "tax", "partial", "exit", "hValue", "hAppr",
                "hSell", "hTax", "h2Price", "idxMonthly", "idxRate", "eqMonthly", "eqRate",
                "comMonthly", "comRate", "altMonthly", "altRate"):
        r = client.post(CALC, json=_inp(**{key: None}))
        assert r.status_code == 422 and r.json()["detail"] == "Fill in every field", key
