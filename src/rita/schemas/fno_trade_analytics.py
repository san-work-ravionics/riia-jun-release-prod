"""Pydantic contracts for the F42 Phase 3 Trade Analysis analytics (Experience GETs).

Every response carries the same envelope (available / reason / filter / quality / tags /
definition / assumptions); each sub-analysis block carries its own ``definition`` and
``assumptions``.  Dates are ISO strings.  Numbers are null when not computable.
PERSONAL DATA: these payloads are built from the caller's own rows only.
"""
from __future__ import annotations

from typing import Optional, Union

from pydantic import BaseModel, Field

Num = Optional[float]
Val = Union[float, int, str, None]


class Info(BaseModel):
    definition: str = ""
    assumptions: list[str] = Field(default_factory=list)


# ── envelope ──────────────────────────────────────────────────────────────────


class AnalyticsFilter(BaseModel):
    underlying: str = "ALL"
    expiry_months: list[int] = Field(default_factory=list)
    expiry_year: int = 0
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    include_expiry_estimate: bool = True


class Quality(BaseModel):
    fills_in_scope: int = 0
    unparsed_excluded: int = 0
    timestamp_coverage_pct: Num = None
    spot_days_missing: Optional[int] = None
    spot_last_date: Optional[str] = None
    ledger_gap_days: Optional[int] = None
    lots_coverage_pct: Num = None
    expiry_estimated_lots: int = 0
    expiry_unknown_lots: int = 0


class Tags(BaseModel):
    measured: list[str] = Field(default_factory=list)
    estimated: list[str] = Field(default_factory=list)


class AnalyticsEnvelope(BaseModel):
    available: bool = False
    reason: Optional[str] = None
    message: Optional[str] = None
    as_of: Optional[str] = None
    filter: AnalyticsFilter = Field(default_factory=AnalyticsFilter)
    definition: str = ""
    assumptions: list[str] = Field(default_factory=list)
    quality: Quality = Field(default_factory=Quality)
    tags: Tags = Field(default_factory=Tags)


# ── foundation ────────────────────────────────────────────────────────────────


class ReconRow(BaseModel):
    symbol: str
    underlying: Optional[str] = None
    expiry_ym: Optional[str] = None
    fifo_measured: Num = None
    fifo_expiry_estimate: Num = None
    sheet_realised: Num = None
    gap_measured: Num = None
    gap_with_estimate: Num = None
    within_tolerance: bool = False
    within_tolerance_with_estimate: bool = False
    fifo_open_qty: int = 0
    sheet_open_qty: Optional[int] = None
    intrinsic_px: Num = None
    sheet_implied_px: Num = None
    causes: list[str] = Field(default_factory=list)


class ReconTotals(BaseModel):
    symbols: int = 0
    n_symbols_ok: int = 0
    n_symbols_gap: int = 0
    fifo_measured: Num = None
    fifo_expiry_estimate: Num = None
    sheet_realised: Num = None
    gap_measured: Num = None
    gap_with_estimate: Num = None
    expiry_estimate_explains: Num = None
    sheet_lines_overlap_dropped: int = 0
    pre_history_symbols: int = 0


class ReconBlock(Info):
    tolerance_inr: float = 0.0
    rows: list[ReconRow] = Field(default_factory=list)
    rows_total: int = 0
    totals: ReconTotals = Field(default_factory=ReconTotals)


class PeriodRange(BaseModel):
    from_date: Optional[str] = None
    to_date: Optional[str] = None


class CoverageBlock(BaseModel):
    first_fill_date: Optional[str] = None
    last_fill_date: Optional[str] = None
    ledger_first: Optional[str] = None
    ledger_last: Optional[str] = None
    pnl_periods: list[PeriodRange] = Field(default_factory=list)


class OpenLotRow(BaseModel):
    symbol: str
    side: str
    qty: int
    avg_entry: Num = None
    open_date: str
    expiry: Optional[str] = None
    expired: bool = False
    expiry_unknown: bool = False
    settlement_unpriced: bool = False
    est_settled: bool = False
    lots: Num = None
    lots_basis: str = "unknown"


class FifoTotals(BaseModel):
    closed_trades: int = 0
    measured_pnl: Num = None
    estimated_pnl: Num = None


class FoundationResponse(AnalyticsEnvelope):
    reconciliation: Optional[ReconBlock] = None
    coverage: Optional[CoverageBlock] = None
    open_lots: list[OpenLotRow] = Field(default_factory=list)
    fifo_totals: Optional[FifoTotals] = None


