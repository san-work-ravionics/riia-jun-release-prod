"""GoalSelectionService — F44 P3 goal-driven selection over the location's DDQN v2 sleeves.

- ``universe(location)``          — the location's instruments (the P2 instrument → location rule)
- ``location_runs(location)``     — every eligible instrument's lineage policy replayed at every
                                    trained τ (cached), plus the exclusions with reasons
- ``select_for_goal(location, r)`` — min-variance mix of the sleeves with fit μ ≥ r, judged on test
- ``required_return(...)``        — the annual SL response with the agreed guard (R3 N2)
- ``model_runs(location)``        — per-instrument, per-τ fit / test evidence
- ``warm()`` / ``start_warm_thread()`` — background warm-up at start-up (own session, §8)

ADR-002: files only through ``ModelArtifactRepository`` / ``ModelRunCacheRepository``; the
instruments table through ``InstrumentRepository``.  No network: models, CSVs and the cache are
local.  Replays are cached in-process and on disk; one lock per instrument so concurrent callers
compute an instrument once.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import structlog
from sqlalchemy.orm import Session

from rita.config import ModelLineage, get_settings
from rita.core.data_integrity import check_window
from rita.core.goal_model_runs import (
    ACTION_ALLOCATION,
    TOLERANCE_LEVELS,
    LineageSplit,
    ModelRun,
    check_bad_data,
    check_compat,
    env_config_hash,
    required_columns,
    run_policy,
    window_frame,
)
from rita.core.goal_selection import (
    GoalSelection,
    MixResult,
    run_metrics,
    select,
    windows,
)
from rita.core.goal_targets import decide_sl_response
from rita.core.goal_targets import required_return as compute_required_return
from rita.core.instrument_config import load_instrument_env_config
from rita.core.performance import TRADING_DAYS
from rita.repositories.instrument import InstrumentRepository
from rita.repositories.model_artifact import ModelArtifactRepository
from rita.repositories.model_run_cache import ModelRunCacheRepository, cache_key
from rita.schemas.goal_selection import (
    ExcludedOut,
    GoalSelectionOut,
    GradedOut,
    HoldingOut,
    InstrumentRunsOut,
    LadderOut,
    MixOut,
    ModelRunOut,
    ModelRunsOut,
    RequiredReturnOut,
    RunMetricsOut,
    WindowOut,
    YearOut,
)
from rita.services.user_portfolio_service import UserPortfolioService, location_currency

log = structlog.get_logger(__name__)

# The graded project objective, as in performance.compute_all_metrics (reported, not optimised).
GRADED_SHARPE = 1.0
GRADED_MDD = -0.10


class GoalSelectionError(Exception):
    """A coded failure: ``invalid_input`` | ``not_found`` | ``unavailable``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ── process-wide caches + locks ────────────────────────────────────────────────

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()
_RUN_MEMO: dict[tuple[str, str, str], tuple[str, ModelRun]] = {}   # (inst, lineage, τ) → (key, run)
_MEMO_GUARD = threading.Lock()


