"""Pydantic schemas for the F42 Trade Analysis Experience endpoint.

GET /api/v1/experience/fno/trade-analysis/live — today's Kite orders/trades/positions for
the configured option underlyings and expiry months, joined to the NFO instrument master.

Semantics (kept simple on purpose):
  source            "kite" when live Kite data was returned, "fallback" when none was.
  kpis.lots_traded  sum(trade quantity / lot_size) over trades whose lot_size is known;
                    None when no trade has a known lot size.
  kpis.round_trips_today
                    per tradingsymbol, floor(min(total buy qty, total sell qty) / lot_size),
                    summed; symbols without a known lot size are skipped.
  kpis.open_positions   non-FLAT positions in scope (FLAT ones still count in realised_pnl).
  excluded          DISTINCT tradingsymbols left out: non_option (non-NFO / futures),
                    other_underlying (outside the selected underlying), out_of_window (expiry
                    month not in the configured window), unresolved (not in the instrument master).
All nullable numerics render as "—" in the UI; nothing is guessed.
A KPI is None when the leg it derives from failed (orders_* <- orders; trades_count, buy_qty,
sell_qty, lots_traded, round_trips_today <- trades; open_positions, *_pnl <- positions).
excluded.unresolved also holds FINNIFTY/other-index and equity options, because the master
only contains the configured underlyings' CE/PE contracts.
include_closed only filters the positions list, not KPIs or by_expiry.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class TradeFilter(BaseModel):
    underlyings: list[str] = Field(default_factory=list)
    expiry_months: list[int] = Field(default_factory=list)
    underlying: str = "ALL"


class TradeKpis(BaseModel):
    orders_total: Optional[int] = None
    orders_complete: Optional[int] = None
    orders_rejected: Optional[int] = None
    orders_cancelled: Optional[int] = None
    orders_open: Optional[int] = None
    trades_count: Optional[int] = None
    buy_qty: Optional[int] = None
    sell_qty: Optional[int] = None
    lots_traded: Optional[float] = None
    open_positions: Optional[int] = None
    net_pnl: Optional[float] = None
    realised_pnl: Optional[float] = None
    unrealised_pnl: Optional[float] = None
    round_trips_today: Optional[int] = None


class OrderRow(BaseModel):
    order_id: Optional[str] = None
    tradingsymbol: str
    underlying: Optional[str] = None
    expiry: Optional[str] = None
    strike: Optional[float] = None
    option_type: Optional[str] = None
    transaction_type: Optional[str] = None
    status: Optional[str] = None
    product: Optional[str] = None
    order_type: Optional[str] = None
    quantity: Optional[int] = None
    filled_quantity: Optional[int] = None
    pending_quantity: Optional[int] = None
    average_price: Optional[float] = None
    lot_size: Optional[int] = None
    lots: Optional[float] = None
    order_timestamp: Optional[str] = None


class TradeRow(BaseModel):
    trade_id: Optional[str] = None
    order_id: Optional[str] = None
    tradingsymbol: str
    underlying: Optional[str] = None
    expiry: Optional[str] = None
    strike: Optional[float] = None
    option_type: Optional[str] = None
    transaction_type: Optional[str] = None
    quantity: Optional[int] = None
    average_price: Optional[float] = None
    lot_size: Optional[int] = None
    lots: Optional[float] = None
    fill_timestamp: Optional[str] = None


class PositionRow(BaseModel):
    tradingsymbol: str
    underlying: Optional[str] = None
    expiry: Optional[str] = None
    strike: Optional[float] = None
    option_type: Optional[str] = None
    product: Optional[str] = None
    net_quantity: int = 0
    lot_size: Optional[int] = None
    lots: Optional[float] = None
    side: Literal["LONG", "SHORT", "FLAT"] = "FLAT"
    average_price: Optional[float] = None
    last_price: Optional[float] = None
    pnl: Optional[float] = None
    m2m: Optional[float] = None
    realised: Optional[float] = None
    unrealised: Optional[float] = None


class ExpirySummary(BaseModel):
    underlying: str
    expiry: str
    label: str
    trades: int = 0
    orders: int = 0
    net_quantity: int = 0
    open_legs: int = 0
    pnl: Optional[float] = None


class SnapshotInfo(BaseModel):
    available: bool = False
    days_captured: int = 0
    first_date: Optional[str] = None
    last_date: Optional[str] = None
    total_trades: int = 0


class ExcludedCounts(BaseModel):
    non_option: int = 0
    other_underlying: int = 0
    out_of_window: int = 0
    unresolved: int = 0


class TradeAnalysisLiveResponse(BaseModel):
    available: bool
    source: Literal["kite", "fallback"]
    reason: Optional[
        Literal["middleware_unreachable", "token_expired", "upstream_error", "bad_response"]
    ] = None
    message: Optional[str] = None
    fetched_at: Optional[str] = None
    as_of_date: Optional[str] = None
    filter: TradeFilter = Field(default_factory=TradeFilter)
    history_note: str = ""
    kpis: Optional[TradeKpis] = None
    orders: list[OrderRow] = Field(default_factory=list)
    trades: list[TradeRow] = Field(default_factory=list)
    positions: list[PositionRow] = Field(default_factory=list)
    by_expiry: list[ExpirySummary] = Field(default_factory=list)
    snapshot: SnapshotInfo = Field(default_factory=SnapshotInfo)
    excluded: ExcludedCounts = Field(default_factory=ExcludedCounts)
