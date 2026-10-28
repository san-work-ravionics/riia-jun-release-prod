"""RITA Core — goal-driven selection over DDQN-managed sleeves (F44 P3, design 2 rev 1–3 + N9).

**What is a model and what is not.** Each sleeve's daily return stream is the output of that
instrument's own DDQN v2 policy (``core/goal_model_runs.py``).  The selection (which instruments)
and the cross-instrument weights are NOT produced by any RITA model: they come from a
min-variance solve over those model sleeves subject to the goal (disclosed as ``method`` in every output, ``schemas/goal_selection.py``).

Holding model (Revision 1 A4): the union of the location's trading dates (a sleeve's return is 0
on a day its market is closed — forward-filled value); sleeves are bought at weights ``w`` at each
calendar-year start and drift with their model-managed values; Jan 1 is the only rebalance:
``V_t = V_{y0} · Σ w_i · S_{i,t}/S_{i,y0}``.

Annualisation: ``μ = (V_end/V_0)^{365.25/calendar_days} − 1`` (calendar time, anchor = the close
before the window); ``σ = std(R)·√(bars per year)`` with the actual union bars per year; MDD from
``V``; Sharpe via ``performance.sharpe_ratio`` with the weighted instrument ``rf`` (the rate each
policy's DSR was trained on).

Solve (Revision 3 N1/N2, N9): per τ, ``min σ²(w) s.t. fit μ(w) ≥ r, w ≥ 0, Σw = 1`` with
multi-start SLSQP (equal weights, each vertex, the max-μ mix); integer % by largest remainder
(ties by instrument id); repair by 1-point moves from the lowest-fit-μ holding to the
highest-fit-μ instrument while μ_from < μ_to, at most 100 moves.  If that does not give a
feasible integer mix: a deterministic 1 % scan of the segment from the unconstrained
min-variance mix to the max-μ mix, each point rounded and re-checked (``fallback_segment``,
``fallback_checked``).  τ* = lowest fit σ among feasible τ; tie → smaller |tolerance_mdd|.
``meets_goal = fit-feasible AND test μ ≥ target``.

Pure: no I/O.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from rita.core.goal_model_runs import LineageSplit, ModelRun
from rita.core.performance import TRADING_DAYS, max_drawdown, sharpe_ratio

DAYS_PER_YEAR = 365.25
MAX_REPAIR_MOVES = 100
SEGMENT_STEPS = 100            # 1 % steps, the resolution of the integer-% weights
FEAS_TOL = 1e-12


# ── windows + sleeve matrix ────────────────────────────────────────────────────

@dataclass(frozen=True)
class Window:
    name: str          # "fit" | "test"
    anchor: date       # the close before the window (value 1.0)
    start: date
    end: date


def windows(split: LineageSplit, as_of: date) -> tuple[Window, Window]:
    """Fit = the lineage's val years; test = lineage backtest start → ``as_of``."""
    fit = Window("fit", split.val_start - timedelta(days=1), split.val_start, split.val_end)
    test = Window("test", split.backtest_start - timedelta(days=1), split.backtest_start, as_of)
    return fit, test


@dataclass
class SleeveMatrix:
    instruments: list[str]
    dates: pd.DatetimeIndex
    growth: np.ndarray           # (T, K) cumulative growth since the start of the row's year
    segments: list[tuple[int, int, int]]   # (year, first row, last row)
    days: int                    # calendar days anchor → last bar
    rf_daily: np.ndarray         # (K,)

    @property
    def bars(self) -> int:
        return len(self.dates)


