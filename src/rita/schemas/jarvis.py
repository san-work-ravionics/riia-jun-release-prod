"""Pydantic contracts for the F44 P4 Jarvis module (P4a backend; P4b builds only from these and
``tests/unit/fixtures/f44_p4_contract.json``).

Rates are fractions; dates ISO; money carries ``currency``.  Every number Jarvis shows comes from
a tool result: ``PnlOut`` / ``SleeveTraceOut`` / ``SigmaLevelsOut`` / ``AstaTraceOut`` are MCP
tool outputs; the page payloads (A4–A6) are composed from them.
"""
from __future__ import annotations

from datetime import date, datetime
from datetime import date as _Date
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from rita.schemas.goal_selection import GoalOut, GoalSelectionOut, ModelAction, RequiredReturnOut, Tolerance

Location = Literal["europe", "india", "us"]
JourneyState = Literal["no_goal", "goal_loaded", "selected", "cant_reach", "tracking",
                       "reselect_proposed", "back_to_plan", "closed"]
JourneyEvent = Literal["start", "select", "track", "propose", "accept", "decline", "back_to_plan"]
BackToPlanReason = Literal["year_end", "count", "cap", "test_shortfall"]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── journey ────────────────────────────────────────────────────────────────────

class TrackingIn(BaseModel):
    """One tracked holding (rev 1 shape; replaces P0 target / stop_loss / band_source)."""

    model_config = ConfigDict(extra="forbid")

    instrument_id: str
    allocation_pct: int
    tolerance: Tolerance
    entry_date: date
    entry_close: float | None = None
    sl_drawdown_limit: float
    sl_basis: Literal["sleeve_drawdown_from_episode_peak"] = "sleeve_drawdown_from_episode_peak"
    episode_start: date | None = None
    episode_length: int | None = None
    model_sha12: str | None = None


class SegmentHoldingOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument_id: str
    allocation_pct: int
    tolerance: Tolerance


class SegmentOut(BaseModel):
    """A held mix over ``(from, to]`` bars (``to`` null = open).  ytd chains the segments."""

    model_config = ConfigDict(extra="forbid", validate_by_name=True, validate_by_alias=True,
                              serialize_by_alias=True)

    from_: date = Field(alias="from")
    to: date | None = None
    holdings: list[SegmentHoldingOut]
    cause: Literal["track", "accept", "preview"]


class ReselectionEventOut(BaseModel):
    at: date
    event: Literal["proposed", "accepted", "declined"]
    from_return: float | None = None
    to_return: float | None = None
    trigger: Literal["sl_hit", "behind_target"] | None = None


class JourneyGoalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    saved: bool
    plan_updated_at: datetime | None = None
    goal_return: float | None = None
    horizon_years: float | None = None
    goal_value: float | None = None


class JourneySaveIn(_In):
    """``journey.save`` input — the only MCP write (no user argument: the user is the caller)."""

    location: Location
    event: JourneyEvent
    expected_version: int | None = Field(None, ge=1, description="compare-and-set: the version read")
    as_of: date | None = Field(None, description="data date of the event (default today)")
    goal: JourneyGoalIn | None = None
    selection: GoalSelectionOut | None = None
    tracking: list[TrackingIn] | None = None
    proposal: RequiredReturnOut | None = None
    trigger: Literal["sl_hit", "behind_target"] | None = None
    reason: BackToPlanReason | None = None


class JourneyGetIn(_In):
    location: Location


class JourneyOut(BaseModel):
    journey_id: str
    location: str
    currency: str
    state: JourneyState
    back_to_plan_reason: str | None = None
    goal_return: float | None = None
    horizon_years: float | None = None
    goal_value: float | None = None
    plan_updated_at: datetime | None = None
    target_return: float | None = None
    reselect_count: int
    reselect_year: int | None = None
    max_reselections: int
    selection: GoalSelectionOut | None = None
    proposal: RequiredReturnOut | None = None
    tracking: list[TrackingIn] = []
    reselections: list[ReselectionEventOut] = []
    segments: list[SegmentOut] = []
    plan_year_start: date | None = None
    previous_journey_id: str | None = None
    version: int
    updated_at: datetime | None = None


# ── portfolio.pnl ──────────────────────────────────────────────────────────────

