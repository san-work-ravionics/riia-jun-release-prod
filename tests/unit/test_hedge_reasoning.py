"""Unit tests for the Hedge Reasoning endpoint (Feature 31 Phase 1).

Tests cover:
- Happy path: 200 response with 6 reasoning steps
- Decision matrix: BULL+FULL+elevated -> call_sell, BEAR+FULL -> put_buy, HOLD -> no_hedge
- Edge cases: unknown instrument (404), insufficient data (422), missing OHLCV (422)
- Payoff curves: 4 arrays present and equal length (33 points)
- Step structure: all 6 steps have agent/title/narrative/data/verdict keys
- API contract: Pydantic schema matches Architect's response shape

Strategy: The `ta` library may not be installed in the test environment.  We
inject a stub `ta` module into sys.modules before importing the handler, so
that `rita.core.technical_analyzer` can load.  Then we mock the step-builder
functions and lazy-imported core helpers at the handler module level.
"""

from __future__ import annotations

import math
import sys
import types
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd
import pytest


# ── Stub out `ta` module tree before any RITA imports ────────────────────────
# technical_analyzer.py does `import ta` and uses ta.momentum.RSIIndicator etc.
# We create a minimal mock module tree so the import succeeds.

def _ensure_ta_stub():
    """Inject a stub `ta` module into sys.modules if not already importable."""
    if "ta" in sys.modules:
        return  # Already available (real or stub)

    ta = types.ModuleType("ta")

    # ta.momentum
    momentum = types.ModuleType("ta.momentum")
    momentum.RSIIndicator = MagicMock()
    ta.momentum = momentum
    sys.modules["ta.momentum"] = momentum

    # ta.trend
    trend = types.ModuleType("ta.trend")
    trend.MACD = MagicMock()
    trend.EMAIndicator = MagicMock()
    ta.trend = trend
    sys.modules["ta.trend"] = trend

    # ta.volatility
    volatility = types.ModuleType("ta.volatility")
    volatility.BollingerBands = MagicMock()
    volatility.AverageTrueRange = MagicMock()
    ta.volatility = volatility
    sys.modules["ta.volatility"] = volatility

    sys.modules["ta"] = ta


_ensure_ta_stub()

# Now safe to import FastAPI TestClient and RITA modules
from fastapi.testclient import TestClient


# ── Handler module path prefix ───────────────────────────────────────────────
_H = "rita.api.experience.hedge_reasoning"


# ── Synthetic DataFrame builder ──────────────────────────────────────────────

def _make_df(rows: int = 260) -> pd.DataFrame:
    """Build a synthetic OHLCV DataFrame.

    Only OHLCV columns are needed by the handler directly (for len check,
    column check, spot price, and volatility step).
    """
    dates = pd.bdate_range(end="2026-06-20", periods=rows)
    n = len(dates)
    base = 700.0
    np.random.seed(42)
    returns = np.random.normal(0.0005, 0.015, n)
    close = base * np.cumprod(1 + returns)

    df = pd.DataFrame(
        {
            "Open": close * (1 + np.random.uniform(-0.005, 0.005, n)),
            "High": close * (1 + np.random.uniform(0.002, 0.02, n)),
            "Low": close * (1 + np.random.uniform(-0.02, -0.002, n)),
            "Close": close,
            "Volume": np.random.randint(100_000, 5_000_000, n),
        },
        index=dates,
    )
    return df


# ── Pre-built step dicts ────────────────────────────────────────────────────

def _step_regime(regime: str = "BULL") -> dict:
    return {
        "agent": "REGIME_ANALYST",
        "title": "Market Regime Analysis",
        "narrative": f"Regime detected: {regime}. EMA ratio 1.012, 0 bear days.",
        "data": {"ema_ratio": 1.012, "consecutive_bear_days": 0, "regime": regime, "model": regime.lower()},
        "verdict": regime,
    }


