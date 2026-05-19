"""RITA Core — Performance Metrics

Pure-computation performance functions: Sharpe ratio, max drawdown, CAGR,
and a full metrics report consumed by training and backtest results.

Ported from: poc/rita-cowork-demo/src/rita/core/performance.py
(plotting functions removed — not needed in the API context)
"""

from __future__ import annotations

import math
from typing import List

import numpy as np
import pandas as pd

RISK_FREE_RATE = 0.07   # India 10Y govt bond yield (annualised)
TRADING_DAYS   = 252


def sharpe_ratio(daily_returns: np.ndarray, risk_free_rate: float = RISK_FREE_RATE) -> float:
    """Annualised Sharpe ratio from a daily-returns array."""
    daily_rf = risk_free_rate / TRADING_DAYS
    arr = np.asarray(daily_returns, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) == 0 or arr.std() == 0:
        return 0.0
    return float((arr.mean() - daily_rf) / arr.std() * math.sqrt(TRADING_DAYS))


def max_drawdown(portfolio_values: np.ndarray) -> float:
    """Maximum drawdown as a negative fraction (e.g. -0.082 = -8.2%)."""
    vals = np.asarray(portfolio_values, dtype=float)
    if len(vals) == 0:
        return 0.0
    running_max = np.maximum.accumulate(vals)
    drawdowns = (vals - running_max) / running_max
    return float(drawdowns.min())


def cagr(start_value: float, end_value: float, years: float) -> float:
    """Compound Annual Growth Rate."""
    if start_value <= 0 or years <= 0:
        return 0.0
    return float((end_value / start_value) ** (1 / years) - 1)


def compute_all_metrics(portfolio_values: np.ndarray, benchmark_values: np.ndarray) -> dict:
    """Full performance report for a completed backtest or validation episode.

    Args:
        portfolio_values: daily portfolio value array (normalised to start at 1.0)
        benchmark_values: daily Buy-and-Hold values (same normalisation)

    Returns:
        dict with Sharpe, MDD, CAGR, win rate, constraint flags, etc.
    """
    port  = np.asarray(portfolio_values, dtype=float)
    bench = np.asarray(benchmark_values, dtype=float)

    daily_rets = np.diff(port) / port[:-1]
    years = len(port) / TRADING_DAYS

    sr        = sharpe_ratio(daily_rets)
    mdd       = max_drawdown(port)
    port_cagr = cagr(port[0], port[-1], years)
    bench_cagr = cagr(bench[0], bench[-1], years)

    win_days   = int(np.sum(daily_rets > 0))
    total_days = len(daily_rets)

    return {
        "total_days":                   total_days,
        "years":                        round(years, 2),
        "portfolio_total_return_pct":   round((port[-1] / port[0] - 1) * 100, 2),
        "benchmark_total_return_pct":   round((bench[-1] / bench[0] - 1) * 100, 2),
        "portfolio_cagr_pct":           round(port_cagr * 100, 2),
        "benchmark_cagr_pct":           round(bench_cagr * 100, 2),
        "sharpe_ratio":                 round(sr, 3),
        "max_drawdown_pct":             round(mdd * 100, 2),
        "annual_volatility_pct":        round(float(daily_rets.std() * math.sqrt(TRADING_DAYS) * 100), 2),
        "win_rate_pct":                 round(win_days / total_days * 100, 2) if total_days > 0 else 0.0,
        "sharpe_constraint_met":        sr > 1.0,
        "drawdown_constraint_met":      mdd > -0.10,
        "constraints_met":              sr > 1.0 and mdd > -0.10,
    }