# ── overtrading ───────────────────────────────────────────────────────────────


class FillsPerDay(BaseModel):
    mean: Num = None
    median: Num = None
    p90: Num = None
    max: Optional[int] = None


class ActivityBlock(Info):
    fills_total: int = 0
    orders_total: int = 0
    active_days: int = 0
    market_days: Optional[int] = None
    fills_per_day: FillsPerDay = Field(default_factory=FillsPerDay)


class WeeklyRow(BaseModel):
    week: str
    fills: int = 0
    active_days: int = 0
    closed_trades: int = 0


class GroupRow(BaseModel):
    key: str
    fills: int = 0
    closed_trades: int = 0
    win_rate: Num = None
    pnl: Num = None


class Bucket(BaseModel):
    label: str
    count: int = 0


class HoldingBlock(Info):
    available: bool = False
    reason: Optional[str] = None
    median_minutes: Num = None
    p25: Num = None
    p75: Num = None
    p90: Num = None
    buckets: list[Bucket] = Field(default_factory=list)
    median_days_multiday: Num = None


class ChurnBlock(Info):
    churn_qty_pct: Num = None
    churn_count_pct: Num = None
    churn_pnl: Num = None
    same_day_trades: int = 0


class BurstRow(BaseModel):
    date: str
    start: Optional[str] = None
    fills: int = 0
    symbols_count: int = 0
    pnl: Num = None


class Reentry(BaseModel):
    count: Optional[int] = None
    pnl: Num = None


class BurstBlock(Info):
    available: bool = False
    reason: Optional[str] = None
    count: Optional[int] = None
    top: list[BurstRow] = Field(default_factory=list)
    reentries_after_loss: Reentry = Field(default_factory=Reentry)


class ChargesBlock(Info):
    available: bool = False
    reason: Optional[str] = None
    total_sheet: Num = None
    est_window: Num = None
    pct_of_gross: Num = None
    per_closed_trade: Num = None
    breakeven_gross_per_trade: Num = None
    breakeven_trades_needed: Optional[int] = None
    estimated: bool = True
    net_gross_negative: bool = False


class WLGroup(BaseModel):
    key: str
    n: int = 0
    win_rate: Num = None
    pnl: Num = None


class MeasuredOnly(BaseModel):
    n: int = 0
    win_rate: Num = None
    expectancy: Num = None
    pnl: Num = None


class WinLossBlock(Info):
    n: int = 0
    wins: int = 0
    losses: int = 0
    scratch: int = 0
    win_rate: Num = None
    avg_win: Num = None
    avg_loss: Num = None
    payoff: Num = None
    expectancy: Num = None
    profit_factor: Num = None
    breakeven_win_rate: Num = None
    largest_win: Num = None
    largest_loss: Num = None
    max_loss_streak: int = 0
    pnl: Num = None
    by_side: list[WLGroup] = Field(default_factory=list)
    by_underlying: list[WLGroup] = Field(default_factory=list)
    measured_only: MeasuredOnly = Field(default_factory=MeasuredOnly)


class OvertradingResponse(AnalyticsEnvelope):
    activity: Optional[ActivityBlock] = None
    weekly: list[WeeklyRow] = Field(default_factory=list)
    by_expiry: list[GroupRow] = Field(default_factory=list)
    by_underlying: list[GroupRow] = Field(default_factory=list)
    holding: Optional[HoldingBlock] = None
    churn: Optional[ChurnBlock] = None
    bursts: Optional[BurstBlock] = None
    charges: Optional[ChargesBlock] = None
    winloss: Optional[WinLossBlock] = None


# ── build-up ──────────────────────────────────────────────────────────────────


class TimelineRow(BaseModel):
    underlying: str
    expiry_ym: str
    date: str
    long_units: int = 0
    short_units: int = 0
    opened_units: int = 0
    scale_in_units: int = 0
    scale_out_units: int = 0
    closed_units: int = 0
    adverse_add_units: int = 0
    short_notional_proxy: Num = None
    open_symbols: int = 0
    carried_in: int = 0
    long_lots: Num = None
    short_lots: Num = None


class EventCounts(BaseModel):
    open_new: int = 0
    scale_in: int = 0
    scale_out: int = 0
    close: int = 0
    flip: int = 0


class AveragingBlock(Info):
    adverse_add_fills: int = 0
    adverse_add_units: int = 0
    share_of_entries_pct: Num = None
    adverse_add_closed_pnl: Num = None
    adverse_add_open_units: int = 0
    adverse_add_lots: Num = None
    spot_adverse_adds: Optional[int] = None