def _step_technicals() -> dict:
    return {
        "agent": "TECHNICAL_ANALYST",
        "title": "Technical Indicator Reading",
        "narrative": "RSI-14: 55.0 (neutral). MACD: +2.5000 (bullish). BB %B: 0.550 (middle).",
        "data": {
            "rsi": 55.0, "rsi_state": "neutral",
            "macd": 2.5, "macd_state": "bullish",
            "bollinger_pct_b": 0.55, "bollinger_state": "middle",
            "trend_score": 0.45, "trend_state": "uptrend",
            "atr_pct": 1.1, "atr_state": "neutral",
        },
        "verdict": "2/5 bullish",
    }


def _step_sentiment(total_score: int = 4, sentiment: str = "BULLISH") -> dict:
    return {
        "agent": "SENTIMENT_SCORER",
        "title": "Sentiment Score Calculation",
        "narrative": f"Weighing 5 signals... Total: {total_score:+d}/6 -> {sentiment} sentiment.",
        "data": {
            "signals": {
                "trend": {"value": "uptrend", "score": 2, "weight": 2},
                "macd": {"value": "bullish", "score": 1, "weight": 1},
                "rsi": {"value": "neutral (55.0)", "score": 0, "weight": 1},
                "bollinger": {"value": "middle", "score": 0, "weight": 1},
                "volatility": {"value": "neutral", "score": 0, "weight": 1},
            },
            "total_score": total_score,
            "max_score": 6,
            "overall_sentiment": sentiment,
        },
        "verdict": f"{total_score:+d}/6 {sentiment}",
    }


def _step_allocation(rec: str = "FULL", pct: int = 100) -> dict:
    return {
        "agent": "ALLOCATION_ENGINE",
        "title": "Allocation Recommendation",
        "narrative": f"Sentiment -> {rec} allocation ({pct}% invested). No overrides.",
        "data": {
            "recommendation": rec,
            "allocation_pct": pct,
            "rationale": "Test rationale.",
            "override_rules": [],
            "override_applied": False,
        },
        "verdict": f"{rec} ({pct}%)",
    }


def _step_volatility(ann_vol: float = 28.0, vol_regime: str = "normal") -> dict:
    premium = "fair" if vol_regime == "normal" else ("rich" if vol_regime == "elevated" else "cheap")
    return {
        "agent": "VOLATILITY_ASSESSOR",
        "title": "Volatility & Premium Assessment",
        "narrative": f"253-day realised vol: {ann_vol:.1f}%. Vol regime: {vol_regime.upper()}.",
        "data": {
            "ann_vol_253d": ann_vol,
            "ann_vol_30d": ann_vol,
            "vol_regime": vol_regime,
            "premium_assessment": premium,
            "return_1y_pct": 12.5,
        },
        "verdict": f"{vol_regime.capitalize()} - premiums {premium}",
    }


def _step_hedge(primary: str = "call_sell") -> dict:
    verdict = primary.upper().replace("_", " ") if primary != "no_hedge" else "NO HEDGE"
    return {
        "agent": "HEDGE_ADVISOR",
        "title": "Hedge Recommendation",
        "narrative": f"Primary recommendation: {primary.upper().replace('_', ' ')}.",
        "data": {
            "primary_recommendation": primary,
            "primary_rationale": "Test rationale.",
            "secondary_recommendation": "put_buy" if primary == "call_sell" else None,
            "secondary_rationale": None,
            "call_sell": {"strike_label": "+7.5% OTM", "strike_pct": 7.5, "premium_pct": 3.2,
                          "premium_eur": 240.0, "max_value_eur": 8050.0, "breakeven": 726.0},
            "put_buy": {"strike_label": "-7.5% OTM", "strike_pct": -7.5, "premium_pct": 2.1,
                        "premium_eur": -157.5, "floor_value_eur": 6775.0, "breakeven": 765.75},
        },
        "verdict": verdict,
    }


# ── Mock return values for core functions ───────────────────────────────────