def _instrument_lock(instrument: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(instrument, threading.Lock())


def clear_memo() -> None:
    """Drop the in-process replay cache (tests)."""
    with _MEMO_GUARD:
        _RUN_MEMO.clear()


@dataclass
class _Prepared:
    runs: dict[str, ModelRun] | None = None      # τ → run
    excluded: ExcludedOut | None = None
    last_date: date | None = None


@dataclass
class LocationRuns:
    location: str
    lineage: ModelLineage
    split: LineageSplit
    runs: dict[str, dict[str, ModelRun]] = field(default_factory=dict)   # inst → τ → run
    excluded: list[ExcludedOut] = field(default_factory=list)
    as_of: date | None = None
    window_start: date | None = None


def _excl(inst: str, reason: str, detail: str | None = None) -> ExcludedOut:
    return ExcludedOut(instrument_id=inst, reason=reason, detail=detail)


class GoalSelectionService:
    def __init__(self, db: Session, artifacts: ModelArtifactRepository | None = None,
                 cache: ModelRunCacheRepository | None = None) -> None:
        self._db = db
        self._artifacts = artifacts or ModelArtifactRepository.from_settings()
        self._cache = cache or ModelRunCacheRepository.from_settings()

    # ── universe + lineage ─────────────────────────────────────────────────────

    @staticmethod
    def check_location(location: str) -> None:
        if location not in get_settings().retirement_plan.locations:
            raise GoalSelectionError("invalid_input", f"unknown location {location!r}")

    def universe(self, location: str) -> list[str]:
        """The location's instruments: the same instrument → location rule as P2's 422."""
        self.check_location(location)
        pf = UserPortfolioService(self._db)
        ids = [i.instrument_id for i in InstrumentRepository(self._db).read_all()]
        return sorted(i for i in ids if pf.instrument_location(i) == location)

    @staticmethod
    def active_lineage() -> ModelLineage:
        lineages = get_settings().goal_selection.model_lineages
        if not lineages:
            raise GoalSelectionError("unavailable", "no model lineage is registered")
        return lineages[0]

    # ── replays ────────────────────────────────────────────────────────────────

    def _prepare(self, inst: str, lineage: ModelLineage, split: LineageSplit) -> _Prepared:
        path = self._artifacts.find(inst, lineage)
        if path is None:
            return _Prepared(excluded=_excl(inst, "no_model", f"no {lineage.name} model"))
        marker = self._artifacts.rewrite_marker(inst)
        if marker is not None:
            invalid = marker.get("lineages_invalidated") or []
            if lineage.name in invalid or "*" in invalid:
                after = marker.get("integrity_after_passed")
                return _Prepared(excluded=_excl(
                    inst, "retrain_needed",
                    f"price history rewritten {marker.get('rewritten_at', '?')[:10]} "
                    f"(post-rewrite integrity {'pass' if after else 'fail'}); "
                    f"the {lineage.name} model was trained on the old data"))
        try:
            frame = self._artifacts.load_indicator_frame(inst)
        except Exception as exc:  # noqa: BLE001 — unreadable data is an exclusion, not a crash
            return _Prepared(excluded=_excl(inst, "bad_data", f"data load failed: {type(exc).__name__}"))
        if frame is None:
            return _Prepared(excluded=_excl(inst, "no_data"))
        df = frame.df
        if window_frame(df, split.train_end).shape[0] < 2:
            return _Prepared(excluded=_excl(inst, "no_data", f"no bars after {split.train_end}"))
        integ = check_window(df["Close"], split.train_end)
        if not integ.passed:
            return _Prepared(excluded=_excl(inst, "data_integrity", integ.detail()))

        env_cfg = load_instrument_env_config(inst)
        sha = self._artifacts.sha256(path)
        parts = (inst, lineage.name, sha, env_config_hash(env_cfg), split.split_hash(),
                 frame.data_hash)
        keys = {tau: cache_key(*parts, tau) for tau in TOLERANCE_LEVELS}

        with _instrument_lock(inst):
            runs: dict[str, ModelRun] = {}
            for tau in TOLERANCE_LEVELS:
                with _MEMO_GUARD:
                    hit = _RUN_MEMO.get((inst, lineage.name, tau))
                if hit is not None and hit[0] == keys[tau]:
                    runs[tau] = hit[1]
                    continue
                cached = self._cache.get(inst, lineage.name, tau, keys[tau])
                if cached is not None:
                    try:
                        runs[tau] = ModelRun.from_dict(cached)
                    except (KeyError, TypeError, ValueError):
                        continue
                    with _MEMO_GUARD:
                        _RUN_MEMO[(inst, lineage.name, tau)] = (keys[tau], runs[tau])
            missing = [t for t in TOLERANCE_LEVELS if t not in runs]
            if missing:
                try:
                    model = self._artifacts.load(path)
                except Exception as exc:  # noqa: BLE001
                    return _Prepared(excluded=_excl(inst, "load_failed", type(exc).__name__))
                if check_compat(model, df, env_cfg) is not None:
                    return _Prepared(excluded=_excl(
                        inst, "feature_mismatch",
                        f"model obs {getattr(model.observation_space, 'shape', '?')}, "
                        f"actions {getattr(model.action_space, 'n', '?')}"))
                n_obs = int(model.observation_space.shape[0])
                bad = check_bad_data(window_frame(df, split.train_end),
                                     required_columns(df, env_cfg, n_obs))
                if bad is not None:
                    return _Prepared(excluded=_excl(inst, "bad_data", bad))
                for tau in missing:
                    run = run_policy(model, df, env_cfg, split, tau, instrument=inst,
                                     lineage=lineage.name, model_sha12=sha[:12])
                    self._cache.put(inst, lineage.name, tau, keys[tau], run.to_dict())
                    with _MEMO_GUARD:
                        _RUN_MEMO[(inst, lineage.name, tau)] = (keys[tau], run)
                    runs[tau] = run
                log.info("goal_selection.replayed", instrument=inst, lineage=lineage.name,
                         tolerances=len(missing))
        return _Prepared(runs=runs, last_date=frame.last_date)

    def location_runs(self, location: str) -> LocationRuns:
        lineage = self.active_lineage()
        split = self._artifacts.lineage_split(lineage)
        out = LocationRuns(location=location, lineage=lineage, split=split)
        prepared: dict[str, _Prepared] = {}
        for inst in self.universe(location):
            p = self._prepare(inst, lineage, split)
            if p.excluded is not None:
                out.excluded.append(p.excluded)
            else:
                prepared[inst] = p
        if prepared:
            latest = max(p.last_date for p in prepared.values())
            for inst, p in prepared.items():
                if p.last_date < latest:
                    out.excluded.append(_excl(inst, "stale_data",
                                              f"last bar {p.last_date}, location {latest}"))
                else:
                    out.runs[inst] = p.runs
            out.as_of = latest
            if out.runs:
                out.window_start = min(r["medium"].window_start for r in out.runs.values())
        out.excluded.sort(key=lambda e: e.instrument_id)
        return out

    def _eligible(self, location: str) -> LocationRuns:
        self.check_location(location)
        lr = self.location_runs(location)
        if not lr.runs:
            detail = ", ".join(f"{e.instrument_id}:{e.reason}" for e in lr.excluded) or "none"
            raise GoalSelectionError(
                "not_found", f"no eligible model-managed instrument in {location} (excluded: {detail})")
        return lr

    # ── outputs ────────────────────────────────────────────────────────────────

    @staticmethod
    def _holdings(lr: LocationRuns, tau: str, weights: dict[str, int]) -> list[HoldingOut]:
        out = []
        for inst in sorted(weights):
            run = lr.runs[inst][tau]
            pct = int(weights[inst])
            out.append(HoldingOut(
                instrument_id=inst, allocation_pct=pct, tolerance=tau,
                tolerance_mdd=run.tolerance_mdd, model_action=run.today_action,
                model_exit=run.today_action == "cash",
                model_derisk=run.today_action in ("half", "hedged"),
                invested_pct=pct * ACTION_ALLOCATION[run.today_action],
                sl_drawdown_limit=run.hard_mdd_limit, episode_start=run.episode_start,
                episode_day=run.episode_day, episode_length=run.episode_length,
                model_sha12=run.model_sha12,
            ))
        return out

    def _mix_out(self, lr: LocationRuns, mix: MixResult) -> MixOut:
        return MixOut(
            tolerance=mix.tolerance, tolerance_mdd=mix.tolerance_mdd,
            holdings=self._holdings(lr, mix.tolerance, mix.weights),
            fit_return=mix.fit.ret, fit_vol=mix.fit.vol, fit_mdd=mix.fit.mdd,
            test_return=mix.test.ret, test_vol=mix.test.vol, test_mdd=mix.test.mdd, gap=mix.gap,
        )

    def _selection_out(self, lr: LocationRuns, sel: GoalSelection) -> GoalSelectionOut:
        fit_w, test_w = sel.fit_window, sel.test_window
        out = GoalSelectionOut(
            location=lr.location, currency=location_currency(lr.location),
            target_return=sel.target_return, meets_goal=sel.meets_goal, lineage=lr.lineage.name,
            fit_window=WindowOut(start=fit_w.start, end=fit_w.end),
            test_window=WindowOut(start=test_w.start, end=test_w.end),
            cap_fit=sel.cap_fit, cap_test=sel.cap_test,
            ladder=[LadderOut(**row) for row in sel.ladder],
            tolerance_sensitive=sel.tolerance_sensitive, fallback_checked=sel.fallback_checked,
            excluded=lr.excluded, as_of=lr.as_of, window_start=lr.window_start,
        )
        if sel.tolerance is not None:
            out.tolerance, out.tolerance_mdd = sel.tolerance, sel.tolerance_mdd
            out.fit_return, out.fit_vol, out.fit_mdd = sel.fit.ret, sel.fit.vol, sel.fit.mdd
            out.test_return, out.test_vol, out.test_mdd = sel.test.ret, sel.test.vol, sel.test.mdd
            out.test_sharpe, out.rf_annual = sel.test.sharpe, sel.test.rf_annual
            out.gap = sel.gap
            out.years = [YearOut(year=y.year, split=y.split, year_return=y.year_return,
                                 partial=y.partial, met=y.met) for y in sel.years]
            out.holdings = self._holdings(lr, sel.tolerance, sel.weights)
            out.graded = GradedOut(sharpe_gt_1=sel.test.sharpe > GRADED_SHARPE,
                                   mdd_within_10=sel.test.mdd > GRADED_MDD)
            out.solver = sel.solver
        if sel.closest is not None:
            out.closest = self._mix_out(lr, sel.closest)
        return out

    @staticmethod
    def _by_tau(lr: LocationRuns) -> dict[str, dict[str, ModelRun]]:
        return {tau: {inst: r[tau] for inst, r in lr.runs.items()} for tau in TOLERANCE_LEVELS}

    def _select(self, lr: LocationRuns, target_return: float) -> GoalSelection:
        try:
            return select(self._by_tau(lr), target_return, lr.split, lr.as_of)
        except ValueError as exc:
            raise GoalSelectionError("unavailable", str(exc)) from exc

    def select_for_goal(self, location: str, target_return: float,
                        as_of: date | None = None) -> GoalSelectionOut:
        lr = self._eligible(location)
        if as_of is not None and as_of != lr.as_of:
            raise GoalSelectionError(
                "invalid_input", f"as_of must be the cached data date {lr.as_of.isoformat()}")
        return self._selection_out(lr, self._select(lr, target_return))

    def required_return(self, location: str, goal_return: float, ytd_return: float,
                        as_of: date, year_start: date, reselections_used: int) -> RequiredReturnOut:
        self.check_location(location)
        try:
            req = compute_required_return(goal_return, ytd_return, as_of, year_start)
        except ValueError as exc:
            raise GoalSelectionError("invalid_input", str(exc)) from exc
        max_n = get_settings().goal_selection.max_reselections_per_year
        base: dict[str, Any] = dict(
            location=location, goal_return=goal_return, ytd_return=ytd_return,
            year_fraction=req.year_fraction, remaining_fraction=req.remaining_fraction,
            rest_of_year_return=req.rest_of_year_return, required_return=req.required_return,
            effective_return=req.effective_return, reselections_used=reselections_used,
            reselections_next=reselections_used, max_reselections=max_n,
        )
        # Steps 1–3 need no model run (cap unknown yet → +inf never trips step 4).
        pre = decide_sl_response(req, float("inf"), reselections_used, max_n)
        if pre.action != "solve":
            status = "on_track" if pre.action == "on_track" else "back_to_plan"
            return RequiredReturnOut(**base, status=status, reason=pre.reason)

        lr = self._eligible(location)
        r_prime = req.required_return
        sel = self._select(lr, r_prime)
        base.update(cap_fit=sel.cap_fit, cap_test=sel.cap_test)
        decision = decide_sl_response(req, sel.cap_fit, reselections_used, max_n)
        if decision.reason == "cap" or sel.tolerance is None:
            closest = sel.closest or sel.cap_mix
            return RequiredReturnOut(**base, status="back_to_plan", reason="cap",
                                     closest=self._mix_out(lr, closest) if closest else None)
        if sel.meets_goal:
            base["reselections_next"] = reselections_used + 1
            return RequiredReturnOut(**base, status="reselect_proposed", reason="ok",
                                     proposal=self._selection_out(lr, sel))
        solved = MixResult(sel.tolerance, sel.tolerance_mdd, sel.weights, sel.fit, sel.test,
                           sel.gap if sel.gap is not None else r_prime - sel.test.ret)
        return RequiredReturnOut(**base, status="back_to_plan", reason="test_shortfall",
                                 closest=self._mix_out(lr, solved))

    def model_runs(self, location: str) -> ModelRunsOut:
        lr = self._eligible(location)
        fit_w, test_w = windows(lr.split, lr.as_of)
        instruments = []
        for inst in sorted(lr.runs):
            runs_out = []
            for tau in TOLERANCE_LEVELS:
                run = lr.runs[inst][tau]
                metrics = {}
                for name, w in (("fit", fit_w), ("test", test_w)):
                    m = run_metrics(run, w)
                    metrics[name] = RunMetricsOut(ann_return=m.ret, ann_vol=m.vol, mdd=m.mdd,
                                                  sharpe=m.sharpe, bars=m.bars)
                runs_out.append(ModelRunOut(tolerance=tau, tolerance_mdd=run.tolerance_mdd,
                                            oob_bars=run.oob_bars, today_action=run.today_action,
                                            **metrics))
            med = lr.runs[inst]["medium"]
            instruments.append(InstrumentRunsOut(
                instrument_id=inst, lineage=med.lineage, model_sha12=med.model_sha12,
                rf_annual=float(med.rf_daily) * TRADING_DAYS, episode_length=med.episode_length,
                runs=runs_out))
        return ModelRunsOut(
            location=location, lineage=lr.lineage.name, as_of=lr.as_of,
            window_start=lr.window_start,
            fit_window=WindowOut(start=fit_w.start, end=fit_w.end),
            test_window=WindowOut(start=test_w.start, end=test_w.end),
            instruments=instruments, excluded=lr.excluded,
        )

    # ── warm-up ────────────────────────────────────────────────────────────────

    def warm(self) -> dict[str, int]:
        """Replay every location's eligible instruments into the caches; never raises."""
        done: dict[str, int] = {}
        for location in get_settings().retirement_plan.locations:
            try:
                lr = self.location_runs(location)
                done[location] = len(lr.runs)
            except Exception as exc:  # noqa: BLE001 — warm-up must never take the app down
                log.warning("goal_selection.warm_failed", location=location,
                            error=type(exc).__name__)
        log.info("goal_selection.warmed", **done)
        return done


def _warm_job() -> None:
    from rita.database import SessionLocal

    db = SessionLocal()
    try:
        GoalSelectionService(db).warm()
    except Exception as exc:  # noqa: BLE001
        log.warning("goal_selection.warm_thread_failed", error=type(exc).__name__)
    finally:
        db.close()


def start_warm_thread() -> threading.Thread:
    """Start the background warm-up (own ``SessionLocal``, closed in ``finally``); returns at once."""
    t = threading.Thread(target=_warm_job, name="goal-selection-warm", daemon=True)
    t.start()
    return t
