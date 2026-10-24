"""RetirementPlanService — F43 "What I Need" calculation + per-user plan persistence.

- ``calculate(inputs, start_year=None)`` — pure: validate (mock messages) → core.calc.
  Raises ``PlanValidationError`` (a ValueError) with the mock's string.
- ``RetirementPlanService(db).load(user_id)`` — read-only: the saved plan, or the
  location preset defaults from config when there is no user / no row / a corrupt row.
- ``RetirementPlanService(db).save(user_id, inputs)`` — validate, upsert, single commit
  (rollback on any failure).  Invalid plans are never stored.

ADR-002: data access only through ``UserRetirementPlanRepo``.
"""
from __future__ import annotations

from datetime import date

import structlog
from pydantic import ValidationError
from sqlalchemy.orm import Session

from rita.config import get_settings
from rita.core.retirement_plan import calc, to_params, validate_plan
from rita.repositories.user_retirement_plan import UserRetirementPlanRepo
from rita.schemas.retirement_plan import (
    RetirementPlanInputs,
    RetirementPlanOut,
    RetirementPlanResult,
)

log = structlog.get_logger(__name__)

SCHEMA_VERSION = 1


class PlanValidationError(ValueError):
    """The plan inputs fail a mock validation check — routes map this to HTTP 422."""


def calculate(inputs: RetirementPlanInputs, start_year: int | None = None) -> RetirementPlanResult:
    """Validate and calculate. ``start_year`` defaults to the server's current year."""
    raw = inputs.model_dump()
    err = validate_plan(raw)
    if err is not None:
        raise PlanValidationError(err)
    year = start_year if start_year is not None else date.today().year
    result = calc(to_params(raw), year)
    return RetirementPlanResult.model_validate(result, from_attributes=True)


def _preset(location: str | None = None) -> tuple[str, str, RetirementPlanInputs]:
    cfg = get_settings().retirement_plan
    key = location if location in cfg.locations else cfg.default_location
    preset = cfg.locations[key]
    return key, preset.currency, RetirementPlanInputs.model_validate(preset.defaults)


def default_plan() -> RetirementPlanOut:
    """Preset defaults for the default location, ``saved=False``."""
    key, currency, inputs = _preset()
    return RetirementPlanOut(saved=False, updated_at=None, location=key, currency=currency, inputs=inputs)


class RetirementPlanService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._plans = UserRetirementPlanRepo(db)

    def load(self, user_id: str | None) -> RetirementPlanOut:
        """Saved plan for the user, else preset defaults. Never writes."""
        if user_id is None:
            return default_plan()
        row = self._plans.find_by_user_id(user_id)
        if row is None:
            return default_plan()
        try:
            if row.schema_version != SCHEMA_VERSION:
                raise ValueError(f"unsupported schema_version {row.schema_version}")
            inputs = RetirementPlanInputs.model_validate(row.inputs)
            key, currency, _ = _preset(row.location)
        except (ValidationError, ValueError, TypeError) as exc:
            log.warning("retirement_plan.saved_plan_unreadable", user_id=user_id, error=str(exc))
            return default_plan()
        return RetirementPlanOut(
            saved=True, updated_at=row.updated_at, location=key, currency=currency, inputs=inputs,
        )

    def save(self, user_id: str, inputs: RetirementPlanInputs) -> RetirementPlanOut:
        """Validate and upsert the user's plan; one commit."""
        err = validate_plan(inputs.model_dump())
        if err is not None:
            raise PlanValidationError(err)
        key, currency, _ = _preset()
        try:
            row = self._plans.upsert(
                user_id, inputs.model_dump(mode="json", by_alias=True), SCHEMA_VERSION, key,
            )
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise
        self._db.refresh(row)
        log.info("retirement_plan.saved", user_id=user_id)
        return RetirementPlanOut(
            saved=True, updated_at=row.updated_at, location=key, currency=currency, inputs=inputs,
        )