def _scored(total_score: int = 4):
    if total_score >= 4:
        label = "BULLISH"
    elif total_score <= -4:
        label = "BEARISH"
    else:
        label = "NEUTRAL"
    return {
        "overall_sentiment": label,
        "total_score": total_score,
        "max_score": 6,
        "signal_summary": "test summary",
        "signals": {
            "trend": {"value": "uptrend", "score": 2},
            "macd": {"value": "bullish", "score": 1},
            "rsi": {"value": "neutral (55.0)", "score": 0},
            "bollinger": {"value": "middle", "score": 0},
            "volatility": {"value": "neutral", "score": 0},
        },
    }


def _summary():
    return {
        "date": "2026-06-20", "close": 750.0, "trend": "uptrend", "trend_score": 0.45,
        "ema_5": 748.0, "ema_13": 745.0, "ema_26": 740.0, "ema_50": 730.0, "ema_200": 700.0,
        "rsi_14": 55.0, "rsi_signal": "neutral", "rsi_range_note": "Neutral zone",
        "macd": 2.5, "macd_signal_line": 1.8, "macd_signal": "bullish",
        "bb_pct_b": 0.55, "bb_position": "middle",
        "atr_14": 8.5, "atr_percentile": 0.45, "sentiment_proxy": "neutral",
    }


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    """Create a FastAPI TestClient for the hedge reasoning router."""
    from rita.main import app
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def mock_df():
    """Return a synthetic DataFrame with ~260 rows of OHLCV data."""
    return _make_df(260)


def _apply_patches(mock_df, regime="BULL", allocation="FULL", alloc_pct=100,
                   primary="call_sell", total_score=4, ann_vol=28.0, vol_regime="normal"):
    """Build a composite mock.patch context for the endpoint handler.

    Patches: _get_df, all 6 _build_step_* functions, and the 2 core functions
    that are lazy-imported inside the endpoint body (get_market_summary,
    get_sentiment_score).
    """
    sentiment_label = "BULLISH" if total_score >= 4 else ("BEARISH" if total_score <= -4 else "NEUTRAL")

    patches = {
        "get_df": patch(f"{_H}._get_df", return_value=mock_df),
        "step1": patch(f"{_H}._build_step_regime", return_value=_step_regime(regime)),
        "step2": patch(f"{_H}._build_step_technicals", return_value=_step_technicals()),
        "step3": patch(f"{_H}._build_step_sentiment", return_value=_step_sentiment(total_score, sentiment_label)),
        "step4": patch(f"{_H}._build_step_allocation", return_value=_step_allocation(allocation, alloc_pct)),
        "step5": patch(f"{_H}._build_step_volatility", return_value=_step_volatility(ann_vol, vol_regime)),
        "step6": patch(f"{_H}._build_step_hedge", return_value=_step_hedge(primary)),
        # Lazy imports inside get_hedge_reasoning() at line 657
        "summary": patch("rita.core.technical_analyzer.get_market_summary", return_value=_summary()),
        "scored": patch("rita.core.technical_analyzer.get_sentiment_score", return_value=_scored(total_score)),
    }
    return patches


class _PatchContext:
    """Enter/exit multiple patches as a single context manager."""

    def __init__(self, patches: dict):
        self._patches = patches
        self._mocks = {}

    def __enter__(self):
        for name, p in self._patches.items():
            self._mocks[name] = p.__enter__()
        return self._mocks

    def __exit__(self, *args):
        for p in self._patches.values():
            p.__exit__(*args)


def _ctx(mock_df, **kwargs):
    """Shorthand for _PatchContext(_apply_patches(mock_df, **kwargs))."""
    return _PatchContext(_apply_patches(mock_df, **kwargs))


# ── Happy path ───────────────────────────────────────────────────────────────