class PnlPointOut(BaseModel):
    date: date
    ret: float                              # chained return since the year start (rebased)
    source: Literal["saved", "model_sleeves"]


class TargetPointOut(BaseModel):
    date: date
    target: float


class PnlHoldingOut(BaseModel):
    instrument_id: str
    allocation_pct: float
    return_since: float | None = None
    status: Literal["ok", "no_price_data", "no_shares", "excluded"]


class MoneyPointOut(BaseModel):
    date: date
    value: float
    pnl: float


class MoneyHoldingOut(BaseModel):
    instrument_id: str
    shares: int | None = None
    entry_close: float | None = None
    last_close: float | None = None
    pnl: float | None = None


class MoneyOut(BaseModel):
    """Money figures of the saved portfolio (null for model sleeves — a selection has no amounts)."""

    portfolio_id: str
    name: str | None = None
    legacy_note: bool = False
    value_entry: float | None = None
    value_now: float | None = None
    pnl: float | None = None
    return_since_entry: float | None = None
    cash: float = 0.0
    series: list[MoneyPointOut] = []
    holdings: list[MoneyHoldingOut] = []


class PnlOut(BaseModel):
    location: str
    currency: str
    source: Literal["saved", "model_sleeves", "mixed", "model_sleeves_preview"]
    as_of: date | None = None
    year_start: date
    entry_date: date | None = None
    goal_return: float | None = None
    ytd_return: float | None = None
    target_to_date: float | None = None
    coverage: float
    series: list[PnlPointOut] = []
    target_path: list[TargetPointOut] = []
    holdings: list[PnlHoldingOut] = []
    money: MoneyOut | None = None


# ── portfolio.sleeve_trace ─────────────────────────────────────────────────────

class MarkerOut(BaseModel):
    date: date
    kind: Literal["entry", "exit", "derisk", "rerisk"]
    close: float | None = None
    from_action: ModelAction
    to_action: ModelAction


class RationaleInputOut(BaseModel):
    name: str
    raw: float | None = None
    model_input: float | None = None


class RationaleStateOut(BaseModel):
    name: str
    value: float | str | None = None


class RationaleOut(BaseModel):
    date: date
    action: str | None = None
    prev_action: str | None = None
    inputs: list[RationaleInputOut] = []
    state: list[RationaleStateOut] = []
    note: str | None = None


class SleeveDetailOut(BaseModel):
    dates: list[date]
    close: list[float | None]
    allocation: list[float]
    hedged: list[float]
    sleeve_value: list[float]
    sl_line: list[float]
    episode_starts: list[date]
    markers: list[MarkerOut]
    rationale: RationaleOut | None = None


class SleeveMethodOut(BaseModel):
    levels: str = "ddqn_v2 replay actions"
    sl: str = "training constraint hard_mdd_limit (config input, not a model output)"
    next_reset: str = "business-day estimate from the episode length"


class SleeveTraceOut(BaseModel):
    instrument_id: str
    status: Literal["ok", "excluded"]
    excluded_reason: str | None = None
    excluded_detail: str | None = None
    engine: Literal["rita_ddqn_v2"] = "rita_ddqn_v2"
    lineage: str | None = None
    model_sha12: str | None = None
    tolerance: Tolerance | None = None
    tolerance_rule: Literal["selection", "p3_tau_rule_single_sleeve"] | None = None
    as_of: date | None = None
    window_start: date | None = None
    episode_length: int | None = None
    episode_start: date | None = None
    episode_day: int | None = None
    next_reset: date | None = None
    hard_mdd_limit: float | None = None
    today_action: ModelAction | None = None
    invested_fraction: float | None = None
    last_close: float | None = None
    since: date | None = None
    return_since: float | None = None
    sleeve_peak: float | None = None
    sleeve_now: float | None = None
    sl_level: float | None = None
    sl_distance: float | None = None
    sl_hit: bool | None = None
    last_entry_date: date | None = None
    last_exit_date: date | None = None
    detail: SleeveDetailOut | None = None
    method: SleeveMethodOut = Field(default_factory=SleeveMethodOut)


# ── fno.sigma_levels ───────────────────────────────────────────────────────────

class SigmaLevelsBandOut(BaseModel):
    entry: float
    plus_1sigma: float
    minus_1sigma: float