def build_matrix(runs: dict[str, ModelRun], window: Window) -> SleeveMatrix:
    """Union calendar of the window's bars; 0 return on a day an instrument does not trade."""
    ids = sorted(runs)
    if not ids:
        raise ValueError("no sleeves")
    lo, hi = pd.Timestamp(window.start), pd.Timestamp(window.end)
    cols = {}
    for i in ids:
        s = runs[i].returns_series()
        s = s[(s.index >= lo) & (s.index <= hi)]
        if not np.isfinite(s.to_numpy(dtype=float)).all():   # design edge 7 (QA-F1)
            raise ValueError(f"{i}: sleeve returns are not finite in the {window.name} window")
        cols[i] = s
    rets = pd.DataFrame(cols).sort_index().fillna(0.0)
    if rets.empty:
        raise ValueError(f"no bars in the {window.name} window")
    arr = rets.to_numpy(dtype=float)
    years = rets.index.year.to_numpy()
    growth = np.empty_like(arr)
    segments: list[tuple[int, int, int]] = []
    for y in sorted(set(years.tolist())):
        idx = np.flatnonzero(years == y)
        first, last = int(idx[0]), int(idx[-1])
        growth[first:last + 1] = np.cumprod(1.0 + arr[first:last + 1], axis=0)
        segments.append((int(y), first, last))
    days = max(1, (rets.index[-1].date() - window.anchor).days)
    rf = np.array([runs[i].rf_daily for i in ids], dtype=float)
    return SleeveMatrix(ids, rets.index, growth, segments, days, rf)


def portfolio_path(m: SleeveMatrix, w: np.ndarray) -> np.ndarray:
    """``V_t`` (start value 1.0 at the anchor), bought at ``w`` at each year start."""
    inner = m.growth @ w
    V = np.empty(m.bars)
    level = 1.0
    for _y, first, last in m.segments:
        V[first:last + 1] = level * inner[first:last + 1]
        level = V[last]
    return V


def _log_end(m: SleeveMatrix, w: np.ndarray) -> float:
    inner_end = np.array([m.growth[last] @ w for _y, _f, last in m.segments])
    return float(np.sum(np.log(np.maximum(inner_end, 1e-300))))


@dataclass(frozen=True)
class Metrics:
    ret: float          # annualised (calendar time)
    vol: float          # annualised with actual bars per year
    mdd: float          # negative fraction
    sharpe: float
    rf_annual: float
    bars: int


def metrics(m: SleeveMatrix, w: np.ndarray) -> Metrics:
    V = portfolio_path(m, w)
    full = np.concatenate([[1.0], V])
    R = np.diff(full) / full[:-1]
    years = m.days / DAYS_PER_YEAR
    mu = float(full[-1] ** (1.0 / years) - 1.0) if full[-1] > 0 else -1.0
    bpy = m.bars / years
    vol = float(np.std(R) * math.sqrt(bpy))
    rf_annual = float(w @ m.rf_daily) * TRADING_DAYS
    return Metrics(ret=mu, vol=vol, mdd=max_drawdown(full), sharpe=sharpe_ratio(R, rf_annual),
                   rf_annual=rf_annual, bars=m.bars)


def _variance(m: SleeveMatrix, w: np.ndarray) -> float:
    full = np.concatenate([[1.0], portfolio_path(m, w)])
    R = np.diff(full) / full[:-1]
    return float(np.var(R) * m.bars / (m.days / DAYS_PER_YEAR))


def _need(m: SleeveMatrix, target: float) -> float:
    """log V_end needed for μ = target over the window."""
    return math.log1p(target) * m.days / DAYS_PER_YEAR


# ── optimisation ───────────────────────────────────────────────────────────────

def _clean(w: np.ndarray) -> np.ndarray:
    w = np.clip(np.asarray(w, dtype=float), 0.0, None)
    s = w.sum()
    return w / s if s > 0 else np.full(len(w), 1.0 / len(w))


def _starts(k: int, extra: list[np.ndarray] | None = None) -> list[np.ndarray]:
    starts = [np.full(k, 1.0 / k)] + [np.eye(k)[i] for i in range(k)]
    return starts + [np.asarray(e, dtype=float) for e in (extra or [])]