class ChainStep(BaseModel):
    """One fill of a position chain (F42 P6 chain ladder); all fields from the FIFO FillEvent."""
    date: str
    time: Optional[str] = None
    cls: str
    qty_delta: int = 0
    pos_after: int = 0
    lots_after: Num = None
    price: Num = None
    avg_before: Num = None
    adverse: bool = False
    worse_pct: Num = None


class ChainRow(BaseModel):
    symbol: str
    expiry_ym: Optional[str] = None
    side: str
    open_date: Optional[str] = None
    close_date: Optional[str] = None
    peak_qty: int = 0
    adds: int = 0
    adverse_adds: int = 0
    pnl_measured: Num = None
    pnl_estimated: Num = None
    still_open: bool = False
    # F42 P6 additive: lots, story rank (1..N on the SAME ordering as chains[]), per-fill steps.
    peak_lots: Num = None
    story_rank: Optional[int] = None
    steps: list[ChainStep] = Field(default_factory=list)
    steps_total: Optional[int] = None
    steps_truncated: bool = False


class ChainTotals(BaseModel):
    count: int = 0
    with_adverse_add: int = 0
    max_adds: int = 0


class LotsBlock(BaseModel):
    lots_available: bool = False
    lots_basis: str = "unknown"
    coverage_pct: Num = None


class BuildupResponse(AnalyticsEnvelope):
    timeline: list[TimelineRow] = Field(default_factory=list)
    timeline_info: Optional[Info] = None
    events: Optional[EventCounts] = None
    averaging: Optional[AveragingBlock] = None
    chains: list[ChainRow] = Field(default_factory=list)
    chain_totals: Optional[ChainTotals] = None
    chains_info: Optional[Info] = None
    lots: Optional[LotsBlock] = None


# ── market turn ───────────────────────────────────────────────────────────────


class SpotBlock(BaseModel):
    available: bool = False
    last_date: Optional[str] = None
    stale: Optional[bool] = None


class TurnKpis(BaseModel):
    n_turn_days: int = 0
    n_big_move_days: int = 0
    n_adverse_exposed: int = 0
    adverse_exposed_pct: Num = None
    realised_pnl_turn_adverse: Num = None
    realised_from_carried_in: Num = None
    realised_from_opened_that_day: Num = None
    avg_realised_other_days: Num = None


class TurnDay(BaseModel):
    date: str
    underlying: str
    spot_close: Num = None
    ret_pct: Num = None
    is_reversal: bool = False
    bias_units_in: int = 0
    bias_label: str = "flat"
    adverse_exposed: bool = False
    open_symbols_in: list[str] = Field(default_factory=list)
    short_notional_proxy_in: Num = None
    realised_pnl_day: Num = None
    realised_from_carried_in: Num = None
    realised_from_opened_that_day: Num = None
    delta1_bound_pnl: Num = None


class TurnSeries(BaseModel):
    underlying: str
    dates: list[str] = Field(default_factory=list)
    spot_close: list[Num] = Field(default_factory=list)
    bias_units: list[int] = Field(default_factory=list)
    realised_pnl_day: list[Num] = Field(default_factory=list)
    turn_flag: list[int] = Field(default_factory=list)


class WorstDay(BaseModel):
    date: str
    realised_pnl_day: Num = None
    open_symbols: list[str] = Field(default_factory=list)


class MarketTurnResponse(AnalyticsEnvelope):
    spot: Optional[SpotBlock] = None
    kpis: Optional[TurnKpis] = None
    turn_days: list[TurnDay] = Field(default_factory=list)
    series: list[TurnSeries] = Field(default_factory=list)
    worst_days: list[WorstDay] = Field(default_factory=list)
    info: Optional[Info] = None
    delta1_note: Optional[str] = None


# ── margin trap ───────────────────────────────────────────────────────────────


class LedgerBlock(BaseModel):
    available: bool = False
    balance_sign: Optional[int] = None
    balance_sign_match_pct: Num = None
    first: Optional[str] = None
    last: Optional[str] = None
    ordering_ambiguous_days: int = 0
    ledger_gap_days: int = 0


class CashBlock(BaseModel):
    start: Num = None
    end: Num = None
    min: Num = None
    min_date: Optional[str] = None
    days_below_threshold: int = 0
    days_negative: int = 0
    threshold: float = 0.0
    info: Optional[Info] = None


