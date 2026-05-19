"""Repository for agent_build_runs and agent_build_agents tables."""
from typing import Optional

from sqlalchemy.orm import Session

from rita.models.agent_builds import AgentBuildAgentModel, AgentBuildRunModel


class AgentBuildRepository:
    """Repository for agent build pipeline run data."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def list_with_agents(
        self,
        limit: int = 20,
        app_filter: Optional[str] = None,
    ) -> list[AgentBuildRunModel]:
        """Return run rows ordered by run_id descending, optionally filtered by app."""
        q = self._db.query(AgentBuildRunModel)
        if app_filter is not None:
            q = q.filter(AgentBuildRunModel.app == app_filter)
        return q.order_by(AgentBuildRunModel.run_id.desc()).limit(limit).all()

    def list_all_agents(self) -> list[AgentBuildAgentModel]:
        """Return all agent rows."""
        return self._db.query(AgentBuildAgentModel).all()

    def upsert_run(self, run_data: dict) -> AgentBuildRunModel:
        """Insert or update a run record by run_id."""
        existing = self._db.query(AgentBuildRunModel).filter(
            AgentBuildRunModel.run_id == run_data["run_id"]
        ).first()
        if existing:
            for key, value in run_data.items():
                if key != "recorded_at" and hasattr(existing, key):
                    setattr(existing, key, value)
            self._db.commit()
            self._db.refresh(existing)
            return existing
        else:
            obj = AgentBuildRunModel(
                **{k: v for k, v in run_data.items() if hasattr(AgentBuildRunModel, k)}
            )
            self._db.add(obj)
            self._db.commit()
            self._db.refresh(obj)
            return obj

    def upsert_agents(
        self,
        run_id: str,
        agents: list[dict],
        actual_tokens_total: Optional[int] = None,
    ) -> list[str]:
        """Insert or update agent records for a run."""
        results = []
        for agent in agents:
            role = agent.get("role", "unknown")
            agent_id = f"{run_id}-{role}"

            # Resolve actual_tokens: dict["total_tokens"] -> int, or int directly
            raw_actual = agent.get("actual_tokens")
            if isinstance(raw_actual, dict):
                actual_int = raw_actual.get("total_tokens")
            elif isinstance(raw_actual, int):
                actual_int = raw_actual
            else:
                actual_int = actual_tokens_total

            existing = self._db.query(AgentBuildAgentModel).filter(
                AgentBuildAgentModel.agent_id == agent_id
            ).first()
            if existing:
                existing.status = agent.get("status", existing.status)
                existing.token_estimate = agent.get("token_estimate", existing.token_estimate)
                existing.actual_tokens_total = actual_int
                existing.adherence_score = agent.get("adherence_score", existing.adherence_score)
            else:
                obj = AgentBuildAgentModel(
                    agent_id=agent_id,
                    run_id=run_id,
                    role=role,
                    status=agent.get("status"),
                    token_estimate=agent.get("token_estimate"),
                    actual_tokens_total=actual_int,
                    adherence_score=agent.get("adherence_score"),
                )
                self._db.add(obj)
            results.append(role)
        self._db.commit()
        return results
