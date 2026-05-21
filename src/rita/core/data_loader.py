"""
RITA Core — Data Loader
Loads OHLCV data from the local CSV store.

Folder layout (all paths relative to the project root):
    data/raw/{INSTRUMENT}/       — source CSVs as downloaded (read-only)
    data/input/{INSTRUMENT}/     — processed/merged CSVs ready for the model
    data/output/{INSTRUMENT}/    — backtest results, risk timeline, trade events
    models/{INSTRUMENT}/         — trained model ZIPs

Expected CSV columns: date, open, high, low, close, shares traded, turnover (₹ cr)
Date format: "1999-07-01 00:00:00+05:30" (timezone-aware IST)
"""

from pathlib import Path

import numpy as np
import pandas as pd

from rita.config import settings


# ---------------------------------------------------------------------------
# Path helpers — resolve instrument-scoped directories from config
# ---------------------------------------------------------------------------

def raw_dir(instrument: str) -> Path:
    """Return the raw data directory for *instrument*, creating it if needed."""
    p = Path(settings.data.raw_dir) / instrument.upper()
    p.mkdir(parents=True, exist_ok=True)
    return p


def input_dir(instrument: str) -> Path:
    """Return the processed input directory for *instrument*, creating it if needed."""
    p = Path(settings.data.input_dir) / instrument.upper()
    p.mkdir(parents=True, exist_ok=True)
    return p


def output_dir(instrument: str) -> Path:
    """Return the output directory for *instrument*, creating it if needed."""
    p = Path(settings.data.output_dir) / instrument.upper()
    p.mkdir(parents=True, exist_ok=True)
    return p


def model_dir(instrument: str) -> Path:
    """Return the model directory for *instrument*, creating it if needed."""
    p = Path(settings.model.path) / instrument.upper()
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# CSV loader
# ---------------------------------------------------------------------------

def load_ohlcv_csv(csv_path: str) -> pd.DataFrame:
    """
    Load OHLCV data from a CSV file (instrument-agnostic).

    Returns a DataFrame with DatetimeIndex and columns:
    Open, High, Low, Close, Volume
    """
    df = pd.read_csv(csv_path)

    # Normalize column names
    df.columns = [c.strip().lower() for c in df.columns]

    # Parse and normalize the date column (strip timezone if present)
    sample = str(df["date"].iloc[0])
    if "+" in sample or len(sample) > 12:
        # Timezone-aware format: "1999-07-01 00:00:00+05:30"
        df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    elif "-" in sample and any(c.isalpha() for c in sample):
        # NSE manual format: "16-MAR-2026"
        df["date"] = pd.to_datetime(df["date"], format="%d-%b-%Y")
    else:
        # Plain ISO date: "2001-03-09"
        df["date"] = pd.to_datetime(df["date"], format="%Y-%m-%d")
    df = df.set_index("date")
    df.index.name = "Date"

    # Rename to standard OHLCV names
    rename_map = {
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "shares traded": "Volume",  # Nifty NSE column name
        "volume": "Volume",         # Generic / international column name
    }
    df = df.rename(columns=rename_map)

    # Drop unused columns
    keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    df = df[keep]

    # Sort and validate
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="first")]
    df = df.dropna(subset=["Close"])

    if len(df) == 0:
        raise ValueError(f"No valid data found in {csv_path}")

    return df


# Backward-compat alias — kept so any direct references continue to resolve.
load_nifty_csv = load_ohlcv_csv


