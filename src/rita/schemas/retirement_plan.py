"""Pydantic contracts for the F43 "What I Need" retirement plan (Phase 1, D2/D10).

JSON is camelCase (``alias_generator=to_camel``); Python attributes are snake_case.
Money is EUR, rates are fractions — identical to the mock's ``readInputs()`` shape.
The backend never rounds; formatting and all user-facing copy stay in JS (D7).

RetirementPlanInputs      — request body (calculate / save) and the persisted plan JSON
RetirementPlanResult      — calculate response (built from ``core.retirement_plan.PlanResult``)
RetirementPlanOut         — load / save response
UserRetirementPlanSchema  — ORM row mirror (from_attributes)
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

_CAMEL = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


# ── Inputs ───────────────────────────────────────────────────────────────────


class OneTimeEventIn(BaseModel):
    """One time event (+ saving in / − expense out). Null = empty field in the form."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    age: float | None
    amt: float | None


class RetirementPlanInputs(BaseModel):
    """Every numeric is required-but-nullable so an empty form field (JS NaN → null)
    reaches ``validate_plan`` and yields the mock's message, never a Pydantic list error."""

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid", allow_inf_nan=False,
    )

    need: float | None
    infl: float | None
    now: float | None
    ret: float | None
    end: float | None
    tax: float | None
    partial: float | None
    exit: float | None
    h_value: float | None
    h_appr: float | None
    h_sell: float | None
    h_tax: float | None
    h2_price: float | None
    h2_mode: Literal["same", "new"]
    sv: list[OneTimeEventIn] = Field(min_length=3, max_length=3)
    bx: list[OneTimeEventIn] = Field(min_length=3, max_length=3)
    idx_monthly: float | None
    idx_rate: float | None
    eq_monthly: float | None
    eq_rate: float | None
    com_monthly: float | None
    com_rate: float | None
    alt_monthly: float | None
    alt_rate: float | None


# ── Result ───────────────────────────────────────────────────────────────────


class _Camel(BaseModel):
    model_config = _CAMEL


class YearRowOut(_Camel):
    age: int
    year: int
    monthly: float
    cum: float


class AssetResultOut(_Camel):
    key: Literal["idx", "eq", "com", "alt"]
    monthly: float
    rate: float
    put: float
    value: float
    gain: float
    profit_m: float
    withdrawn_net: float


class PotRowOut(_Camel):
    age: int
    put: float
    idx: float
    eq: float
    com: float
    alt: float


class SimEventOut(_Camel):
    kind: Literal["house", "saving", "expense"]
    amount: float


class SimPointOut(_Camel):
    age: int
    pot: float
    corpus: float
    put_in: float
    income: float
    need: float
    sold: float
    bal: list[float]
    basis: list[float]
    events: list[SimEventOut]


class SimResultOut(_Camel):
    points: list[SimPointOut]
    run_out: int | None
    corpus_out: int | None


class AgeCellOut(_Camel):
    age: int
    off: bool = False
    monthly: float | None = None
    income: float | None = None
    from_pot: float | None = None
    pot: float | None = None
    corpus: float | None = None
    need: float | None = None
    share: float | None = None


class RetirementPlanResult(_Camel):
    start_year: int
    max_age: int
    years: list[YearRowOut]
    total: float
    assets: list[AssetResultOut]
    monthly: float
    put: float
    value: float
    pot: list[PotRowOut]
    portfolio: SimResultOut
    portfolio0: SimResultOut
    h_value_at: float
    h_gain: float
    h_tax_amt: float
    h_net: float
    h2_at: float
    house_release: float
    big_expenses: float
    savings: float
    target: float
    need_all: float
    need_ret: float
    by_age: list[AgeCellOut]
    at_ret: AgeCellOut


# ── Load / save ──────────────────────────────────────────────────────────────


class RetirementPlanOut(_Camel):
    saved: bool
    updated_at: datetime | None = None
    location: str = "europe"
    currency: str = "EUR"
    inputs: RetirementPlanInputs


class RetirementPlanWithResult(RetirementPlanOut):
    """The user's saved plan (or the preset defaults) with its result, calculated now."""

    result: RetirementPlanResult


class RetirementPlanHistoryItem(_Camel):
    """One saved plan in the user's history: the key figures shown at save time."""

    history_id: str
    saved_at: datetime
    location: str
    retire_age: int
    plan_until: int
    need_at_retire: float
    monthly_at_retire: float
    corpus_at_retire: float
    sustainable_until: int | None = None
    corpus_out_age: int | None = None
    app_version: str = ""


class RetirementPlanHistoryOut(_Camel):
    items: list[RetirementPlanHistoryItem]


class RetirementPlanHistoryDetail(RetirementPlanHistoryItem):
    """A history row with its inputs and the result recalculated from them."""

    inputs: RetirementPlanInputs
    result: RetirementPlanResult


class UserRetirementPlanSchema(BaseModel):
    model_config = {"from_attributes": True}

    user_id: str
    inputs: dict[str, Any]
    schema_version: int = 1
    location: str = "europe"
    created_at: datetime | None = None
    updated_at: datetime | None = None
