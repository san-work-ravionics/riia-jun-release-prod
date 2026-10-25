"""Repository for the mcp_calls table."""
from __future__ import annotations

from sqlalchemy import desc, or_
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
        """All rows, newest first (internal use — not filtered by user)."""
        return (
            self._db.query(MCPCallModel)
            .order_by(desc(MCPCallModel.timestamp))
            .limit(limit)
            .all()
        )

    def get_recent_visible_to(self, user_id: str, *, all_users: bool, limit: int = 100) -> list[MCPCallModel]:
        """Newest-first rows a viewer may see (F44 P1 review): ``all_users`` (ops) → every row;
        otherwise only rows with no user (stdio / anonymous) or the viewer's own rows."""
        q = self._db.query(MCPCallModel)
        if not all_users:
            q = q.filter(or_(MCPCallModel.user_id.is_(None), MCPCallModel.user_id == user_id))
        return q.order_by(desc(MCPCallModel.timestamp)).limit(limit).all()

    def get_recent_for_viewer(
        self, user_id: str | None, *, all_users: bool, limit: int = 100,
    ) -> list[tuple[MCPCallModel, bool]]:
        """Newest-first rows for the mcp-calls view (F44 P1 review pass 2, user option B), each paired
        with ``full`` — whether the viewer may see ``user_id`` / ``args_summary`` / ``result_summary``.

        - ``all_users`` (ops)                → every row full;
        - signed in (``user_id`` given)      → own rows and rows with no user full, others anonymised;
        - anonymous (``user_id`` is None)    → every row anonymised.
        """
        rows = self.get_recent(limit)
        return [
            (r, all_users or (user_id is not None and (r.user_id is None or r.user_id == user_id)))
            for r in rows
        ]
