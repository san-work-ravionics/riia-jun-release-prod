"""Repository for the audit_log table (API and agent action log)."""

from sqlalchemy.orm import Session

from rita.models.audit import AuditLogModel
from rita.repositories.base import SqlRepository
from rita.schemas.audit import AuditLog


class AuditLogRepository(SqlRepository[AuditLog, AuditLogModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, AuditLogModel, AuditLog, "log_id")