class SigmaMonthOut(BaseModel):
    month: str
    anchor_close: float
    plus_1sigma: float
    minus_1sigma: float
    ann_vol_pct: float


class ClosePointOut(BaseModel):
    date: date
    close: float


class SigmaLevelsOut(BaseModel):
    instrument_id: str
    currency: str | None = None
    as_of: date | None = None
    status: Literal["ok", "no_price_data", "insufficient_data"]
    last_close: float | None = None
    ann_vol_pct: float | None = None
    monthly_sigma_pct: float | None = None
    lookback_returns: int | None = None
    anchor_close: float | None = None
    anchor_date: date | None = None
    levels: SigmaLevelsBandOut | None = None
    closes: list[ClosePointOut] = []
    monthly: list[SigmaMonthOut] = []
    method: str = ("±1σ monthly band from the last 252 daily returns (statistical, not a model)")


# ── market.asta_trace ──────────────────────────────────────────────────────────

class AstaSignalOut(BaseModel):
    date: date
    signal: Literal["BUY", "SELL"]
    setup: str
    confidence: float
    mandatory_met: int
    mandatory_total: int
    optional_met: int
    optional_total: int
    stop_loss: float | None = None
    target: float | None = None


class AstaWindowOut(BaseModel):
    test_start: date | None = None
    test_end: date | None = None
    verified: bool
    basis: str


class AstaTrainingRecordOut(BaseModel):
    run_id: str
    test_sharpe: float | None = None
    test_mdd: float | None = None
    test_return: float | None = None
    test_trades: int | None = None


class AstaPipelineBacktestOut(BaseModel):
    run_id: str
    status: str


class AstaDetailOut(BaseModel):
    dates: list[date]
    close: list[float]
    allocation: list[float]
    hedged: list[float]
    markers: list[MarkerOut]
    signals: list[AstaSignalOut]
    rationale: RationaleOut | None = None


class AstaMethodOut(BaseModel):
    entries: str = "ASTA DDQN actions (model)"
    sl_target: str = "ASTA labeller setup levels (rule engine, not a model)"


class AstaTraceOut(BaseModel):
    instrument_id: str
    status: Literal["ok", "no_model", "warming", "no_data", "no_recorded_window"]
    engine: Literal["rita_ddqn_asta"] = "rita_ddqn_asta"
    model_sha12: str | None = None
    window_start: date | None = None
    window: AstaWindowOut | None = None
    training_record: AstaTrainingRecordOut | None = None
    pipeline_backtest: AstaPipelineBacktestOut | None = None
    as_of: date | None = None
    today_action: ModelAction | None = None
    since: date | None = None
    return_since: float | None = None
    last_signal: AstaSignalOut | None = None
    model_note: str | None = None
    live_replay_note: str | None = None
    detail: AstaDetailOut | None = None
    method: AstaMethodOut = Field(default_factory=AstaMethodOut)


# ── chat cards (rev 1 B3: discriminated union on ``kind``) ─────────────────────

class CardHoldingOut(BaseModel):
    instrument_id: str
    allocation_pct: int
    model_action: ModelAction | None = None


class WindowDatesOut(BaseModel):
    start: date
    end: date


class GoalCardData(BaseModel):
    location: str
    currency: str
    goal_return: float | None = None
    horizon_years: float | None = None
    goal_value: float | None = None
    plan_updated_at: datetime | None = None


class SelectionCardData(BaseModel):
    location: str
    currency: str
    target_return: float
    meets_goal: bool
    tolerance: Tolerance | None = None
    n_tolerances: int
    holdings: list[CardHoldingOut]
    fit_return: float | None = None
    test_return: float | None = None
    test_mdd: float | None = None
    gap: float | None = None
    test_window: WindowDatesOut
    method_weights: str


class ClosestCardData(BaseModel):
    target_return: float
    holdings: list[CardHoldingOut]
    fit_return: float | None = None
    test_return: float | None = None
    gap: float | None = None
    cap_fit: float
    cap_test: float


class WhyRowOut(BaseModel):
    instrument_id: str
    allocation_pct: int
    fit_return: float | None = None
    test_return: float | None = None
    test_mdd: float | None = None
    today_action: ModelAction | None = None


class ExcludedRowOut(BaseModel):
    instrument_id: str
    reason: str


