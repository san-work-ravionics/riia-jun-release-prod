"""RITA Core — Portfolio Engine

Provides two pure-computation entry points consumed by the portfolio API router:

- portfolio_overview()  — load all 4 instruments, align dates, return normalized
                          prices and return correlation matrix.
- portfolio_backtest()  — run each instrument's trained DDQN model over the
                          selected period, combine with EUR-weighted allocations,
                          return combined Sharpe / MDD / daily series.

Whole-share constraint:
    Each allocation is converted to a number of whole shares using the
    approximate FX rate.  Uninvested capital (remainder) stays flat at 1.0.
    This means a €250 allocation into ASML (~€700/share) yields 0 shares and
    no RL exposure — the user sees a cash return of 0%.

FX rates (static approximations — sufficient for exploration):
    EUR/INR ≈ 91  →  1 INR = 1/91 EUR
    EUR/USD ≈ 1.09 → 1 USD = 1/1.09 EUR
    EUR/EUR = 1.0
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import norm
import structlog

from rita.config import get_settings
from rita.core.data_loader import load_ohlcv_csv
from rita.core.data_understanding import find_instrument_csv
from rita.core.technical_analyzer import calculate_indicators
from rita.core.performance import compute_all_metrics, sharpe_ratio

log = structlog.get_logger()

# ── Constants ──────────────────────────────────────────────────────────────────

FX_EUR_PER_UNIT: dict[str, float] = {
    "INR": 1 / 91.0,
    "EUR": 1.0,
    "USD": 1 / 1.09,
}

INSTRUMENT_CCY: dict[str, str] = {
    "NIFTY":     "INR",
    "BANKNIFTY": "INR",
    "ASML":      "EUR",
    "NVIDIA":    "USD",
}

INSTRUMENT_NAMES: dict[str, str] = {
    "NIFTY":     "NIFTY 50",
    "BANKNIFTY": "BANKNIFTY",
    "ASML":      "ASML",
    "NVIDIA":    "NVIDIA",
}

ALL_INSTRUMENTS = list(INSTRUMENT_CCY.keys())
TRADING_DAYS = 252


# ── Internal helpers ───────────────────────────────────────────────────────────

def _load_with_indicators(instrument_id: str) -> pd.DataFrame:
    """Load OHLCV CSV and compute technical indicators. Returns DatetimeIndex df."""
    csv_path = find_instrument_csv(instrument_id)
    df = load_ohlcv_csv(str(csv_path))
    return calculate_indicators(df)


def _find_best_model(instrument_id: str) -> Path | None:
    """Return the most recently modified .zip model for the instrument, or None."""
    cfg = get_settings()
    model_dir = Path(cfg.model.path) / instrument_id.upper()
    if not model_dir.exists():
        return None
    zips = sorted(model_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    return zips[0] if zips else None


def _invested_fraction(alloc_eur: float, price_eur: float) -> float:
    """Whole-share constraint: fraction of alloc_eur that is actually invested.

    Examples:
        alloc=250, price=700  → 0 shares → 0.0 fraction
        alloc=250, price=2.64 → 94 shares → 248.16/250 ≈ 0.993 fraction
        alloc=1000, price=700 → 1 share  → 700/1000 = 0.70 fraction
    """
    if price_eur <= 0 or alloc_eur <= 0:
        return 0.0
    n = math.floor(alloc_eur / price_eur)
    return min(n * price_eur / alloc_eur, 1.0)


def _adjust_for_cash(port_values: list[float], invested_frac: float) -> list[float]:
    """Scale portfolio values to account for uninvested cash (whole-share constraint).

    Adjusted_value[t] = invested_frac * port_value[t] + (1 - invested_frac) * 1.0
    Cash portion remains at its initial value (1.0, normalised cost basis).
    """
    c = 1.0 - invested_frac
    return [invested_frac * v + c for v in port_values]


# ── Portfolio Overview ─────────────────────────────────────────────────────────

def portfolio_overview() -> dict[str, Any]:
    """Cross-instrument overview: normalised prices + daily return correlation.

    Loads all 4 instruments, aligns to their common date intersection, then
    computes normalised Close prices and a Pearson correlation matrix of daily
    returns.  The normalised price series is down-sampled to ≤ 500 points to
    keep the JSON payload small.

    Returns:
        instruments: per-instrument metadata (rows, date range, currency)
        common_days: number of aligned trading days
        date_from / date_to: extent of the common window
        normalized_returns: [{date, nifty, banknifty, asml, nvidia}, ...]
        correlation_matrix: {nifty: {banknifty: 0.42, ...}, ...}
    """
    dfs: dict[str, pd.DataFrame] = {}
    instrument_meta: list[dict] = []

    for iid in ALL_INSTRUMENTS:
        try:
            df = _load_with_indicators(iid)
            dfs[iid] = df
            instrument_meta.append({
                "id":        iid.lower(),
                "name":      INSTRUMENT_NAMES[iid],
                "currency":  INSTRUMENT_CCY[iid],
                "rows":      len(df),
                "date_from": str(df.index.min().date()),
                "date_to":   str(df.index.max().date()),
            })
            log.info("portfolio_overview.loaded", instrument=iid, rows=len(df))
        except Exception as exc:
            log.warning("portfolio_overview.skip", instrument=iid, error=str(exc))

    if not dfs:
        raise ValueError("No instrument data could be loaded.")

    # Align to date intersection
    common_idx: pd.DatetimeIndex | None = None
    for df in dfs.values():
        idx = df.index.normalize()
        common_idx = idx if common_idx is None else common_idx.intersection(idx)

    if common_idx is None or len(common_idx) == 0:
        raise ValueError("No common trading dates found across instruments.")

    # Build aligned Close series
    aligned: dict[str, pd.Series] = {}
    for iid, df in dfs.items():
        s = df["Close"].copy()
        s.index = s.index.normalize()
        aligned[iid] = s.reindex(common_idx)

    aligned_df = pd.DataFrame(aligned).dropna()
    if len(aligned_df) == 0:
        raise ValueError("Empty aligned DataFrame after dropping NaN rows.")

    # Normalised prices (base = 1.0 at first common date)
    norm_df = aligned_df / aligned_df.iloc[0]

    # Daily returns for correlation
    returns_df = aligned_df.pct_change().dropna()
    corr = returns_df.corr().round(4)
    correlation_matrix: dict[str, dict[str, float]] = {
        k.lower(): {kk.lower(): float(v) for kk, v in row.items()}
        for k, row in corr.to_dict().items()
    }

    # Down-sample normalised series to ≤ 500 rows
    step = max(1, len(norm_df) // 500)
    sampled = norm_df.iloc[::step]
    normalized_returns = [
        {"date": str(d.date()), **{k.lower(): round(float(v), 4) for k, v in zip(sampled.columns, row)}}
        for d, row in zip(sampled.index, sampled.values)
    ]

    return {
        "instruments":        instrument_meta,
        "common_days":        len(aligned_df),
        "date_from":          str(aligned_df.index.min().date()),
        "date_to":            str(aligned_df.index.max().date()),
        "normalized_returns": normalized_returns,
        "correlation_matrix": correlation_matrix,
    }


# ── Portfolio Backtest ─────────────────────────────────────────────────────────

def portfolio_backtest(
    instruments: list[str],
    allocations_eur: dict[str, float],
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """Run DDQN portfolio backtest for selected instruments.

    Pipeline per instrument:
    1. Load OHLCV + indicators, filter to [start_date, end_date].
    2. Find the most recent trained .zip model.
       If no model exists, fall back to buy-and-hold (model_used = "bnh_fallback").
    3. Run run_episode() to get normalised portfolio / benchmark values.
    4. Apply whole-share invested fraction (uninvested cash stays at 1.0).

    Combination:
    - Combined portfolio  = EUR-weighted average of per-instrument adjusted port values.
    - Combined benchmark  = EUR-weighted average of per-instrument B&H (Close / Close[0]).
    - Combined metrics    = compute_all_metrics() on the two combined arrays.

    Returns:
        Flat performance dict + instruments[] + daily[] + instrument_series{}.
    """
    # Normalise instrument ids (use uppercase internally, lowercase for JSON output)
    inst_upper = [i.upper() for i in instruments]
    alloc_norm: dict[str, float] = {}
    for iid in inst_upper:
        alloc_norm[iid] = (
            allocations_eur.get(iid.lower())
            or allocations_eur.get(iid)
            or 0.0
        )

    total_eur = sum(alloc_norm.values())
    if total_eur <= 0:
        raise ValueError("Total EUR allocation must be > 0.")

    start_ts = pd.Timestamp(start_date)
    end_ts   = pd.Timestamp(end_date)

    # ── Per-instrument run ─────────────────────────────────────────────────────
    inst_results: list[dict] = []

    for iid in inst_upper:
        alloc_eur = alloc_norm[iid]
        ccy       = INSTRUMENT_CCY.get(iid, "USD")
        fx        = FX_EUR_PER_UNIT.get(ccy, 1.0)

        try:
            df = _load_with_indicators(iid)
            df_f = df[(df.index >= start_ts) & (df.index <= end_ts)].copy()

            if len(df_f) < 20:
                log.warning("portfolio_backtest.insufficient_data", instrument=iid, rows=len(df_f))
                continue

            # Whole-share constraint
            first_price_eur = float(df_f["Close"].iloc[0]) * fx
            inv_frac = _invested_fraction(alloc_eur, first_price_eur)

            # Model or B&H fallback
            model_path = _find_best_model(iid)
            model_used = "bnh_fallback"

            close_arr = df_f["Close"].values
            bnh_raw   = close_arr / close_arr[0]     # buy-and-hold normalised

            if model_path is not None:
                from rita.core.trading_env import load_agent, run_episode
                model = load_agent(str(model_path))
                ep = run_episode(model, df_f)
                port_raw  = np.array(ep["portfolio_values"])
                model_used = model_path.name
            else:
                port_raw = bnh_raw.copy()

            # Adjust for whole-share cash constraint
            n = min(len(port_raw), len(bnh_raw))
            port_adj = _adjust_for_cash(list(port_raw[:n]), inv_frac)
            bnh_adj  = _adjust_for_cash(list(bnh_raw[:n]),  inv_frac)
            dates    = list(df_f.index[:n])

            # Per-instrument metrics
            p_arr = np.array(port_adj)
            dr    = np.diff(p_arr) / np.where(p_arr[:-1] == 0, 1, p_arr[:-1])
            inst_sharpe = float(sharpe_ratio(dr))
            inst_return = float((p_arr[-1] - 1) * 100)

            inst_results.append({
                "id":           iid.lower(),
                "name":         INSTRUMENT_NAMES.get(iid, iid),
                "currency":     ccy,
                "allocated_eur":    alloc_eur,
                "invested_eur":     round(alloc_eur * inv_frac, 2),
                "invested_frac":    round(inv_frac, 4),
                "return_pct":       round(inst_return, 2),
                "sharpe":           round(inst_sharpe, 3),
                "weight_pct":       None,     # filled below
                "model_used":       model_used,
                "_port":  port_adj,   # internal — removed before response
                "_bnh":   bnh_adj,
                "_dates": dates,
            })
            log.info("portfolio_backtest.instrument_done",
                     instrument=iid, model=model_used,
                     invested_frac=round(inv_frac, 3),
                     return_pct=round(inst_return, 2))

        except Exception as exc:
            log.warning("portfolio_backtest.instrument_failed", instrument=iid, error=str(exc))

    if not inst_results:
        raise ValueError("No instruments produced valid backtest results.")

    # ── Combination ───────────────────────────────────────────────────────────
    n_days = min(len(r["_dates"]) for r in inst_results)

    # EUR weights (based on allocated, not invested, so allocation intent is preserved)
    for r in inst_results:
        r["weight_pct"] = round(alloc_norm[r["id"].upper()] / total_eur * 100, 1)

    combined_port  = np.zeros(n_days)
    combined_bench = np.zeros(n_days)

    for r in inst_results:
        w = alloc_norm[r["id"].upper()] / total_eur
        combined_port  += w * np.array(r["_port"][:n_days])
        combined_bench += w * np.array(r["_bnh"][:n_days])

    perf = compute_all_metrics(combined_port, combined_bench)

    # Daily output series
    common_dates = inst_results[0]["_dates"][:n_days]
    daily_out = [
        {
            "date":            str(common_dates[i].date()),
            "portfolio_value": round(float(combined_port[i]),  4),
            "benchmark_value": round(float(combined_bench[i]), 4),
        }
        for i in range(n_days)
    ]

    # Per-instrument daily series (for individual lines on the chart)
    instrument_series: dict[str, list[float]] = {
        r["id"]: [round(float(v), 4) for v in r["_port"][:n_days]]
        for r in inst_results
    }

    # Strip internal keys before returning
    for r in inst_results:
        r.pop("_port", None)
        r.pop("_bnh",  None)
        r.pop("_dates", None)

    return {
        "sharpe_ratio":               perf["sharpe_ratio"],
        "max_drawdown_pct":           perf["max_drawdown_pct"],
        "portfolio_total_return_pct": perf["portfolio_total_return_pct"],
        "benchmark_total_return_pct": perf["benchmark_total_return_pct"],
        "portfolio_cagr_pct":         perf["portfolio_cagr_pct"],
        "total_days":                 perf["total_days"],
        "instruments_count":          len(inst_results),
        "total_eur_allocated":        total_eur,
        "instruments":                inst_results,
        "daily":                      daily_out,
        "instrument_series":          instrument_series,
    }


# ── Equity Hedge Scenarios ─────────────────────────────────────────────────────

def equity_hedge_scenarios(
    instrument: str,
    n_shares: int,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """Compute equity portfolio performance + Black-Scholes hedge scenarios.

    Returns a dict with:
      portfolio  — period stats + daily value series
      hedge_scenarios — mild_bearish (covered call) + strong_bearish (protective put)
                        + payoff_curves over a price grid
    """
    df = _load_with_indicators(instrument.upper())
    df_f = df[(df.index >= pd.Timestamp(start_date)) & (df.index <= pd.Timestamp(end_date))].copy()

    if len(df_f) < 5:
        raise ValueError(
            f"Insufficient data: need at least 5 trading days, got {len(df_f)}"
        )

    start_price = float(df_f["Close"].iloc[0])
    end_price   = float(df_f["Close"].iloc[-1])
    return_pct  = round((end_price - start_price) / start_price * 100, 4) if start_price else 0.0

    # 30-day annualised volatility
    n_vol = min(30, len(df_f))
    close_series = df_f["Close"].iloc[-n_vol:]
    vol_30d = float(
        np.log(close_series / close_series.shift(1)).dropna().std() * math.sqrt(252)
    )
    if not math.isfinite(vol_30d) or vol_30d == 0:
        vol_30d = 0.25

    # Black-Scholes params
    S       = end_price
    K_call  = round(S * 1.05, 2)   # covered call strike (5% OTM)
    K_put   = round(S, 2)          # protective put strike (at-the-money)
    T       = 30 / 252             # 30 calendar days to expiry
    r       = 0.03
    sigma   = vol_30d

    def _bs_call(s: float, k: float, t: float, rv: float, rate: float) -> float:
        if rv <= 0 or t <= 0 or k <= 0:
            return 0.0
        d1 = (math.log(s / k) + (rate + 0.5 * rv ** 2) * t) / (rv * math.sqrt(t))
        d2 = d1 - rv * math.sqrt(t)
        return float(s * norm.cdf(d1) - k * math.exp(-rate * t) * norm.cdf(d2))

    def _bs_put(s: float, k: float, t: float, rv: float, rate: float) -> float:
        if rv <= 0 or t <= 0 or k <= 0:
            return 0.0
        # Put via put-call parity
        call = _bs_call(s, k, t, rv, rate)
        return float(call - s + k * math.exp(-rate * t))

    premium_call_per_share = _bs_call(S, K_call, T, sigma, r)
    premium_put_per_share  = _bs_put(S, K_put,  T, sigma, r)

    total_premium_call = round(premium_call_per_share * n_shares, 2)
    total_premium_put  = round(premium_put_per_share  * n_shares, 2)
    portfolio_value    = round(S * n_shares, 2)

    # Payoff grid
    price_range = list(np.linspace(max(100.0, S * 0.75), S * 1.25, 33).round(2))

    def _unhedged_pnl(p: float) -> float:
        return round((p - S) * n_shares, 2)

    def _covered_call_pnl(p: float) -> float:
        # Long stock + short call (premium received)
        stock_pnl = (p - S) * n_shares
        call_pnl  = -(max(p - K_call, 0) - premium_call_per_share) * n_shares
        return round(stock_pnl + call_pnl, 2)

    def _protective_put_pnl(p: float) -> float:
        # Long stock + long put (premium paid)
        stock_pnl = (p - S) * n_shares
        put_pnl   = (max(K_put - p, 0) - premium_put_per_share) * n_shares
        return round(stock_pnl + put_pnl, 2)

    payoff_curves = {
        "price_range":     [round(float(p), 2) for p in price_range],
        "unhedged":        [_unhedged_pnl(p) for p in price_range],
        "covered_call":    [_covered_call_pnl(p) for p in price_range],
        "protective_put":  [_protective_put_pnl(p) for p in price_range],
    }

    # Daily portfolio series
    daily = [
        {
            "date":  str(d.date()),
            "price": round(float(p), 2),
            "value": round(float(p) * n_shares, 2),
        }
        for d, p in zip(df_f.index, df_f["Close"])
    ]

    return {
        "portfolio": {
            "instrument":     instrument.upper(),
            "n_shares":       n_shares,
            "start_price":    round(start_price, 2),
            "end_price":      round(end_price, 2),
            "return_pct":     return_pct,
            "vol_30d_pct":    round(vol_30d * 100, 4),
            "portfolio_value": portfolio_value,
            "daily":          daily,
        },
        "hedge_scenarios": {
            "mild_bearish": {
                "strategy":         "covered_call",
                "strike_label":     f"€{K_call:.2f}",
                "premium_per_share": round(premium_call_per_share, 4),
                "total_premium_eur": total_premium_call,
                "max_value_eur":    round(K_call * n_shares + total_premium_call, 2),
                "breakeven_price":  round(S - premium_call_per_share, 2),
                "description": (
                    f"Sell {n_shares}× {instrument.upper()} calls @ €{K_call:.2f} "
                    f"(5% OTM). Collect €{total_premium_call:.2f} premium. "
                    f"Upside capped at €{K_call:.2f}/share."
                ),
            },
            "strong_bearish": {
                "strategy":         "protective_put",
                "strike_label":     f"€{K_put:.2f}",
                "premium_per_share": round(premium_put_per_share, 4),
                "total_premium_eur": total_premium_put,
                "floor_value_eur":  round(K_put * n_shares - total_premium_put, 2),
                "breakeven_price":  round(S + premium_put_per_share, 2),
                "description": (
                    f"Buy {n_shares}× {instrument.upper()} puts @ €{K_put:.2f} (ATM). "
                    f"Pay €{total_premium_put:.2f} premium. "
                    f"Portfolio floor at €{round(K_put * n_shares - total_premium_put, 2):.2f}."
                ),
            },
            "payoff_curves": payoff_curves,
        },
    }
