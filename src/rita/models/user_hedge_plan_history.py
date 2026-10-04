"""ORM model for user_hedge_plan_history table (F40 Phase 2).

Append-only archive: one row per hedge-plan PUT (explicit save or autosave).
Rows are never updated or deleted by the application.  Used for later analysis
of hedge performance (what was hedged, with which strategy, at what spot/value).

Fields
------
history_id      PK, uuid4 string
key_id          FK -> user_portfolio_keys.key_id (indexed with saved_at)
user_id         Owner user id (no FK: the dev user is synthetic).  May be an email — PII-class.
saved_at        Server timestamp of the save
trigger         "explicit" | "autosave"
source          "workflow" | "overview"
last_step       Workflow step stored on the plan at save time (nullable)
scenario_tab    Active scenario tab
coverage        Coverage slider value 0-100
duration        Always "1y"
hedged_ids      JSON list of hedged instrument ids
selections      JSON {instrument_id: "put_buy"|"call_sell"} or null
instruments     JSON list of per-instrument snapshot dicts (server market block + client block)
portfolio       JSON {total_value_eur, cash_eur, n_holdings}
margin          JSON client-supplied margin block or null
schema_version  Row schema version (1)
app_version     Application version at save time
"""
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String

from rita.database import Base


class UserHedgePlanHistoryModel(Base):
    __tablename__ = "user_hedge_plan_history"

    history_id = Column(String, primary_key=True)
    key_id = Column(String, ForeignKey("user_portfolio_keys.key_id"), nullable=False)
    user_id = Column(String, nullable=False, index=True)
    saved_at = Column(DateTime(timezone=True), nullable=False)
    trigger = Column(String, nullable=False)
    source = Column(String, nullable=False)
    last_step = Column(String, nullable=True)
    scenario_tab = Column(String, nullable=False)
    coverage = Column(Integer, nullable=False)
    duration = Column(String, nullable=False, default="1y")
    hedged_ids = Column(JSON, nullable=False, default=list)
    selections = Column(JSON, nullable=True)
    instruments = Column(JSON, nullable=False, default=list)
    portfolio = Column(JSON, nullable=False, default=dict)
    margin = Column(JSON, nullable=True)
    schema_version = Column(Integer, nullable=False, default=1)
    app_version = Column(String, nullable=False, default="")

    __table_args__ = (
        Index("ix_user_hedge_plan_history_key_saved", "key_id", "saved_at"),
    )