class CashPoint(BaseModel):
    date: str
    cash: Num = None
    carried: bool = False
    # F42 P6 additive per-day fields (None / 0 when an older server omits them).
    short_notional_proxy: Num = None
    open_losers_count: int = 0
    known_loss_est: Num = None
    adverse_add_units: int = 0


class Streak(BaseModel):
    start: str
    end: str
    days: int = 0
    net_outflow: Num = None
    cash_at_end: Num = None


class ExposureBlock(BaseModel):
    peak_short_notional_proxy: Num = None
    avg_proxy_to_cash_ratio: Num = None
    estimated: bool = True


class TrapDay(BaseModel):
    date: str
    cash: Num = None
    open_losers_count: int = 0
    short_notional_proxy: Num = None
    proxy_to_cash_ratio: Num = None
    known_loss_est: Num = None
    long_premium_at_risk: Num = None


class LossGrowth(BaseModel):
    symbols_n: int = 0
    first_trap_date: Optional[str] = None
    loss_at_first_trap_est: Num = None
    final_closed_pnl: Num = None
    growth: Num = None


class AddsOnLowCash(BaseModel):
    fills: int = 0
    units: int = 0
    adverse_fills: int = 0
    adverse_units: int = 0


class TrapBlock(BaseModel):
    days: int = 0
    days_list: list[TrapDay] = Field(default_factory=list)
    loss_growth_est: Optional[LossGrowth] = None
    lots_unmarked: int = 0
    adds_on_low_cash: Optional[AddsOnLowCash] = None   # None (not zeros) when absent -> UI hides the widget
    info: Optional[Info] = None


class StopRow(BaseModel):
    multiple: float
    n_exceeded: int = 0
    realised_loss_exceeding: Num = None
    saved_if_stopped: Num = None
    share_of_total_loss_pct: Num = None
    open_beyond_n: int = 0
    open_beyond_excess_est: Num = None


class StopsBlock(Info):
    long_closed_excluded: int = 0
    short_closed: int = 0
    rows: list[StopRow] = Field(default_factory=list)


class MarginTrapResponse(AnalyticsEnvelope):
    ledger: Optional[LedgerBlock] = None
    cash: Optional[CashBlock] = None
    cash_series: list[CashPoint] = Field(default_factory=list)
    debit_streaks: list[Streak] = Field(default_factory=list)
    exposure: Optional[ExposureBlock] = None
    trap: Optional[TrapBlock] = None
    stops: Optional[StopsBlock] = None


# ── suggestions ───────────────────────────────────────────────────────────────


class RuleParam(BaseModel):
    name: str
    value: Val = None
    unit: str = ""
    lots: Num = None


class WhatIf(BaseModel):
    baseline_pnl: Num = None
    whatif_pnl: Num = None
    delta: Num = None
    trades_removed: int = 0
    units_removed: Num = None
    closed_trades_affected: int = 0
    open_units_vetoed: Num = None
    method: str = ""


class Evidence(BaseModel):
    label: str
    value: Val = None
    source: str = ""


class Variant(BaseModel):
    multiple: float
    saved_if_stopped: Num = None
    n_exceeded: int = 0


class Rule(BaseModel):
    id: str
    title: str
    status: str
    parameter: Optional[RuleParam] = None
    threshold_basis: str = ""
    what_if: Optional[WhatIf] = None
    evidence: list[Evidence] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    variants: list[Variant] = Field(default_factory=list)


class Combined(Info):
    rules_included: list[str] = Field(default_factory=list)
    what_if: Optional[WhatIf] = None
    stop_addon: Num = None
    combined_with_stop: Num = None


class Observation(BaseModel):
    id: str
    text: str
    evidence: list[Evidence] = Field(default_factory=list)


class Sample(BaseModel):
    closed_trades: int = 0
    min_required: int = 0


class SuggestionsResponse(AnalyticsEnvelope):
    disclaimer: str = ""
    sample: Optional[Sample] = None
    baseline_pnl: Num = None
    rules: list[Rule] = Field(default_factory=list)
    combined: Optional[Combined] = None
    observations: list[Observation] = Field(default_factory=list)


# ── spot vs P&L (F42 P4) ──────────────────────────────────────────────────────


