"""System router for model health / drift checks.

ADR-001 Tier 1: single-domain health check, no UI composition.
URLs preserved from observability.py (Option A migration).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from rita.database import get_db

router = APIRouter(prefix="/api/v1", tags=["system:drift"])


@router.get("/drift", summary="System health and drift checks")
def drift(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Return a structured system health report via DriftDetector.

    Shape:
    {
      "summary": { "overall": "ok" | "warn" | "alert", "checks": {...} },
      "checks": {
        "sharpe_drift":       { "status": "ok", "message": "..." },
        "return_degradation": { "status": "ok", "message": "..." },
        "data_freshness":     { "status": "ok", "days_old": 2 },
        "pipeline_health":    { "status": "ok", "message": "..." },
        "constraint_breach":  { "status": "ok", "message": "..." }
      }
    }
    """
    from rita.core.drift_detector import DriftDetector
    detector = DriftDetector(db)
    report = detector.full_report()
    summary = detector.health_summary(report)
    return {"summary": summary, "checks": report}