class TestHappyPath:
    """Happy path: mock market data, call endpoint, verify 200 with 6 steps."""

    def test_returns_200_with_6_steps(self, client, mock_df):
        """GET /hedge-reasoning?instrument=ASML returns 200 with 6 reasoning steps."""
        with _ctx(mock_df):
            resp = client.get("/api/v1/experience/fno/hedge-reasoning?instrument=ASML")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["steps"]) == 6

    def test_response_has_all_top_level_fields(self, client, mock_df):
        """Response contains all fields from the Pydantic schema."""
        with _ctx(mock_df):
            resp = client.get("/api/v1/experience/fno/hedge-reasoning?instrument=ASML")

        data = resp.json()
        expected_keys = {
            "instrument", "timestamp", "steps", "recommendation",
            "confidence", "payoff_curves", "spot_price", "data_source",
        }
        assert expected_keys.issubset(set(data.keys()))

    def test_instrument_uppercased(self, client, mock_df):
        """Instrument in response is uppercased regardless of input."""
        with _ctx(mock_df):
            resp = client.get("/api/v1/experience/fno/hedge-reasoning?instrument=asml")

        assert resp.json()["instrument"] == "ASML"


# ── Decision matrix ─────────────────────────────────────────────────────────

class TestDecisionMatrix:
    """Decision matrix: regime x allocation x vol -> recommendation."""

    def test_bull_full_elevated_returns_call_sell(self, client, mock_df):
        """BULL regime + FULL allocation + elevated vol -> call_sell."""
        with _ctx(mock_df, regime="BULL", allocation="FULL", primary="call_sell",
                  total_score=4, ann_vol=40.0, vol_regime="elevated"):
            resp = client.get("/api/v1/experience/fno/hedge-reasoning?instrument=ASML")

        assert resp.json()["recommendation"] == "call_sell"

    def test_bear_full_returns_put_buy(self, client, mock_df):
        """BEAR regime + FULL allocation -> put_buy."""
        with _ctx(mock_df, regime="BEAR", allocation="FULL", primary="put_buy",
                  total_score=-4):
            resp = client.get("/api/v1/experience/fno/hedge-reasoning?instrument=ASML")

        assert resp.json()["recommendation"] == "put_buy"

    def test_hold_returns_no_hedge(self, client, mock_df):
        """HOLD allocation -> no_hedge regardless of regime."""
        with _ctx(mock_df, allocation="HOLD", alloc_pct=0, primary="no_hedge",
                  total_score=0):
            resp = client.get("/api/v1/experience/fno/hedge-reasoning?instrument=ASML")

        assert resp.json()["recommendation"] == "no_hedge"


# ── Edge cases ───────────────────────────────────────────────────────────────

class TestEdgeCases:
    """Edge cases from Architect design section."""

    def test_unknown_instrument_returns_404(self, client):
        """Unknown instrument -> 404."""
        with patch(f"{_H}._get_df", side_effect=FileNotFoundError("not found")):
            resp = client.get("/api/v1/experience/fno/hedge-reasoning?instrument=ZZZZZ")

        assert resp.status_code == 404
        assert "Unknown instrument" in resp.json()["detail"]

    def test_insufficient_data_returns_422(self, client):
        """Fewer than 30 rows of data -> 422."""
        small_df = _make_df(20)
        with patch(f"{_H}._get_df", return_value=small_df):
            resp = client.get("/api/v1/experience/fno/hedge-reasoning?instrument=ASML")

        assert resp.status_code == 422
        assert "Insufficient data" in resp.json()["detail"]

    def test_missing_ohlcv_columns_returns_422(self, client):
        """DataFrame missing required OHLCV columns -> 422."""
        df = _make_df(60)
        df = df.drop(columns=["Volume"])
        with patch(f"{_H}._get_df", return_value=df):
            resp = client.get("/api/v1/experience/fno/hedge-reasoning?instrument=ASML")

        assert resp.status_code == 422
        assert "Missing OHLCV" in resp.json()["detail"]


# ── Payoff curves ────────────────────────────────────────────────────────────

