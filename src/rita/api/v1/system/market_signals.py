"""System router for market technical indicators time series.

ADR-001 Tier 1: single data domain (market_data cache + CSV fallback),
computes indicators and returns a time series. No DB writes.
URLs preserved from observability.py (Option A migration).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from rita.database import get_db
from rita.repositories.market_data import MarketDataCacheRepository

router = APIRouter(prefix="/api/v1", tags=["system:market-signals"])


@router.get("/market-signals", summary="Market technical indicators time series")
def market_signals(
    timeframe: str = "daily",
    periods: int = 252,
    instrument: str = "NIFTY",
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Return RSI-14, MACD, Bollinger Bands, ATR-14, EMA-5/13/26/50, trend score per bar.

    Params:
    - instrument: uppercase instrument id (default NIFTY)
    - timeframe: daily | weekly | monthly
    - periods: number of most-recent rows to return (default 252)
    """
    import numpy as np
    import pandas as pd

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
    raw_trend    = (0.4 * (ema5_s > ema13_s).astype(float)
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
