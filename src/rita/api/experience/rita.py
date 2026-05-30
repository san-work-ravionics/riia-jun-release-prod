"""Experience Layer — RITA dashboard aggregation router.

ADR-001 Tier 3: read-only composition, no writes, no side effects.
Serves performance, risk, trade, and instrument-selection views for the RITA dashboard.
URLs preserved from observability.py (Option A migration).
"""
from __future__ import annotations

import math as _math
import statistics as _stats
import time
from functools import lru_cache as _lru_cache
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from rita.config import get_settings
from rita.database import get_db
from rita.logging_config import log_event
from rita.repositories.instrument import InstrumentRepository
from rita.repositories.config_overrides import ConfigOverridesRepository
from rita.repositories.backtest import BacktestRunsRepository, BacktestResultsRepository
from rita.repositories.training import TrainingRunsRepository
from rita.repositories.market_data import MarketDataCacheRepository
from rita.core.performance import (
    build_performance_feedback,
    build_portfolio_comparison,
    simulate_stress_scenarios,
)
from rita.schemas.geography import GeographyOverviewResponse, GeoInstrument, GeoRegion
from rita.schemas.strategy_comparison import (
    StrategyComparisonResponse,
    StrategyResult,
    StrategySummaryRow,
)

log = structlog.get_logger()

router = APIRouter(prefix="/api/v1", tags=["experience:rita"])

_COUNTRY_FLAG  = {"IN": "\U0001f1ee\U0001f1f3", "US": "\U0001f1fa\U0001f1f8", "NL": "\U0001f1f3\U0001f1f1"}
_MDD_LIMIT_PCT = 10.0


# ── Shared helpers ────────────────────────────────────────────────────────────

def _get_active_instrument_id(db: Session) -> str:
    try:
        cfg = ConfigOverridesRepository(db).find_by_id("active_instrument_id")
        if cfg and cfg.value:
            return cfg.value.upper()
    except Exception:
        pass
    return "NIFTY"


def _regime(allocation: Any) -> str:
    if allocation is None:
        return "Unknown"
    a = float(allocation)
    if a >= 0.99:
        return "Bull"
    if a >= 0.45:
        return "Neutral"
    return "Bear"


def _load_latest_backtest_df(db: Session) -> tuple[Any, list, Any]:
    """Return (latest_run, daily_results, backtest_df) for the most recent completed run."""
    import pandas as pd

    runs_repo    = BacktestRunsRepository(db)
    results_repo = BacktestResultsRepository(db)

    all_runs = [r for r in runs_repo.read_all() if r.status in ("complete", "completed")]
    if not all_runs:
        return None, [], None

    latest_run    = max(all_runs, key=lambda r: r.ended_at or r.recorded_at)
    daily_results = sorted(
        [r for r in results_repo.read_all() if r.run_id == latest_run.run_id],
        key=lambda r: r.date,
    )
    if not daily_results:
        return latest_run, [], None

    backtest_df = pd.DataFrame([{
        "date":            str(r.date),
        "portfolio_value": r.portfolio_value,
        "benchmark_value": r.benchmark_value,
        "allocation":      r.allocation if r.allocation is not None else 0.0,
        "close_price":     r.close_price if r.close_price is not None else 0.0,
    } for r in daily_results])
    return latest_run, daily_results, backtest_df


# ── GET /api/v1/instrument/active ─────────────────────────────────────────────

