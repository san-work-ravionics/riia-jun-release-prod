"""Repository for user_retirement_plans (F43 Phase 1).

ADR-002 repository pattern: no db.commit() here — RetirementPlanService commits.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from rita.models.user_retirement_plan import UserRetirementPlanModel


class UserRetirementPlanRepo:
    def __init__(self, db: Session) -> None:
        self._db = db

    def find_by_user_id(self, user_id: str) -> UserRetirementPlanModel | None:
        """Return the user's saved plan row, or None."""
        return (
            self._db.query(UserRetirementPlanModel)
            .filter(UserRetirementPlanModel.user_id == user_id)
            .first()
        )

    def upsert(
        self, user_id: str, inputs: dict[str, Any], schema_version: int, location: str,
    ) -> UserRetirementPlanModel:
        """Insert or replace the user's single plan row.  Flushes; caller commits."""
        row = self.find_by_user_id(user_id)
        if row is None:
            row = UserRetirementPlanModel(
                user_id=user_id, inputs=inputs, schema_version=schema_version, location=location,
            )
            self._db.add(row)
        else:
            row.inputs = inputs
            row.schema_version = schema_version
            row.location = location
            row.updated_at = func.now()
        self._db.flush()  # SessionLocal has autoflush off; make the row visible, no commit
        return row