def load_instrument_data(instrument: str) -> "pd.DataFrame":
    """Load the full OHLCV history for an instrument, appending any manual supplement.

    For instruments whose raw CSV ends before the current year (e.g. NIFTY merged.csv
    ends 2025-12-31), this function looks for a manual supplement at:
        data/input/DAILY-DATA/{instrument_lower}_manual.csv
    and concatenates it so that backtests can cover up-to-date dates.

    Returns a deduplicated, date-sorted DataFrame identical in shape to load_ohlcv_csv().
    """
    from rita.core.data_understanding import find_instrument_csv

    primary_path = find_instrument_csv(instrument)
    df = load_ohlcv_csv(str(primary_path))

    # Check for manual supplement (e.g. nifty_manual.csv for 2026 data)
    manual_path = (
        Path(settings.data.input_dir) / "DAILY-DATA" / f"{instrument.lower()}_manual.csv"
    )
    if manual_path.exists():
        df_manual = load_ohlcv_csv(str(manual_path))
        df = pd.concat([df, df_manual])
        df = df[~df.index.duplicated(keep="last")].sort_index()
        df = df.dropna(subset=["Close"])

    # Companion yf file merge (_yf.csv for instruments with companion strategy)
    # NIFTY and BANKNIFTY download a separate _yf.csv via the data refresh service.
    # Loaded independently via load_ohlcv_csv() so each file's date format is
    # handled correctly before concat. keep="last" means yfinance data wins on overlap.
    yf_path = Path(settings.data.raw_dir) / instrument.upper() / f"{instrument.lower()}_yf.csv"
    if yf_path.exists():
        df_yf = load_ohlcv_csv(str(yf_path))
        df = pd.concat([df, df_yf])
        df = df[~df.index.duplicated(keep="last")].sort_index()
        df = df.dropna(subset=["Close"])

    return df


def get_period_return_estimates(df: pd.DataFrame, period_days: int) -> dict:
    """
    Compute rolling-window return distribution for a given investment horizon.

    Slides a window of `period_days` calendar days across the full history and
    collects the total return for each window.  Returns percentile-based
    scenarios anchored to real Nifty 50 data.
    """
    close = df["Close"]

    # Convert calendar days → approximate trading days (252 / 365)
    trading_days = max(1, round(period_days * 252 / 365))

    rolling_returns = close.pct_change(trading_days).dropna() * 100

    if len(rolling_returns) < 10:
        raise ValueError(
            f"Not enough historical data to estimate {period_days}-day returns "
            f"(only {len(rolling_returns)} windows available)."
        )

    p10 = float(np.percentile(rolling_returns, 10))
    p25 = float(np.percentile(rolling_returns, 25))
    p50 = float(np.percentile(rolling_returns, 50))
    p75 = float(np.percentile(rolling_returns, 75))
    p90 = float(np.percentile(rolling_returns, 90))

    win_rate = float((rolling_returns > 0).sum() / len(rolling_returns) * 100)
    years = period_days / 365.0

    def _annualize(total_pct: float) -> float:
        total = total_pct / 100.0
        if years >= 1.0 and total > -1.0:
            return round(((1.0 + total) ** (1.0 / years) - 1.0) * 100.0, 2)
        return round(total_pct, 2)

    start_date = df.index.min().strftime("%Y-%m-%d")
    end_date   = df.index.max().strftime("%Y-%m-%d")

    return {
        "period_days":        period_days,
        "trading_days_used":  trading_days,
        "sample_windows":     len(rolling_returns),
        "data_range":         f"{start_date} to {end_date}",
        "win_rate_pct":       round(win_rate, 1),
        "scenarios": {
            "conservative": {"total_return_pct": round(p10, 2), "annualized_pct": _annualize(p10)},
            "cautious":     {"total_return_pct": round(p25, 2), "annualized_pct": _annualize(p25)},
            "median":       {"total_return_pct": round(p50, 2), "annualized_pct": _annualize(p50)},
            "optimistic":   {"total_return_pct": round(p75, 2), "annualized_pct": _annualize(p75)},
            "best_case":    {"total_return_pct": round(p90, 2), "annualized_pct": _annualize(p90)},
        },
        "suggested_target_pct": round(p10, 2),
        "note": (
            f"Conservative estimate based on 10th percentile of {len(rolling_returns)} "
            f"rolling {period_days}-day windows ({start_date} to {end_date})."
        ),
    }
