"""Unit tests — F30 Phase 3: API-frontend contract verification.

Phase 3 is a pure JS frontend refactor — no new Python backend code was
written.  These tests verify the Python backend contract that Phase 3 JS
modules rely on:

1. PositionItemSchema has all fields consumed by the new Overview positions
   grid (renderOverviewFromState) and Manoeuvre page.
2. scenario_levels are present and can be normalised to bull/bear shape
   (_normScenarioLevels logic).
3. payoff has portfolio/hedged nested structure for renderPayoffChart.
4. hedge_quality has positions list for renderPortfolioHedgeRadar.

No new endpoint was created in Phase 3 — the existing endpoint
GET /api/v1/experience/fno/portfolio-analytics?mode=real|mock (F30 Phase 1)
is reused.

API-Frontend contract (Phase 3 JS reads — from Architect design section)
------------------------------------------------------------------------
  state.positions         → Overview positions grid, Manoeuvre
  state.scenarioLevels    → Scenarios (rr.js), after _normScenarioLevels
  state.payoffData        → Risk (payoff.js), portfolio-shape vs legacy
  state.hedgeQuality      → Hedge Radar (renderPortfolioHedgeRadar)
  state.stressData        → Risk (stress.js — renderAnalyticsStress)
  state.netGreeks         → Risk (greeks.js)
  state.greeksData        → Risk (greeks.js, uses g.und + g.hedge_type)
  state.portfolioMeta     → Overview (my-portfolio.js)
  state.marketData        → Overview instrument selector

Edge cases from Architect design (F30 Phase 3):
  1. Empty positions array
  2. state.scenarioLevels empty → _normScenarioLevels({}) returns {}
  3. API error / network failure — all new render functions guard on null state
  4. Instrument selector with no market data — fall back gracefully
  5. payoff with empty labels arrays — guard in renderPayoffChart
  6. hedge_quality.positions instruments not in state.positions.und — render directly
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Import paths — exact module + class names verified from worktree source:
#   src/rita/schemas/portfolio_analytics.py
# ---------------------------------------------------------------------------

from rita.schemas.portfolio_analytics import (
    GreekItemSchema,
    HedgeQualityPositionSchema,
    HedgeQualitySchema,
    MarketEntrySchema,
    NetGreeksSchema,
    PayoffCurveSchema,
    PayoffSchema,
    PortfolioAnalyticsResponse,
    PortfolioMetaSchema,
    PositionItemSchema,
    ScenarioLevelSchema,
    StressEventSchema,
)


# ---------------------------------------------------------------------------
# Test 1 — PositionItemSchema has all fields consumed by Overview grid + Manoeuvre
# ---------------------------------------------------------------------------

class TestPositionItemSchema:
    """Verify PositionItemSchema has all fields that Phase 3 JS reads.

    From Architect design — state.positions fields consumed by:
    - renderOverviewFromState() in my-portfolio.js: und, full, exp, type, side,
      qty, allocation_pct, position_eur, avg, ltp, chg, pnl, currency, ann_vol_pct, region
    - manoeuvre.js line 140: p.full ?? p.instrument ?? p.und
    """

    _REQUIRED_FIELDS = {
        "und", "full", "exp", "type", "side", "qty",
        "allocation_pct", "position_eur", "avg", "ltp",
        "chg", "pnl", "currency", "ann_vol_pct", "region",
    }

    def test_portfolio_analytics_schema_has_positions_fields(self):
        """PositionItemSchema must have all 15 fields consumed by Phase 3 JS modules."""
        model_fields = set(PositionItemSchema.model_fields.keys())
        missing = self._REQUIRED_FIELDS - model_fields
        assert not missing, (
            f"PositionItemSchema is missing fields consumed by Phase 3 JS: {missing}\n"
            f"Current fields: {sorted(model_fields)}"
        )

    def test_position_item_schema_instantiation_with_all_required_fields(self):
        """PositionItemSchema instantiates cleanly with all fields the JS grid reads."""
        item = PositionItemSchema(
            und="ASML",
            full="ASML Holding N.V.",
            exp="EQUITY",
            type="EQ",
            side="Long",
            qty=1,
            allocation_pct=20.0,
            position_eur=10000.0,
            avg=890.5,
            ltp=890.5,
            chg=2.4,
            pnl=0.0,
            currency="EUR",
            ann_vol_pct=31.0,
            region="EU",
        )
        assert item.und == "ASML"
        assert item.full == "ASML Holding N.V."
        assert item.region == "EU"
        assert item.ann_vol_pct == 31.0
        assert item.currency == "EUR"

    def test_position_item_schema_optional_fields_allow_none(self):
        """PositionItemSchema optional fields (currency, region) accept None."""
        item = PositionItemSchema(
            und="NIFTY",
            full="Nifty 50 Index",
            exp="EQUITY",
            type="EQ",
            side="Long",
            qty=1,
            allocation_pct=30.0,
            position_eur=15000.0,
            avg=24200.0,
            ltp=24200.0,
            chg=1.7,
            pnl=0.0,
            currency=None,
            ann_vol_pct=18.4,
            region=None,
        )
        assert item.currency is None
        assert item.region is None


# ---------------------------------------------------------------------------
# Test 2 — scenario_levels field exists in PortfolioAnalyticsResponse
# ---------------------------------------------------------------------------

class TestScenarioLevelsSchema:
    """Verify scenario_levels is present and has the correct shape.

    Phase 3 _normScenarioLevels(raw) in app-init.js expects:
    - scenario_levels: dict[str, ScenarioLevelSchema] with {target, sl} per instrument
    """

    def test_portfolio_analytics_schema_has_scenario_levels(self):
        """PortfolioAnalyticsResponse must have scenario_levels field."""
        model_fields = set(PortfolioAnalyticsResponse.model_fields.keys())
        assert "scenario_levels" in model_fields, (
            "PortfolioAnalyticsResponse is missing scenario_levels field — "
            "_normScenarioLevels in app-init.js will receive undefined"
        )

    def test_scenario_level_schema_has_target_and_sl(self):
        """ScenarioLevelSchema must have target and sl fields."""
        level_fields = set(ScenarioLevelSchema.model_fields.keys())
        assert "target" in level_fields, "ScenarioLevelSchema missing target field"
        assert "sl" in level_fields, "ScenarioLevelSchema missing sl field"

    def test_scenario_level_schema_instantiation(self):
        """ScenarioLevelSchema instantiates with target and sl."""
        level = ScenarioLevelSchema(target=26649.0, sl=15503.0)
        assert level.target == 26649.0
        assert level.sl == 15503.0

    def test_scenario_levels_dict_type_in_response(self):
        """PortfolioAnalyticsResponse.scenario_levels annotation is dict[str, ...]."""
        import typing
        hint = PortfolioAnalyticsResponse.model_fields["scenario_levels"]
        # annotation should be a dict type; verify by checking the annotation string
        ann_str = str(hint.annotation)
        assert "dict" in ann_str.lower() or "Dict" in ann_str, (
            f"scenario_levels annotation should be dict, got: {ann_str}"
        )


# ---------------------------------------------------------------------------
# Test 3 — payoff field structure for renderPayoffChart
# ---------------------------------------------------------------------------

class TestPayoffSchema:
    """Verify payoff has portfolio/hedged nested structure for Phase 3 renderPayoffChart.

    renderPayoffChart() in payoff.js now detects portfolio-shape vs NIFTY/BANKNIFTY
    legacy shape. Must have payoff.portfolio.{labels, data} + payoff.hedged.{labels, data}.
    """

    def test_portfolio_analytics_schema_has_payoff(self):
        """PortfolioAnalyticsResponse must have payoff field."""
        model_fields = set(PortfolioAnalyticsResponse.model_fields.keys())
        assert "payoff" in model_fields, (
            "PortfolioAnalyticsResponse is missing payoff field — "
            "renderPayoffChart will not render"
        )

    def test_payoff_schema_has_portfolio_and_hedged(self):
        """PayoffSchema must have portfolio and hedged fields."""
        payoff_fields = set(PayoffSchema.model_fields.keys())
        assert "portfolio" in payoff_fields, "PayoffSchema missing portfolio field"
        assert "hedged" in payoff_fields, "PayoffSchema missing hedged field"

    def test_payoff_curve_schema_has_labels_and_data(self):
        """PayoffCurveSchema must have labels and data fields."""
        curve_fields = set(PayoffCurveSchema.model_fields.keys())
        assert "labels" in curve_fields, "PayoffCurveSchema missing labels field"
        assert "data" in curve_fields, "PayoffCurveSchema missing data field"

    def test_payoff_schema_instantiation(self):
        """PayoffSchema instantiates with portfolio and hedged curves of equal length."""
        labels = [-30.0, -15.0, 0.0, 15.0, 30.0]
        portfolio_data = [-15000, -7500, 0, 7500, 15000]
        hedged_data    = [-11250, -5625, 0, 7500, 15000]

        payoff = PayoffSchema(
            portfolio=PayoffCurveSchema(labels=labels, data=portfolio_data),
            hedged=PayoffCurveSchema(labels=labels, data=hedged_data),
        )
        assert len(payoff.portfolio.labels) == len(payoff.portfolio.data)
        assert len(payoff.hedged.labels) == len(payoff.hedged.data)
        assert payoff.portfolio.labels[2] == 0.0
        assert payoff.hedged.data[0] == -11250

    def test_payoff_empty_labels_arrays_accepted(self):
        """PayoffSchema with empty labels/data arrays must be accepted (edge case 5)."""
        payoff = PayoffSchema(
            portfolio=PayoffCurveSchema(labels=[], data=[]),
            hedged=PayoffCurveSchema(labels=[], data=[]),
        )
        assert payoff.portfolio.labels == []
        assert payoff.hedged.data == []


# ---------------------------------------------------------------------------
# Test 4 — hedge_quality field for renderPortfolioHedgeRadar
# ---------------------------------------------------------------------------

class TestHedgeQualitySchema:
    """Verify hedge_quality has positions list for renderPortfolioHedgeRadar.

    Phase 3 added renderPortfolioHedgeRadar() in hedge.js that reads from
    state.hedgeQuality.positions — must be a list of HedgeQualityPositionSchema.
    """

    def test_portfolio_analytics_schema_has_hedge_quality(self):
        """PortfolioAnalyticsResponse must have hedge_quality field with positions list."""
        model_fields = set(PortfolioAnalyticsResponse.model_fields.keys())
        assert "hedge_quality" in model_fields, (
            "PortfolioAnalyticsResponse is missing hedge_quality field — "
            "renderPortfolioHedgeRadar will not render"
        )

    def test_hedge_quality_schema_has_positions_list(self):
        """HedgeQualitySchema must have positions field."""
        hq_fields = set(HedgeQualitySchema.model_fields.keys())
        assert "positions" in hq_fields, (
            "HedgeQualitySchema is missing positions field — "
            "renderPortfolioHedgeRadar guard state.hedgeQuality?.positions?.length will fail"
        )

    def test_hedge_quality_position_schema_has_all_required_fields(self):
        """HedgeQualityPositionSchema must have all fields read by renderPortfolioHedgeRadar."""
        required = {"instrument", "hqs", "hqs_tier", "hedged", "strategy", "coverage_pct", "note"}
        pos_fields = set(HedgeQualityPositionSchema.model_fields.keys())
        missing = required - pos_fields
        assert not missing, (
            f"HedgeQualityPositionSchema missing fields: {missing}"
        )

    def test_hedge_quality_schema_instantiation_with_positions(self):
        """HedgeQualitySchema instantiates with a non-empty positions list."""
        hq = HedgeQualitySchema(positions=[
            HedgeQualityPositionSchema(
                instrument="ASML",
                hqs=5,
                hqs_tier="red",
                hedged=False,
                strategy=None,
                coverage_pct=None,
                note="No hedge assigned",
            ),
            HedgeQualityPositionSchema(
                instrument="NIFTY",
                hqs=75,
                hqs_tier="green",
                hedged=True,
                strategy="protective_put",
                coverage_pct=50,
                note=None,
            ),
        ])
        assert len(hq.positions) == 2
        assert hq.positions[0].instrument == "ASML"
        assert hq.positions[0].hedged is False
        assert hq.positions[1].hqs_tier == "green"

    def test_hedge_quality_empty_positions_list_accepted(self):
        """HedgeQualitySchema with empty positions list must be valid (edge case 3 guard)."""
        hq = HedgeQualitySchema(positions=[])
        assert hq.positions == []


# ---------------------------------------------------------------------------
# Test 5 — _normScenarioLevels logic (pure Python simulation)
# ---------------------------------------------------------------------------

class TestNormScenarioLevelsLogic:
    """Verify the _normScenarioLevels normalisation logic.

    The JS function in app-init.js converts API shape {INST: {target, sl}}
    to bull/bear shape {INST: {bull: {target, sl}, bear: {target, sl}}}.
    This test simulates the same logic in Python to verify the contract.

    From app-init.js lines 43–58:
      if val.bull !== undefined → pass through (already normalised)
      elif val.target !== undefined and val.sl !== undefined →
        bull: {target: val.target, sl: val.sl}
        bear: {target: val.sl,     sl: val.target}   ← swap target ↔ sl
      else → pass through unchanged
    """

    @staticmethod
    def _norm_scenario_levels(raw: dict) -> dict:
        """Python mirror of the JS _normScenarioLevels() function in app-init.js."""
        out = {}
        for key, val in (raw or {}).items():
            if val is None:
                out[key] = val
            elif "bull" in val:
                out[key] = val  # already normalised
            elif "target" in val and "sl" in val:
                out[key] = {
                    "bull": {"target": val["target"], "sl": val["sl"]},
                    "bear": {"target": val["sl"],     "sl": val["target"]},
                }
            else:
                out[key] = val
        return out

    def test_norm_scenario_levels_logic_flat_input(self):
        """Given {NIFTY: {target: 26649, sl: 15503}} — bull.target==26649, bear.target==15503."""
        raw = {"NIFTY": {"target": 26649.0, "sl": 15503.0}}
        result = self._norm_scenario_levels(raw)

        assert "NIFTY" in result, "NIFTY key missing from normalised output"
        assert "bull" in result["NIFTY"], "bull key missing from normalised NIFTY"
        assert "bear" in result["NIFTY"], "bear key missing from normalised NIFTY"
        assert result["NIFTY"]["bull"]["target"] == 26649.0, (
            f"bull.target should be 26649.0; got {result['NIFTY']['bull']['target']}"
        )
        assert result["NIFTY"]["bear"]["target"] == 15503.0, (
            f"bear.target should be sl value 15503.0; got {result['NIFTY']['bear']['target']}"
        )

    def test_norm_scenario_levels_bull_bear_passthrough(self):
        """Already-normalised bull/bear shape passes through unchanged."""
        raw = {
            "NIFTY": {
                "bull": {"target": 26649.0, "sl": 15503.0},
                "bear": {"target": 15503.0, "sl": 26649.0},
            }
        }
        result = self._norm_scenario_levels(raw)
        assert result["NIFTY"]["bull"]["target"] == 26649.0
        assert result["NIFTY"]["bear"]["target"] == 15503.0

    def test_norm_scenario_levels_empty_input_returns_empty(self):
        """_normScenarioLevels({}) returns {} — edge case 2: state guard must handle this."""
        result = self._norm_scenario_levels({})
        assert result == {}, (
            f"_normScenarioLevels({{}}) should return {{}}; got {result}"
        )

    def test_norm_scenario_levels_multi_instrument(self):
        """Multi-instrument input normalises all instruments correctly."""
        raw = {
            "NIFTY":     {"target": 26649.0, "sl": 15503.0},
            "BANKNIFTY": {"target": 57632.0, "sl": 33344.0},
            "ASML":      {"target": 1167.0,  "sl": 508.0},
        }
        result = self._norm_scenario_levels(raw)
        assert len(result) == 3
        # NIFTY bull/bear swap
        assert result["NIFTY"]["bull"]["target"] == 26649.0
        assert result["NIFTY"]["bear"]["target"] == 15503.0
        # ASML bull/bear swap
        assert result["ASML"]["bull"]["target"] == 1167.0
        assert result["ASML"]["bear"]["target"] == 508.0

    def test_norm_scenario_levels_sl_becomes_bear_target(self):
        """The sl value in flat input becomes the bear target (bull/bear swap contract)."""
        raw = {"NVIDIA": {"target": 191.3, "sl": 47.6}}
        result = self._norm_scenario_levels(raw)
        # bear.target == original sl
        assert result["NVIDIA"]["bear"]["target"] == 47.6
        # bear.sl == original target (the 'ceiling' of the bear scenario)
        assert result["NVIDIA"]["bear"]["sl"] == 191.3


# ---------------------------------------------------------------------------
# Test 6 — PortfolioAnalyticsResponse top-level contract (Phase 3 state fields)
# ---------------------------------------------------------------------------

class TestPortfolioAnalyticsResponsePhase3:
    """Verify PortfolioAnalyticsResponse exports all fields consumed by Phase 3 JS.

    This is the primary Phase 3 QA gate: if the backend removes or renames
    any of the 9 fields the Phase 3 JS modules read from state.*, the new
    renderers will silently receive undefined and display nothing.
    """

    # All fields consumed by Phase 3 JS modules (from Architect state field table)
    _PHASE3_STATE_FIELDS = {
        "portfolio_meta",   # my-portfolio.js — Overview KPIs
        "positions",        # my-portfolio.js — Overview positions grid + manoeuvre.js
        "market",           # my-portfolio.js — instrument selector
        "scenario_levels",  # rr.js — after _normScenarioLevels
        "payoff",           # payoff.js — portfolio-shape detection
        "stress",           # stress.js — renderAnalyticsStress
        "hedge_quality",    # hedge.js — renderPortfolioHedgeRadar
        "net_greeks",       # greeks.js — renderGreeksCards
        "greeks",           # greeks.js — renderGreeksTable (uses g.und + g.hedge_type)
    }

    def test_portfolio_analytics_response_has_all_phase3_state_fields(self):
        """PortfolioAnalyticsResponse schema has all 9 fields consumed by Phase 3 JS."""
        model_fields = set(PortfolioAnalyticsResponse.model_fields.keys())
        missing = self._PHASE3_STATE_FIELDS - model_fields
        assert not missing, (
            f"PortfolioAnalyticsResponse is missing Phase 3 state fields: {missing}\n"
            f"These are consumed by new Phase 3 JS renderers and will silently break "
            f"if absent."
        )

    def test_portfolio_analytics_response_stress_field_present(self):
        """stress field present — renderAnalyticsStress in stress.js consumes it."""
        model_fields = set(PortfolioAnalyticsResponse.model_fields.keys())
        assert "stress" in model_fields, (
            "PortfolioAnalyticsResponse missing stress field — "
            "renderAnalyticsStress will receive undefined"
        )

    def test_greek_item_schema_uses_und_and_hedge_type_not_full(self):
        """GreekItemSchema uses und + hedge_type fields (Phase 3 greeks.js fix: g.full → g.und + g.hedge_type)."""
        greek_fields = set(GreekItemSchema.model_fields.keys())
        assert "und" in greek_fields, (
            "GreekItemSchema missing und field — greeks.js Phase 3 fix requires g.und"
        )
        assert "hedge_type" in greek_fields, (
            "GreekItemSchema missing hedge_type field — greeks.js Phase 3 fix requires g.hedge_type"
        )
        assert "ann_vol_pct" in greek_fields, (
            "GreekItemSchema missing ann_vol_pct field — greeks.js Phase 3 fix requires g.ann_vol_pct"
        )
        # Verify 'full' is NOT a field (greeks.js was fixed to stop reading g.full)
        # Note: 'full' is absent from GreekItemSchema by design
        assert "full" not in greek_fields, (
            "GreekItemSchema should NOT have 'full' field — greeks.js Phase 3 uses g.und+g.hedge_type"
        )
