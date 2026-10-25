"""F43 "What I Need" retirement plan — pure port of the approved mock rev 39.

Source of truth for the numbers: ``dashboard/js/investgame-app/what-i-need.js`` at
b1a9b4c (``validate()``, ``fvFactor()``, ``simulate()``, ``calc()``).  Golden output
of that JS is pinned in ``tests/fixtures/what_i_need_golden.json``.

Parity rules (task brief 20261024-1254, pitfalls P1–P20):
- every sum is a left-to-right float sum from 0 (``_jsum``) — never builtin ``sum``
  or ``math.fsum`` (their compensated / different order would drift from JS);
- the same operation order and exponents as the JS (``(1 + r) ** (1/12) - 1``,
  inflation from the current age with a full exponent);
- the backend never rounds.

No I/O, no DB, no settings — callers pass validated params and the start year.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

MAX_AGE = 120  # portfolio run-out is followed past plan-until up to this age
AGE_PANELS: tuple[int, ...] = (55, 60, 65, 70, 75, 80, 85)
ASSET_KEYS: tuple[str, ...] = ("idx", "eq", "com", "alt")
MAX_AMOUNT = 1_000_000_000.0
MIN_INFL = -0.5  # inflation floor: keeps the inflated need (a divisor) > 0

_NUMERIC_FIELDS: tuple[str, ...] = (
    "need", "infl", "now", "ret", "end", "tax", "partial", "exit",
    "h_value", "h_appr", "h_sell", "h_tax", "h2_price",
    *(f"{k}_monthly" for k in ASSET_KEYS),
    *(f"{k}_rate" for k in ASSET_KEYS),
)


def _jsum(xs: Iterable[float]) -> float:
    """Left-to-right float sum starting at 0 — identical to JS ``reduce((s, v) => s + v, 0)``."""
    s = 0.0
    for x in xs:
        s = s + x
    return s


# ── Data shapes ──────────────────────────────────────────────────────────────


@dataclass(slots=True, frozen=True)
class OneTimeEvent:
    age: float
    amt: float


@dataclass(slots=True, frozen=True)
class AssetInput:
    key: str
    monthly: float
    rate: float


@dataclass(slots=True, frozen=True)
class PlanParams:
    need: float
    infl: float
    now: int
    ret: int
    end: int
    tax: float
    partial: float
    exit: int
    h_value: float
    h_appr: float
    h_sell: int
    h_tax: float
    h2_price: float
    h2_mode: str
    sv: tuple[OneTimeEvent, ...]
    bx: tuple[OneTimeEvent, ...]
    assets: tuple[AssetInput, ...]


@dataclass(slots=True)
class SimEvent:
    kind: str  # "house" | "saving" | "expense" — copy is formatted in JS (D7)
    amount: float


@dataclass(slots=True)
class SimPoint:
    age: int
    savings: float
    portfolio: float
    put_in: float
    income: float
    need: float
    sold: float
    bal: list[float]
    basis: list[float]
    events: list[SimEvent]


@dataclass(slots=True)
class SimResult:
    points: list[SimPoint]
    savings_out: int | None
    portfolio_out: int | None


@dataclass(slots=True)
class YearRow:
    age: int
    year: int
    monthly: float
    cum: float


@dataclass(slots=True)
class AssetResult:
    key: str
    monthly: float
    rate: float
    put: float
    value: float
    gain: float
    profit_m: float
    withdrawn_net: float


@dataclass(slots=True)
class PotRow:
    age: int
    put: float
    idx: float
    eq: float
    com: float
    alt: float


@dataclass(slots=True)
class AgeCell:
    age: int
    off: bool = False
    monthly: float | None = None
    income: float | None = None
    from_savings: float | None = None
    savings: float | None = None
    portfolio: float | None = None
    need: float | None = None
    share: float | None = None


@dataclass(slots=True)
class PlanResult:
    start_year: int
    max_age: int
    years: list[YearRow]
    total: float
    assets: list[AssetResult]
    monthly: float
    put: float
    value: float
    portfolio_growth: list[PotRow]
    with_investing: SimResult
    without_investing: SimResult
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
    by_age: list[AgeCell] = field(default_factory=list)
    at_ret: AgeCell | None = None


# ── Validation (P19) ─────────────────────────────────────────────────────────


def _is_whole(v: float) -> bool:
    return float(v).is_integer()


def validate_plan(raw: Mapping[str, Any]) -> str | None:
    """Return the mock's message for the first failed check, or None when valid.

    ``raw`` is the snake_case dump of ``RetirementPlanInputs`` (JS NaN arrives as None).
    Checks run in the mock's order; the extra backend guards run after them.
    """
    if any(raw.get(k) is None for k in _NUMERIC_FIELDS):
        return "Fill in every field"
    events = [*raw["sv"], *raw["bx"]]
    if any(x.get("age") is None or x.get("amt") is None for x in events):
        return "Fill in every one time event (use 0 for none)"
    if any(x["amt"] < 0 for x in events):
        return "One time amounts must be 0 or more (the sign is fixed)"
    now = raw["now"]
    if any(x["amt"] > 0 and x["age"] < now for x in events):
        return "One time event age must be from current age on"
    if not (raw["ret"] > now):
        return "Retirement must be after current age"
    if not (raw["end"] > raw["ret"]):
        return "Plan until must be after retirement"
    if not (raw["h_sell"] > now):
        return "House value-until age must be after current age"
    if raw["need"] <= 0 or raw["tax"] < 0 or raw["tax"] >= 1:
        return "Check monthly need and tax %"
    if raw["partial"] < 0 or raw["partial"] > 1:
        return "Partial profit must be 0–100%"
    if not (raw["exit"] >= raw["ret"]):
        return "Exit age must be from retirement age on"
    if any(raw[f"{k}_monthly"] < 0 for k in ASSET_KEYS):
        return "Monthly investments must be 0 or more"
    if raw["h_value"] < 0 or raw["h2_price"] < 0 or raw["h_tax"] < 0 or raw["h_tax"] >= 1:
        return "Check house values and tax %"
    # ── backend guards (after the mock checks) ──
    ages = (raw["now"], raw["ret"], raw["end"], raw["exit"], raw["h_sell"])
    if not all(_is_whole(a) for a in ages):
        return "Ages must be whole years"
    if raw["end"] > MAX_AGE:
        return "Plan until must be at most 120"
    if raw["now"] < 0 or raw["h_sell"] > MAX_AGE:
        return "Ages must be between 0 and 120"
    rates = (raw["infl"], raw["h_appr"], *(raw[f"{k}_rate"] for k in ASSET_KEYS))
    if any(r <= -1 or r > 1 for r in rates):
        return "Rates must be between −100% and 100%"
    amounts = (
        raw["need"], raw["h_value"], raw["h2_price"],
        *(raw[f"{k}_monthly"] for k in ASSET_KEYS),
        *(x["amt"] for x in events),
    )
    if any(a > MAX_AMOUNT for a in amounts):
        return "Amounts must be at most €1,000,000,000"
    # The inflated need is a divisor (share of the need); keep it > 0 at every age up to
    # plan-until. With infl ≥ −50% and at most 120 years the factor stays ≥ 0.5**120, and
    # the floor check catches any remaining underflow (e.g. a tiny need).
    if raw["infl"] < MIN_INFL:
        return "Inflation must be between −50% and 100%"
    if not (raw["need"] * (1.0 + raw["infl"]) ** (raw["end"] - raw["now"]) > 0):
        return "Check monthly need and tax %"
    return None


def to_params(raw: Mapping[str, Any]) -> PlanParams:
    """Build ``PlanParams`` from a validated snake_case dump (P20: ages become int)."""
    return PlanParams(
        need=float(raw["need"]), infl=float(raw["infl"]),
        now=int(raw["now"]), ret=int(raw["ret"]), end=int(raw["end"]),
        tax=float(raw["tax"]), partial=float(raw["partial"]), exit=int(raw["exit"]),
        h_value=float(raw["h_value"]), h_appr=float(raw["h_appr"]), h_sell=int(raw["h_sell"]),
        h_tax=float(raw["h_tax"]), h2_price=float(raw["h2_price"]), h2_mode=str(raw["h2_mode"]),
        sv=tuple(OneTimeEvent(float(x["age"]), float(x["amt"])) for x in raw["sv"]),
        bx=tuple(OneTimeEvent(float(x["age"]), float(x["amt"])) for x in raw["bx"]),
        assets=tuple(
            AssetInput(k, float(raw[f"{k}_monthly"]), float(raw[f"{k}_rate"])) for k in ASSET_KEYS
        ),
    )


# ── Maths ────────────────────────────────────────────────────────────────────


def _monthly_rate(r: float) -> float:
    return (1.0 + r) ** (1.0 / 12.0) - 1.0


def fv_factor(r: float, k: int) -> float:
    """Future value of 1/month for k months at annual rate r (monthly compounding) — P3."""
    m = _monthly_rate(r)
    return float(k) if m == 0.0 else ((1.0 + m) ** k - 1.0) / m


def simulate(
    p: PlanParams, assets: list[AssetResult] | tuple[AssetInput, ...], house_release: float,
    invest: bool = True,
) -> SimResult:
    """Year by year (12 months each) from current age, followed past plan-until to MAX_AGE (P4–P11)."""
    n = len(assets)
    m_rate = [_monthly_rate(a.rate) for a in assets]
    monthly = [a.monthly for a in assets]
    bal = [0.0] * n
    basis = [0.0] * n
    state = {"savings": 0.0, "portfolio_out": None}
    savings_out: int | None = None
    points: list[SimPoint] = []

    def sell_portfolio(age: int) -> float:
        b = _jsum(bal)
        if not invest or age < p.exit or state["savings"] >= 0 or b <= 0:
            return 0.0
        net = 1.0 - p.tax * max(0.0, b - _jsum(basis)) / b if b > 0 else 0.0
        gross = min(b, -state["savings"] / net)
        keep = 1.0 - gross / b
        for i in range(n):
            bal[i] *= keep
            basis[i] *= keep
        state["savings"] = state["savings"] + gross * net
        if state["portfolio_out"] is None and _jsum(bal) < 1:
            state["portfolio_out"] = age
        return gross * net

    def share(age: int) -> float:
        return 1.0 if age >= p.exit else p.partial if age >= p.ret else 0.0

    total = _jsum(monthly)
    split: list[float | None] = [(m / total if total > 0 else None) for m in monthly]

    def income_now(age: int) -> float:
        if not invest:
            return 0.0
        return _jsum(b * m_rate[i] for i, b in enumerate(bal)) * share(age) * (1.0 - p.tax)

    for age in range(p.now, MAX_AGE + 1):
        past = age > p.end
        if past and (not invest or state["portfolio_out"] is not None):
            break
        events: list[SimEvent] = []
        if age == p.h_sell and p.h2_mode != "same":
            state["savings"] = state["savings"] + house_release
            events.append(SimEvent("house", house_release))
        sv_in = 0.0
        for x in p.sv:
            sv_in = sv_in + (x.amt if (x.amt > 0 and x.age == age) else 0.0)
        if sv_in > 0:
            state["savings"] = state["savings"] + sv_in
            events.append(SimEvent("saving", sv_in))
        bx_out = 0.0
        for x in p.bx:
            bx_out = bx_out + (x.amt if (x.amt > 0 and x.age == age) else 0.0)
        if bx_out > 0:
            state["savings"] = state["savings"] - bx_out
            events.append(SimEvent("expense", bx_out))
        sell_portfolio(age)
        if savings_out is None and not past and state["savings"] < -0.5:
            savings_out = age
        income = income_now(age)
        need = p.need * (1.0 + p.infl) ** (age - p.now) if age >= p.ret else 0.0
        if not past:
            points.append(SimPoint(
                age=age, savings=state["savings"], portfolio=_jsum(bal), put_in=_jsum(basis),
                income=income, need=need, sold=0.0, bal=list(bal), basis=list(basis), events=events,
            ))
        sold_year = 0.0
        for _m in range(12):
            if age < p.ret:
                for i in range(n):
                    if invest:
                        bal[i] = bal[i] * (1.0 + m_rate[i]) + monthly[i]
                        basis[i] = basis[i] + monthly[i]
                    else:
                        state["savings"] = state["savings"] + monthly[i]
                continue
            withdrawn = 0.0
            if invest:
                profits = [b * m_rate[i] for i, b in enumerate(bal)]
                profit = _jsum(profits)
                sh = share(age)
                withdrawn = profit * sh
                kept = profit - withdrawn
                for i in range(n):
                    s = split[i]
                    bal[i] = bal[i] + (profits[i] * (1.0 - sh) if s is None else kept * s)
            state["savings"] = state["savings"] + (withdrawn * (1.0 - p.tax) - need)
            if invest and age < p.exit and total > 0:
                # retirement → exit: keep investing the monthly amounts, paid from savings (after the
                # need); when savings fall short, invest what they cover, split in the same proportions
                put = min(total, max(0.0, state["savings"]))
                for i in range(n):
                    bal[i] = bal[i] + put * monthly[i] / total
                    basis[i] = basis[i] + put * monthly[i] / total
                state["savings"] = state["savings"] - put
            sold_year = sold_year + sell_portfolio(age)
            if savings_out is None and age < p.end and state["savings"] < -0.5:
                savings_out = age
        if not past:
            points[-1].sold = sold_year
    return SimResult(points=points, savings_out=savings_out, portfolio_out=state["portfolio_out"])


def calc(p: PlanParams, start_year: int) -> PlanResult:
    """Full plan result — port of the mock's ``calc()`` (P12–P18)."""
    years: list[YearRow] = []
    total = 0.0
    for a in range(p.ret, p.end):
        monthly = p.need * (1.0 + p.infl) ** (a - p.now)
        total = total + monthly * 12
        years.append(YearRow(age=a, year=start_year + a - p.now, monthly=monthly, cum=total))

    h_years = p.h_sell - p.now
    h_value_at = p.h_value * (1.0 + p.h_appr) ** h_years
    h_gain = max(0.0, h_value_at - p.h_value)
    h_tax_amt = h_gain * p.h_tax
    h_net = h_value_at - h_tax_amt
    h2_at = p.h2_price * (1.0 + p.h_appr) ** h_years
    house_release = 0.0 if p.h2_mode == "same" else h_net - h2_at
    big_expenses = _jsum(x.amt for x in p.bx)
    savings = _jsum(x.amt for x in p.sv)
    target = max(0.0, total + big_expenses - savings - house_release)

    pay_months = (p.ret - p.now) * 12
    assets: list[AssetResult] = []
    for a in p.assets:
        put = a.monthly * pay_months
        value = a.monthly * fv_factor(a.rate, pay_months)
        profit_m = value * _monthly_rate(a.rate)
        assets.append(AssetResult(
            key=a.key, monthly=a.monthly, rate=a.rate, put=put, value=value,
            gain=max(0.0, value - put), profit_m=profit_m,
            withdrawn_net=profit_m * p.partial * (1.0 - p.tax),
        ))
    monthly_sum = _jsum(a.monthly for a in assets)
    put_sum = _jsum(a.put for a in assets)
    value_sum = _jsum(a.value for a in assets)

    with_investing = simulate(p, assets, house_release)
    without_investing = simulate(p, assets, house_release, invest=False)
    portfolio_growth = [
        PotRow(age=x.age, put=x.put_in, **{a.key: x.bal[i] - x.basis[i] for i, a in enumerate(assets)})
        for x in with_investing.points
    ]
    need_all = total + big_expenses
    need_ret = years[0].monthly
    by_point = {x.age: x for x in with_investing.points}

    def at(age: int) -> AgeCell:
        x = by_point[age]
        need = p.need * (1.0 + p.infl) ** (age - p.now)
        income = x.income + x.sold / 12
        # savings pay the shortfall (need − investing) first, as in simulate(); at most a twelfth
        # of the balance a month (that year's draw); a balance at or below zero pays nothing.
        # Working ages too: what the savings could pay if you stopped at that age (display only)
        shortfall = max(0.0, need - income)
        from_savings = min(shortfall, max(0.0, x.savings) / 12)
        monthly = income + from_savings
        return AgeCell(
            age=age, off=False, monthly=monthly, income=income, from_savings=from_savings,
            savings=x.savings, portfolio=x.portfolio, need=need, share=monthly / need,
        )

    by_age = [at(age) if p.now <= age <= p.end else AgeCell(age=age, off=True) for age in AGE_PANELS]
    return PlanResult(
        start_year=start_year, max_age=MAX_AGE, years=years, total=total, assets=assets,
        monthly=monthly_sum, put=put_sum, value=value_sum, portfolio_growth=portfolio_growth,
        with_investing=with_investing, without_investing=without_investing,
        h_value_at=h_value_at, h_gain=h_gain, h_tax_amt=h_tax_amt, h_net=h_net, h2_at=h2_at,
        house_release=house_release, big_expenses=big_expenses, savings=savings, target=target,
        need_all=need_all, need_ret=need_ret, by_age=by_age, at_ret=at(p.ret),
    )
