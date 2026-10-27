"""RITA Core — annual goal targets and the stop-loss response guard (F44 P3, A8 + R3 N2).

Targets are per calendar year of the location's exchange.  One day-count convention: ``as_of``
is a close; ``s`` = the year start (Jan 1, or the first track date); ``D`` = days in the year.

- ``f_Y = (Dec31 − s + 1)/D``            — the fraction of the year the plan runs this year
- ``φ   = (Dec31 − as_of)/D``           — the fraction still to run after today's close
- ``g   = (1+r)^{f_Y}/(1+ytd) − 1``      — rest-of-year return still needed (full year: the
  user's ``(1+r)/(1+ytd) − 1``)
- ``r′  = ((1+r)^{f_Y}/(1+ytd))^{1/φ} − 1`` — that need, annualised (the target the models are
  re-run at); at ``as_of = s − 1`` with ytd = 0, ``r′ = r`` exactly
- ``r′_eff = max(r′, r)``

Guard (R3 N2), in order: (1) ``as_of = Dec31`` → back_to_plan / ``year_end``; (2) ``r′ ≤ r`` →
``on_track``; (3) re-selections used ≥ max → back_to_plan / ``count``; (4) ``r′ > cap_fit`` →
back_to_plan / ``cap``; (5) solve at r′ (the service): test μ ≥ r′ → ``reselect_proposed`` else
back_to_plan / ``test_shortfall``.  A re-selection is counted only on ``reselect_proposed``.

The guard limit is the agreed constant from settings (``goal_selection.max_reselections_per_year``),
passed in.  Pure: no I/O.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

ASSET_CLASSES = ("idx", "eq", "com", "alt")


def blend_goal_return(assets: Iterable[tuple[float | None, float | None]]) -> float | None:
    """Σ(monthly·rate)/Σmonthly over ``(monthly, rate)`` pairs; None when Σmonthly = 0.
    A missing (None) amount counts as 0; an amount with no rate counts as rate 0."""
    total = 0.0
    weighted = 0.0
    for monthly, rate in assets:
        m = float(monthly or 0.0)
        total += m
        weighted += m * float(rate or 0.0)
    if total == 0:
        return None
    return weighted / total


def _year_end(d: date) -> date:
    return date(d.year, 12, 31)


def _days_in_year(year: int) -> int:
    return (date(year, 12, 31) - date(year - 1, 12, 31)).days


def year_fraction(start: date, end: date) -> float:
    """Calendar-day fraction of ``start``'s year from ``start`` to ``end``, start inclusive."""
    return ((end - start).days + 1) / _days_in_year(start.year)


@dataclass(frozen=True)
class RequiredReturn:
    goal_return: float
    ytd_return: float
    year_fraction: float                  # f_Y
    remaining_fraction: float             # φ
    rest_of_year_return: float            # g
    required_return: float | None         # r′ (None at year end)
    effective_return: float | None        # max(r′, r)
    year_end: bool


def required_return(goal_return: float, ytd_return: float, as_of: date,
                    year_start: date) -> RequiredReturn:
    """A8.  ``ValueError`` when ytd ≤ −1 or ``as_of`` is outside ``[year_start − 1, Dec31]``."""
    if ytd_return <= -1.0:
        raise ValueError("ytd_return must be greater than -1")
    if goal_return <= -1.0:
        raise ValueError("goal_return must be greater than -1")
    dec31 = _year_end(year_start)
    if not (year_start - timedelta(days=1) <= as_of <= dec31):
        raise ValueError("as_of must be between the day before year_start and Dec 31 of that year")
    D = _days_in_year(year_start.year)
    f_y = year_fraction(year_start, dec31)
    phi = (dec31 - as_of).days / D
    growth_needed = (1.0 + goal_return) ** f_y / (1.0 + ytd_return)
    g = growth_needed - 1.0
    if phi <= 0:
        return RequiredReturn(goal_return, ytd_return, f_y, 0.0, g, None, None, True)
    # = growth_needed ** (1/φ) − 1, in log space (log1p / expm1) so r′ = r at as_of = s − 1
    # holds to the last bit instead of picking up the (1 + r) − 1 rounding.
    r_prime = math.expm1((f_y * math.log1p(goal_return) - math.log1p(ytd_return)) / phi)
    return RequiredReturn(goal_return, ytd_return, f_y, phi, g, r_prime,
                          max(r_prime, goal_return), False)


def target_to_date(goal_return: float, year_start: date, as_of: date) -> float:
    """F44 P4 (rev 1 B2): the annual goal's path to date, ``T = (1+r)^{(as_of − s + 1)/D} − 1``,
    with ``D`` = days in ``s``'s calendar year (the same day count as ``required_return``).

    ``r`` is always the user's annual goal — never a re-selection rate r′.  ``as_of = s − 1`` (or
    earlier) → 0.  Property: a ytd equal to ``T`` gives ``required_return(...).required_return
    == r`` (on the path ⇔ the guard's ``on_track``)."""
    if goal_return <= -1.0:
        raise ValueError("goal_return must be greater than -1")
    days = (as_of - year_start).days + 1
    if days <= 0:
        return 0.0
    return math.expm1(days / _days_in_year(year_start.year) * math.log1p(goal_return))


def chain_returns(segment_returns: Iterable[float]) -> float:
    """F44 P4 (rev 2 N1): one return over consecutive periods, ``Π(1+r_k) − 1``."""
    growth = 1.0
    for r in segment_returns:
        growth *= 1.0 + float(r)
    return growth - 1.0


@dataclass(frozen=True)
class SlDecision:
    action: str          # "back_to_plan" | "on_track" | "solve"
    reason: str          # "year_end" | "on_track" | "count" | "cap" | "ok"


def decide_sl_response(required: RequiredReturn, cap_fit: float | None, reselections_used: int,
                       max_reselections: int) -> SlDecision:
    """Guard steps 1–4; ``solve`` means step 5 (re-run the selection at r′) is the caller's."""
    if required.year_end or required.required_return is None:
        return SlDecision("back_to_plan", "year_end")
    if required.required_return <= required.goal_return:
        return SlDecision("on_track", "on_track")
    if reselections_used >= max_reselections:
        return SlDecision("back_to_plan", "count")
    if cap_fit is None or required.required_return > cap_fit:
        return SlDecision("back_to_plan", "cap")
    return SlDecision("solve", "ok")
