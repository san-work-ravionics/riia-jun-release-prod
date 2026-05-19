"""Pydantic schemas for the snapshots table (manoeuvre position snapshot)."""
from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict


class SnapshotBase(BaseModel):
    date: date
    underlying: Literal["NIFTY", "BANKNIFTY", "ASML", "NVIDIA"]
    month: str                               # e.g. APR, MAY
    group_id: str                            # e.g. anchor, hedge1
    group_name: str                          # e.g. Monthly Anchor
    view: Literal["bull", "bear", "neutral"]
    lot_key: str                             # e.g. NIFTY26APR22700CE_L1
    instrument: str
    option_type: Literal["CE", "PE"]
    side: Literal["Long", "Short"]
    lot_size: int                            # from config — NIFTY=75, BANKNIFTY=30
    avg_price: float
    pnl_now: float
    pnl_sl: float                            # P&L at stop-loss level
    pnl_target: float                        # P&L at target level


class SnapshotCreate(SnapshotBase):
    pass


class Snapshot(SnapshotBase):
    model_config = ConfigDict(from_attributes=True)

    snapshot_id: str
    recorded_at: datetime