_SUM1 = {"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0)}


def _slsqp(fun, x0: np.ndarray, constraints: list[dict]):
    k = len(x0)
    return minimize(fun, x0, method="SLSQP", bounds=[(0.0, 1.0)] * k, constraints=constraints,
                    options={"maxiter": 300, "ftol": 1e-12})


def max_return_mix(m: SleeveMatrix) -> np.ndarray:
    """The mix with the highest window return (log V_end is concave in w → well posed).
    Vertices are scored exactly; SLSQP refines from each start; best wins (first on ties)."""
    k = len(m.instruments)
    cands = [np.eye(k)[i] for i in range(k)]
    if k > 1:
        for x0 in _starts(k):
            res = _slsqp(lambda w: -_log_end(m, _clean(w)), x0, [_SUM1])
            cands.append(_clean(res.x))
    scores = [_log_end(m, c) for c in cands]
    return cands[int(np.argmax(scores))]


def min_variance_mix(m: SleeveMatrix) -> np.ndarray:
    """Unconstrained (no return floor) least-variance mix — the fallback segment's start."""
    k = len(m.instruments)
    cands = [np.eye(k)[i] for i in range(k)]
    if k > 1:
        for x0 in _starts(k):
            res = _slsqp(lambda w: _variance(m, _clean(w)), x0, [_SUM1])
            cands.append(_clean(res.x))
    scores = [_variance(m, c) for c in cands]
    return cands[int(np.argmin(scores))]


def min_variance_at(m: SleeveMatrix, target: float, w_max: np.ndarray) -> np.ndarray | None:
    """Least-variance mix with window μ ≥ target (multi-start SLSQP); None if no start converged
    to a feasible point."""
    k = len(m.instruments)
    need = _need(m, target)
    if k == 1:
        w = np.ones(1)
        return w if _log_end(m, w) >= need - FEAS_TOL else None
    cons = [_SUM1, {"type": "ineq", "fun": lambda w: _log_end(m, _clean(w)) - need}]
    best, best_var = None, math.inf
    for x0 in _starts(k, [w_max]):
        res = _slsqp(lambda w: _variance(m, _clean(w)), x0, cons)
        w = _clean(res.x)
        if not res.success or _log_end(m, w) < need - 1e-9:
            continue
        v = _variance(m, w)
        if v < best_var - 1e-15:
            best, best_var = w, v
    return best


# ── integer weights ────────────────────────────────────────────────────────────

def round_weights(w: np.ndarray, ids: list[str]) -> np.ndarray:
    """Integer % summing to 100 by largest remainder; ties by instrument id."""
    raw = np.round(np.asarray(w, dtype=float) * 100.0, 9)
    base = np.floor(raw).astype(int)
    rem = raw - base
    short = 100 - int(base.sum())
    order = sorted(range(len(ids)), key=lambda i: (-rem[i], ids[i]))
    for i in order[:max(0, short)]:
        base[i] += 1
    return base


def _feasible(m: SleeveMatrix, w_int: np.ndarray, target: float) -> bool:
    return metrics(m, w_int / 100.0).ret >= target - FEAS_TOL


def repair(m: SleeveMatrix, w_int: np.ndarray, target: float,
           sleeve_mu: np.ndarray) -> tuple[np.ndarray, bool]:
    """1-point moves lowest-fit-μ holding → highest-fit-μ instrument while μ_from < μ_to, at
    most ``MAX_REPAIR_MOVES``; returns (weights, feasible)."""
    w = w_int.copy()
    ids = m.instruments
    to = min(range(len(ids)), key=lambda i: (-sleeve_mu[i], ids[i]))
    for _ in range(MAX_REPAIR_MOVES):
        if _feasible(m, w, target):
            return w, True
        holdings = [i for i in range(len(ids)) if w[i] > 0]
        frm = min(holdings, key=lambda i: (sleeve_mu[i], ids[i]))
        if not sleeve_mu[frm] < sleeve_mu[to]:
            break
        w[frm] -= 1
        w[to] += 1
    return w, _feasible(m, w, target)


# ── per-τ solve and the selection ──────────────────────────────────────────────

@dataclass
class TauSolution:
    tolerance: str
    tolerance_mdd: float
    feasible: bool
    weights: np.ndarray | None          # integer %, aligned to the fit matrix instruments
    solver: str | None                  # "slsqp" | "fallback_segment"
    fallback_checked: bool
    fit: Metrics | None
    cap_weights: np.ndarray             # integer %, the max-μ mix
    cap_fit: float
    cap_test: float


def solve_tau(fit_m: SleeveMatrix, test_m: SleeveMatrix, target: float, tolerance: str,
              tolerance_mdd: float) -> TauSolution:
    ids = fit_m.instruments
    k = len(ids)
    w_max = max_return_mix(fit_m)
    cap_int = round_weights(w_max, ids)
    cap_fit = metrics(fit_m, cap_int / 100.0).ret
    cap_test = metrics(test_m, cap_int / 100.0).ret
    sleeve_mu = np.array([metrics(fit_m, np.eye(k)[i]).ret for i in range(k)])

    w_star = min_variance_at(fit_m, target, w_max)
    if w_star is not None:
        w_int, ok = repair(fit_m, round_weights(w_star, ids), target, sleeve_mu)
        if ok:
            return TauSolution(tolerance, tolerance_mdd, True, w_int, "slsqp", False,
                               metrics(fit_m, w_int / 100.0), cap_int, cap_fit, cap_test)

    # N9 fallback: 1 % scan of the segment min-variance → max-μ, rounded and re-checked.
    w_mv = min_variance_mix(fit_m)
    best: tuple[float, int, np.ndarray] | None = None
    for step in range(SEGMENT_STEPS + 1):
        lam = step / SEGMENT_STEPS
        w_int = round_weights((1.0 - lam) * w_mv + lam * w_max, ids)
        mt = metrics(fit_m, w_int / 100.0)
        if mt.ret < target - FEAS_TOL:
            continue
        if best is None or mt.vol < best[0] - 1e-15:
            best = (mt.vol, step, w_int)
    if best is not None:
        w_int = best[2]
        return TauSolution(tolerance, tolerance_mdd, True, w_int, "fallback_segment", True,
                           metrics(fit_m, w_int / 100.0), cap_int, cap_fit, cap_test)
    return TauSolution(tolerance, tolerance_mdd, False, None, None, True, None,
                       cap_int, cap_fit, cap_test)


@dataclass(frozen=True)
class YearResult:
    year: int
    split: str           # fit | test
    year_return: float   # the mix's return in that year (not annualised)
    partial: bool
    met: bool            # vs the target pro-rated to the days covered


def year_results(m: SleeveMatrix, w: np.ndarray, window: Window, target: float) -> list[YearResult]:
    out = []
    for y, _first, last in m.segments:
        r = float(m.growth[last] @ w - 1.0)
        start = max(window.anchor, date(y - 1, 12, 31))
        end = m.dates[last].date()
        days_in_year = (date(y, 12, 31) - date(y - 1, 12, 31)).days
        # Partial = the window itself covers only part of that calendar year.
        partial = window.anchor > date(y - 1, 12, 31) or window.end < date(y, 12, 31)
        frac = (end - start).days / days_in_year if partial else 1.0
        out.append(YearResult(y, window.name, r, partial, r >= (1.0 + target) ** frac - 1.0 - FEAS_TOL))
    return out


@dataclass
class MixResult:
    tolerance: str
    tolerance_mdd: float
    weights: dict[str, int]
    fit: Metrics
    test: Metrics
    gap: float           # target − test return


@dataclass
class GoalSelection:
    target_return: float
    meets_goal: bool
    fit_window: Window
    test_window: Window
    tolerance: str | None = None
    tolerance_mdd: float | None = None
    weights: dict[str, int] = field(default_factory=dict)   # w > 0 only
    fit: Metrics | None = None
    test: Metrics | None = None
    gap: float | None = None
    years: list[YearResult] = field(default_factory=list)
    solver: str | None = None
    fallback_checked: bool = False
    closest: MixResult | None = None
    cap_mix: MixResult | None = None     # the max-μ mix of the best-cap τ (cap_fit / cap_test)
    cap_fit: float = 0.0
    cap_test: float = 0.0
    ladder: list[dict] = field(default_factory=list)
    tolerance_sensitive: bool = False


def _tolerance_sensitive(runs_by_tau: dict[str, dict[str, ModelRun]]) -> bool:
    taus = list(runs_by_tau)
    if len(taus) < 2:
        return False
    ref = runs_by_tau[taus[0]]
    for t in taus[1:]:
        for inst, run in runs_by_tau[t].items():
            if run.daily_returns != ref[inst].daily_returns:
                return True
    return False


def select(runs_by_tau: dict[str, dict[str, ModelRun]], target_return: float,
           split: LineageSplit, as_of: date) -> GoalSelection:
    """``runs_by_tau[τ][instrument]`` → the selection for ``target_return`` (A4/A5, R3)."""
    fit_w, test_w = windows(split, as_of)
    sols: list[tuple[TauSolution, SleeveMatrix, SleeveMatrix]] = []
    for tau, runs in runs_by_tau.items():
        if not runs:
            continue
        fit_m, test_m = build_matrix(runs, fit_w), build_matrix(runs, test_w)
        tol_mdd = next(iter(runs.values())).tolerance_mdd
        sols.append((solve_tau(fit_m, test_m, target_return, tau, tol_mdd), fit_m, test_m))
    if not sols:
        raise ValueError("no eligible sleeves")

    def _tie_key(sol: TauSolution) -> float:
        return abs(sol.tolerance_mdd)

    ladder = [{"tolerance": s.tolerance, "tolerance_mdd": s.tolerance_mdd, "feasible": s.feasible,
               "cap_fit": s.cap_fit, "cap_test": s.cap_test,
               "fit_vol": s.fit.vol if s.fit else None} for s, _f, _t in sols]
    cap_sol, cap_fm, cap_tm = max(sols, key=lambda x: (x[0].cap_fit, -_tie_key(x[0])))
    result = GoalSelection(target_return=target_return, meets_goal=False, fit_window=fit_w,
                           test_window=test_w, cap_fit=cap_sol.cap_fit, cap_test=cap_sol.cap_test,
                           ladder=ladder, tolerance_sensitive=_tolerance_sensitive(runs_by_tau))

    cw = cap_sol.cap_weights / 100.0
    cap_test_m = metrics(cap_tm, cw)
    result.cap_mix = MixResult(
        cap_sol.tolerance, cap_sol.tolerance_mdd,
        {i: int(v) for i, v in zip(cap_fm.instruments, cap_sol.cap_weights) if v > 0},
        metrics(cap_fm, cw), cap_test_m, target_return - cap_test_m.ret)

    feasible = [x for x in sols if x[0].feasible]
    if not feasible:
        result.closest = result.cap_mix
        result.fallback_checked = cap_sol.fallback_checked
        return result

    best = min(feasible, key=lambda x: (x[0].fit.vol, _tie_key(x[0])))
    # exact-tie rule: equal σ → smaller |tolerance_mdd|
    ties = [x for x in feasible if abs(x[0].fit.vol - best[0].fit.vol) <= 1e-12]
    sol, fm, tm_ = min(ties, key=lambda x: _tie_key(x[0]))
    w = sol.weights / 100.0
    test = metrics(tm_, w)
    result.tolerance, result.tolerance_mdd = sol.tolerance, sol.tolerance_mdd
    result.weights = {i: int(v) for i, v in zip(fm.instruments, sol.weights) if v > 0}
    result.fit, result.test = sol.fit, test
    result.solver, result.fallback_checked = sol.solver, sol.fallback_checked
    result.years = year_results(fm, w, fit_w, target_return) + \
        year_results(tm_, w, test_w, target_return)
    result.meets_goal = test.ret >= target_return - FEAS_TOL
    if not result.meets_goal:
        result.gap = target_return - test.ret
    return result


def run_metrics(run: ModelRun, window: Window) -> Metrics:
    """One sleeve alone over a window (evidence for ``portfolio.model_runs``)."""
    m = build_matrix({run.instrument: run}, window)
    return metrics(m, np.ones(1))
