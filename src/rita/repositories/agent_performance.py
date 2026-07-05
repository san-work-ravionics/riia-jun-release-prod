"""Repository for the agent_performance table (Feature 32, ADR-002).

record()             — best-effort single insert used by the classifier hook.
summary_for_agents() — read-only KPI aggregation for the dashboard endpoint.
pending_outcomes()   — rows awaiting outcome evaluation (Phase 4 backfill).
set_outcome()        — write a realized outcome_status onto one row.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from rita.models.agent_performance import AgentPerformance
from rita.repositories.base import SqlRepository
from rita.schemas.agent_performance import AgentPerformanceSchema

# Outcome verdicts that count as a genuine evaluation (denominator for match-rate).
# "not_evaluable" is excluded — those rows have no price-truth.
EVALUATED_OUTCOMES = ("match", "miss", "neutral")


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


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

    def pending_outcomes(self, limit: int | None = None) -> list[AgentPerformance]:
        """Rows whose outcome has not been evaluated yet (outcome_status IS NULL).

        Read-only. The evaluator decides per row whether it is now mature; rows
        that are still immature simply stay null and resurface next run.
        """
        q = (
            self._db.query(AgentPerformance)
            .filter(AgentPerformance.outcome_status.is_(None))
            .order_by(AgentPerformance.created_at.asc())
        )
        if limit is not None:
            q = q.limit(limit)
        return q.all()

    def set_outcome(self, perf_id: str, outcome_status: str) -> bool:
        """Write a realized outcome onto one row. Commits. Returns True if updated."""
        row = (
            self._db.query(AgentPerformance)
            .filter(AgentPerformance.perf_id == perf_id)
            .one_or_none()
        )
        if row is None:
            return False
        row.outcome_status = outcome_status
        self._db.commit()
        return True

    def outcome_match_windows(
        self,
        agent_name: str,
        window_days: int = 30,
    ) -> tuple[float | None, int, float | None, int]:
        """Outcome-match rate for one agent: current window vs the prior window.

        Returns (current_rate, current_n, prior_rate, prior_n). Rate is None when
        that window has no genuine verdicts. Only EVALUATED_OUTCOMES count (a
        not_evaluable / NULL row is ignored). Read-only — drives the retrain trigger.
        """
        now = datetime.now(timezone.utc)
        cur_start = now - timedelta(days=window_days)
        prior_start = now - timedelta(days=2 * window_days)

        rows = (
            self._db.query(AgentPerformance)
            .filter(AgentPerformance.agent_name == agent_name)
            .filter(AgentPerformance.created_at >= prior_start)
            .all()
        )

        cur_m = cur_n = pri_m = pri_n = 0
        for r in rows:
            created = _as_utc(r.created_at)
            if created is None or r.outcome_status not in EVALUATED_OUTCOMES:
                continue
            if created >= cur_start:
                cur_n += 1
                cur_m += 1 if r.outcome_status == "match" else 0
            elif created >= prior_start:
                pri_n += 1
                pri_m += 1 if r.outcome_status == "match" else 0

        cur_rate = cur_m / cur_n if cur_n else None
        pri_rate = pri_m / pri_n if pri_n else None
        return cur_rate, cur_n, pri_rate, pri_n

    def scored_rows_windows(
        self,
        agent_name: str,
        window_days: int = 30,
    ) -> tuple[list[AgentPerformance], list[AgentPerformance]]:
        """Evaluated rows (outcome_status set) for an agent, split current vs prior.

        Returns (current_rows, prior_rows). Used by the risk-adjusted retrain
        trigger, which recomputes each row's advised return from price. Read-only.
        """
        now = datetime.now(timezone.utc)
        cur_start = now - timedelta(days=window_days)
        prior_start = now - timedelta(days=2 * window_days)

        rows = (
            self._db.query(AgentPerformance)
            .filter(AgentPerformance.agent_name == agent_name)
            .filter(AgentPerformance.created_at >= prior_start)
            .filter(AgentPerformance.outcome_status.in_(EVALUATED_OUTCOMES))
            .all()
        )
        current, prior = [], []
        for r in rows:
            created = _as_utc(r.created_at)
            if created is None:
                continue
            if created >= cur_start:
                current.append(r)
            elif created >= prior_start:
                prior.append(r)
        return current, prior

    def timeline_buckets(
        self,
        start: datetime,
        end: datetime,
        bucket_days: int = 7,
    ) -> list[dict]:
        """Bucketed team activity over [start, end] for the performance-over-period plot.

        Each bucket: invocations, evaluated count, matches, and match_rate (None when
        no genuine verdicts in the bucket). Read-only. Empty buckets are included so
        the timeline has no gaps.
        """
        rows = (
            self._db.query(AgentPerformance)
            .filter(AgentPerformance.created_at >= start)
            .filter(AgentPerformance.created_at <= end)
            .all()
        )

        n_buckets = max(1, ((end - start).days // bucket_days) + 1)
        agg = [{"invocations": 0, "evaluated": 0, "matches": 0} for _ in range(n_buckets)]
        for r in rows:
            created = _as_utc(r.created_at)
            if created is None:
                continue
            idx = (created - start).days // bucket_days
            if idx < 0 or idx >= n_buckets:
                continue
            agg[idx]["invocations"] += 1
            if r.outcome_status in EVALUATED_OUTCOMES:
                agg[idx]["evaluated"] += 1
                if r.outcome_status == "match":
                    agg[idx]["matches"] += 1

        out: list[dict] = []
        for i, b in enumerate(agg):
            bucket_start = (start + timedelta(days=i * bucket_days)).date().isoformat()
            match_rate = b["matches"] / b["evaluated"] if b["evaluated"] else None
            out.append({"bucket": bucket_start, **b, "match_rate": match_rate})
        return out

    def scored_rows_in_range(
        self,
        start: datetime,
        end: datetime,
    ) -> list[AgentPerformance]:
        """Evaluated rows (outcome_status set) within [start, end], for advised-return
        analytics (e.g. the timeline Sortino). Read-only, chronological."""
        return (
            self._db.query(AgentPerformance)
            .filter(AgentPerformance.created_at >= start)
            .filter(AgentPerformance.created_at <= end)
            .filter(AgentPerformance.outcome_status.in_(EVALUATED_OUTCOMES))
            .order_by(AgentPerformance.created_at.asc())
            .all()
        )

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
                    # Only genuine verdicts (match/miss/neutral) count toward the
                    # rate; "not_evaluable" and NULL are excluded from the denominator.
                    if r.outcome_status in EVALUATED_OUTCOMES:
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