class WhyCardData(BaseModel):
    tolerance: Tolerance | None = None
    n_tolerances: int
    rows: list[WhyRowOut]
    excluded: list[ExcludedRowOut] = []


class TrackingCardHoldingOut(BaseModel):
    instrument_id: str
    entry_close: float | None = None
    today_action: ModelAction | None = None


class TrackingCardData(BaseModel):
    entry_date: date
    sl_drawdown_limit: float | None = None
    next_reset: date | None = None
    holdings: list[TrackingCardHoldingOut]


class ProgressCardData(BaseModel):
    source: Literal["saved", "model_sleeves", "mixed"]
    as_of: date | None = None
    year_start: date
    ytd_return: float | None = None
    target_to_date: float | None = None
    required_return: float | None = None
    status: str | None = None
    reason: str | None = None


class ProposalCardData(BaseModel):
    required_return: float | None = None
    effective_return: float | None = None
    holdings: list[CardHoldingOut]
    test_return: float | None = None
    reselections_next: int
    max_reselections: int


class WhatIfRowOut(BaseModel):
    instrument_id: str
    sl_distance: float | None = None


class WhatIfCardData(BaseModel):
    ytd_return: float
    required_return: float | None = None
    status: str
    reason: str
    rows: list[WhatIfRowOut]


class HedgeCardData(BaseModel):
    n_hedged: int
    coverage: int
    updated_at: datetime | None = None


class ExcludedCardData(BaseModel):
    rows: list[ExcludedRowOut]


class GoalCard(BaseModel):
    kind: Literal["goal"] = "goal"
    data: GoalCardData


class SelectionCard(BaseModel):
    kind: Literal["selection"] = "selection"
    data: SelectionCardData


class ClosestCard(BaseModel):
    kind: Literal["closest"] = "closest"
    data: ClosestCardData


class WhyCard(BaseModel):
    kind: Literal["why"] = "why"
    data: WhyCardData


class TrackingCard(BaseModel):
    kind: Literal["tracking"] = "tracking"
    data: TrackingCardData


class ProgressCard(BaseModel):
    kind: Literal["progress"] = "progress"
    data: ProgressCardData


class ProposalCard(BaseModel):
    kind: Literal["proposal"] = "proposal"
    data: ProposalCardData


class WhatIfCard(BaseModel):
    kind: Literal["what_if"] = "what_if"
    data: WhatIfCardData


class HedgeCard(BaseModel):
    kind: Literal["hedge"] = "hedge"
    data: HedgeCardData


class ExcludedCard(BaseModel):
    kind: Literal["excluded"] = "excluded"
    data: ExcludedCardData


CardOut = Annotated[
    Union[GoalCard, SelectionCard, ClosestCard, WhyCard, TrackingCard, ProgressCard, ProposalCard,
          WhatIfCard, HedgeCard, ExcludedCard],
    Field(discriminator="kind"),
]
CARD_KINDS = ("goal", "selection", "closest", "why", "tracking", "progress", "proposal",
              "what_if", "hedge", "excluded")


# ── A1–A3 (Workflow) ───────────────────────────────────────────────────────────

class WarmupOut(BaseModel):
    status: Literal["ready", "unavailable"]
    intents: int


class SessionIn(_In):
    location: Location


class SessionOut(BaseModel):
    session_id: str
    started_at: datetime
    reused: bool


class MessageIn(_In):
    session_id: str = Field(..., min_length=1, max_length=64)
    text: str = Field(..., min_length=1, max_length=500)
    location: Location


class ChipOut(BaseModel):
    label: str
    text: str


class ToolCallOut(BaseModel):
    tool: str
    mcp_call_id: str | None = None
    status: Literal["ok", "error", "not_found"]


class ReplyOut(BaseModel):
    text: str
    template_id: str
    intent: str | None = None
    confidence: float | None = None
    low_confidence: bool
    chips: list[ChipOut] = []
    cards: list[CardOut] = []
    tool_calls: list[ToolCallOut] = []


class MessageOut(BaseModel):
    session_id: str
    reply: ReplyOut
    journey: JourneyOut | None = None


# ── A4–A6 (Experience) ─────────────────────────────────────────────────────────

