"""SleeveTraceService — one instrument's RITA DDQN v2 sleeve, its levels and the model inputs behind
them (F44 P4 ``portfolio.sleeve_trace``).

Everything comes from ``GoalSelectionService.instrument_runs`` (the P3 replay cache; never a new
model family when warm):
- entry / exit = the model's own action changes (cash → invested / → cash);
- SL = the sleeve's drawdown from its peak since max(entry, current episode start) at
  ``hard_mdd_limit`` (the lineage's training constraint — a config input, not a model output); the
  peak resets at each model-episode start, as in training;
- the rationale = the v2 observation recomputed by ``core/jarvis_rationale`` (parity-tested);
- τ = the journey's (``tolerance_rule = selection``) or, for an instrument outside the pick, the
  P3 τ* rule on this one sleeve: the τ with the lowest fit-window volatility.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from rita.core.goal_model_runs import ACTION_ALLOCATION, TOLERANCE_LEVELS, ModelRun, window_frame
from rita.core.goal_selection import run_metrics, windows
from rita.core.instrument_config import load_instrument_env_config
from rita.core.jarvis_rationale import action_name, v2_episode_observations, v2_rationale
from rita.core.trading_env_v2 import _ema_ratio_enabled
from rita.schemas.jarvis import MarkerOut, RationaleOut, SleeveDetailOut, SleeveTraceOut
from rita.services.goal_selection_service import GoalSelectionError, GoalSelectionService, InstrumentRuns


def tau_star(runs: dict[str, ModelRun], split, as_of: date) -> str:
    """P3 τ* rule on one sleeve: the trained τ with the lowest fit-window volatility."""
    fit_w, _ = windows(split, as_of)
    vols = [(run_metrics(runs[t], fit_w).vol, i, t) for i, t in enumerate(TOLERANCE_LEVELS)]
    return min(vols)[2]


def marker_kind(prev: tuple[float, float], new: tuple[float, float]) -> str | None:
    if prev == new:
        return None
    if prev[0] == 0.0 and new[0] > 0.0:
        return "entry"
    if new[0] == 0.0:
        return "exit"
    if new[0] < prev[0] or (new[0] == prev[0] and new[1] > prev[1]):
        return "derisk"
    return "rerisk"


def next_reset(as_of: date, episode_day: int, episode_length: int) -> date:
    """Business-day estimate of the next model-episode start."""
    remaining = max(1, int(episode_length) - int(episode_day))
    return pd.Timestamp(np.busday_offset(np.datetime64(as_of), remaining, roll="forward")).date()


def _value_path(dates: list[date], rets: list[float], start: date) -> tuple[list[date], np.ndarray]:
    """Sleeve value from the close of ``start`` (value 1 there) over the bars after it."""
    keep = [k for k, d in enumerate(dates) if d > start]
    vals = np.cumprod([1.0 + rets[k] for k in keep]) if keep else np.array([])
    return [start] + [dates[k] for k in keep], np.concatenate([[1.0], vals])


def _base_date(run: ModelRun, d: date | None) -> date:
    """The last bar on or before ``d`` (window start when ``d`` is earlier / None)."""
    if d is None or d <= run.window_start:
        return run.window_start
    prior = [x for x in run.dates if x <= d]
    return prior[-1] if prior else run.window_start


class SleeveTraceService:
    def __init__(self, db: Session, goal: GoalSelectionService | None = None) -> None:
        self._goal = goal or GoalSelectionService(db)

    def _check(self, location: str, instrument: str) -> str:
        inst = instrument.upper()
        if inst not in self._goal.universe(location):
            raise GoalSelectionError("invalid_input", f"instrument {inst} is not in location {location}")
        return inst

    def trace(self, location: str, instrument: str, tolerance: str | None = None,
              entry_date: date | None = None, since: date | None = None,
              detail: bool = False) -> SleeveTraceOut:
        inst = self._check(location, instrument)
        ir: InstrumentRuns = self._goal.instrument_runs(inst)
        if ir.excluded is not None:
            return SleeveTraceOut(instrument_id=inst, status="excluded", excluded_reason=ir.excluded.reason,
                                  excluded_detail=ir.excluded.detail, lineage=ir.lineage.name)
        runs = ir.runs
        any_run = runs["medium"]
        if tolerance is not None:
            tau, rule = tolerance, "selection"
        else:
            tau, rule = tau_star(runs, ir.split, any_run.as_of), "p3_tau_rule_single_sleeve"
        run = runs[tau]
        close = ir.frame["Close"] if ir.frame is not None else None

        def close_at(d: date) -> float | None:
            if close is None:
                return None
            ts = pd.Timestamp(d)
            return float(close.loc[ts]) if ts in close.index else None

        # return since
        since_base = _base_date(run, since or entry_date)
        _, v = _value_path(run.dates, run.daily_returns, since_base)
        ret_since = float(v[-1] - 1.0)

        # SL: peak since max(entry, current episode start)
        peak_base = _base_date(run, max(entry_date or run.window_start, run.episode_start))
        _, pv = _value_path(run.dates, run.daily_returns, peak_base)
        running_peak = np.maximum.accumulate(pv)
        peak, now = float(running_peak[-1]), float(pv[-1])
        limit = float(run.hard_mdd_limit)
        sl_level = peak * (1.0 + limit)
        sl_hit = bool(np.min(pv / running_peak - 1.0) <= limit)

        # entries / exits from the model's own actions
        markers = self._markers(run, close_at)
        last_entry = next((m.date for m in reversed(markers) if m.kind == "entry"), None)
        last_exit = next((m.date for m in reversed(markers) if m.kind == "exit"), None)
        if ACTION_ALLOCATION[run.today_action] > 0:
            last_exit = None if (last_entry and last_exit and last_exit < last_entry) else last_exit

        out = SleeveTraceOut(
            instrument_id=inst, status="ok", lineage=run.lineage, model_sha12=run.model_sha12,
            tolerance=tau, tolerance_rule=rule, as_of=run.as_of, window_start=run.window_start,
            episode_length=run.episode_length, episode_start=run.episode_start,
            episode_day=run.episode_day,
            next_reset=next_reset(run.as_of, run.episode_day, run.episode_length),
            hard_mdd_limit=limit, today_action=run.today_action,
            invested_fraction=ACTION_ALLOCATION[run.today_action], last_close=close_at(run.as_of),
            since=since_base, return_since=ret_since, sleeve_peak=peak, sleeve_now=now,
            sl_level=sl_level, sl_distance=sl_level / now - 1.0, sl_hit=sl_hit,
            last_entry_date=last_entry, last_exit_date=last_exit,
        )
        if detail:
            out.detail = self._detail(inst, ir, run, since, entry_date, markers, close_at)
        return out

    @staticmethod
    def _markers(run: ModelRun, close_at) -> list[MarkerOut]:
        out = []
        prev = (0.0, 0.0)
        decision_dates = [run.window_start] + run.dates[:-1]
        for k, d in enumerate(decision_dates):
            new = (float(run.allocations[k]), float(run.hedge_flags[k]))
            kind = marker_kind(prev, new)
            if kind is not None:
                out.append(MarkerOut(date=d, kind=kind, close=close_at(d), from_action=action_name(*prev),
                                     to_action=action_name(*new)))
            prev = new
        today = (ACTION_ALLOCATION[run.today_action], 1.0 if run.today_action == "hedged" else 0.0)
        kind = marker_kind(prev, today)
        if kind is not None:
            out.append(MarkerOut(date=run.as_of, kind=kind, close=close_at(run.as_of),
                                 from_action=action_name(*prev), to_action=run.today_action))
        return out

    def _detail(self, inst: str, ir: InstrumentRuns, run: ModelRun, since: date | None,
                entry_date: date | None, markers: list[MarkerOut], close_at) -> SleeveDetailOut:
        # the chart always spans the whole replay window; ``since`` only moves ``return_since``
        start = run.window_start
        dates, vals = _value_path(run.dates, run.daily_returns, start)
        # SL line: running peak since max(entry, episode start), reset at each episode start
        starts = set(run.episode_starts)
        sl_line, peak = [], 0.0
        for d, v in zip(dates, vals):
            if d in starts and (entry_date is None or d >= entry_date):
                peak = v
            if entry_date is not None and d < entry_date:
                peak = v
            peak = max(peak, v)
            sl_line.append(peak * (1.0 + run.hard_mdd_limit))
        idx = {d: k for k, d in enumerate(run.dates)}
        alloc = [0.0] + [run.allocations[idx[d]] for d in dates[1:]]
        hedged = [0.0] + [run.hedge_flags[idx[d]] for d in dates[1:]]
        rationale = self.rationale(inst, ir, run, markers[-1].date if markers else run.as_of)
        return SleeveDetailOut(
            dates=dates, close=[close_at(d) for d in dates], allocation=alloc, hedged=hedged,
            sleeve_value=[float(x) for x in vals], sl_line=sl_line,
            episode_starts=[d for d in run.episode_starts if d >= start],
            markers=[m for m in markers if m.date >= start], rationale=rationale,
        )

    @staticmethod
    def rationale(inst: str, ir: InstrumentRuns, run: ModelRun, when: date) -> RationaleOut | None:
        """The v2 observation at the decision bar ``when`` (the model's inputs that day)."""
        if ir.frame is None:
            return None
        cfg = load_instrument_env_config(inst)
        data = window_frame(ir.frame, ir.split.train_end)
        pos = {d.date(): k for k, d in enumerate(data.index)}
        if when not in pos:
            return None
        p = pos[when]
        anchor = max(s for s in run.episode_starts if s <= when)
        a = pos[anchor]
        i = p - a
        L = int(run.episode_length)
        use_ema = _ema_ratio_enabled(data, cfg)
        allocs = run.allocations[a:p]
        hedges = run.hedge_flags[a:p]
        obs = v2_episode_observations(data.iloc[a:p + 1], allocs, hedges, cfg, run.tolerance, L, use_ema)[i]
        inputs, state = v2_rationale(data.iloc[p], obs, run.tolerance, use_ema)
        if p == len(data) - 1:
            action = run.today_action
        else:
            action = action_name(run.allocations[p], run.hedge_flags[p])
        prev = action_name(run.allocations[p - 1], run.hedge_flags[p - 1]) if i > 0 else "cash"
        return RationaleOut(date=when, action=action, prev_action=prev, inputs=inputs, state=state)