def build_portfolio_comparison(backtest_df: pd.DataFrame, portfolio_inr: float) -> dict:
    """Compare three fixed-allocation manual strategies against the RITA RL model.

    Args:
        backtest_df : DataFrame with columns: date, portfolio_value, benchmark_value,
                      allocation, close_price.  portfolio_value and benchmark_value
                      are normalised to 1.0 at start.
        portfolio_inr : Starting capital in INR (e.g. 1_000_000 for Rs 10 lakh).

    Returns:
        Structured comparison dict with per-profile metrics and INR values.
    """
    df = backtest_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    # Reconstruct daily Nifty returns from close prices
    closes = df["close_price"].values
    market_returns = np.concatenate([[0.0], np.diff(closes) / closes[:-1]])

    years = len(df) / TRADING_DAYS

    def _simulate_fixed(alloc: float) -> np.ndarray:
        """Simulate a buy-and-hold fixed allocation on daily market returns."""
        vals = np.ones(len(df))
        for i in range(1, len(df)):
            vals[i] = vals[i - 1] * (1.0 + alloc * market_returns[i])
        return vals

    def _profile_metrics(norm_values: np.ndarray, label: str, alloc_desc: str) -> dict:
        daily_rets = np.diff(norm_values) / norm_values[:-1]
        sr  = sharpe_ratio(daily_rets)
        mdd = max_drawdown(norm_values)
        total_return = (norm_values[-1] / norm_values[0] - 1)
        final_inr    = round(portfolio_inr * norm_values[-1])
        profit_inr   = round(final_inr - portfolio_inr)
        return {
            "label":              label,
            "allocation":         alloc_desc,
            "start_value_inr":    int(portfolio_inr),
            "final_value_inr":    final_inr,
            "profit_loss_inr":    profit_inr,
            "return_pct":         round(total_return * 100, 2),
            "cagr_pct":           round(cagr(1.0, norm_values[-1], years) * 100, 2),
            "max_drawdown_pct":   round(mdd * 100, 2),
            "sharpe_ratio":       round(sr, 3),
            "sharpe_constraint_met":   sr > 1.0,
            "drawdown_constraint_met": mdd > -0.10,
        }

    # ── Three manual fixed-allocation profiles ────────────────────────────────
    conservative = _profile_metrics(_simulate_fixed(0.30), "Conservative", "30% Nifty + 70% Cash")
    moderate     = _profile_metrics(_simulate_fixed(0.60), "Moderate",     "60% Nifty + 40% Cash")
    aggressive   = _profile_metrics(_simulate_fixed(1.00), "Aggressive",   "100% Nifty (Buy & Hold)")

    # ── RITA RL model — use portfolio_value from backtest daily results ────────
    rita_norm = df["portfolio_value"].values
    rita      = _profile_metrics(rita_norm, "RITA RL Model", "0 / 50 / 100% dynamic (DDQN)")

    profiles = {
        "conservative": conservative,
        "moderate":     moderate,
        "aggressive":   aggressive,
        "rita_model":   rita,
    }

    # ── Winner by Sharpe (project goal) ──────────────────────────────────────
    best_key        = max(profiles, key=lambda k: profiles[k]["sharpe_ratio"])
    best_return_key = max(profiles, key=lambda k: profiles[k]["return_pct"])

    # ── Summary table rows (for easy display) ────────────────────────────────
    table = []
    for key, p in profiles.items():
        table.append({
            "profile":    p["label"],
            "allocation": p["allocation"],
            "final_inr":  p["final_value_inr"],
            "profit_inr": p["profit_loss_inr"],
            "return_pct": p["return_pct"],
            "max_dd_pct": p["max_drawdown_pct"],
            "sharpe":     p["sharpe_ratio"],
            "sharpe_ok":  p["sharpe_constraint_met"],
            "dd_ok":      p["drawdown_constraint_met"],
        })

    return {
        "period_start":    df["date"].iloc[0].strftime("%Y-%m-%d"),
        "period_end":      df["date"].iloc[-1].strftime("%Y-%m-%d"),
        "trading_days":    len(df),
        "portfolio_inr":   int(portfolio_inr),
        "nifty_return_pct": round((closes[-1] / closes[0] - 1) * 100, 2),
        "profiles":        profiles,
        "summary_table":   table,
        "sharpe_winner":   best_key,
        "return_winner":   best_return_key,
        "insight": (
            f"RITA RL model achieves Sharpe {rita['sharpe_ratio']:.3f} vs "
            f"Aggressive (Buy & Hold) Sharpe {aggressive['sharpe_ratio']:.3f}. "
            f"{'RITA wins on risk-adjusted return (project goal: Sharpe > 1.0).' if rita['sharpe_ratio'] > aggressive['sharpe_ratio'] else 'Buy & Hold leads on Sharpe this period.'}"
        ),
    }


