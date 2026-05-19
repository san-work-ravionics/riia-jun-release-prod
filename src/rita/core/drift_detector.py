"""
RITA Core — Drift & Health Detector (DB-backed)

Monitors model performance stability, data freshness, and pipeline health
by reading all data from the SQLAlchemy database instead of CSV files.

Key checks:
  1. Sharpe drift        : Latest Sharpe vs rolling-window mean (warn if Δ > threshold)
  2. Return degradation  : Backtest return trend over last N rounds (warn if consistently declining)
  3. Data freshness      : Days since latest date in market_data_cache table (CSV fallback)
  4. Pipeline health     : Run failure rate + per-model-version timing from training/backtest tables
  5. Constraint breach   : Count of rounds failing Sharpe > 1.0 or MDD < 10%

Status levels:  "ok" | "warn" | "alert"
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

import structlog
from sqlalchemy.orm import Session

from rita.repositories.training import TrainingRunsRepository
from rita.repositories.backtest import BacktestRunsRepository
from rita.repositories.market_data import MarketDataCacheRepository

log = structlog.get_logger()


# ─── Constants ────────────────────────────────────────────────────────────────

SHARPE_TARGET = 1.0
MDD_LIMIT_PCT = 10.0          # absolute value

DRIFT_WARN_THRESHOLD  = 0.15  # Δ Sharpe > 15% of rolling mean → warn
DRIFT_ALERT_THRESHOLD = 0.30  # Δ Sharpe > 30% → alert

CAGR_DECLINE_ROUNDS = 3       # N consecutive rounds of return decline → warn

DATA_FRESH_WARN_DAYS  = 7     # data older than 7 days → warn  (production: tighter than POC)
DATA_FRESH_ALERT_DAYS = 30    # data older than 30 days → alert

STEP_FAIL_WARN_RATE   = 0.10  # >10% of recent runs failed → warn
STEP_FAIL_ALERT_RATE  = 0.25  # >25% failed → alert

ROLLING_WINDOW = 5            # rounds to use for rolling averages


class DriftDetector:
    """
    Analyses training_runs, backtest_runs, and market_data_cache tables
    to surface performance drift, data quality issues, and pipeline health problems.

    Usage:
        detector = DriftDetector(db)
        report   = detector.full_report()
        summary  = detector.health_summary(report)   # overall status badge
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    # ─── Loaders ─────────────────────────────────────────────────────────────

    def _load_completed_training_runs(self) -> list:
        """Return all completed training runs sorted by recorded_at ascending."""
        try:
            repo = TrainingRunsRepository(self._db)
            runs = repo.read_all()
            completed = [r for r in runs if r.status in ("complete", "completed")]
            return sorted(completed, key=lambda r: r.recorded_at)
        except Exception:
            log.warning("drift_detector.training_runs.load_failed", exc_info=True)
            return []

    def _load_all_runs(self) -> tuple[list, list]:
        """Return (training_runs, backtest_runs) — all statuses, sorted by recorded_at."""
        try:
            train_runs = TrainingRunsRepository(self._db).read_all()
            bt_runs = BacktestRunsRepository(self._db).read_all()
            return (
                sorted(train_runs, key=lambda r: r.recorded_at),
                sorted(bt_runs, key=lambda r: r.recorded_at),
            )
        except Exception:
            log.warning("drift_detector.all_runs.load_failed", exc_info=True)
            return [], []

    # ─── Check 1: Sharpe Drift ────────────────────────────────────────────────

    def check_sharpe_drift(self) -> dict[str, Any]:
        """Compare latest backtest Sharpe against rolling mean of last N rounds.

        Returns drift_pct (relative deviation), status, and trend series.
        Only penalises downward drift (model degrading). Upward = improvement = ok.
        """
        runs = self._load_completed_training_runs()
        sharpe_series = [r.backtest_sharpe for r in runs if r.backtest_sharpe is not None]

        if not sharpe_series:
            return {"status": "ok", "message": "No training history yet.", "drift_pct": 0.0, "trend": []}

        if len(sharpe_series) < 2:
            return {
                "status": "ok",
                "message": f"Only {len(sharpe_series)} round(s) recorded — need ≥2 for drift.",
                "drift_pct": 0.0,
                "trend": sharpe_series,
            }

        latest = sharpe_series[-1]
        window = sharpe_series[-ROLLING_WINDOW - 1: -1]  # exclude latest
        rolling_mean = float(sum(window) / len(window)) if window else latest

        direction = "↓" if latest < rolling_mean else "↑"
        raw_drift_pct = abs(latest - rolling_mean) / max(abs(rolling_mean), 1e-6)
        # Only penalise downward drift
        drift_pct = raw_drift_pct if latest < rolling_mean else 0.0

        if drift_pct >= DRIFT_ALERT_THRESHOLD:
            status = "alert"
            message = (
                f"Sharpe drifted {direction} {raw_drift_pct * 100:.1f}% from rolling mean "
                f"({rolling_mean:.3f} → {latest:.3f})"
            )
        elif drift_pct >= DRIFT_WARN_THRESHOLD:
            status = "warn"
            message = (
                f"Sharpe shifted {direction} {raw_drift_pct * 100:.1f}% from rolling mean "
                f"({rolling_mean:.3f} → {latest:.3f})"
            )
        else:
            status = "ok"
            message = f"Sharpe stable — latest {latest:.3f} vs mean {rolling_mean:.3f}"

        return {
            "status": status,
            "message": message,
            "latest_sharpe": latest,
            "rolling_mean_sharpe": round(rolling_mean, 4),
            "drift_pct": round(raw_drift_pct * 100, 2),
            "direction": direction,
            "trend": sharpe_series,
        }

    # ─── Check 2: Return Degradation ─────────────────────────────────────────

    def check_return_degradation(self) -> dict[str, Any]:
        """Detect if backtest_return has been consistently declining over the last N rounds.

        backtest_return is stored as a fraction (e.g. 0.18 = 18%); multiply by 100 for pct.
        """
        runs = self._load_completed_training_runs()
        return_series = [
            round(r.backtest_return * 100, 2)
            for r in runs
            if r.backtest_return is not None
        ]

        if not return_series:
            return {"status": "ok", "message": "No return history yet.", "trend": []}

        if len(return_series) < CAGR_DECLINE_ROUNDS:
            return {
                "status": "ok",
                "message": f"Only {len(return_series)} rounds — need ≥{CAGR_DECLINE_ROUNDS} to detect trend.",
                "trend": return_series,
            }

        recent = return_series[-CAGR_DECLINE_ROUNDS:]
        declining = all(recent[i] < recent[i - 1] for i in range(1, len(recent)))

        if declining:
            drop = recent[0] - recent[-1]
            status = "warn"
            message = (
                f"Return declining for {CAGR_DECLINE_ROUNDS} consecutive rounds: "
                f"{recent[0]:.1f}% → {recent[-1]:.1f}% (−{drop:.1f}%)"
            )
        else:
            status = "ok"
            message = f"No sustained return decline detected (latest {return_series[-1]:.1f}%)"

        return {
            "status": status,
            "message": message,
            "recent_returns": recent,
            "trend": return_series,
        }

    # ─── Check 3: Data Freshness ──────────────────────────────────────────────

    def check_data_freshness(self) -> dict[str, Any]:
        """Check how old the latest date in the market_data_cache table is.

        Falls back to reading the CSV directly when the DB is empty or stale,
        using the same paths as the market_signals endpoint.
        """
        from pathlib import Path as _Path  # noqa: PLC0415

        db_latest: date | None = None
        try:
            repo = MarketDataCacheRepository(self._db)
            records = repo.read_all()
            if records:
                raw = max(r.date for r in records)
                db_latest = raw.date() if isinstance(raw, datetime) else raw
        except Exception:
            log.warning("drift_detector.market_data.load_failed", exc_info=True)

        csv_latest: date | None = None
        try:
            from rita.core.data_loader import load_ohlcv_csv  # noqa: PLC0415
            from rita.config import get_settings  # noqa: PLC0415
            _raw = _Path("data/raw/NIFTY/merged.csv")
            csv_path = _raw if _raw.exists() else _Path(get_settings().data.input_dir) / "DAILY-DATA" / "nifty_manual.csv"
            if csv_path.exists():
                _df = load_ohlcv_csv(str(csv_path))
                if not _df.empty:
                    csv_latest = _df.index[-1].date()
        except Exception:
            log.warning("drift_detector.csv_date_read_failed", exc_info=True)

        latest_date = max(d for d in (db_latest, csv_latest) if d is not None) if (db_latest or csv_latest) else None

        if latest_date is None:
            return {
                "status": "warn",
                "message": "No market data found — load price data to enable freshness check.",
                "days_old": None,
                "latest_date": None,
            }

        try:
            days_old = (date.today() - latest_date).days
        except Exception as exc:
            return {"status": "warn", "message": f"Could not compute data age: {exc}", "days_old": None}

        if days_old >= DATA_FRESH_ALERT_DAYS:
            status = "alert"
            message = f"Market data is {days_old} days old (latest: {latest_date}) — refresh recommended"
        elif days_old >= DATA_FRESH_WARN_DAYS:
            status = "warn"
            message = f"Market data is {days_old} days old (latest: {latest_date})"
        else:
            status = "ok"
            message = f"Market data is current — {days_old} day(s) old (latest: {latest_date})"

        return {
            "status": status,
            "message": message,
            "latest_date": str(latest_date),
            "days_old": days_old,
        }

    # ─── Check 4: Pipeline Health ─────────────────────────────────────────────

    def check_pipeline_health(self) -> dict[str, Any]:
        """Analyse recent failure rate and per-model-version timing.

        Uses the last 50 runs combined from training_runs + backtest_runs.
        step_stats: keyed by model_version (training) or run_id prefix (backtest).
        recent_runs: last 10 runs as list of dicts.
        """
        train_runs, bt_runs = self._load_all_runs()

        # Combine and keep last 50
        all_runs = train_runs + bt_runs
        # Sort by recorded_at descending, take last 50
        all_runs_sorted = sorted(all_runs, key=lambda r: r.recorded_at)
        recent_50 = all_runs_sorted[-50:]

        if not recent_50:
            return {"status": "ok", "message": "No pipeline runs recorded yet.", "step_stats": {}, "recent_runs": []}

        ended = [r for r in recent_50 if r.status in ("complete", "completed", "failed")]
        if not ended:
            return {"status": "ok", "message": "No completed/failed runs yet.", "step_stats": {}, "recent_runs": []}

        total = len(ended)
        failed_count = sum(1 for r in ended if r.status == "failed")
        fail_rate = failed_count / total if total > 0 else 0.0

        # Per-model-version timing from training runs that have started_at/ended_at
        step_stats: dict[str, Any] = {}
        for run in train_runs:
            if run.started_at and run.ended_at:
                duration = (run.ended_at - run.started_at).total_seconds()
                mv = getattr(run, "model_version", None) or "unknown"
                if mv not in step_stats:
                    step_stats[mv] = {"durations": [], "runs": 0, "failures": 0}
                step_stats[mv]["durations"].append(duration)
                step_stats[mv]["runs"] += 1
                if run.status == "failed":
                    step_stats[mv]["failures"] += 1

        # Flatten step_stats: replace raw duration list with avg/max
        step_stats_out: dict[str, Any] = {}
        for mv, data in step_stats.items():
            durs = data["durations"]
            step_stats_out[mv] = {
                "avg_duration_secs": round(sum(durs) / len(durs), 1) if durs else None,
                "max_duration_secs": round(max(durs), 1) if durs else None,
                "runs": data["runs"],
                "failures": data["failures"],
            }

        # Recent 10 runs — most recent first
        recent_10 = sorted(all_runs, key=lambda r: r.recorded_at, reverse=True)[:10]
        recent_runs_list: list[dict[str, Any]] = []
        for run in recent_10:
            duration = None
            if run.started_at and run.ended_at:
                duration = (run.ended_at - run.started_at).total_seconds()
            recent_runs_list.append({
                "run_id": run.run_id,
                "status": run.status,
                "model_version": getattr(run, "model_version", None),
                "duration_secs": round(duration, 1) if duration is not None else None,
                "recorded_at": run.recorded_at.isoformat() if run.recorded_at else None,
            })

        if fail_rate >= STEP_FAIL_ALERT_RATE:
            status = "alert"
            message = f"High run failure rate: {failed_count}/{total} ({fail_rate * 100:.0f}%) in last 50 entries"
        elif fail_rate >= STEP_FAIL_WARN_RATE:
            status = "warn"
            message = f"Elevated failure rate: {failed_count}/{total} ({fail_rate * 100:.0f}%) in last 50 entries"
        else:
            status = "ok"
            message = f"Pipeline healthy — {failed_count}/{total} failures ({fail_rate * 100:.0f}%) in last 50 entries"

        return {
            "status": status,
            "message": message,
            "total_logged": total,
            "failed_steps": failed_count,
            "fail_rate_pct": round(fail_rate * 100, 1),
            "step_stats": step_stats_out,
            "recent_runs": recent_runs_list,
        }

    # ─── Check 5: Constraint Breach Rate ──────────────────────────────────────

    def check_constraint_breach(self) -> dict[str, Any]:
        """Count how many completed training rounds failed the Sharpe or MDD constraint.

        Sharpe target: >= 1.0
        MDD limit: abs(backtest_mdd * 100) <= 10.0%
        """
        runs = self._load_completed_training_runs()
        if not runs:
            return {"status": "ok", "message": "No training history yet.", "breach_rounds": []}

        breaches: list[dict[str, Any]] = []
        for run in runs:
            sharpe_val = run.backtest_sharpe if run.backtest_sharpe is not None else 0.0
            mdd_val = run.backtest_mdd if run.backtest_mdd is not None else 0.0
            sharpe_ok = float(sharpe_val) >= SHARPE_TARGET
            mdd_ok = abs(float(mdd_val) * 100) <= MDD_LIMIT_PCT
            if not (sharpe_ok and mdd_ok):
                breaches.append({
                    "run_id": run.run_id,
                    "model_version": getattr(run, "model_version", None),
                    "sharpe": round(float(sharpe_val), 3),
                    "mdd_pct": round(float(mdd_val) * 100, 2),
                })

        total = len(runs)
        breach_count = len(breaches)
        breach_rate = breach_count / total if total > 0 else 0.0

        if breach_rate >= 0.5:
            status = "warn"
            message = f"{breach_count}/{total} rounds failed constraints ({breach_rate * 100:.0f}%)"
        elif breach_count > 0:
            status = "ok"
            message = f"{breach_count}/{total} rounds failed constraints — latest round OK"
        else:
            status = "ok"
            message = f"All {total} rounds met constraints"

        return {
            "status": status,
            "message": message,
            "total_rounds": total,
            "breach_count": breach_count,
            "breach_rate_pct": round(breach_rate * 100, 1),
            "breach_rounds": breaches,
        }

    # ─── Full Report ──────────────────────────────────────────────────────────

    def full_report(self) -> dict[str, Any]:
        """Run all checks and return a structured dict suitable for display."""
        return {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sharpe_drift": self.check_sharpe_drift(),
            "return_degradation": self.check_return_degradation(),
            "data_freshness": self.check_data_freshness(),
            "pipeline_health": self.check_pipeline_health(),
            "constraint_breach": self.check_constraint_breach(),
        }

    # ─── Health Summary ───────────────────────────────────────────────────────

    def health_summary(self, report: Optional[dict] = None) -> dict[str, Any]:
        """Roll up all check statuses into a single badge.

        Returns:
            {
              "overall": "ok" | "warn" | "alert",
              "checks":  dict of check_name → status
            }
        """
        if report is None:
            report = self.full_report()

        check_keys = [
            "sharpe_drift", "return_degradation",
            "data_freshness", "pipeline_health", "constraint_breach",
        ]
        statuses = {k: report[k]["status"] for k in check_keys if k in report}

        if any(s == "alert" for s in statuses.values()):
            overall = "alert"
        elif any(s == "warn" for s in statuses.values()):
            overall = "warn"
        else:
            overall = "ok"

        return {"overall": overall, "checks": statuses}
