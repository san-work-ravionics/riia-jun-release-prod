"""RITA Core — Data Understanding

Computes statistical summaries, distributions, correlations, time series
and K-means clustering for a given instrument's OHLCV CSV.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

from rita.config import get_settings
from rita.core.data_loader import load_ohlcv_csv


# ── CSV discovery ──────────────────────────────────────────────────────────────

def find_instrument_csv(instrument_id: str) -> Path:
    """Return the best CSV path for an instrument.

    Dynamic glob-based resolution — no hardcoded paths per instrument.

    NIFTY exception: primary = data/raw/NIFTY/merged.csv
    BANKNIFTY exception: primary = data/raw/BANKNIFTY/banknifty_daily_25yr_rounded.csv

    For all other instruments:
      Priority 1: first CSV in data/raw/{TICKER}/
      Priority 2: first CSV in data/input/{TICKER}/  (fallback)
    """
    cfg = get_settings()
    uid = instrument_id.upper()
    raw_dir = Path(cfg.data.raw_dir) / uid
    input_dir = Path(cfg.data.input_dir) / uid

    # NIFTY — merged pre-built file takes priority
    if uid == "NIFTY":
        merged = raw_dir / "merged.csv"
        if merged.exists():
            return merged

    # BANKNIFTY — explicit named file
    if uid == "BANKNIFTY":
        named = raw_dir / "banknifty_daily_25yr_rounded.csv"
        if named.exists():
            return named

    # Generic instruments — glob raw dir first, then input dir
    csvs = sorted(raw_dir.glob("*.csv"), key=lambda p: p.stat().st_size, reverse=True)
    if csvs:
        return csvs[0]

    csvs = sorted(input_dir.glob("*.csv"), key=lambda p: p.stat().st_size, reverse=True)
    if csvs:
        return csvs[0]

    raise FileNotFoundError(
        f"No CSV data found for instrument '{instrument_id}'. "
        f"Expected files in {raw_dir} or {input_dir}."
    )


# ── Technical indicators ───────────────────────────────────────────────────────

def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _macd(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    macd_line = _ema(series, 12) - _ema(series, 26)
    signal = _ema(macd_line, 9)
    return macd_line, signal


def _bollinger_pct_b(series: pd.Series, period: int = 20) -> pd.Series:
    sma = series.rolling(period).mean()
    std = series.rolling(period).std()
    upper = sma + 2 * std
    lower = sma - 2 * std
    band_width = (upper - lower).replace(0, np.nan)
    return (series - lower) / band_width


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["daily_return"]  = df["Close"].pct_change() * 100
    df["log_return"]    = np.log(df["Close"] / df["Close"].shift(1)) * 100
    df["rsi_14"]        = _rsi(df["Close"])
    df["macd"], _       = _macd(df["Close"])
    df["bb_pct_b"]      = _bollinger_pct_b(df["Close"])
    df["volatility_20"] = df["daily_return"].rolling(20).std() * np.sqrt(252)
    return df


# ── Histogram helper ───────────────────────────────────────────────────────────

def _histogram(series: pd.Series, bins: int = 30) -> dict[str, Any]:
    clean = series.dropna()
    if clean.empty:
        return {"labels": [], "values": []}
    counts, edges = np.histogram(clean, bins=bins)
    labels = [f"{round(float(edges[i]), 4)}" for i in range(len(edges) - 1)]
    return {"labels": labels, "values": [int(c) for c in counts]}


# ── Clustering helpers (sklearn) ───────────────────────────────────────────────

def _fit_kmeans(Xs: np.ndarray, k: int, seed: int = 42) -> KMeans:
    km = KMeans(n_clusters=k, random_state=seed, n_init="auto")
    km.fit(Xs)
    return km


def _pca2(Xs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    pca = PCA(n_components=2)
    proj = pca.fit_transform(Xs)
    return proj[:, 0], proj[:, 1]


# ── Main entry point ────────────────────────────────────────────────────────────

def compute_understanding(instrument_id: str) -> dict[str, Any]:
    """Load instrument CSV, compute all sections and return the full payload."""

    csv_path = find_instrument_csv(instrument_id)
    raw = load_ohlcv_csv(str(csv_path))
    df  = add_indicators(raw)

    # ── Summary ───────────────────────────────────────────────────────────────
    rows      = len(df)
    feat_cols = ["daily_return", "log_return", "rsi_14", "macd", "bb_pct_b", "volatility_20"]
    avail     = [c for c in feat_cols if c in df.columns]
    date_from = str(df.index.min().date()) if hasattr(df.index.min(), "date") else str(df.index.min())[:10]
    date_to   = str(df.index.max().date()) if hasattr(df.index.max(), "date") else str(df.index.max())[:10]

    total_cells  = rows * len(df.columns)
    missing_cnt  = int(df.isnull().sum().sum())
    missing_pct  = round(missing_cnt / total_cells * 100, 2) if total_cells else 0.0

    # Trend classes: Bear / Neutral / Bull
    trend_classes = 3

    summary = {
        "rows":          rows,
        "features":      len(avail),
        "date_from":     date_from,
        "date_to":       date_to,
        "missing_pct":   missing_pct,
        "trend_classes": trend_classes,
    }

    # ── Distributions ─────────────────────────────────────────────────────────
    DIST_COLS = {
        "close":        ("Close",        "Close Price"),
        "daily_return": ("daily_return", "Daily Return (%)"),
        "rsi_14":       ("rsi_14",       "RSI (14)"),
        "volume":       ("Volume",       "Volume"),
        "macd":         ("macd",         "MACD"),
        "log_return":   ("log_return",   "Log Return (%)"),
        "bb_pct_b":     ("bb_pct_b",     "Bollinger %B"),
        "volatility_20":("volatility_20","Volatility 20d"),
    }
    distributions: dict[str, Any] = {}
    for key, (col, label) in DIST_COLS.items():
        if col in df.columns:
            h = _histogram(df[col])
            distributions[key] = {"label": label, **h}

    # ── Correlation ───────────────────────────────────────────────────────────
    corr_cols = ["Close", "daily_return", "rsi_14", "macd", "bb_pct_b", "volatility_20"]
    corr_cols = [c for c in corr_cols if c in df.columns]
    corr_df   = df[corr_cols].dropna()
    corr_matrix = corr_df.corr().round(4).values.tolist()
    correlation = {
        "features": corr_cols,
        "matrix":   corr_matrix,
    }

    # ── Time Series (downsample to max 500 points) ────────────────────────────
    ts_df    = df[["Close", "Volume", "rsi_14", "macd"]].copy()
    step     = max(1, len(ts_df) // 500)
    ts_df    = ts_df.iloc[::step]
    dates    = [str(d.date()) if hasattr(d, "date") else str(d)[:10] for d in ts_df.index]
    vol_col  = ts_df["Volume"].tolist() if "Volume" in ts_df.columns else []

    timeseries = {
        "dates":  dates,
        "close":  [round(float(v), 2) if pd.notna(v) else None for v in ts_df["Close"]],
        "volume": [int(v) if pd.notna(v) and v == v else None for v in vol_col],
        "rsi":    [round(float(v), 2) if pd.notna(v) else None for v in ts_df["rsi_14"]],
        "macd":   [round(float(v), 4) if pd.notna(v) else None for v in ts_df["macd"]],
    }

    # ── Clustering (sklearn) ──────────────────────────────────────────────────
    clustering: dict[str, Any] = {}
    try:
        feat_df = df[avail].dropna()
        if len(feat_df) > 50:
            X = feat_df.values.astype(float)

            # Standardise with sklearn
            scaler = StandardScaler()
            Xs = scaler.fit_transform(X)

            # Elbow: k = 2..6
            k_range = list(range(2, 7))
            inertias = []
            for k in k_range:
                km = _fit_kmeans(Xs, k)
                inertias.append(round(float(km.inertia_), 2))
            clustering["elbow"] = {"k": k_range, "inertia": inertias}

            # PCA scatter with k=3
            km3 = _fit_kmeans(Xs, 3)
            labels_k3 = km3.labels_

            # Downsample PCA points to 300 max
            n = min(300, len(Xs))
            idx = np.round(np.linspace(0, len(Xs) - 1, n)).astype(int)
            px, py = _pca2(Xs[idx])
            clustering["pca"] = {
                "x":       [round(float(v), 4) for v in px],
                "y":       [round(float(v), 4) for v in py],
                "cluster": [int(v) for v in labels_k3[idx]],
            }
    except Exception:  # noqa: BLE001 — clustering is best-effort
        pass

    return {
        "instrument_id": instrument_id.upper(),
        "csv_path":      str(csv_path),
        "summary":       summary,
        "distributions": distributions,
        "correlation":   correlation,
        "timeseries":    timeseries,
        "clustering":    clustering,
    }