class SessionStateOut(BaseModel):
    session_id: str
    status: str
    last_activity_at: datetime | None = None


class MessageRowOut(BaseModel):
    message_id: str
    role: Literal["user", "assistant"]
    text: str | None = None
    intent: str | None = None
    template_id: str | None = None
    created_at: datetime | None = None


class LiveHoldingOut(BaseModel):
    """N2: the model's view today for each holding of the current segment (from sleeve_trace)."""

    instrument_id: str
    model_action: ModelAction | None = None
    invested_fraction: float | None = None
    sl_distance: float | None = None
    sl_hit: bool | None = None
    next_reset: date | None = None
    as_of: date | None = None
    status: Literal["ok", "excluded", "unavailable"] = "ok"


class StateOut(BaseModel):
    location: str
    location_name: str
    currency: str
    goal: GoalOut | None = None
    plan_stale: bool
    journey: JourneyOut | None = None
    session: SessionStateOut | None = None
    messages: list[MessageRowOut] = []
    chips: list[ChipOut] = []
    chat_model: Literal["ready", "not_loaded"]
    live_holdings: list[LiveHoldingOut] = []


class RequiredOut(BaseModel):
    status: str
    reason: str
    required_return: float | None = None
    effective_return: float | None = None
    reselections_used: int
    max_reselections: int


class PerfOut(PnlOut):
    """A5 ``perf``: the PnlOut of the chosen source + ``pnl_source``."""

    pnl_source: Literal["saved", "model_sleeves", "mixed", "model_sleeves_preview"]


class InstrumentRowOut(BaseModel):
    instrument_id: str
    held: bool
    selected: bool
    allocation_pct: float | None = None
    shares: int | None = None
    last_close: float | None = None
    pnl: float | None = None
    ret: float | None = None
    model_action: ModelAction | None = None
    sl_distance: float | None = None
    sl_hit: bool | None = None
    engines_available: list[Literal["rita", "fno", "asta"]] = []


class EngineRowOut(BaseModel):
    engine: Literal["rita", "asta", "fno", "held"]
    label: str
    model_based: bool
    coverage: float | None = None
    return_since: float | None = None
    target_to_date: float | None = None
    gap: float | None = None
    on_pace: bool | None = None
    status: Literal["ok", "no_model", "excluded", "warming", "levels_only", "unavailable",
                    "no_recorded_window", "none"]
    note: str | None = None


class PortfolioPageOut(BaseModel):
    location: str
    currency: str
    as_of: date | None = None
    pnl_source: Literal["saved", "model_sleeves", "mixed", "model_sleeves_preview", "none"]
    perf: PerfOut | None = None
    required: RequiredOut | None = None
    journey_state: JourneyState | None = None
    instruments: list[InstrumentRowOut] = []
    engines: list[EngineRowOut] = []


class LevelOut(BaseModel):
    date: _Date | None = None
    value: float
    basis: str


class LevelsOut(BaseModel):
    entry: LevelOut | None = None
    exit: LevelOut | None = None
    stop_loss: LevelOut | None = None
    target: LevelOut | None = None


class ChartMarkerOut(BaseModel):
    date: date
    kind: Literal["entry", "exit", "derisk", "rerisk"]
    close: float | None = None


class SeriesOut(BaseModel):
    sleeve_value: list[float] = []
    sl_line: list[float] = []
    band_upper: list[float | None] = []
    band_lower: list[float | None] = []


class PerformanceOut(BaseModel):
    return_since: float | None = None
    since: date | None = None
    target_to_date: float | None = None
    gap: float | None = None


class InstrumentEngineOut(BaseModel):
    engine: Literal["rita", "fno", "asta"]
    status: str
    label: str
    model_based: bool
    prices: list[ClosePointOut] = []
    markers: list[ChartMarkerOut] = []
    levels: LevelsOut = Field(default_factory=LevelsOut)
    series: SeriesOut = Field(default_factory=SeriesOut)
    episode_starts: list[date] = []
    rationale: RationaleOut | None = None
    performance: PerformanceOut | None = None
    method: Any = None
    tolerance_rule: str | None = None
    asta: AstaTraceOut | None = None


class InstrumentPageOut(BaseModel):
    instrument_id: str
    currency: str | None = None
    as_of: date | None = None
    engines: list[InstrumentEngineOut]