@router.get("/instrument/active", summary="Currently active instrument")
def active_instrument(db: Session = Depends(get_db)) -> dict[str, Any]:
    _start = time.monotonic()
    sources: dict[str, Any] = {}

    active_id = _get_active_instrument_id(db)

    t0 = time.monotonic()
    try:
        repo = InstrumentRepository(db)
        inst = repo.find_by_id(active_id)
        sources["active_instrument"] = {
            "status": "ok" if inst else "empty",
            "record_count": 1 if inst else 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        inst = None
        sources["active_instrument"] = {
            "status": "error",
            "record_count": 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }

    if inst is None:
        cfg = get_settings()
        response = {
            "id": "NIFTY", "name": "Nifty 50", "flag": "\U0001f1ee\U0001f1f3",
            "exchange": "NSE", "lot_size": cfg.instruments.nifty.lot_size,
        }
    else:
        response = {
            "id":       inst.instrument_id,
            "name":     inst.name,
            "flag":     _COUNTRY_FLAG.get(inst.country_code, ""),
            "exchange": inst.exchange,
            "lot_size": inst.lot_size,
        }

    statuses = [s["status"] for s in sources.values()]
    if all(s == "ok" for s in statuses):
        overall = "ok"
    elif any(s == "ok" for s in statuses):
        overall = "partial"
    else:
        overall = "error"

    log_event(
        log, "info", "experience.compose",
        handler="active_instrument",
        duration_ms=int((time.monotonic() - _start) * 1000),
        overall_status=overall,
        response_keys=list(response.keys()),
        sources=sources,
    )
    return response


# ── GET /api/v1/performance-summary ──────────────────────────────────────────

@router.get("/performance-summary", summary="Latest backtest performance KPIs")
def performance_summary(db: Session = Depends(get_db)) -> dict[str, Any]:
    _start = time.monotonic()
    sources: dict[str, Any] = {}

    active_id  = _get_active_instrument_id(db)

    t0 = time.monotonic()
    try:
        runs_repo  = BacktestRunsRepository(db)
        results_repo = BacktestResultsRepository(db)
        all_runs = [
            r for r in runs_repo.read_all()
            if r.status in ("complete", "completed")
            and (r.instrument or "NIFTY").upper() == active_id
        ]
        sources["backtest_runs"] = {
            "status": "ok" if all_runs else "empty",
            "record_count": len(all_runs),
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        all_runs = []
        sources["backtest_runs"] = {
            "status": "error",
            "record_count": 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }

    run_instrument = active_id if all_runs else "NONE"

    _empty = {
        "portfolio_total_return_pct": None, "benchmark_total_return_pct": None,
        "portfolio_cagr_pct": None, "benchmark_cagr_pct": None,
        "sharpe_ratio": None, "max_drawdown_pct": None,
        "annual_volatility_pct": None, "win_rate_pct": None,
        "total_days": 0, "constraints_met": False,
        "_run_instrument_id": run_instrument, "_active_instrument_id": active_id,
    }

    if not all_runs:
        statuses = [s["status"] for s in sources.values()]
        overall = "ok" if all(s == "ok" for s in statuses) else ("partial" if any(s == "ok" for s in statuses) else "error")
        log_event(
            log, "info", "experience.compose",
            handler="performance_summary",
            duration_ms=int((time.monotonic() - _start) * 1000),
            overall_status=overall,
            response_keys=list(_empty.keys()),
            sources=sources,
        )
        return _empty

    latest_run = max(all_runs, key=lambda r: r.ended_at or r.recorded_at)

    t0 = time.monotonic()
    try:
        results = sorted(
            [r for r in results_repo.read_all() if r.run_id == latest_run.run_id],
            key=lambda r: r.date,
        )
        sources["backtest_results"] = {
            "status": "ok" if results else "empty",
            "record_count": len(results),
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        results = []
        sources["backtest_results"] = {
            "status": "error",
            "record_count": 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }

    if not results:
        statuses = [s["status"] for s in sources.values()]
        overall = "ok" if all(s == "ok" for s in statuses) else ("partial" if any(s == "ok" for s in statuses) else "error")
        log_event(
            log, "info", "experience.compose",
            handler="performance_summary",
            duration_ms=int((time.monotonic() - _start) * 1000),
            overall_status=overall,
            response_keys=list(_empty.keys()),
            sources=sources,
        )
        return _empty

    port_final      = results[-1].portfolio_value
    bench_final     = results[-1].benchmark_value
    port_return_pct = round((port_final - 1.0) * 100, 2)
    bench_return_pct = round((bench_final - 1.0) * 100, 2)
    total_days      = (results[-1].date - results[0].date).days or 1
    years           = total_days / 365.25
    port_cagr  = round((port_final ** (1 / years) - 1) * 100, 2) if years > 0 else port_return_pct
    bench_cagr = round((bench_final ** (1 / years) - 1) * 100, 2) if years > 0 else bench_return_pct

    sharpe: Optional[float] = results[0].sharpe_ratio
    if sharpe is None:
        daily_returns = []
        for i in range(1, len(results)):
            prev = results[i - 1].portfolio_value
            curr = results[i].portfolio_value
            if prev and prev > 0:
                daily_returns.append((curr - prev) / prev)
        if len(daily_returns) > 1:
            import statistics
            mean_r = statistics.mean(daily_returns)
            std_r  = statistics.stdev(daily_returns)
            sharpe = round((mean_r / std_r) * (252 ** 0.5), 3) if std_r > 0 else None

    peak = 1.0
    max_dd = 0.0
    for r in results:
        v = r.portfolio_value
        if v > peak:
            peak = v
        dd = (v - peak) / peak * 100 if peak > 0 else 0
        if dd < max_dd:
            max_dd = dd
    max_dd_pct = round(max_dd, 2)

    daily_returns = []
    for i in range(1, len(results)):
        prev = results[i - 1].portfolio_value
        curr = results[i].portfolio_value
        if prev and prev > 0:
            daily_returns.append((curr - prev) / prev)
    vol_pct: Optional[float] = None
    if len(daily_returns) > 1:
        import statistics
        vol_pct = round(statistics.stdev(daily_returns) * (252 ** 0.5) * 100, 2)

    wins = sum(1 for i in range(1, len(results)) if results[i].portfolio_value > results[i - 1].portfolio_value)
    win_rate_pct = round(wins / (len(results) - 1) * 100, 1) if len(results) > 1 else None
    constraints_met = sharpe is not None and sharpe >= 1.0 and abs(max_dd_pct) < 10

    allocs = [r.allocation for r in results if r.allocation is not None]
    total_trades = sum(1 for i in range(1, len(allocs)) if abs(allocs[i] - allocs[i - 1]) > 0) if len(allocs) > 1 else 0

    response = {
        "portfolio_total_return_pct": port_return_pct,
        "benchmark_total_return_pct": bench_return_pct,
        "portfolio_cagr_pct": port_cagr,
        "benchmark_cagr_pct": bench_cagr,
        "sharpe_ratio": sharpe,
        "max_drawdown_pct": max_dd_pct,
        "annual_volatility_pct": vol_pct,
        "win_rate_pct": win_rate_pct,
        "total_days": total_days,
        "total_trades": total_trades,
        "backtest_start_date": str(results[0].date),
        "backtest_end_date": str(results[-1].date),
        "constraints_met": constraints_met,
        "_run_instrument_id": run_instrument,
        "_active_instrument_id": active_id,
    }

    statuses = [s["status"] for s in sources.values()]
    if all(s == "ok" for s in statuses):
        overall = "ok"
    elif any(s == "ok" for s in statuses):
        overall = "partial"
    else:
        overall = "error"

    log_event(
        log, "info", "experience.compose",
        handler="performance_summary",
        duration_ms=int((time.monotonic() - _start) * 1000),
        overall_status=overall,
        response_keys=list(response.keys()),
        sources=sources,
    )
    return response


# ── GET /api/v1/backtest-daily ────────────────────────────────────────────────

@router.get("/backtest-daily", summary="Daily backtest results for charting")
def backtest_daily(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    _start = time.monotonic()
    sources: dict[str, Any] = {}

    active_id = _get_active_instrument_id(db)

    t0 = time.monotonic()
    try:
        runs_repo  = BacktestRunsRepository(db)
        results_repo = BacktestResultsRepository(db)
        all_runs = [
            r for r in runs_repo.read_all()
            if r.status in ("complete", "completed")
            and (r.instrument or "NIFTY").upper() == active_id
        ]
        sources["backtest_runs"] = {
            "status": "ok" if all_runs else "empty",
            "record_count": len(all_runs),
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        all_runs = []
        sources["backtest_runs"] = {
            "status": "error",
            "record_count": 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }

    if not all_runs:
        log_event(
            log, "info", "experience.compose",
            handler="backtest_daily",
            duration_ms=int((time.monotonic() - _start) * 1000),
            overall_status="empty",
            response_keys=[],
            sources=sources,
        )
        return []

    latest_run = max(all_runs, key=lambda r: r.ended_at or r.recorded_at)

    t0 = time.monotonic()
    try:
        results = sorted(
            [r for r in results_repo.read_all() if r.run_id == latest_run.run_id],
            key=lambda r: r.date,
        )
        sources["backtest_results"] = {
            "status": "ok" if results else "empty",
            "record_count": len(results),
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        results = []
        sources["backtest_results"] = {
            "status": "error",
            "record_count": 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }

    response = [{
        "date":            str(r.date),
        "portfolio_value": r.portfolio_value,
        "benchmark_value": r.benchmark_value,
        "allocation":      r.allocation,
        "close_price":     r.close_price,
    } for r in results]

    statuses = [s["status"] for s in sources.values()]
    if all(s == "ok" for s in statuses):
        overall = "ok"
    elif any(s == "ok" for s in statuses):
        overall = "partial"
    else:
        overall = "error"

    log_event(
        log, "info", "experience.compose",
        handler="backtest_daily",
        duration_ms=int((time.monotonic() - _start) * 1000),
        overall_status=overall,
        response_keys=[],
        sources=sources,
    )
    return response


# ── GET /api/v1/performance-feedback ─────────────────────────────────────────

@router.get("/performance-feedback", summary="Performance feedback for latest backtest")
def performance_feedback(db: Session = Depends(get_db)) -> dict[str, Any]:
    _start = time.monotonic()
    sources: dict[str, Any] = {}

    t0 = time.monotonic()
    try:
        latest_run, daily_results, backtest_df = _load_latest_backtest_df(db)
        sources["backtest_df"] = {
            "status": "ok" if backtest_df is not None else "empty",
            "record_count": len(daily_results) if daily_results else 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        latest_run, daily_results, backtest_df = None, [], None
        sources["backtest_df"] = {
            "status": "error",
            "record_count": 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }

    if backtest_df is None:
        log_event(
            log, "info", "experience.compose",
            handler="performance_feedback",
            duration_ms=int((time.monotonic() - _start) * 1000),
            overall_status="error",
            response_keys=["error"],
            sources=sources,
        )
        return {"error": "No completed backtest run found"}

    total_days = len(daily_results)
    years      = total_days / 252.0
    stored_sharpe = daily_results[0].sharpe_ratio
    stored_mdd    = daily_results[0].max_drawdown
    port_start    = daily_results[0].portfolio_value
    port_end      = daily_results[-1].portfolio_value
    total_return_pct = round((port_end / port_start - 1) * 100, 2) if port_start else 0.0
    port_cagr_pct = (
        round(((port_end / port_start) ** (1.0 / years) - 1) * 100, 2)
        if years > 0 and port_start and port_start > 0 else 0.0
    )
    sharpe  = stored_sharpe if stored_sharpe is not None else 0.0
    mdd_pct = round(stored_mdd * 100, 2) if stored_mdd is not None else 0.0

    perf_metrics: dict[str, Any] = {
        "sharpe_ratio": sharpe, "max_drawdown_pct": mdd_pct,
        "portfolio_total_return_pct": total_return_pct, "portfolio_cagr_pct": port_cagr_pct,
        "benchmark_total_return_pct": 0.0, "benchmark_cagr_pct": 0.0,
        "annual_volatility_pct": 0.0, "win_rate_pct": 0.0,
        "total_days": total_days, "years": round(years, 2),
        "sharpe_constraint_met": sharpe >= 1.0,
        "drawdown_constraint_met": abs(mdd_pct) < 10,
        "constraints_met": sharpe >= 1.0 and abs(mdd_pct) < 10,
    }

    t0 = time.monotonic()
    try:
        train_repo      = TrainingRunsRepository(db)
        training_rounds = len([r for r in train_repo.read_all() if r.status in ("complete", "completed")])
        sources["training_rounds"] = {
            "status": "ok",
            "record_count": training_rounds,
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        training_rounds = 0
        sources["training_rounds"] = {
            "status": "error",
            "record_count": 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }

    t0 = time.monotonic()
    try:
        result = build_performance_feedback(backtest_df, perf_metrics, training_rounds)
        sources["performance_feedback_build"] = {
            "status": "ok",
            "record_count": len(result) if isinstance(result, dict) else 1,
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
        log.info("performance_feedback.served", run_id=latest_run.run_id, training_rounds=training_rounds)
    except Exception as exc:
        sources["performance_feedback_build"] = {
            "status": "error",
            "record_count": 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }
        log.error("performance_feedback.failed", run_id=latest_run.run_id, exc_info=True)
        log_event(
            log, "info", "experience.compose",
            handler="performance_feedback",
            duration_ms=int((time.monotonic() - _start) * 1000),
            overall_status="error",
            response_keys=["error"],
            sources=sources,
        )
        return {"error": "Failed to compute performance feedback"}

    statuses = [s["status"] for s in sources.values()]
    if all(s == "ok" for s in statuses):
        overall = "ok"
    elif any(s == "ok" for s in statuses):
        overall = "partial"
    else:
        overall = "error"

    log_event(
        log, "info", "experience.compose",
        handler="performance_feedback",
        duration_ms=int((time.monotonic() - _start) * 1000),
        overall_status=overall,
        response_keys=list(result.keys()) if isinstance(result, dict) else [],
        sources=sources,
    )
    return result


# ── GET /api/v1/portfolio-comparison ─────────────────────────────────────────

@router.get("/portfolio-comparison", summary="RITA model vs fixed allocation profiles")
def portfolio_comparison(
    portfolio_inr: float = 1_000_000,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _start = time.monotonic()
    sources: dict[str, Any] = {}

    t0 = time.monotonic()
    try:
        latest_run, _daily_results, backtest_df = _load_latest_backtest_df(db)
        sources["backtest_df"] = {
            "status": "ok" if backtest_df is not None else "empty",
            "record_count": len(_daily_results) if _daily_results else 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        latest_run, backtest_df = None, None
        sources["backtest_df"] = {
            "status": "error",
            "record_count": 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }

    if backtest_df is None:
        log_event(
            log, "info", "experience.compose",
            handler="portfolio_comparison",
            duration_ms=int((time.monotonic() - _start) * 1000),
            overall_status="error",
            response_keys=["error"],
            sources=sources,
        )
        return {"error": "No completed backtest run found"}

    t0 = time.monotonic()
    try:
        result = build_portfolio_comparison(backtest_df, portfolio_inr)
        sources["portfolio_comparison_build"] = {
            "status": "ok",
            "record_count": len(result) if isinstance(result, dict) else 1,
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
        log.info("portfolio_comparison.served", run_id=latest_run.run_id, portfolio_inr=portfolio_inr)
    except Exception as exc:
        sources["portfolio_comparison_build"] = {
            "status": "error",
            "record_count": 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }
        log.error("portfolio_comparison.failed", run_id=latest_run.run_id, exc_info=True)
        log_event(
            log, "info", "experience.compose",
            handler="portfolio_comparison",
            duration_ms=int((time.monotonic() - _start) * 1000),
            overall_status="error",
            response_keys=["error"],
            sources=sources,
        )
        return {"error": "Failed to compute portfolio comparison"}

    statuses = [s["status"] for s in sources.values()]
    if all(s == "ok" for s in statuses):
        overall = "ok"
    elif any(s == "ok" for s in statuses):
        overall = "partial"
    else:
        overall = "error"

    log_event(
        log, "info", "experience.compose",
        handler="portfolio_comparison",
        duration_ms=int((time.monotonic() - _start) * 1000),
        overall_status=overall,
        response_keys=list(result.keys()) if isinstance(result, dict) else [],
        sources=sources,
    )
    return result


# ── GET /api/v1/risk-timeline ─────────────────────────────────────────────────

@router.get("/risk-timeline", summary="Risk timeline from latest backtest")
def risk_timeline(
    phase: str = "all",
    instrument: str = "NIFTY",
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    _start = time.monotonic()
    sources: dict[str, Any] = {}

    t0 = time.monotonic()
    try:
        runs_repo    = BacktestRunsRepository(db)
        results_repo = BacktestResultsRepository(db)
        all_runs = [
            r for r in runs_repo.read_all()
            if r.status in ("complete", "completed") and (r.instrument or "NIFTY") == instrument
        ]
        sources["backtest_runs"] = {
            "status": "ok" if all_runs else "empty",
            "record_count": len(all_runs),
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        all_runs = []
        sources["backtest_runs"] = {
            "status": "error",
            "record_count": 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }

    if not all_runs:
        log_event(
            log, "info", "experience.compose",
            handler="risk_timeline",
            duration_ms=int((time.monotonic() - _start) * 1000),
            overall_status="empty",
            response_keys=[],
            sources=sources,
        )
        return []

    latest_run = max(all_runs, key=lambda r: r.ended_at or r.recorded_at)

    t0 = time.monotonic()
    try:
        results = sorted(
            [r for r in results_repo.read_all() if r.run_id == latest_run.run_id],
            key=lambda r: r.date,
        )
        sources["backtest_results"] = {
            "status": "ok" if results else "empty",
            "record_count": len(results),
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        results = []
        sources["backtest_results"] = {
            "status": "error",
            "record_count": 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }

    port_values  = [r.portfolio_value if r.portfolio_value is not None else 1.0 for r in results]
    bench_values = [r.benchmark_value if r.benchmark_value is not None else 1.0 for r in results]

    def _daily_rets(vals: list[float]) -> list[Optional[float]]:
        rets: list[Optional[float]] = [None]
        for i in range(1, len(vals)):
            prev = vals[i - 1]
            rets.append((vals[i] - prev) / prev if prev else None)
        return rets

    port_rets  = _daily_rets(port_values)
    bench_rets = _daily_rets(bench_values)

    def _rolling_vol(rets: list[Optional[float]], i: int, window: int = 20) -> Optional[float]:
        window_rets = [r for r in rets[max(0, i - window + 1): i + 1] if r is not None]
        if len(window_rets) < 2:
            return None
        return round(_stats.stdev(window_rets) * _math.sqrt(252) * 100, 4)

    def _var_95(rets: list[Optional[float]], i: int, window: int = 20) -> Optional[float]:
        window_rets = sorted(r for r in rets[max(0, i - window + 1): i + 1] if r is not None)
        if not window_rets:
            return None
        idx = max(0, int(len(window_rets) * 0.05) - 1)
        return round(window_rets[idx] * 100, 4)

    peak = 1.0
    drawdowns: list[float] = []
    for v in port_values:
        if v > peak:
            peak = v
        dd = (v - peak) / peak * 100 if peak > 0 else 0.0
        drawdowns.append(round(dd, 4))

    _ = phase  # accepted for forward-compatibility, not yet used for filtering

    response = [{
        "date":                  str(r.date),
        "portfolio_value":       r.portfolio_value,
        "portfolio_value_norm":  r.portfolio_value,
        "benchmark_value":       r.benchmark_value,
        "allocation":            r.allocation,
        "close_price":           r.close_price,
        "current_drawdown_pct":  drawdowns[i],
        "drawdown_budget_pct":   round(min(abs(drawdowns[i]) / _MDD_LIMIT_PCT * 100.0, 150.0), 2),
        "rolling_vol_20d":       _rolling_vol(port_rets, i),
        "market_var_95":         _var_95(bench_rets, i),
        "portfolio_var_95":      _var_95(port_rets, i),
        "regime":                _regime(r.allocation),
        "trend_score":           round(((r.allocation if r.allocation is not None else 0.5) - 0.5) * 2.0, 4),
        "phase":                 "Backtest",
        "run_id":                r.run_id,
    } for i, r in enumerate(results)]

    statuses = [s["status"] for s in sources.values()]
    if all(s == "ok" for s in statuses):
        overall = "ok"
    elif any(s == "ok" for s in statuses):
        overall = "partial"
    else:
        overall = "error"

    log_event(
        log, "info", "experience.compose",
        handler="risk_timeline",
        duration_ms=int((time.monotonic() - _start) * 1000),
        overall_status=overall,
        response_keys=[],
        sources=sources,
    )
    return response


# ── GET /api/v1/trade-events ──────────────────────────────────────────────────

@router.get("/trade-events", summary="Trade entry/exit events derived from backtest allocation changes")
def trade_events(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    _start = time.monotonic()
    sources: dict[str, Any] = {}

    t0 = time.monotonic()
    try:
        runs_repo    = BacktestRunsRepository(db)
        results_repo = BacktestResultsRepository(db)
        all_runs = [r for r in runs_repo.read_all() if r.status in ("complete", "completed")]
        sources["backtest_runs"] = {
            "status": "ok" if all_runs else "empty",
            "record_count": len(all_runs),
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        all_runs = []
        sources["backtest_runs"] = {
            "status": "error",
            "record_count": 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }

    if not all_runs:
        log_event(
            log, "info", "experience.compose",
            handler="trade_events",
            duration_ms=int((time.monotonic() - _start) * 1000),
            overall_status="empty",
            response_keys=[],
            sources=sources,
        )
        return []

    latest_run = max(all_runs, key=lambda r: r.ended_at or r.recorded_at)

    t0 = time.monotonic()
    try:
        results = sorted(
            [r for r in results_repo.read_all() if r.run_id == latest_run.run_id],
            key=lambda r: r.date,
        )
        sources["backtest_results"] = {
            "status": "ok" if results else "empty",
            "record_count": len(results),
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        results = []
        sources["backtest_results"] = {
            "status": "error",
            "record_count": 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }

    if not results:
        log_event(
            log, "info", "experience.compose",
            handler="trade_events",
            duration_ms=int((time.monotonic() - _start) * 1000),
            overall_status="empty",
            response_keys=[],
            sources=sources,
        )
        return []

    port_values   = [r.portfolio_value if r.portfolio_value is not None else 1.0 for r in results]
    daily_rets: list[Optional[float]] = [None]
    for i in range(1, len(port_values)):
        prev = port_values[i - 1]
        daily_rets.append((port_values[i] - prev) / prev if prev else None)

    def _var_95(i: int, window: int = 20) -> Optional[float]:
        window_rets = sorted(r for r in daily_rets[max(0, i - window + 1): i + 1] if r is not None)
        if not window_rets:
            return None
        idx = max(0, int(len(window_rets) * 0.05) - 1)
        return round(window_rets[idx] * 100, 4)

    def _rolling_sharpe(i: int, window: int = 63) -> Optional[float]:
        window_rets = [r for r in daily_rets[max(0, i - window + 1): i + 1] if r is not None]
        if len(window_rets) < 2:
            return None
        mn = sum(window_rets) / len(window_rets)
        sd = _math.sqrt(sum((r - mn) ** 2 for r in window_rets) / len(window_rets))
        return round((mn / sd) * _math.sqrt(252), 3) if sd > 0 else None

    def _trade_regime(alloc: Optional[float]) -> str:
        if alloc is None:
            return "unknown"
        if alloc > 0.6:
            return "bullish"
        if alloc < 0.2:
            return "bearish"
        return "neutral"

    ALLOC_THRESHOLD = 0.05
    events: list[dict[str, Any]] = []
    entry_pv: Optional[float] = None

    for i in range(1, len(results)):
        cur  = results[i]
        prev = results[i - 1]
        cur_alloc  = cur.allocation  if cur.allocation  is not None else 0.0
        prev_alloc = prev.allocation if prev.allocation is not None else 0.0
        delta = round(cur_alloc - prev_alloc, 4)

        if abs(delta) < ALLOC_THRESHOLD:
            continue

        var95      = _var_95(i)
        prev_var95 = _var_95(i - 1)
        delta_var  = round((var95 or 0.0) - (prev_var95 or 0.0), 4)

        if delta > 0:
            risk_action = "Increased"
            event_type  = "entry"
            entry_pv    = port_values[i]
            pnl         = None
        else:
            risk_action = "Reduced"
            event_type  = "exit"
            pnl = round((port_values[i] - entry_pv) / entry_pv * 100, 4) if entry_pv and entry_pv > 0 else None
            entry_pv = None

        events.append({
            "date": str(cur.date), "phase": "Backtest",
            "event_type": event_type, "trade_type": event_type,
            "risk_action": risk_action,
            "allocation": round(cur_alloc, 4), "delta_allocation": delta,
            "price": cur.close_price, "pnl": pnl,
            "portfolio_var_95": var95, "delta_var": delta_var,
            "regime": _trade_regime(cur_alloc), "sharpe_at_trade": _rolling_sharpe(i),
        })

    statuses = [s["status"] for s in sources.values()]
    if all(s == "ok" for s in statuses):
        overall = "ok"
    elif any(s == "ok" for s in statuses):
        overall = "partial"
    else:
        overall = "error"

    log_event(
        log, "info", "experience.compose",
        handler="trade_events",
        duration_ms=int((time.monotonic() - _start) * 1000),
        overall_status=overall,
        response_keys=[],
        sources=sources,
    )
    return events


# ── GET /api/v1/stress-scenarios ──────────────────────────────────────────────

@router.get("/stress-scenarios", summary="Point-in-time stress test across market moves")
def stress_scenarios(
    portfolio_inr: float = 1_000_000,
    rita_allocation_pct: float = 50.0,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _start = time.monotonic()
    sources: dict[str, Any] = {}

    market_moves = [-20, -10, -5, 5, 10, 20]

    t0 = time.monotonic()
    try:
        result = simulate_stress_scenarios(portfolio_inr, market_moves, rita_allocation_pct)
        sources["stress_scenarios"] = {
            "status": "ok" if result else "empty",
            "record_count": len(result) if isinstance(result, dict) else 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        sources["stress_scenarios"] = {
            "status": "error",
            "record_count": 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }
        log_event(
            log, "info", "experience.compose",
            handler="stress_scenarios",
            duration_ms=int((time.monotonic() - _start) * 1000),
            overall_status="error",
            response_keys=["error"],
            sources=sources,
        )
        return {"error": str(exc)}

    statuses = [s["status"] for s in sources.values()]
    if all(s == "ok" for s in statuses):
        overall = "ok"
    elif any(s == "ok" for s in statuses):
        overall = "partial"
    else:
        overall = "error"

    log_event(
        log, "info", "experience.compose",
        handler="stress_scenarios",
        duration_ms=int((time.monotonic() - _start) * 1000),
        overall_status=overall,
        response_keys=list(result.keys()) if isinstance(result, dict) else [],
        sources=sources,
    )
    return result


# ── GET /api/experience/rita/technical-commentary ─────────────────────────────

@router.get("/experience/rita/technical-commentary", summary="Technical commentary + signal summary")
def technical_commentary(
    instrument: str = "NIFTY",
    db: Session = Depends(get_db),
) -> dict:
    """Return a short technical commentary and signal summary for the active instrument.

    Reads the latest market-signals data from MarketDataCacheRepository (CSV fallback
    if DB empty) and derives commentary from RSI-14, ATR%, and trend score.
    Read-only — no db.commit().
    """
    import math
    import numpy as np
    import pandas as pd

    from rita.repositories.market_data import MarketDataCacheRepository
    from rita.schemas.technical import TechnicalCommentaryResponse, SignalSummaryItem

    inst = instrument.upper()

    # ── Fetch price data (same path as market_signals router) ─────────────────
    records = MarketDataCacheRepository(db).read_all()
    nifty = sorted([r for r in records if r.underlying == inst], key=lambda r: r.date)

    if not nifty:
        try:
            from rita.core.data_loader import load_ohlcv_csv
            from rita.core.data_understanding import find_instrument_csv
            csv_path = find_instrument_csv(inst)
            _df = load_ohlcv_csv(str(csv_path))
            close  = _df["Close"].astype(float)
            high   = _df["High"].astype(float)
            low    = _df["Low"].astype(float)
        except Exception:
            return TechnicalCommentaryResponse(
                instrument=inst,
                commentary="No data available.",
                signal_summary=[],
            ).model_dump()
    else:
        close  = pd.Series([r.close for r in nifty], dtype=float)
        high   = pd.Series([getattr(r, "high", r.close) for r in nifty], dtype=float)
        low    = pd.Series([getattr(r, "low",  r.close) for r in nifty], dtype=float)

    # ── Compute indicators ─────────────────────────────────────────────────────
    # RSI-14
    delta    = close.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=13, adjust=False).mean()
    avg_loss = loss.ewm(com=13, adjust=False).mean()
    rs       = avg_gain / avg_loss.replace(0, np.nan)
    rsi_series = 100 - (100 / (1 + rs))

    # ATR-14
    tr       = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr_series = tr.ewm(com=13, adjust=False).mean()

    # Trend score (simple EMA crossover composite)
    ema5_s  = close.ewm(span=5,  adjust=False).mean()
    ema13_s = close.ewm(span=13, adjust=False).mean()
    ema26_s = close.ewm(span=26, adjust=False).mean()
    raw_trend = (0.4 * (ema5_s > ema13_s).astype(float)
                 + 0.3 * (ema13_s > ema26_s).astype(float)
                 + 0.3 * (close > ema26_s).astype(float))
    trend_score_series = (raw_trend - 0.5) * 2

    # ── Latest values ──────────────────────────────────────────────────────────
    rsi_val    = float(rsi_series.iloc[-1])   if not rsi_series.empty    else float("nan")
    atr_val    = float(atr_series.iloc[-1])   if not atr_series.empty    else float("nan")
    price_val  = float(close.iloc[-1])        if not close.empty         else float("nan")
    trend_val  = float(trend_score_series.iloc[-1]) if not trend_score_series.empty else float("nan")

    atr_pct = (atr_val / price_val * 100) if (math.isfinite(atr_val) and math.isfinite(price_val) and price_val) else float("nan")

    # ── Derive labels ──────────────────────────────────────────────────────────
    rsi_valid  = math.isfinite(rsi_val)
    atr_valid  = math.isfinite(atr_pct)
    trend_valid = math.isfinite(trend_val)

    rsi_state  = ("bearish" if rsi_val > 70 else "bullish" if rsi_val < 30 else "neutral") if rsi_valid else "neutral"
    atr_state  = ("bearish" if atr_pct > 1.5 else "bullish" if atr_pct < 0.8 else "normal") if atr_valid else "normal"
    trend_state = ("up" if trend_val > 0.2 else "down" if trend_val < -0.2 else "neutral") if trend_valid else "neutral"

    rsi_label  = "Overbought" if rsi_val > 70 else "Oversold" if rsi_val < 30 else "Neutral"
    atr_label  = "High volatility" if atr_pct > 1.5 else "Compressed" if atr_pct < 0.8 else "Normal range"
    trend_label = "Strong uptrend" if trend_val > 0.5 else "Mild uptrend" if trend_val > 0.2 else "Strong downtrend" if trend_val < -0.5 else "Mild downtrend" if trend_val < -0.2 else "Sideways"

    # ── Commentary string ──────────────────────────────────────────────────────
    parts = []
    if rsi_valid:
        parts.append(f"RSI at {rsi_val:.1f} — {rsi_label}.")
    if atr_valid:
        parts.append(f"ATR% at {atr_pct:.2f}% — {atr_label}.")
    if trend_valid:
        parts.append(f"Trend score {trend_val:.2f} — {trend_label}.")
    commentary = " ".join(parts) if parts else "Insufficient data for commentary."

    # ── Signal summary items ───────────────────────────────────────────────────
    signal_summary = []
    if rsi_valid:
        signal_summary.append(SignalSummaryItem(label="RSI-14", value=f"{rsi_val:.1f}", state=rsi_state))
    if atr_valid:
        signal_summary.append(SignalSummaryItem(label="ATR%", value=f"{atr_pct:.2f}%", state=atr_state))
    if trend_valid:
        signal_summary.append(SignalSummaryItem(label="Trend", value=f"{trend_val:.2f}", state=trend_state))

    return TechnicalCommentaryResponse(
        instrument=inst,
        commentary=commentary,
        signal_summary=signal_summary,
    ).model_dump()


# ── GET /api/v1/experience/rita/geography-overview ────────────────────────────

_EU_COUNTRY_CODES = frozenset({"NL", "DE", "FR", "GB", "BE", "CH", "SE", "ES", "IT", "AT", "FI", "DK", "IE", "PL", "PT"})
_EU_COUNTRY_NAMES = frozenset({"netherlands", "germany", "france", "united kingdom", "belgium", "switzerland", "sweden", "spain", "italy", "austria", "finland", "denmark", "ireland", "poland", "portugal"})

_REGION_FLAGS = {
    "US":    "\U0001f1fa\U0001f1f8",
    "EU":    "\U0001f1ea\U0001f1fa",
    "India": "\U0001f1ee\U0001f1f3",
    "Other": "\U0001f310",
}


def _country_to_region(country_code: str) -> str:
    """Map a country_code string to a geography bucket.

    Accepts both ISO-2 codes ('US', 'IN') and full names ('United States',
    'India') because yfinance returns full names which get stored as-is.
    """
    raw = (country_code or "").strip()
    cc = raw.upper()
    name = raw.lower()
    if cc in ("IN",) or name == "india":
        return "India"
    if cc in ("US", "USA") or name in ("united states", "united states of america"):
        return "US"
    if cc in _EU_COUNTRY_CODES or name in _EU_COUNTRY_NAMES:
        return "EU"
    return "Other"


@router.get(
    "/experience/rita/geography-overview",
    summary="Geography panels — latest close and daily return for all available instruments",
    response_model=GeographyOverviewResponse,
)
def geography_overview(db: Session = Depends(get_db)) -> GeographyOverviewResponse:
    """Read-only. Returns close price and daily return for all is_available instruments
    grouped by geography (dynamically from the instruments table).
    Missing instruments are returned with null values so the UI never receives an error
    for instruments not yet in the data cache.
    No db.commit() in this endpoint.
    """
    _start = time.monotonic()
    sources: dict[str, Any] = {}

    # Build a lookup: instrument_id (upper) → (close, daily_return_pct)
    price_map: dict[str, tuple[Optional[float], Optional[float]]] = {}

    t0 = time.monotonic()
    try:
        cache_repo = MarketDataCacheRepository(db)
        all_records = cache_repo.read_all()
        sources["market_data_cache"] = {
            "status": "ok" if all_records else "empty",
            "record_count": len(all_records),
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }

        # Group by underlying, keep the two most-recent rows to compute daily return
        from collections import defaultdict
        by_instrument: dict[str, list[Any]] = defaultdict(list)
        for rec in all_records:
            by_instrument[rec.underlying.upper()].append(rec)

        for inst_id, recs in by_instrument.items():
            recs_sorted = sorted(recs, key=lambda r: r.date)
            latest = recs_sorted[-1]
            close = float(latest.close) if latest.close is not None else None
            if len(recs_sorted) >= 2:
                prev_close = float(recs_sorted[-2].close) if recs_sorted[-2].close else None
                if prev_close and prev_close != 0 and close is not None:
                    daily_return_pct = round((close - prev_close) / prev_close * 100, 4)
                else:
                    daily_return_pct = None
            else:
                daily_return_pct = None
            price_map[inst_id] = (close, daily_return_pct)

    except Exception as exc:
        sources["market_data_cache"] = {
            "status": "error",
            "record_count": 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }

    def _signal(daily_return_pct: Optional[float]) -> str:
        if daily_return_pct is None:
            return "neutral"
        if daily_return_pct > 0.5:
            return "bullish"
        if daily_return_pct < -0.5:
            return "bearish"
        return "neutral"

    # Load available instruments dynamically from DB
    t0 = time.monotonic()
    try:
        inst_repo = InstrumentRepository(db)
        all_instruments = [i for i in inst_repo.read_all() if i.is_available]
        sources["instruments"] = {
            "status": "ok",
            "count": len(all_instruments),
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        all_instruments = []
        sources["instruments"] = {
            "status": "error",
            "count": 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }

    # Group instruments by region bucket
    from collections import defaultdict as _defaultdict
    region_buckets: dict[str, list[Any]] = _defaultdict(list)
    for inst in all_instruments:
        region = _country_to_region(inst.country_code)
        region_buckets[region].append(inst)

    regions: list[GeoRegion] = []
    for region_name in ("India", "US", "EU", "Other"):
        bucket = region_buckets.get(region_name, [])
        if not bucket:
            continue
        flag = _REGION_FLAGS.get(region_name, "\U0001f310")
        geo_instruments: list[GeoInstrument] = []
        for inst in bucket:
            inst_id = inst.instrument_id.upper()
            close, daily_return_pct = price_map.get(inst_id, (None, None))
            geo_instruments.append(
                GeoInstrument(
                    id=inst_id,
                    name=inst.name,
                    flag=flag,
                    close=close,
                    daily_return_pct=daily_return_pct,
                    signal=_signal(daily_return_pct),
                )
            )
        regions.append(
            GeoRegion(
                region=region_name,
                flag=flag,
                instruments=geo_instruments,
            )
        )

    overall = "ok" if sources.get("market_data_cache", {}).get("status") == "ok" else "partial"
    log_event(
        log, "info", "experience.compose",
        handler="geography_overview",
        duration_ms=int((time.monotonic() - _start) * 1000),
        overall_status=overall,
        response_keys=["regions"],
        sources=sources,
    )
    return GeographyOverviewResponse(regions=regions)


# ── GET /api/v1/experience/rita/backtest-daily ────────────────────────────────

@router.get("/experience/rita/backtest-daily", summary="Daily backtest results (experience tier)")
def experience_backtest_daily(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Experience-tier alias of /backtest-daily. Read-only, no db.commit()."""
    _start = time.monotonic()
    sources: dict[str, Any] = {}

    active_id = _get_active_instrument_id(db)

    t0 = time.monotonic()
    try:
        runs_repo    = BacktestRunsRepository(db)
        results_repo = BacktestResultsRepository(db)
        all_runs = [
            r for r in runs_repo.read_all()
            if r.status in ("complete", "completed")
            and (r.instrument or "NIFTY").upper() == active_id
        ]
        sources["backtest_runs"] = {
            "status": "ok" if all_runs else "empty",
            "record_count": len(all_runs),
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        all_runs = []
        sources["backtest_runs"] = {
            "status": "error",
            "record_count": 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }

    if not all_runs:
        log_event(
            log, "info", "experience.compose",
            handler="experience_backtest_daily",
            duration_ms=int((time.monotonic() - _start) * 1000),
            overall_status="empty",
            response_keys=[],
            sources=sources,
        )
        return []

    latest_run = max(all_runs, key=lambda r: r.ended_at or r.recorded_at)

    t0 = time.monotonic()
    try:
        results = sorted(
            [r for r in results_repo.read_all() if r.run_id == latest_run.run_id],
            key=lambda r: r.date,
        )
        sources["backtest_results"] = {
            "status": "ok" if results else "empty",
            "record_count": len(results),
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        results = []
        sources["backtest_results"] = {
            "status": "error",
            "record_count": 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }

    response = [{
        "date":            str(r.date),
        "portfolio_value": r.portfolio_value,
        "benchmark_value": r.benchmark_value,
        "allocation":      r.allocation,
        "close_price":     r.close_price,
    } for r in results]

    statuses = [s["status"] for s in sources.values()]
    if all(s == "ok" for s in statuses):
        overall = "ok"
    elif any(s == "ok" for s in statuses):
        overall = "partial"
    else:
        overall = "error"

    log_event(
        log, "info", "experience.compose",
        handler="experience_backtest_daily",
        duration_ms=int((time.monotonic() - _start) * 1000),
        overall_status=overall,
        response_keys=[],
        sources=sources,
    )
    return response


# ── GET /api/v1/experience/rita/risk-timeline ─────────────────────────────────

@router.get("/experience/rita/risk-timeline", summary="Risk timeline (experience tier)")
def experience_risk_timeline(
    phase: str = "all",
    instrument: str = "NIFTY",
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Experience-tier alias of /risk-timeline. Read-only, no db.commit()."""
    _start = time.monotonic()
    sources: dict[str, Any] = {}

    instrument = instrument.upper()

    t0 = time.monotonic()
    try:
        runs_repo    = BacktestRunsRepository(db)
        results_repo = BacktestResultsRepository(db)
        all_runs = [
            r for r in runs_repo.read_all()
            if r.status in ("complete", "completed") and (r.instrument or "NIFTY") == instrument
        ]
        sources["backtest_runs"] = {
            "status": "ok" if all_runs else "empty",
            "record_count": len(all_runs),
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        all_runs = []
        sources["backtest_runs"] = {
            "status": "error",
            "record_count": 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }

    if not all_runs:
        log_event(
            log, "info", "experience.compose",
            handler="experience_risk_timeline",
            duration_ms=int((time.monotonic() - _start) * 1000),
            overall_status="empty",
            response_keys=[],
            sources=sources,
        )
        return []

    latest_run = max(all_runs, key=lambda r: r.ended_at or r.recorded_at)

    t0 = time.monotonic()
    try:
        results = sorted(
            [r for r in results_repo.read_all() if r.run_id == latest_run.run_id],
            key=lambda r: r.date,
        )
        sources["backtest_results"] = {
            "status": "ok" if results else "empty",
            "record_count": len(results),
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        results = []
        sources["backtest_results"] = {
            "status": "error",
            "record_count": 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }

    port_values  = [r.portfolio_value if r.portfolio_value is not None else 1.0 for r in results]
    bench_values = [r.benchmark_value if r.benchmark_value is not None else 1.0 for r in results]

    def _daily_rets(vals: list[float]) -> list[Optional[float]]:
        rets: list[Optional[float]] = [None]
        for i in range(1, len(vals)):
            prev = vals[i - 1]
            rets.append((vals[i] - prev) / prev if prev else None)
        return rets

    port_rets  = _daily_rets(port_values)
    bench_rets = _daily_rets(bench_values)

    def _rolling_vol(rets: list[Optional[float]], i: int, window: int = 20) -> Optional[float]:
        window_rets = [r for r in rets[max(0, i - window + 1): i + 1] if r is not None]
        if len(window_rets) < 2:
            return None
        return round(_stats.stdev(window_rets) * _math.sqrt(252) * 100, 4)

    def _var_95(rets: list[Optional[float]], i: int, window: int = 20) -> Optional[float]:
        window_rets = sorted(r for r in rets[max(0, i - window + 1): i + 1] if r is not None)
        if not window_rets:
            return None
        idx = max(0, int(len(window_rets) * 0.05) - 1)
        return round(window_rets[idx] * 100, 4)

    peak = 1.0
    drawdowns: list[float] = []
    for v in port_values:
        if v > peak:
            peak = v
        dd = (v - peak) / peak * 100 if peak > 0 else 0.0
        drawdowns.append(round(dd, 4))

    _ = phase  # accepted for forward-compatibility, not yet used for filtering

    response = [{
        "date":                  str(r.date),
        "portfolio_value":       r.portfolio_value,
        "portfolio_value_norm":  r.portfolio_value,
        "benchmark_value":       r.benchmark_value,
        "allocation":            r.allocation,
        "close_price":           r.close_price,
        "current_drawdown_pct":  drawdowns[i],
        "drawdown_budget_pct":   round(min(abs(drawdowns[i]) / _MDD_LIMIT_PCT * 100.0, 150.0), 2),
        "rolling_vol_20d":       _rolling_vol(port_rets, i),
        "market_var_95":         _var_95(bench_rets, i),
        "portfolio_var_95":      _var_95(port_rets, i),
        "regime":                _regime(r.allocation),
        "trend_score":           round(((r.allocation if r.allocation is not None else 0.5) - 0.5) * 2.0, 4),
        "phase":                 "Backtest",
        "run_id":                r.run_id,
    } for i, r in enumerate(results)]

    statuses = [s["status"] for s in sources.values()]
    if all(s == "ok" for s in statuses):
        overall = "ok"
    elif any(s == "ok" for s in statuses):
        overall = "partial"
    else:
        overall = "error"

    log_event(
        log, "info", "experience.compose",
        handler="experience_risk_timeline",
        duration_ms=int((time.monotonic() - _start) * 1000),
        overall_status=overall,
        response_keys=[],
        sources=sources,
    )
    return response


# ── GET /api/v1/experience/rita/training-history ──────────────────────────────

@router.get("/experience/rita/training-history", summary="Training run history (experience tier)")
def experience_training_history(
    instrument: str = "NIFTY",
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Experience-tier alias of /training-history. Read-only, no db.commit()."""
    from rita.repositories.training import TrainingRunsRepository

    repo = TrainingRunsRepository(db)
    runs = sorted(
        [r for r in repo.read_all() if (r.instrument or "NIFTY") == instrument],
        key=lambda r: r.recorded_at,
    )

    def _pct(v: Any) -> Optional[float]:
        return round(v * 100, 2) if v is not None else None

    def _f(v: Any) -> Optional[float]:
        return round(v, 4) if v is not None else None

    result = []
    for i, r in enumerate(runs):
        bt_sharpe = _f(r.backtest_sharpe)
        bt_mdd    = _pct(r.backtest_mdd)
        bt_ret    = _pct(r.backtest_return)
        bt_constraints = (
            bool(bt_sharpe >= 1.0 and abs(bt_mdd) < 10)
            if bt_sharpe is not None and bt_mdd is not None else None
        )
        result.append({
            "round":    i + 1,
            "run_id":   r.run_id,
            "instrument": r.instrument or "NIFTY",
            "timestamp":  r.recorded_at.isoformat(),
            "model_version": r.model_version,
            "algorithm": r.algorithm,
            "status":    r.status,
            "timesteps": r.timesteps,
            "source": "trained",
            "train_sharpe":     _f(r.train_sharpe),
            "train_mdd_pct":    _pct(r.train_mdd),
            "train_return_pct": _pct(r.train_return),
            "train_trades":     r.train_trades,
            "val_sharpe":       _f(r.val_sharpe),
            "val_mdd_pct":      _pct(r.val_mdd),
            "val_return_pct":   _pct(r.val_return),
            "val_cagr_pct":     _pct(r.val_cagr),
            "val_trades":       r.val_trades,
            "backtest_sharpe":          bt_sharpe,
            "backtest_mdd_pct":         bt_mdd,
            "backtest_return_pct":      bt_ret,
            "backtest_cagr_pct":        bt_ret,
            "backtest_trades":          r.backtest_trades,
            "backtest_constraints_met": bt_constraints,
            "notes": "",
        })
    result.reverse()
    return result


# ── GET /api/v1/experience/rita/strategy-comparison ──────────────────────────

# ─ Strategy runner helpers ───────────────────────────────────────────────────

_INITIAL_CAPITAL = 10_000.0
_STRATEGY_COLORS = {
    "Buy and Hold":        "#0056B8",
    "Value Investing":     "#1A6B3C",
    "Momentum Investing":  "#92480A",
    "Swing Trading":       "#6B2FA0",
    "Support-Resistance":  "#9B1C1C",
}


def _sanitize(v: float) -> float:
    """Replace NaN/inf with 0.0."""
    import math
    if v is None or math.isnan(v) or math.isinf(v):
        return 0.0
    return round(v, 4)


def _compute_metrics(equity: list[float], n_trades: int, wins: int) -> StrategySummaryRow:
    """Derive aggregate metrics from an equity curve."""
    import statistics as _stats_mod

    final_value = equity[-1] if equity else _INITIAL_CAPITAL
    total_return_pct = _sanitize((final_value - _INITIAL_CAPITAL) / _INITIAL_CAPITAL * 100)

    # Daily returns for Sharpe
    daily_ret: list[float] = []
    for i in range(1, len(equity)):
        r = (equity[i] - equity[i - 1]) / max(equity[i - 1], 1e-9)
        daily_ret.append(r)

    if len(daily_ret) >= 2:
        mu = _stats_mod.mean(daily_ret)
        sd = _stats_mod.stdev(daily_ret)
        sharpe = _sanitize((mu / sd) * (252 ** 0.5) if sd > 1e-12 else 0.0)
    else:
        sharpe = 0.0

    # Max drawdown
    peak = equity[0] if equity else _INITIAL_CAPITAL
    mdd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        dd = (peak - v) / max(peak, 1e-9) * 100
        if dd > mdd:
            mdd = dd
    max_drawdown_pct = _sanitize(mdd)

    win_rate_pct = _sanitize((wins / n_trades * 100) if n_trades > 0 else 0.0)
    return StrategySummaryRow(
        name="",  # filled by caller
        total_return_pct=total_return_pct,
        sharpe=sharpe,
        max_drawdown_pct=max_drawdown_pct,
        n_trades=n_trades,
        win_rate_pct=win_rate_pct,
        final_value=_sanitize(final_value),
    )


def _run_buy_and_hold(close: "list[float]") -> tuple[list[float], int, int]:
    capital = _INITIAL_CAPITAL
    shares = capital / close[0] if close[0] > 0 else 0
    equity = [shares * p for p in close]
    return equity, 1, 1 if equity[-1] > _INITIAL_CAPITAL else 0


def _run_value_investing(close: "list[float]") -> tuple[list[float], int, int]:
    import math
    n = len(close)
    # RSI-14 with 50-day warmup
    rsi: list[float] = [float("nan")] * n
    period = 14
    gains = [0.0] * n
    losses = [0.0] * n
    for i in range(1, n):
        d = close[i] - close[i - 1]
        gains[i] = max(d, 0.0)
        losses[i] = max(-d, 0.0)
    if n > period:
        avg_g = sum(gains[1:period + 1]) / period
        avg_l = sum(losses[1:period + 1]) / period
        for i in range(period, n):
            avg_g = (avg_g * (period - 1) + gains[i]) / period
            avg_l = (avg_l * (period - 1) + losses[i]) / period
            rs = avg_g / avg_l if avg_l > 1e-12 else 100.0
            rsi[i] = 100.0 - 100.0 / (1.0 + rs)

    capital = _INITIAL_CAPITAL
    shares = 0.0
    equity = []
    n_trades = 0
    wins = 0
    entry_price = 0.0
    in_pos = False
    for i, p in enumerate(close):
        r = rsi[i]
        if not math.isnan(r):
            if not in_pos and r < 30:
                shares = capital / p if p > 0 else 0
                capital = 0.0
                in_pos = True
                entry_price = p
            elif in_pos and r > 70:
                capital = shares * p
                n_trades += 1
                if p > entry_price:
                    wins += 1
                shares = 0.0
                in_pos = False
        pv = capital + shares * p
        equity.append(pv)
    return equity, n_trades, wins


def _run_momentum(close: "list[float]") -> tuple[list[float], int, int]:
    n = len(close)
    sma: list[float] = [float("nan")] * n
    period = 20
    for i in range(period - 1, n):
        sma[i] = sum(close[i - period + 1:i + 1]) / period

    import math
    capital = _INITIAL_CAPITAL
    shares = 0.0
    equity = []
    n_trades = 0
    wins = 0
    entry_price = 0.0
    in_pos = False
    for i, p in enumerate(close):
        s = sma[i]
        if not math.isnan(s) and i > 0 and not math.isnan(sma[i - 1]):
            prev_above = close[i - 1] > sma[i - 1]
            curr_above = p > s
            if not in_pos and not prev_above and curr_above:
                shares = capital / p if p > 0 else 0
                capital = 0.0
                in_pos = True
                entry_price = p
            elif in_pos and prev_above and not curr_above:
                capital = shares * p
                n_trades += 1
                if p > entry_price:
                    wins += 1
                shares = 0.0
                in_pos = False
        pv = capital + shares * p
        equity.append(pv)
    return equity, n_trades, wins


def _run_swing_trading(close: "list[float]") -> tuple[list[float], int, int]:
    window = 5
    capital = _INITIAL_CAPITAL
    shares = 0.0
    equity = []
    n_trades = 0
    wins = 0
    entry_price = 0.0
    in_pos = False
    for i, p in enumerate(close):
        if i >= window:
            local_low  = min(close[i - window:i])
            local_high = max(close[i - window:i])
            if not in_pos and p <= local_low:
                shares = capital / p if p > 0 else 0
                capital = 0.0
                in_pos = True
                entry_price = p
            elif in_pos and p >= local_high:
                capital = shares * p
                n_trades += 1
                if p > entry_price:
                    wins += 1
                shares = 0.0
                in_pos = False
        pv = capital + shares * p
        equity.append(pv)
    return equity, n_trades, wins


def _run_support_resistance(close: "list[float]") -> tuple[list[float], int, int]:
    period = 252
    capital = _INITIAL_CAPITAL
    shares = 0.0
    equity = []
    n_trades = 0
    wins = 0
    entry_price = 0.0
    in_pos = False
    for i, p in enumerate(close):
        if i >= period:
            window = close[i - period:i]
            low_252  = min(window)
            high_252 = max(window)
            if not in_pos and p <= low_252 * 1.05:
                shares = capital / p if p > 0 else 0
                capital = 0.0
                in_pos = True
                entry_price = p
            elif in_pos and p >= high_252 * 0.95:
                capital = shares * p
                n_trades += 1
                if p > entry_price:
                    wins += 1
                shares = 0.0
                in_pos = False
        pv = capital + shares * p
        equity.append(pv)
    return equity, n_trades, wins


@_lru_cache(maxsize=64)
def _run_strategies_cached(instrument: str, year: int) -> StrategyComparisonResponse:
    """Compute all 5 strategies. LRU-cached on (instrument, year)."""
    import pandas as pd
    from rita.core.data_loader import load_instrument_data

    try:
        df = load_instrument_data(instrument)
    except FileNotFoundError:
        return StrategyComparisonResponse(
            instrument=instrument,
            year=year,
            error=f"No OHLCV data found for instrument '{instrument}'",
        )
    except Exception as exc:
        return StrategyComparisonResponse(
            instrument=instrument,
            year=year,
            error=f"Data load error: {exc}",
        )

    # Filter to requested year with 50-day prior warmup window
    year_start = pd.Timestamp(f"{year}-01-01")
    year_end   = pd.Timestamp(f"{year}-12-31")

    df_year = df.loc[year_start:year_end]
    if df_year.empty:
        return StrategyComparisonResponse(
            instrument=instrument,
            year=year,
            error=f"No data available for {instrument} in {year}",
        )

    # Build warmup slice (up to 252 prior trading days)
    warmup_start = df.index[max(0, df.index.get_loc(df_year.index[0]) - 252)] if len(df_year) > 0 else year_start
    df_warm = df.loc[warmup_start:year_end]
    close_all: list[float] = df_warm["Close"].tolist()

    # Trim index alignment — strategy runners return equity of same length as close_all
    # We then slice to the year-only portion for the response
    n_warmup = len(df_warm.loc[warmup_start:year_start]) - 1
    year_slice = slice(n_warmup, None)

    dates_all = [str(d.date()) for d in df_warm.index]
    dates = dates_all[year_slice]

    runners = [
        ("Buy and Hold",       _run_buy_and_hold),
        ("Value Investing",    _run_value_investing),
        ("Momentum Investing", _run_momentum),
        ("Swing Trading",      _run_swing_trading),
        ("Support-Resistance", _run_support_resistance),
    ]

    strategies: list[StrategyResult] = []
    summary: list[StrategySummaryRow] = []

    for name, runner in runners:
        try:
            eq_full, n_trades, wins = runner(close_all)
            eq = eq_full[year_slice]
            # Normalise equity so all strategies start at INITIAL_CAPITAL on day 1 of the year
            if eq and eq[0] > 0:
                scale = _INITIAL_CAPITAL / eq[0]
                eq = [v * scale for v in eq]
        except Exception as exc:
            log.warning("strategy_comparison.runner_error", strategy=name, error=str(exc))
            eq = [_INITIAL_CAPITAL] * len(dates)
            n_trades = 0
            wins = 0

        eq_safe = [_sanitize(v) for v in eq]
        metrics = _compute_metrics(eq_safe, n_trades, wins)
        metrics.name = name

        strategies.append(StrategyResult(
            name=name,
            equity=eq_safe,
            color=_STRATEGY_COLORS.get(name, "#666666"),
        ))
        summary.append(metrics)

    return StrategyComparisonResponse(
        instrument=instrument,
        year=year,
        dates=dates,
        strategies=strategies,
        summary=summary,
    )


@router.get(
    "/experience/rita/strategy-comparison",
    response_model=StrategyComparisonResponse,
    summary="Strategy Comparison — 5-strategy OHLCV performance (experience tier)",
)
def experience_strategy_comparison(
    instrument: Optional[str] = None,
    year: int = 2025,
    db: Session = Depends(get_db),
) -> StrategyComparisonResponse:
    """Run 5 rule-based strategies on OHLCV data and return equity curves + metrics.

    Experience tier — read-only. No db.commit().
    LRU-cached per (instrument, year).
    """
    if year not in (2025, 2026):
        year = 2025

    inst = (instrument or _get_active_instrument_id(db)).upper()

    _start = time.monotonic()
    result = _run_strategies_cached(inst, year)
    log_event(
        log, "info", "experience.compose",
        handler="experience_strategy_comparison",
        instrument=inst,
        year=year,
        duration_ms=int((time.monotonic() - _start) * 1000),
        response_keys=["strategies", "summary", "dates"],
        sources={"csv": {"status": "ok" if not result.error else "error"}},
    )
    return result


# ── GET /api/v1/experience/rita/portfolio-performance ─────────────────────────

@router.get(
    "/experience/rita/portfolio-performance",
    summary="Custom portfolio 2025 daily performance index (base=100)",
)
def portfolio_performance(
    holdings: str = "",
    year: int = 2025,
) -> dict[str, Any]:
    """Compute a daily portfolio value index for user-defined allocations.

    holdings: comma-separated pairs, e.g. "NIFTY:40,NVIDIA:30,ASML:30"
    Returns {dates, values} where values start at 100 on the first trading day.
    """
    import pandas as pd
    from rita.core.data_loader import load_instrument_data

    if not holdings.strip():
        return {"dates": [], "values": [], "instruments": []}

    parsed: dict[str, float] = {}
    for part in holdings.split(","):
        part = part.strip()
        if ":" not in part:
            continue
        inst_raw, pct_s = part.split(":", 1)
        try:
            parsed[inst_raw.strip().upper()] = float(pct_s.strip()) / 100.0
        except ValueError:
            pass

    if not parsed:
        return {"dates": [], "values": [], "instruments": []}

    year_start = pd.Timestamp(f"{year}-01-01")
    year_end   = pd.Timestamp(f"{year}-12-31")

    series: dict[str, pd.Series] = {}
    for inst in parsed:
        try:
            df = load_instrument_data(inst)
            s = df.loc[year_start:year_end, "Close"].dropna()
            if len(s) >= 2:
                series[inst] = s
        except Exception:
            pass

    if not series:
        return {"dates": [], "values": [], "instruments": list(parsed.keys())}

    all_dates = pd.DatetimeIndex(
        sorted(set().union(*[set(s.index) for s in series.values()]))
    )

    portfolio = pd.Series(0.0, index=all_dates)
    for inst, weight in parsed.items():
        if inst not in series:
            continue
        s = series[inst].reindex(all_dates).ffill().bfill()
        base = float(s.iloc[0])
        if base > 0:
            portfolio += (s / base) * 100.0 * weight

    return {
        "dates":       [str(d.date()) for d in portfolio.index],
        "values":      [round(float(v), 2) for v in portfolio],
        "instruments": list(series.keys()),
    }