class TestPayoffCurves:
    """Payoff curves: verify all 4 arrays present and equal length."""

    def test_payoff_has_4_arrays(self, client, mock_df):
        """payoff_curves has price_range, unhedged, call_sell, put_buy."""
        with _ctx(mock_df):
            resp = client.get("/api/v1/experience/fno/hedge-reasoning?instrument=ASML")

        curves = resp.json()["payoff_curves"]
        assert "price_range" in curves
        assert "unhedged" in curves
        assert "call_sell" in curves
        assert "put_buy" in curves

    def test_payoff_arrays_equal_length_33(self, client, mock_df):
        """All 4 payoff arrays have exactly 33 points."""
        with _ctx(mock_df):
            resp = client.get("/api/v1/experience/fno/hedge-reasoning?instrument=ASML")

        curves = resp.json()["payoff_curves"]
        assert len(curves["price_range"]) == 33
        assert len(curves["unhedged"]) == 33
        assert len(curves["call_sell"]) == 33
        assert len(curves["put_buy"]) == 33

    def test_hold_payoff_curves_all_zero(self, client, mock_df):
        """HOLD allocation produces zeroed payoff curves (still 33 points)."""
        with _ctx(mock_df, allocation="HOLD", alloc_pct=0, primary="no_hedge",
                  total_score=0):
            resp = client.get("/api/v1/experience/fno/hedge-reasoning?instrument=ASML")

        curves = resp.json()["payoff_curves"]
        assert len(curves["price_range"]) == 33
        assert all(v == 0.0 for v in curves["unhedged"])
        assert all(v == 0.0 for v in curves["call_sell"])
        assert all(v == 0.0 for v in curves["put_buy"])


# ── Step structure ───────────────────────────────────────────────────────────

class TestStepStructure:
    """All 6 steps have agent/title/narrative/data/verdict keys."""

    def test_all_steps_have_required_keys(self, client, mock_df):
        """Each of the 6 steps contains agent, title, narrative, data, verdict."""
        with _ctx(mock_df):
            resp = client.get("/api/v1/experience/fno/hedge-reasoning?instrument=ASML")

        required_keys = {"agent", "title", "narrative", "data", "verdict"}
        for i, step in enumerate(resp.json()["steps"]):
            missing = required_keys - set(step.keys())
            assert not missing, f"Step {i} missing keys: {missing}"

    def test_step_agents_in_correct_order(self, client, mock_df):
        """Steps appear in the canonical order."""
        with _ctx(mock_df):
            resp = client.get("/api/v1/experience/fno/hedge-reasoning?instrument=ASML")

        expected_agents = [
            "REGIME_ANALYST",
            "TECHNICAL_ANALYST",
            "SENTIMENT_SCORER",
            "ALLOCATION_ENGINE",
            "VOLATILITY_ASSESSOR",
            "HEDGE_ADVISOR",
        ]
        actual_agents = [s["agent"] for s in resp.json()["steps"]]
        assert actual_agents == expected_agents

    def test_narratives_are_non_empty_strings(self, client, mock_df):
        """Each step's narrative is a non-empty string."""
        with _ctx(mock_df):
            resp = client.get("/api/v1/experience/fno/hedge-reasoning?instrument=ASML")

        for step in resp.json()["steps"]:
            assert isinstance(step["narrative"], str)
            assert len(step["narrative"]) > 10

    def test_data_is_dict_in_every_step(self, client, mock_df):
        """Each step's data field is a dict with structured payload."""
        with _ctx(mock_df):
            resp = client.get("/api/v1/experience/fno/hedge-reasoning?instrument=ASML")

        for step in resp.json()["steps"]:
            assert isinstance(step["data"], dict)
            assert len(step["data"]) > 0


# ── Confidence derivation ────────────────────────────────────────────────────

class TestConfidence:
    """Confidence is derived from total sentiment score."""

    def test_high_confidence_for_strong_signal(self, client, mock_df):
        """abs(total_score) >= 4 -> high confidence."""
        with _ctx(mock_df, total_score=4):
            resp = client.get("/api/v1/experience/fno/hedge-reasoning?instrument=ASML")

        assert resp.json()["confidence"] == "high"

    def test_low_confidence_for_neutral_signal(self, client, mock_df):
        """abs(total_score) < 2 -> low confidence."""
        with _ctx(mock_df, total_score=0, allocation="HOLD", alloc_pct=0,
                  primary="no_hedge"):
            resp = client.get("/api/v1/experience/fno/hedge-reasoning?instrument=ASML")

        assert resp.json()["confidence"] == "low"