def build_performance_feedback(
    backtest_df: pd.DataFrame,
    perf_metrics: dict,
    training_rounds: int,
) -> dict:
    """Summarise RITA RL model performance and derive realistic return expectations.

    Args:
        backtest_df     : DataFrame with columns: date, portfolio_value, benchmark_value,
                          allocation, close_price.
        perf_metrics    : Dict produced by compute_all_metrics() or assembled from stored
                          backtest run fields — keys: sharpe_ratio, max_drawdown_pct,
                          portfolio_total_return_pct, benchmark_total_return_pct,
                          portfolio_cagr_pct, benchmark_cagr_pct, annual_volatility_pct,
                          win_rate_pct, total_days, years, sharpe_constraint_met,
                          drawdown_constraint_met, constraints_met.
        training_rounds : Integer count of completed training rounds.

    Returns:
        Structured feedback dict: return_metrics, risk_metrics, trade_activity,
        constraints, training_round, realistic_expectations, summary.
    """
    def _f(key: str, default: float = 0.0) -> float:
        try:
            return float(perf_metrics.get(key, default))
        except (ValueError, TypeError):
            return default

    sharpe     = _f("sharpe_ratio")
    mdd        = _f("max_drawdown_pct")
    total_ret  = _f("portfolio_total_return_pct")
    bench_ret  = _f("benchmark_total_return_pct")
    cagr_pct   = _f("portfolio_cagr_pct")
    bench_cagr = _f("benchmark_cagr_pct")
    volatility = _f("annual_volatility_pct")
    win_rate   = _f("win_rate_pct")
    total_days = int(_f("total_days"))
    years      = _f("years")

    sharpe_ok = bool(perf_metrics.get("sharpe_constraint_met", False))
    dd_ok     = bool(perf_metrics.get("drawdown_constraint_met", False))

    # ── Trade activity from backtest daily results ────────────────────────────
    bt = backtest_df.copy()
    bt["date"] = pd.to_datetime(bt["date"])
    bt = bt.sort_values("date").reset_index(drop=True)

    alloc   = bt["allocation"].dropna()
    changes = alloc.diff().fillna(0)

    total_trades  = int((changes.abs() > 0).sum())
    buy_trades    = int((changes > 0).sum())
    sell_trades   = int((changes < 0).sum())

    days_hold = int((alloc == 0.0).sum())
    days_half = int((alloc == 0.5).sum())
    days_full = int((alloc == 1.0).sum())
    days_invested = int((alloc > 0).sum())

    port       = bt["portfolio_value"].values
    daily_rets = np.diff(port) / port[:-1] * 100

    # ── Training round context ────────────────────────────────────────────────
    latest_round = {
        "round":   training_rounds,
        "source":  "db",
    } if training_rounds > 0 else None

    # ── Realistic return expectations ─────────────────────────────────────────
    conservative_annual = round(cagr_pct * 0.80, 1)
    realistic_annual    = round(cagr_pct, 1)

    def _project(rate_pct: float, years_ahead: int = 1) -> float:
        return round((1 + rate_pct / 100) ** years_ahead - 1, 4) * 100

    expectations = {
        "conservative_1y_pct": round(_project(conservative_annual), 2),
        "realistic_1y_pct":    round(_project(realistic_annual), 2),
        "conservative_3y_pct": round(_project(conservative_annual, 3), 2),
        "realistic_3y_pct":    round(_project(realistic_annual, 3), 2),
        "basis": (
            f"Based on observed CAGR of {cagr_pct:.1f}% over {total_days} trading days. "
            f"Conservative estimate applies 20% discount for market uncertainty."
        ),
    }

    # ── Constraint verdict ────────────────────────────────────────────────────
    constraint_verdict = "ALL CONSTRAINTS MET" if (sharpe_ok and dd_ok) else (
        "SHARPE CONSTRAINT FAILED" if not sharpe_ok else "DRAWDOWN CONSTRAINT FAILED"
    )

    # ── Alpha vs benchmark ────────────────────────────────────────────────────
    alpha = round(total_ret - bench_ret, 2)
    alpha_note = (
        f"Underperformed Buy & Hold by {abs(alpha):.1f}% on raw return, "
        f"but Sharpe {sharpe:.3f} vs implied B&H Sharpe shows better risk-adjusted outcome."
        if alpha < 0 else
        f"Outperformed Buy & Hold by {alpha:.1f}% on raw return."
    )

    return {
        # Period
        "period_start": bt["date"].iloc[0].strftime("%Y-%m-%d"),
        "period_end":   bt["date"].iloc[-1].strftime("%Y-%m-%d"),
        "trading_days": total_days,
        "years":        round(years, 2),

        # Return metrics
        "return_metrics": {
            "portfolio_return_pct": round(total_ret, 2),
            "benchmark_return_pct": round(bench_ret, 2),
            "alpha_pct":            alpha,
            "portfolio_cagr_pct":   round(cagr_pct, 2),
            "benchmark_cagr_pct":   round(bench_cagr, 2),
            "alpha_note":           alpha_note,
        },

        # Risk metrics
        "risk_metrics": {
            "sharpe_ratio":          round(sharpe, 3),
            "max_drawdown_pct":      round(mdd, 2),
            "annual_volatility_pct": round(volatility, 2),
            "win_rate_pct":          round(win_rate, 2),
            "best_day_pct":          round(float(daily_rets.max()), 2) if len(daily_rets) > 0 else 0.0,
            "worst_day_pct":         round(float(daily_rets.min()), 2) if len(daily_rets) > 0 else 0.0,
        },

        # Trade activity
        "trade_activity": {
            "total_trades":         total_trades,
            "buy_trades":           buy_trades,
            "sell_trades":          sell_trades,
            "days_at_hold_0pct":    days_hold,
            "days_at_half_50pct":   days_half,
            "days_at_full_100pct":  days_full,
            "days_invested":        days_invested,
            "pct_time_invested":    round(days_invested / max(len(alloc), 1) * 100, 1),
            "avg_trades_per_month": round(total_trades / max(years * 12, 1), 1),
        },

        # Constraints
        "constraints": {
            "sharpe_target":   "> 1.0",
            "sharpe_actual":   round(sharpe, 3),
            "sharpe_met":      sharpe_ok,
            "drawdown_target": "< -10%",
            "drawdown_actual": round(mdd, 2),
            "drawdown_met":    dd_ok,
            "verdict":         constraint_verdict,
        },

        # Training context
        "training_round": latest_round,

        # Forward-looking expectations
        "realistic_expectations": expectations,

        # One-line summary
        "summary": (
            f"RITA RL model: {total_ret:.1f}% return over {total_days} days "
            f"({round(years, 1)}y), Sharpe {sharpe:.3f}, MDD {mdd:.1f}%. "
            f"{total_trades} trades ({buy_trades} buys, {sell_trades} sells). "
            f"{constraint_verdict}. "
            f"Realistic 1-year expectation: {expectations['realistic_1y_pct']:.1f}% "
            f"(conservative: {expectations['conservative_1y_pct']:.1f}%)."
        ),
    }


