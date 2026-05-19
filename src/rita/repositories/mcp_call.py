"""Repository for the mcp_calls table."""
from __future__ import annotations

from sqlalchemy import desc
from sqlalchemy.orm import Session

from rita.models.mcp_call import MCPCallModel


class MCPCallRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create(self, record: MCPCallModel) -> MCPCallModel:
        self._db.add(record)
        self._db.commit()
        self._db.refresh(record)
        return record

    def get_recent(self, limit: int = 100) -> list[MCPCallModel]:
        return (
            self._db.query(MCPCallModel)
            .order_by(desc(MCPCallModel.timestamp))
            .limit(limit)
            .all()
        )
