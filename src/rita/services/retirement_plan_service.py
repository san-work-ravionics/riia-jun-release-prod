"""RetirementPlanService — F43 "What I Need" calculation + per-user plan persistence.

- ``calculate(inputs, start_year=None)`` — pure: validate (mock messages) → core.calc.
  Raises ``PlanValidationError`` (a ValueError) with the mock's string.
- ``RetirementPlanService(db).load(user_id)`` — read-only: the saved plan, or the
  location preset defaults from config when there is no user / no row / a corrupt row.
- ``RetirementPlanService(db).save(user_id, inputs)`` — validate, upsert, append a history
  row with the key figures, single commit (rollback on any failure).  Invalid plans are
  never stored.
- ``RetirementPlanService(db).load_with_result(user_id)`` — read-only: ``load`` plus the
  result calculated from those inputs (what later screens read for the user).
- ``RetirementPlanService(db).history(user_id)`` / ``.history_entry(user_id, history_id)`` —
  read-only: the user's saved plans, newest first; one entry with its result recalculated.

ADR-002: data access only through ``UserRetirementPlanRepo``.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import structlog
from pydantic import ValidationError
from sqlalchemy.orm import Session

from rita.config import get_settings
from rita.core.retirement_plan import calc, to_params, validate_plan
from rita.models.user_retirement_plan_history import UserRetirementPlanHistoryModel
from rita.repositories.user_retirement_plan import UserRetirementPlanRepo
from rita.repositories.user_retirement_plan_history import UserRetirementPlanHistoryRepo
from rita.schemas.retirement_plan import (
    RetirementPlanHistoryDetail,
    RetirementPlanHistoryItem,
    RetirementPlanHistoryOut,
    RetirementPlanInputs,
    RetirementPlanOut,
    RetirementPlanResult,
    RetirementPlanWithResult,
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
        self._history = UserRetirementPlanHistoryRepo(db)

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

    def load_with_result(self, user_id: str | None) -> RetirementPlanWithResult:
        """The user's plan (or preset defaults) with its result calculated now. Never writes."""
        plan = self.load(user_id)
        try:
            result = calculate(plan.inputs)
        except PlanValidationError as exc:
            # A plan saved under older, looser checks: fall back like a corrupt row.
            log.warning("retirement_plan.saved_plan_invalid", user_id=user_id, error=str(exc))
            plan = default_plan()
            result = calculate(plan.inputs)
        return RetirementPlanWithResult(**plan.model_dump(), result=result)

    def history(self, user_id: str, limit: int = 50) -> RetirementPlanHistoryOut:
        """The user's saved plans, newest first (key figures only). Never writes."""
        rows = self._history.list_by_user_id(user_id, limit=limit)
        return RetirementPlanHistoryOut(
            items=[RetirementPlanHistoryItem.model_validate(r, from_attributes=True) for r in rows],
        )

    def history_entry(self, user_id: str, history_id: str) -> RetirementPlanHistoryDetail | None:
        """One of the user's saved plans with its result recalculated; None if not theirs."""
        row = self._history.find_for_user(user_id, history_id)
        if row is None:
            return None
        try:
            if row.schema_version != SCHEMA_VERSION:
                raise ValueError(f"unsupported schema_version {row.schema_version}")
            inputs = RetirementPlanInputs.model_validate(row.inputs)
            result = calculate(inputs)
        except (ValidationError, ValueError, TypeError) as exc:  # PlanValidationError is a ValueError
            log.warning("retirement_plan.history_entry_unreadable", user_id=user_id,
                        history_id=history_id, error=str(exc))
            return None
        item = RetirementPlanHistoryItem.model_validate(row, from_attributes=True)
        return RetirementPlanHistoryDetail(**item.model_dump(), inputs=inputs, result=result)

    def save(self, user_id: str, inputs: RetirementPlanInputs) -> RetirementPlanOut:
        """Validate, upsert the user's plan and append it to the history; one commit."""
        result = calculate(inputs)  # validates (PlanValidationError) and gives the key figures
        at_ret = result.at_ret
        if at_ret.need is None or at_ret.monthly is None:  # core.at() always fills the retirement cell
            raise RuntimeError("retirement cell missing need/monthly")
        key, currency, _ = _preset()
        dumped = inputs.model_dump(mode="json", by_alias=True)
        try:
            row = self._plans.upsert(user_id, dumped, SCHEMA_VERSION, key)
            self._history.append(UserRetirementPlanHistoryModel(
                history_id=str(uuid.uuid4()),
                user_id=user_id,
                saved_at=datetime.now(timezone.utc),
                inputs=dumped,
                location=key,
                retire_age=at_ret.age,
                plan_until=int(inputs.end),
                need_at_retire=at_ret.need,
                monthly_at_retire=at_ret.monthly,
                corpus_at_retire=result.value,
                sustainable_until=result.portfolio.run_out,
                corpus_out_age=result.portfolio.corpus_out,
                schema_version=SCHEMA_VERSION,
                app_version=get_settings().app.version,
            ))
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise
        self._db.refresh(row)
        log.info("retirement_plan.saved", user_id=user_id)
        return RetirementPlanOut(
            saved=True, updated_at=row.updated_at, location=key, currency=currency, inputs=inputs,
        )
