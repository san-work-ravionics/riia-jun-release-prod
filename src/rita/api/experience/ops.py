"""Experience Layer -- Ops view aggregation router.

ADR-001: Tier 3 (Experience Layer). Read-only composition. No writes, no side effects.
Composes: training run history + backtest run history + recent audit log.
Also provides Ops monitoring summaries (metrics/summary, step-log).
"""

import csv
import json
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from prometheus_client import REGISTRY
from pydantic import BaseModel
from sqlalchemy.orm import Session

from rita.database import get_db
from rita.logging_config import log_event
from rita.repositories.agent_builds import AgentBuildRepository
from rita.repositories.audit import AuditLogRepository
from rita.repositories.training import TrainingRunsRepository
from rita.repositories.backtest import BacktestRunsRepository
from rita.repositories.api_call_log import ApiCallLogRepository
from rita.schemas.api_metrics import ApiMetricsResponse, ApiMetricsRow
from rita.schemas.functional_kpis import FunctionalKPIsResponse, FunctionalKPIsSeries
from rita.schemas.agent_builds import (
    AgentBuildMetrics,
    AgentBuildRunOut,
    AgentBuildsResponse,
    AgentOut,
    FailureEntry,
    GroundingPoint,
    RoleMetrics,
    SkillVersion,
)
from rita.schemas.audit import AuditLog
from rita.schemas.backtest import BacktestRun
from rita.schemas.token_forecast import TokenForecastResponse
from rita.schemas.training import TrainingRun
from rita.services.backtest_service import BacktestService
from rita.services.workflow_service import WorkflowService

log = structlog.get_logger()

router = APIRouter(prefix="/api/experience/ops", tags=["experience:ops"])


class OpsPayload(BaseModel):
    training_runs: list[TrainingRun]
    backtest_runs: list[BacktestRun]
    recent_audit: list[AuditLog]


def get_workflow_svc(db: Session = Depends(get_db)) -> WorkflowService:
    return WorkflowService(db)


def get_backtest_svc(db: Session = Depends(get_db)) -> BacktestService:
    return BacktestService(db)


def get_audit_repo(db: Session = Depends(get_db)) -> AuditLogRepository:
    return AuditLogRepository(db)