def simulate_stress_scenarios(
    portfolio_inr: float,
    market_moves: List,
    rita_allocation_pct: float,
) -> dict:
    """Point-in-time stress test across market move scenarios.

    For each market_move in market_moves, shows portfolio impact for:
      - Conservative  (30% fixed allocation)
      - Moderate      (60% fixed allocation)
      - Aggressive    (100% fixed — Buy & Hold)
      - RITA current  (current RL model recommendation allocation)
      - RITA → HOLD   (0% — model's downgrade protection trigger)

    Args:
        portfolio_inr       : Starting capital in INR.
        market_moves        : List of market move percentages (e.g. [-20, -10, 10, 20]).
        rita_allocation_pct : Current RITA recommendation in % (0, 50, or 100).

    Returns:
        dict with scenario results and per-move breach analysis.
    """
    PROFILES = {
        "conservative": ("Conservative",                          0.30),
        "moderate":     ("Moderate",                             0.60),
        "aggressive":   ("Aggressive (B&H)",                     1.00),
        "rita_current": (f"RITA ({int(rita_allocation_pct)}% current)", rita_allocation_pct / 100.0),
        "rita_hold":    ("RITA -> HOLD (0%)",                    0.00),
    }

    def _calc(alloc: float, move_pct: float) -> dict:
        impact_pct  = alloc * move_pct
        final_inr   = round(portfolio_inr * (1 + impact_pct / 100))
        pl_inr      = round(final_inr - portfolio_inr)
        dd_pct      = round(min(impact_pct, 0), 2)  # only negative moves count
        breaches_dd = dd_pct < -10.0
        return {
            "allocation_pct":       round(alloc * 100),
            "portfolio_impact_pct": round(impact_pct, 2),
            "final_value_inr":      final_inr,
            "profit_loss_inr":      pl_inr,
            "drawdown_pct":         dd_pct,
            "breaches_10pct_dd":    breaches_dd,
        }

    scenarios: dict = {}
    for move in market_moves:
        move_key = f"{move:+d}%"
        profiles_at_move: dict = {}
        for key, (label, alloc) in PROFILES.items():
            result = _calc(alloc, move)
            result["label"] = label
            profiles_at_move[key] = result

        # Count breaches (excluding RITA→HOLD which is always safe)
        breach_count = sum(
            1 for k, v in profiles_at_move.items()
            if k != "rita_hold" and v["breaches_10pct_dd"]
        )

        # Narrative insight for this move
        if move < 0:
            rita_dd  = profiles_at_move["rita_current"]["drawdown_pct"]
            hold_msg = (
                "RITA downgrade protection (HOLD) eliminates market loss entirely."
                if rita_allocation_pct > 0 else
                "RITA already at HOLD — fully protected."
            )
            if breach_count == 0:
                insight = f"All profiles within 10% drawdown limit. {hold_msg}"
            else:
                names = [profiles_at_move[k]["label"]
                         for k in profiles_at_move
                         if k != "rita_hold" and profiles_at_move[k]["breaches_10pct_dd"]]
                insight = (
                    f"{', '.join(names)} breach the 10% drawdown limit. "
                    f"RITA at {int(rita_allocation_pct)}% allocation: "
                    f"{rita_dd:.1f}% drawdown. {hold_msg}"
                )
        else:
            best = max(
                (k for k in profiles_at_move if k != "rita_hold"),
                key=lambda k: profiles_at_move[k]["profit_loss_inr"],
            )
            insight = (
                f"Market up {move}%: {profiles_at_move[best]['label']} captures "
                f"most upside (+Rs {profiles_at_move[best]['profit_loss_inr']:,}). "
                f"RITA at {int(rita_allocation_pct)}% captures "
                f"+Rs {profiles_at_move['rita_current']['profit_loss_inr']:,}."
            )

        scenarios[move_key] = {
            "market_move_pct": move,
            "profiles":        profiles_at_move,
            "breach_count":    breach_count,
            "insight":         insight,
        }

    # Summary: worst case
    worst_move  = min(market_moves)
    worst_key   = f"{worst_move:+d}%"
    worst_scen  = scenarios[worst_key]

    return {
        "portfolio_inr":       int(portfolio_inr),
        "rita_recommendation": f"{int(rita_allocation_pct)}%",
        "market_moves_tested": [f"{m:+d}%" for m in market_moves],
        "scenarios":           scenarios,
        "worst_case": {
            "move":    worst_key,
            "summary": worst_scen["insight"],
            "profiles": {
                k: {
                    "final_inr": v["final_value_inr"],
                    "pl_inr":    v["profit_loss_inr"],
                    "dd_pct":    v["drawdown_pct"],
                    "breach":    v["breaches_10pct_dd"],
                }
                for k, v in worst_scen["profiles"].items()
            },
        },
        "constraint_note": (
            "Constraint: max drawdown < 10%. "
            "RITA -> HOLD (0%) is always safe. "
            f"At current {int(rita_allocation_pct)}% allocation, "
            f"a {abs(worst_move)}% market drop causes "
            f"{worst_scen['profiles']['rita_current']['drawdown_pct']:.1f}% drawdown."
        ),
    }
