"""Experience router for RITA Pipeline tab wizard steps.

ADR-001 Tier 3: aggregated experience endpoints — goal feasibility,
market conditions snapshot, strategy config. No DB writes.
URLs: /api/v1/goal, /api/v1/market, /api/v1/strategy
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from rita.database import get_db

router = APIRouter(prefix="/api/v1", tags=["experience:pipeline-wizard"])


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _get_active_instrument_id(db: Session) -> str:
    try:
        from rita.repositories.config_overrides import ConfigOverridesRepository
        cfg = ConfigOverridesRepository(db).find_by_id("active_instrument_id")
        if cfg and cfg.value:
            return cfg.value.upper()
    except Exception:
        pass
    return "NIFTY"


def _compute_market_signals(
    db: Session,
    instrument: str,
    timeframe: str,
    periods: int,
) -> list[dict[str, Any]]:
    import numpy as np
    import pandas as pd
    from rita.repositories.market_data import MarketDataCacheRepository

    inst = instrument.upper()
    records = MarketDataCacheRepository(db).read_all()
    nifty = [r for r in records if r.underlying == inst]

    if not nifty:
        from rita.core.data_loader import load_ohlcv_csv
        from rita.core.data_understanding import find_instrument_csv
        try:
            csv_path = find_instrument_csv(inst)
            _df = load_ohlcv_csv(str(csv_path))
            daily_close  = _df["Close"].astype(float)
            daily_high   = _df["High"].astype(float)
            daily_low    = _df["Low"].astype(float)
            daily_volume = (_df["Volume"].astype(float) if "Volume" in _df.columns else pd.Series([0.0] * len(_df)))
            daily_dates  = _df.index
            bar_dates    = [str(d.date()) for d in daily_dates]
        except Exception:
            return []
    else:
        nifty.sort(key=lambda r: r.date)
        daily_close  = pd.Series([r.close for r in nifty], dtype=float)
        daily_high   = pd.Series([getattr(r, "high",  r.close) for r in nifty], dtype=float)
        daily_low    = pd.Series([getattr(r, "low",   r.close) for r in nifty], dtype=float)
        daily_volume = pd.Series([int(getattr(r, "shares_traded", None) or 0) for r in nifty], dtype=float)
        daily_dates  = pd.to_datetime([str(rec.date) for rec in nifty])
        bar_dates    = [str(rec.date) for rec in nifty]

    if timeframe in ("weekly", "monthly"):
        df_daily = pd.DataFrame(
            {"close": daily_close.values, "high": daily_high.values,
             "low": daily_low.values, "volume": daily_volume.values},
            index=daily_dates,
        )
        rule = "W-FRI" if timeframe == "weekly" else "ME"
        df = df_daily.resample(rule).agg(
            {"close": "last", "high": "max", "low": "min", "volume": "sum"}
        ).dropna(subset=["close"])
        close  = df["close"]
        high   = df["high"]
        low    = df["low"]
        volume = df["volume"]
        bar_dates = [str(d.date()) for d in df.index]
    else:
        close  = daily_close
        high   = daily_high
        low    = daily_low
        volume = daily_volume
        if nifty:
            bar_dates = [str(rec.date) for rec in nifty]

    # RSI(14)
    delta    = close.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=13, adjust=False).mean()
    avg_loss = loss.ewm(com=13, adjust=False).mean()
    rs       = avg_gain / avg_loss.replace(0, np.nan)
    rsi      = 100 - (100 / (1 + rs))

    # MACD
    ema12            = close.ewm(span=12, adjust=False).mean()
    ema26_raw        = close.ewm(span=26, adjust=False).mean()
    macd_line        = ema12 - ema26_raw
    macd_signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist_s      = macd_line - macd_signal_line

    # Bollinger Bands (20, 2σ)
    sma20      = close.rolling(20).mean()
    std20      = close.rolling(20).std()
    bb_upper_s = sma20 + 2 * std20
    bb_lower_s = sma20 - 2 * std20
    bb_range   = (bb_upper_s - bb_lower_s).replace(0, np.nan)
    bb_pct_b_s = ((close - bb_lower_s) / bb_range).clip(0, 1)

    # ATR(14)
    tr  = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(com=13, adjust=False).mean()

    # EMAs
    ema5_s  = close.ewm(span=5,  adjust=False).mean()
    ema13_s = close.ewm(span=13, adjust=False).mean()
    ema26_s = close.ewm(span=26, adjust=False).mean()
    ema50_s = close.ewm(span=50, adjust=False).mean()

    # Trend score → [-1, 1]
    raw_trend     = (0.4 * (ema5_s > ema13_s).astype(float)
                     + 0.3 * (ema13_s > ema26_s).astype(float)
                     + 0.3 * (close > ema26_s).astype(float))
    trend_score_s = (raw_trend - 0.5) * 2

    def _v(val: Any) -> Any:
        if val is None:
            return None
        try:
            f = float(val)
        except (TypeError, ValueError):
            return None
        return None if (pd.isna(f) or not np.isfinite(f)) else round(f, 4)

    rows: list[dict[str, Any]] = []
    for i in range(len(close)):
        rows.append({
            "date":        bar_dates[i],
            "Close":       _v(close.iloc[i]),
            "Volume":      int(volume.iloc[i]) if volume.iloc[i] else 0,
            "rsi_14":      _v(rsi.iloc[i]),
            "macd":        _v(macd_line.iloc[i]),
            "macd_signal": _v(macd_signal_line.iloc[i]),
            "macd_hist":   _v(macd_hist_s.iloc[i]),
            "bb_upper":    _v(bb_upper_s.iloc[i]),
            "bb_lower":    _v(bb_lower_s.iloc[i]),
            "bb_pct_b":    _v(bb_pct_b_s.iloc[i]),
            "atr_14":      _v(atr.iloc[i]),
            "ema_5":       _v(ema5_s.iloc[i]),
            "ema_13":      _v(ema13_s.iloc[i]),
            "ema_26":      _v(ema26_s.iloc[i]),
            "ema_50":      _v(ema50_s.iloc[i]),
            "trend_score": _v(trend_score_s.iloc[i]),
        })

    return rows[-periods:] if periods > 0 else rows


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class GoalRequest(BaseModel):
    target_return_pct: float
    time_horizon_days: int
    risk_tolerance: str  # "low" | "medium" | "high"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/goal", summary="Step 1 — Financial Goal feasibility analysis")
def wizard_goal(req: GoalRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    from rita.repositories.market_data import MarketDataCacheRepository

    annualised_target = req.target_return_pct * (365 / max(req.time_horizon_days, 1))
    required_monthly  = ((1 + req.target_return_pct / 100) ** (1 / max(req.time_horizon_days / 30, 1)) - 1) * 100

    if annualised_target <= 15:
        feasibility = "conservative"
    elif annualised_target <= 40:
        feasibility = "realistic"
    elif annualised_target <= 80:
        feasibility = "ambitious"
    else:
        feasibility = "unrealistic"

    records = MarketDataCacheRepository(db).read_all()
    nifty   = sorted([r for r in records if r.underlying == "NIFTY"], key=lambda r: r.date)

    last_12m_return = None
    yearly_returns: list[float] = []
    if nifty:
        import pandas as pd
        closes     = pd.Series([r.close for r in nifty], dtype=float)
        dates_idx  = pd.to_datetime([str(r.date) for r in nifty])
        s          = pd.Series(closes.values, index=dates_idx)
        annual     = s.resample("YE").last().pct_change().dropna() * 100
        yearly_returns = [round(float(v), 2) for v in annual.values]

        cutoff = dates_idx[-1] - pd.DateOffset(months=12)
        past   = s[s.index >= cutoff]
        if len(past) >= 2:
            last_12m_return = round((float(past.iloc[-1]) / float(past.iloc[0]) - 1) * 100, 2)

    return {
        "step": 1,
        "name": "Financial Goal",
        "result": {
            "target_return_pct":  req.target_return_pct,
            "time_horizon_days":  req.time_horizon_days,
            "risk_tolerance":     req.risk_tolerance,
            "annualised_target":  round(annualised_target, 2),
            "required_monthly":   round(required_monthly, 2),
            "feasibility":        feasibility,
            "nifty_yearly_returns": yearly_returns,
            "last_12m_return":    last_12m_return,
        },
    }


def _enrich_latest(latest: dict[str, Any], series: list[dict[str, Any]]) -> dict[str, Any]:
    """Add derived label fields that renderMarketResult expects."""
    enriched = dict(latest)

    # Normalise casing: JS reads r.close (lowercase)
    enriched["close"] = enriched.pop("Close", enriched.get("close"))

    # Trend label from trend_score
    ts = enriched.get("trend_score")
    if ts is not None:
        enriched["trend"] = "uptrend" if ts > 0.1 else ("downtrend" if ts < -0.1 else "sideways")

    # RSI-derived labels
    rsi = enriched.get("rsi_14")
    if rsi is not None:
        enriched["rsi_signal"]      = "overbought" if rsi > 70 else ("oversold" if rsi < 30 else "neutral")
        enriched["sentiment_proxy"] = "complacent" if rsi > 70 else ("fearful" if rsi < 30 else "neutral")

    # MACD signal label (macd vs macd_signal_line numeric)
    macd_val  = enriched.get("macd")
    macd_line = enriched.get("macd_signal")  # numeric signal line from _compute_market_signals
    if macd_val is not None and macd_line is not None:
        enriched["macd_signal_line"] = macd_line
        enriched["macd_signal"]      = "bullish" if macd_val > macd_line else "bearish"

    # BB position label
    bb = enriched.get("bb_pct_b")
    if bb is not None:
        enriched["bb_position"] = "near_upper_band" if bb > 0.8 else ("near_lower_band" if bb < 0.2 else "middle")

    # ATR percentile over the full series
    if series:
        atr_vals = [r.get("atr_14") for r in series if r.get("atr_14") is not None]
        current_atr = enriched.get("atr_14")
        if atr_vals and current_atr is not None:
            below = sum(1 for v in atr_vals if v <= current_atr)
            enriched["atr_percentile"] = round(below / len(atr_vals) * 100, 1)

    return enriched


@router.post("/market", summary="Step 2 — Market conditions snapshot")
def wizard_market(db: Session = Depends(get_db)) -> dict[str, Any]:
    instrument = _get_active_instrument_id(db)
    signals    = _compute_market_signals(db, instrument=instrument, timeframe="daily", periods=252)

    latest = _enrich_latest(signals[-1], signals) if signals else {}
    return {
        "step": 2,
        "name": "Market Analysis",
        "result": {
            "instrument": instrument,
            "bars_returned": len(signals),
            "latest": latest,
            "series": signals,
        },
    }


@router.post("/strategy", summary="Step 3 — Strategy design from settings")
def wizard_strategy(db: Session = Depends(get_db)) -> dict[str, Any]:
    from rita.config import get_settings
    s = get_settings()
    return {
        "step": 3,
        "name": "Strategy Design",
        "status": "ok",
        "result": {
            "algorithm":  "DoubleDQN",
            "timesteps":  getattr(s, "timesteps", 200000),
            "learning_rate": getattr(s, "learning_rate", 0.0001),
            "batch_size": getattr(s, "batch_size", 64),
            "gamma":      getattr(s, "gamma", 0.99),
            "instrument": _get_active_instrument_id(db),
        },
    }