@router.get("/", response_model=OpsPayload)
def get_ops(
    audit_limit: int = Query(default=100, ge=1, le=1000),
    workflow_svc: WorkflowService = Depends(get_workflow_svc),
    backtest_svc: BacktestService = Depends(get_backtest_svc),
    audit_repo: AuditLogRepository = Depends(get_audit_repo),
) -> OpsPayload:
    """Return a single aggregated payload for the Ops dashboard."""
    _start = time.monotonic()
    sources: dict[str, Any] = {}

    t0 = time.monotonic()
    try:
        training_runs = workflow_svc.list_runs()
        sources["training_runs"] = {
            "status": "ok" if training_runs else "empty",
            "record_count": len(training_runs),
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        training_runs = []
        sources["training_runs"] = {
            "status": "error",
            "record_count": 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }

    t0 = time.monotonic()
    try:
        backtest_runs = backtest_svc.list_runs()
        sources["backtest_runs"] = {
            "status": "ok" if backtest_runs else "empty",
            "record_count": len(backtest_runs),
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        backtest_runs = []
        sources["backtest_runs"] = {
            "status": "error",
            "record_count": 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }

    t0 = time.monotonic()
    try:
        audit = audit_repo.read_all()
        recent_audit = sorted(audit, key=lambda e: e.timestamp, reverse=True)[:audit_limit]
        sources["recent_audit"] = {
            "status": "ok" if recent_audit else "empty",
            "record_count": len(recent_audit),
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        recent_audit = []
        sources["recent_audit"] = {
            "status": "error",
            "record_count": 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }

    statuses = [s["status"] for s in sources.values()]
    if all(s == "ok" for s in statuses):
        overall = "ok"
    elif any(s == "ok" for s in statuses):
        overall = "partial"
    else:
        overall = "error"

    response = OpsPayload(
        training_runs=training_runs,
        backtest_runs=backtest_runs,
        recent_audit=recent_audit,
    )

    log_event(
        log, "info", "experience.compose",
        handler="get_ops",
        duration_ms=int((time.monotonic() - _start) * 1000),
        overall_status=overall,
        response_keys=["training_runs", "backtest_runs", "recent_audit"],
        sources=sources,
    )
    return response


# ── GET /api/v1/metrics/summary ───────────────────────────────────────────────

def _collect_metrics_summary() -> dict[str, Any]:
    """Read Prometheus REGISTRY and return a structured summary dict."""
    total = 0
    errors = 0
    dur_sum = 0.0
    endpoints: dict[str, dict[str, int]] = defaultdict(lambda: {"count": 0, "errors": 0})

    try:
        for mf in REGISTRY.collect():
            if mf.name != "http_request_duration_seconds":
                continue
            for s in mf.samples:
                handler  = s.labels.get("handler", "unknown")
                sc       = str(s.labels.get("status_code", ""))
                is_error = sc.startswith(("4", "5"))
                if s.name.endswith("_count"):
                    count = int(s.value)
                    total += count
                    endpoints[handler]["count"] += count
                    if is_error:
                        errors += count
                        endpoints[handler]["errors"] += count
                elif s.name.endswith("_sum"):
                    dur_sum += s.value
    except Exception:  # noqa: BLE001
        pass

    avg_ms         = round(dur_sum / total * 1000, 1) if total > 0 else None
    error_rate_pct = round(errors / total * 100, 2) if total > 0 else 0.0
    sorted_eps     = dict(sorted(endpoints.items(), key=lambda kv: kv[1]["count"], reverse=True)[:20])

    return {
        "total_requests": total,
        "error_count": errors,
        "error_rate_pct": error_rate_pct,
        "avg_latency_ms": avg_ms,
        "endpoints": sorted_eps,
    }


@router.get("/metrics/summary", summary="Structured API metrics summary", tags=["experience:ops"])
def metrics_summary(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Compose Prometheus live metrics + training KPIs for the Ops monitoring panel."""
    _start = time.monotonic()
    sources: dict[str, Any] = {}

    t0 = time.monotonic()
    try:
        api = _collect_metrics_summary()
        sources["prometheus_metrics"] = {
            "status": "ok",
            "record_count": api.get("total_requests", 0),
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        api = {"total_requests": 0, "error_count": 0, "error_rate_pct": 0.0, "avg_latency_ms": None, "endpoints": {}}
        sources["prometheus_metrics"] = {
            "status": "error",
            "record_count": 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }

    training: dict[str, Any] = {"rounds": 0}
    pipeline: dict[str, Any] = {"completed_steps": 0, "failed_steps": 0, "step_timing": {}}

    t0 = time.monotonic()
    try:
        train_repo = TrainingRunsRepository(db)
        runs       = train_repo.read_all()
        completed  = [r for r in runs if r.status in ("complete", "completed")]
        failed     = [r for r in runs if r.status == "failed"]

        training["rounds"]           = len(completed)
        pipeline["completed_steps"]  = len(completed)
        pipeline["failed_steps"]     = len(failed)

        if completed:
            latest = max(completed, key=lambda r: r.recorded_at)
            sharpe = latest.backtest_sharpe
            mdd    = latest.backtest_mdd
            ret    = latest.backtest_return
            training["latest_backtest_sharpe"]   = sharpe
            training["latest_backtest_mdd_pct"]  = round(mdd * 100, 2) if mdd is not None else None
            training["latest_backtest_cagr_pct"] = round(ret * 100, 2) if ret is not None else None
            training["latest_constraints_met"]   = (
                sharpe is not None and sharpe >= 1.0
                and mdd is not None and abs(mdd * 100) < 10
            )

        bt_repo  = BacktestRunsRepository(db)
        bt_runs  = [r for r in bt_repo.read_all() if r.status in ("complete", "completed")]
        if bt_runs:
            latest_bt = max(bt_runs, key=lambda r: r.recorded_at)
            training["backtest_start_date"] = str(latest_bt.start_date)
            training["backtest_end_date"]   = str(latest_bt.end_date)

        sources["training_kpis"] = {
            "status": "ok" if completed else "empty",
            "record_count": len(completed),
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:  # noqa: BLE001
        sources["training_kpis"] = {
            "status": "error",
            "record_count": 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }

    response = {"api_requests": api, "pipeline": pipeline, "training": training}

    statuses = [s["status"] for s in sources.values()]
    if all(s == "ok" for s in statuses):
        overall = "ok"
    elif any(s == "ok" for s in statuses):
        overall = "partial"
    else:
        overall = "error"

    log_event(
        log, "info", "experience.compose",
        handler="metrics_summary",
        duration_ms=int((time.monotonic() - _start) * 1000),
        overall_status=overall,
        response_keys=list(response.keys()),
        sources=sources,
    )
    return response


# ── GET /api/v1/step-log ──────────────────────────────────────────────────────

@router.get("/step-log", summary="Pipeline step log", tags=["experience:ops"])
def step_log(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Compose the latest pipeline run as 4 logical steps for the monitoring table."""
    _start = time.monotonic()
    sources: dict[str, Any] = {}

    t0 = time.monotonic()
    try:
        train_repo = TrainingRunsRepository(db)
        bt_repo    = BacktestRunsRepository(db)
        all_trains = sorted(train_repo.read_all(), key=lambda r: r.recorded_at, reverse=True)
        all_bts    = sorted(bt_repo.read_all(),   key=lambda r: r.recorded_at, reverse=True)
        sources["pipeline_runs"] = {
            "status": "ok" if all_trains else "empty",
            "record_count": len(all_trains),
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as exc:
        all_trains, all_bts = [], []
        sources["pipeline_runs"] = {
            "status": "error",
            "record_count": 0,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }

    if not all_trains:
        log_event(
            log, "info", "experience.compose",
            handler="step_log",
            duration_ms=int((time.monotonic() - _start) * 1000),
            overall_status="empty",
            response_keys=[],
            sources=sources,
        )
        return []

    latest    = all_trains[0]
    latest_bt = all_bts[0] if all_bts else None

    def _iso(dt: Any) -> Optional[str]:
        return dt.isoformat() if dt else None

    def _dur(start: Any, end: Any) -> Optional[float]:
        if start and end:
            return (end - start).total_seconds()
        return None

    response = [
        {
            "step_num": 1, "step_name": "Load & Prepare Data", "status": "completed",
            "duration_secs": None, "started_at": _iso(latest.started_at), "ended_at": None,
            "run_id": latest.run_id,
        },
        {
            "step_num": 2, "step_name": "Compute Indicators", "status": "completed",
            "duration_secs": None, "started_at": _iso(latest.started_at), "ended_at": None,
            "run_id": latest.run_id,
        },
        {
            "step_num": 3, "step_name": f"Train Model ({latest.model_version})",
            "status": latest.status,
            "duration_secs": _dur(latest.started_at, latest.ended_at),
            "started_at": _iso(latest.started_at), "ended_at": _iso(latest.ended_at),
            "run_id": latest.run_id,
            "sharpe": latest.backtest_sharpe,
            "mdd": round(latest.backtest_mdd * 100, 2) if latest.backtest_mdd else None,
        },
        {
            "step_num": 4, "step_name": "Backtest",
            "status": latest_bt.status if latest_bt else "pending",
            "duration_secs": _dur(latest_bt.started_at, latest_bt.ended_at) if latest_bt else None,
            "started_at": _iso(latest_bt.started_at) if latest_bt else None,
            "ended_at":   _iso(latest_bt.ended_at)   if latest_bt else None,
            "run_id": latest_bt.run_id if latest_bt else None,
        },
    ]

    statuses = [s["status"] for s in sources.values()]
    if all(s == "ok" for s in statuses):
        overall = "ok"
    elif any(s == "ok" for s in statuses):
        overall = "partial"
    else:
        overall = "error"

    log_event(
        log, "info", "experience.compose",
        handler="step_log",
        duration_ms=int((time.monotonic() - _start) * 1000),
        overall_status=overall,
        response_keys=[],
        sources=sources,
    )
    return response


# ── GET /api/experience/ops/agent-builds ─────────────────────────────────────

@router.get("/agent-builds", response_model=AgentBuildsResponse)
def get_agent_builds(
    limit: int = Query(default=20, ge=1, le=200),
    app: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
) -> AgentBuildsResponse:
    """Return agent build run history and aggregated metrics from the database."""
    run_repo = AgentBuildRepository(db)
    runs = run_repo.list_with_agents(limit=limit, app_filter=app)
    all_agents = run_repo.list_all_agents()

    # Build per_role metrics
    role_data: dict[str, list] = defaultdict(list)
    for agent in all_agents:
        role_data[agent.role].append(agent)

    per_role: dict[str, RoleMetrics] = {}
    for role, agents in role_data.items():
        scores = [a.adherence_score for a in agents if a.adherence_score is not None]
        tokens = [a.token_estimate for a in agents if a.token_estimate is not None]
        first_pass = [a for a in agents if a.status == "pass"]
        per_role[role] = RoleMetrics(
            run_count=len(agents),
            avg_adherence_score=sum(scores) / len(scores) if scores else None,
            first_pass_rate=len(first_pass) / len(agents) if agents else None,
            avg_token_cost=sum(tokens) / len(tokens) if tokens else None,
        )

    # Build grounding trend (one point per run, all agents in that run)
    all_runs_for_trend = run_repo.list_with_agents(limit=200)
    grounding_trend: list[GroundingPoint] = []
    for run in reversed(all_runs_for_trend):
        agents_for_run = [a for a in all_agents if a.run_id == run.run_id]
        checks_passed = 0
        checks_total = 0
        for a in agents_for_run:
            gc = a.grounding_checks or {}
            checks_passed += sum(1 for v in gc.values() if v is True)
            checks_total += len(gc)
        score = checks_passed / checks_total if checks_total > 0 else 0.0
        grounding_trend.append(
            GroundingPoint(
                run_id=run.run_id,
                app=run.app,
                grounding_score=score,
                checks_passed=checks_passed,
                checks_total=checks_total,
            )
        )

    # Build failure_modes
    failure_map: dict[str, dict] = defaultdict(lambda: {"total": 0, "by_role": defaultdict(int)})
    for agent in all_agents:
        for code in (agent.failure_modes or []):
            failure_map[code]["total"] += 1
            failure_map[code]["by_role"][agent.role] += 1
    failure_modes: dict[str, FailureEntry] = {
        code: FailureEntry(total=v["total"], by_role=dict(v["by_role"]))
        for code, v in failure_map.items()
    }

    # Read metrics.json for the 7 extended metric sections + skill_version_history
    _metrics_extra: dict[str, Any] = {}
    _runs_dir = Path(__file__).parents[4] / "data" / "agent-ops"
    _metrics_path = _runs_dir / "metrics.json"
    _metrics_svh_lookup: dict[str, dict] = {}
    if _metrics_path.exists():
        try:
            with _metrics_path.open() as _f:
                _m = json.load(_f)
            for _key in ("task_completion", "quality", "token_forecasting",
                         "efficiency", "reliability", "hitl", "agentic"):
                if _key in _m:
                    _metrics_extra[_key] = _m[_key]
            # Build lookup for skill_version_history by skill_file name
            for _svh in _m.get("skill_version_history", []):
                _sf_key = _svh.get("skill_file")
                if _sf_key:
                    _metrics_svh_lookup[_sf_key] = _svh
        except Exception:
            pass

    # Skill version history — join DB skill files with metrics.json data
    skill_files = list({r.skill_file for r in all_runs_for_trend if r.skill_file})
    skill_version_history: list[SkillVersion] = []
    for sf in skill_files:
        _svh_data = _metrics_svh_lookup.get(sf, {})
        skill_version_history.append(
            SkillVersion(
                skill_file=sf,
                last_updated=_svh_data.get("last_updated"),
                recent_commits=_svh_data.get("recent_commits", []),
                improvement_applied=_svh_data.get("improvement_applied"),
                before_first_pass_rate=_svh_data.get("before_first_pass_rate"),
                after_first_pass_rate=_svh_data.get("after_first_pass_rate"),
            )
        )
    # Also include entries from metrics.json not yet in DB (e.g. enhance.md)
    for _sf_key, _svh_data in _metrics_svh_lookup.items():
        if _sf_key not in skill_files:
            skill_version_history.append(
                SkillVersion(
                    skill_file=_sf_key,
                    last_updated=_svh_data.get("last_updated"),
                    recent_commits=_svh_data.get("recent_commits", []),
                    improvement_applied=_svh_data.get("improvement_applied"),
                    before_first_pass_rate=_svh_data.get("before_first_pass_rate"),
                    after_first_pass_rate=_svh_data.get("after_first_pass_rate"),
                )
            )

    runs_out: list[AgentBuildRunOut] = []
    for run in runs:
        agents_for_run = [a for a in all_agents if a.run_id == run.run_id]
        # Load per-run JSON for v2 fields not stored in DB
        _run_json: dict[str, Any] = {}
        _run_json_path = _runs_dir / "runs" / f"run-{run.run_id}.json"
        if _run_json_path.exists():
            try:
                with _run_json_path.open() as _f:
                    _run_json = json.load(_f)
            except Exception:
                pass
        # Build per-agent actual_tokens lookup from run JSON
        _json_agents_by_role: dict[str, dict] = {
            a["role"]: a
            for a in _run_json.get("agents", [])
            if isinstance(a, dict) and "role" in a
        }
        agents_out = [
            AgentOut(
                role=a.role,
                status=a.status,
                token_estimate=a.token_estimate,
                adherence_score=a.adherence_score,
                steps_required=a.steps_required,
                steps_completed=a.steps_completed,
                grounding_checks=a.grounding_checks,
                failure_modes=a.failure_modes,
                actual_tokens=_json_agents_by_role.get(a.role, {}).get("actual_tokens"),
            )
            for a in agents_for_run
        ]
        runs_out.append(
            AgentBuildRunOut(
                run_id=run.run_id,
                app=run.app,
                request=run.request,
                overall_status=run.overall_status,
                duration_minutes=run.duration_minutes,
                branch=run.branch,
                agents=agents_out,
                token_forecast=_run_json.get("token_forecast"),
                total_tokens_estimated=_run_json.get("total_tokens_estimated"),
                hitl_events=_run_json.get("hitl_events"),
                human_score_csat=_run_json.get("human_score", {}).get("csat"),
            )
        )

    return AgentBuildsResponse(
        runs=runs_out,
        metrics=AgentBuildMetrics(
            total_runs=len(all_runs_for_trend),
            per_role=per_role,
            grounding_trend=grounding_trend,
            failure_modes=failure_modes,
            skill_version_history=skill_version_history,
            **_metrics_extra,
        ),
    )


# ── GET /api/experience/ops/token-forecast ────────────────────────────────────

@router.get("/token-forecast", response_model=TokenForecastResponse)
def get_token_forecast(
    feature_type: str,
    files_to_change: str,
    new_endpoint_or_model: str,
    frontend_scope: str,
    integration_type: str,
) -> TokenForecastResponse:
    """Return a pre-run token budget forecast based on 4 complexity signals."""
    # Resolve metrics.json path at call time — never at module level
    # __file__ = riia-jun-release/src/rita/api/experience/ops.py
    # .parents[4] = riia-jun-release/
    metrics_path = Path(__file__).parents[4] / "data" / "agent-ops" / "metrics.json"

    if not metrics_path.exists():
        raise HTTPException(status_code=503, detail="metrics.json unavailable")

    with open(metrics_path) as f:
        metrics = json.load(f)

    # Resolve complexity from 4 signals
    signal_map = {
        "files_to_change": {"small": 0.7, "medium": 1.0, "large": 1.5},
        "new_endpoint_or_model": {"none": 0.7, "one": 1.0, "both": 1.5},
        "frontend_scope": {"none": 0.7, "panel": 1.0, "page": 1.5},
        "integration_type": {"additive": 0.7, "extends": 1.0, "cross-cutting": 1.5},
    }
    scores = [
        signal_map["files_to_change"].get(files_to_change, 1.0),
        signal_map["new_endpoint_or_model"].get(new_endpoint_or_model, 1.0),
        signal_map["frontend_scope"].get(frontend_scope, 1.0),
        signal_map["integration_type"].get(integration_type, 1.0),
    ]
    complexity_score = sum(scores) / len(scores)
    if complexity_score <= 0.85:
        complexity = "small"
    elif complexity_score <= 1.25:
        complexity = "medium"
    else:
        complexity = "large"

    # Feature type modifier
    modifiers = {"rita": 1.0, "ops": 0.6, "fno": 0.8, "invest-game": 1.1}
    modifier = modifiers.get(feature_type, 1.0)

    # Per-role averages from metrics.json (fall back to hardcoded historical averages)
    per_role_avgs: dict[str, int] = metrics.get(
        "per_role_avg_tokens",
        {"pm": 7612, "architect": 9975, "engineer": 31112, "qa": 11300, "techwriter": 6650},
    )

    per_role = {
        role: round(avg * complexity_score * modifier)
        for role, avg in per_role_avgs.items()
    }
    total_forecast = sum(per_role.values())

    # basis_runs: how many historical runs exist for this feature_type
    ft_data = metrics.get("token_forecasting", {}).get("by_feature_type", {})
    basis_runs = ft_data.get(feature_type, {}).get("run_count", 0)
    confidence = "±25%" if basis_runs >= 5 else "±40%"

    return TokenForecastResponse(
        complexity=complexity,
        complexity_score=round(complexity_score, 2),
        feature_type=feature_type,
        per_role=per_role,
        total_forecast=total_forecast,
        confidence=confidence,
        basis_runs=basis_runs,
    )


@router.get("/api-metrics", response_model=ApiMetricsResponse)
def get_api_metrics(
    limit: int = Query(default=200, ge=1, le=5000),
    method: Optional[str] = Query(default=None),
    path_prefix: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
) -> ApiMetricsResponse:
    """Return per-endpoint call counts, p50/p95 latency percentiles, and error rates."""
    try:
        repo = ApiCallLogRepository(db)
        rows = repo.aggregate_by_path_method(
            limit=limit, method_filter=method, path_prefix=path_prefix
        )
        items = [ApiMetricsRow(**row) for row in rows]
        return ApiMetricsResponse(items=items)
    except Exception as exc:
        log_event(log, "error", "api_metrics.error", error=str(exc))
        return ApiMetricsResponse(items=[])


# ── GET /api/experience/ops/functional-kpis ──────────────────────────────────

def _zero_response(buckets: list[str], generated_at: str) -> FunctionalKPIsResponse:
    """Return an all-zeros response for the given buckets."""
    n = len(buckets)
    return FunctionalKPIsResponse(
        generated_at=generated_at,
        buckets=buckets,
        series=FunctionalKPIsSeries(
            training_success_rate_pct=[0.0] * n,
            chat_low_confidence_pct=[0.0] * n,
            experience_error_pct=[0.0] * n,
            error_rate_pct=[0.0] * n,
            p95_latency_ms=[0.0] * n,
        ),
    )


def _read_chat_monitor_rows() -> list[dict]:
    """Read all rows from chat_monitor.csv; return [] if file does not exist."""
    try:
        from rita.config import get_settings
        path = os.path.join(get_settings().chat.monitor_dir, "chat_monitor.csv")
        if not os.path.exists(path):
            return []
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except Exception:  # noqa: BLE001
        return []


# ── GET /api/experience/ops/github-deploys ───────────────────────────────────

@router.get("/github-deploys", summary="Recent GitHub Actions deploy runs", tags=["experience:ops"])
def get_github_deploys(limit: int = Query(default=10, ge=1, le=50)) -> dict[str, Any]:
    """Return recent GitHub Actions workflow runs for the production repo."""
    import urllib.request as _req

    pat  = os.environ.get("RITA_GITHUB_PAT", "")
    repo = os.environ.get("RITA_GITHUB_REPO", "san-work-ravionics/riia-jun-release-prod")

    if not pat:
        return {"runs": [], "total_count": 0, "error": "RITA_GITHUB_PAT not configured"}

    url = f"https://api.github.com/repos/{repo}/actions/runs?per_page={limit}"
    try:
        request = _req.Request(url, headers={
            "Authorization": f"token {pat}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        with _req.urlopen(request, timeout=10) as resp:
            data = json.loads(resp.read())

        runs = []
        for r in data.get("workflow_runs", []):
            created_str = r.get("created_at", "")
            updated_str = r.get("updated_at", "")
            duration_sec: Optional[int] = None
            if created_str and updated_str:
                try:
                    c = datetime.fromisoformat(created_str.rstrip("Z") + "+00:00")
                    u = datetime.fromisoformat(updated_str.rstrip("Z") + "+00:00")
                    duration_sec = max(0, int((u - c).total_seconds()))
                except Exception:
                    pass
            commit_msg = r.get("head_commit", {}).get("message", "").split("\n")[0]
            runs.append({
                "run_id":       r.get("id"),
                "status":       r.get("status"),
                "conclusion":   r.get("conclusion"),
                "created_at":   created_str,
                "commit_message": commit_msg,
                "commit_sha":   (r.get("head_sha") or "")[:7],
                "actor":        (r.get("actor") or {}).get("login"),
                "duration_sec": duration_sec,
                "url":          r.get("html_url"),
            })

        log_event(log, "info", "github_deploys.ok", runs=len(runs))
        return {"runs": runs, "total_count": data.get("total_count", 0)}

    except Exception as exc:
        log_event(log, "warning", "github_deploys.error", error=str(exc))
        return {"runs": [], "total_count": 0, "error": str(exc)}


# ── GET /api/experience/ops/aws-alerts ────────────────────────────────────────

@router.get("/aws-alerts", summary="Active AWS CloudWatch alarm states", tags=["experience:ops"])
def get_aws_alerts() -> dict[str, Any]:
    """Return current CloudWatch alarm states as structured alert objects."""
    try:
        import boto3 as _boto3

        region = os.environ.get("AWS_DEFAULT_REGION", "ap-south-1")
        cw = _boto3.client("cloudwatch", region_name=region)
        resp = cw.describe_alarms(MaxRecords=100)

        alerts = []
        for alarm in resp.get("MetricAlarms", []):
            state = alarm.get("StateValue", "OK")
            status   = "active" if state in ("ALARM", "INSUFFICIENT_DATA") else "ok"
            severity = "Critical" if state == "ALARM" else ("Warning" if state == "INSUFFICIENT_DATA" else "OK")
            ts = alarm.get("StateUpdatedTimestamp")
            since = ts.isoformat() if ts and hasattr(ts, "isoformat") else ""
            threshold = alarm.get("Threshold")
            op = alarm.get("ComparisonOperator", "").replace("GreaterThanOrEqualToThreshold", "≥").replace("GreaterThanThreshold", ">").replace("LessThanThreshold", "<").replace("LessThanOrEqualToThreshold", "≤")
            message = alarm.get("AlarmDescription") or f"{alarm.get('MetricName','')} {op} {threshold}"
            alerts.append({
                "status":    status,
                "severity":  severity,
                "rule":      alarm.get("AlarmName", ""),
                "component": alarm.get("MetricName", "EC2"),
                "message":   message,
                "since":     since,
            })

        log_event(log, "info", "aws_alerts.ok", alarms=len(alerts))
        return {"alerts": alerts, "generated_at": datetime.now(timezone.utc).isoformat()}

    except Exception as exc:
        log_event(log, "warning", "aws_alerts.error", error=str(exc))
        return {"alerts": [], "generated_at": datetime.now(timezone.utc).isoformat(), "error": str(exc)}


@router.get("/functional-kpis", response_model=FunctionalKPIsResponse)
def get_functional_kpis(
    hours: int = Query(default=24, ge=1, le=168),
    db: Session = Depends(get_db),
) -> FunctionalKPIsResponse:
    """Return hourly KPI time-series for the last N hours.

    Aggregates training success rate, chat low-confidence rate, experience
    endpoint error rate, overall API error rate, and p95 latency per bucket.
    Read-only — no db.commit() calls.
    """
    now = datetime.now(timezone.utc)
    generated_at = now.isoformat()

    # Build hourly bucket labels (oldest → newest)
    buckets: list[str] = []
    bucket_starts: list[datetime] = []
    for i in range(hours - 1, -1, -1):
        bucket_start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=i)
        buckets.append(bucket_start.strftime("%Y-%m-%dT%H:00"))
        bucket_starts.append(bucket_start)

    try:
        from sqlalchemy.exc import OperationalError

        train_repo = TrainingRunsRepository(db)

        # Fetch all training runs and API call log rows needed
        try:
            all_trains = train_repo.read_all()
        except OperationalError:
            all_trains = []

        try:
            # Fetch rows within the time window (oldest bucket start → now).
            # SQLite stores naive datetimes so compare against naive UTC.
            window_start_naive = bucket_starts[0].replace(tzinfo=None)
            from rita.models.api_call_log import ApiCallLogModel
            api_rows = (
                db.query(ApiCallLogModel)
                .filter(ApiCallLogModel.called_at >= window_start_naive)
                .all()
            )
        except OperationalError:
            api_rows = []

        # Chat monitor rows (CSV-based)
        chat_rows = _read_chat_monitor_rows()

        def _to_aware(dt: Any) -> Any:
            """Convert a naive datetime to UTC-aware; return aware dt unchanged."""
            if dt is None:
                return None
            if getattr(dt, "tzinfo", None) is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt

        # Build per-bucket aggregates
        training_success: list[float] = []
        chat_low_conf: list[float] = []
        experience_error: list[float] = []
        error_rate: list[float] = []
        p95_latency: list[float] = []

        for bucket_start in bucket_starts:
            bucket_end = bucket_start + timedelta(hours=1)

            # ── Training success rate ──────────────────────────────────────
            # Use all training runs whose ended_at falls in this bucket
            bucket_trains = [
                r for r in all_trains
                if r.ended_at is not None
                and bucket_start <= _to_aware(r.ended_at) < bucket_end
            ]
            if bucket_trains:
                completed = sum(1 for r in bucket_trains if r.status in ("complete", "completed"))
                training_success.append(round(completed / len(bucket_trains) * 100, 2))
            else:
                training_success.append(0.0)

            # ── API call log bucketing ─────────────────────────────────────
            bucket_api = [
                r for r in api_rows
                if r.called_at is not None
                and bucket_start <= _to_aware(r.called_at) < bucket_end
            ]

            if bucket_api:
                total = len(bucket_api)
                errors = sum(1 for r in bucket_api if r.status_code is not None and r.status_code >= 400)
                exp_total = sum(1 for r in bucket_api if r.path.startswith("/api/experience"))
                exp_errors = sum(
                    1 for r in bucket_api
                    if r.path.startswith("/api/experience")
                    and r.status_code is not None
                    and r.status_code >= 400
                )
                durations = [r.duration_ms for r in bucket_api if r.duration_ms is not None]
                sorted_d = sorted(durations)
                n = len(sorted_d)
                p95 = sorted_d[min(int(n * 0.95), n - 1)] if n else 0.0

                error_rate.append(round(errors / total * 100, 2))
                experience_error.append(round(exp_errors / exp_total * 100, 2) if exp_total else 0.0)
                p95_latency.append(round(p95, 1))
            else:
                error_rate.append(0.0)
                experience_error.append(0.0)
                p95_latency.append(0.0)

            # ── Chat low-confidence rate ───────────────────────────────────
            bucket_chat = []
            for row in chat_rows:
                ts_str = row.get("timestamp", "")
                if not ts_str:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if bucket_start <= ts < bucket_end:
                        bucket_chat.append(row)
                except (ValueError, TypeError):
                    continue

            if bucket_chat:
                low = sum(1 for r in bucket_chat if r.get("low_confidence") == "1")
                chat_low_conf.append(round(low / len(bucket_chat) * 100, 2))
            else:
                chat_low_conf.append(0.0)

        return FunctionalKPIsResponse(
            generated_at=generated_at,
            buckets=buckets,
            series=FunctionalKPIsSeries(
                training_success_rate_pct=training_success,
                chat_low_confidence_pct=chat_low_conf,
                experience_error_pct=experience_error,
                error_rate_pct=error_rate,
                p95_latency_ms=p95_latency,
            ),
        )

    except Exception as exc:  # noqa: BLE001
        log_event(log, "error", "functional_kpis.error", error=str(exc))
        return _zero_response(buckets, generated_at)