class SpotPnlSeries(BaseModel):
    dates: list[str] = Field(default_factory=list)
    spot_close: list[Num] = Field(default_factory=list)
    ret_pct: list[Num] = Field(default_factory=list)
    realised_measured: list[Num] = Field(default_factory=list)
    realised_estimate: list[Num] = Field(default_factory=list)
    cum_measured: list[Num] = Field(default_factory=list)
    cum_total: list[Num] = Field(default_factory=list)
    bias_in: list[int] = Field(default_factory=list)
    closing_day: list[int] = Field(default_factory=list)
    big_move_flag: list[int] = Field(default_factory=list)
    reversal_flag: list[int] = Field(default_factory=list)
    expiry_flag: list[int] = Field(default_factory=list)
    adverse_flag: list[int] = Field(default_factory=list)
    truncated: bool = False
    dropped_days: int = 0


class SpotPnlTotals(BaseModel):
    measured_realised: Num = None
    estimated_realised: Num = None
    pnl_rolled_days: int = 0
    pnl_rolled_amount: Num = None
    pnl_after_last_spot: Num = None
    pnl_after_last_spot_count: int = 0
    n_days: int = 0
    n_closing_days: int = 0
    realised_plus_unrealised: Num = None


class UnrealisedSnapshot(BaseModel):
    available: bool = False
    reason: Optional[str] = None
    as_of: Optional[str] = None
    amount: Num = None
    n_symbols: int = 0
    fifo_open_symbols: int = 0
    symbols_missing_in_sheet: int = 0
    days_behind_spot: Optional[int] = None
    stale: Optional[bool] = None
    tag: str = "measured"
    note: str = ""


class CorrBlock(BaseModel):
    n: int = 0
    pearson: Num = None
    spearman: Num = None
    beta_inr_per_pct: Num = None
    r2: Num = None
    significant: Optional[bool] = None
    reason: Optional[str] = None
    min_required: int = 0
    basis_tag: str = "measured"


class SpotBucket(BaseModel):
    key: str
    n_days: int = 0
    n_closing_days: int = 0
    total_pnl: Num = None
    total_measured: Num = None
    total_estimate: Num = None
    mean_pnl: Num = None
    median_pnl: Num = None
    hit_rate_pct: Num = None
    share_of_total_loss_pct: Num = None
    available: bool = False
    reason: Optional[str] = None
    min_required: int = 0


class Relationship(BaseModel):
    all_days: CorrBlock = Field(default_factory=CorrBlock)
    closing_days: CorrBlock = Field(default_factory=CorrBlock)
    by_direction: list[SpotBucket] = Field(default_factory=list)
    big_move: list[SpotBucket] = Field(default_factory=list)
    big_any: Optional[SpotBucket] = None
    expiry_days: list[SpotBucket] = Field(default_factory=list)


class BiasSide(BaseModel):
    n: int = 0
    mean_ret_pct: Num = None


class ByBias(BaseModel):
    bullish: BiasSide = Field(default_factory=BiasSide)
    bearish: BiasSide = Field(default_factory=BiasSide)


class Alignment(BaseModel):
    days_with_bias: int = 0
    with_n: int = 0
    against_n: int = 0
    flat_market_n: int = 0
    flat_book_n: int = 0
    pct_with: Num = None
    pct_with_ci_low: Num = None
    pct_with_ci_high: Num = None
    verdict: str = "insufficient_sample"
    min_required: int = 0
    with_units_pts: Num = None
    against_units_pts: Num = None
    net_units_pts: Num = None
    by_bias: ByBias = Field(default_factory=ByBias)
    tag: str = "estimated"
    caveat: str = ""


class SpotPnlUnderlying(BaseModel):
    underlying: str
    available: bool = True
    reason: Optional[str] = None
    spot_last_date: Optional[str] = None
    spot_stale: Optional[bool] = None
    series: SpotPnlSeries = Field(default_factory=SpotPnlSeries)
    totals: SpotPnlTotals = Field(default_factory=SpotPnlTotals)
    unrealised_snapshot: UnrealisedSnapshot = Field(default_factory=UnrealisedSnapshot)
    relationship: Optional[Relationship] = None
    alignment: Optional[Alignment] = None
    observations: list[Observation] = Field(default_factory=list)


class RelatedLink(BaseModel):
    observation_id: str
    rule_id: str


class Improvement(BaseModel):
    disclaimer: str = ""
    baseline_pnl: Num = None
    rules: list[Rule] = Field(default_factory=list)
    related: list[RelatedLink] = Field(default_factory=list)


class SpotVsPnlResponse(AnalyticsEnvelope):
    info: Optional[Info] = None
    underlyings: list[SpotPnlUnderlying] = Field(default_factory=list)
    improvement: Optional[Improvement] = None
    delta1_note: str = ""
