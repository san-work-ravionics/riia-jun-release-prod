"""Repository for the agent_performance table (Feature 32, ADR-002).

record()             — best-effort single insert used by the classifier hook.
summary_for_agents() — read-only KPI aggregation for the dashboard endpoint.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from rita.models.agent_performance import AgentPerformance
from rita.repositories.base import SqlRepository
from rita.schemas.agent_performance import AgentPerformanceSchema


class AgentPerformanceRepository(SqlRepository[AgentPerformanceSchema, AgentPerformance]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, AgentPerformance, AgentPerformanceSchema, "perf_id")

    def record(
        self,
        agent_name: str,
        intent: str,
        recommendation: str | None = None,
        outcome_status: str | None = None,
        training_run_id: str | None = None,
    ) -> None:
        """Insert one performance row. Writes (commits) — used off the request path."""
        row = AgentPerformance(
            perf_id=str(uuid.uuid4()),
            agent_name=agent_name,
            intent=intent,
            recommendation=recommendation,
            outcome_status=outcome_status,
            training_run_id=training_run_id,
        )
        self._db.add(row)
        self._db.commit()

    def summary_for_agents(
        self,
        agent_names: list[str],
        window_days: int = 30,
    ) -> dict[str, dict]:
        """Read-only aggregation per agent. NEVER commits.

        Returns: { agent_name: { invocation_count_30d, outcome_match_rate,
        trend_vs_prior_30d } } for agents that have at least one row.  Agents
        with no rows are simply absent (the endpoint fills defaults).
        """
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(days=window_days)
        prior_start = now - timedelta(days=2 * window_days)

        rows = (
            self._db.query(AgentPerformance)
            .filter(AgentPerformance.agent_name.in_(agent_names))
            .filter(AgentPerformance.created_at >= prior_start)
            .all()
        )

        def _aware(dt: datetime | None) -> datetime | None:
            if dt is None:
                return None
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)

        summary: dict[str, dict] = {}
        for name in agent_names:
            agent_rows = [r for r in rows if r.agent_name == name]
            count_30d = 0
            count_prior = 0
            matches = 0
            non_null_outcomes = 0
            for r in agent_rows:
                created = _aware(r.created_at)
                if created is None:
                    continue
                if created >= window_start:
                    count_30d += 1
                    if r.outcome_status is not None:
                        non_null_outcomes += 1
                        if r.outcome_status == "match":
                            matches += 1
                elif created >= prior_start:
                    count_prior += 1

            if not agent_rows:
                continue

            outcome_match_rate = (
                matches / non_null_outcomes if non_null_outcomes > 0 else None
            )
            trend = (
                (count_30d - count_prior) / count_prior if count_prior > 0 else None
            )
            summary[name] = {
                "invocation_count_30d": count_30d,
                "outcome_match_rate": outcome_match_rate,
                "trend_vs_prior_30d": trend,
            }
        return summary
