"""Nifty Options Experiment Backtest.

Runs a daily strangle backtest with configurable target/stop-loss.
Uses real NSE option prices from DB when available,
falls back to BSM estimates when not.

Entry at open, exit at close (or when T/SL hit intraday).
Delta-neutral: equalise notional by buying more lots of the cheaper leg.
"""
from __future__ import annotations

import csv
import math
from datetime import date
from pathlib import Path
from typing import Any

RISK_FREE = 0.065


# ── BSM (fallback when real prices not available) ────────────────────────────

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bsm_call(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)


def _bsm_put(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0:
        return max(K - S, 0.0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def _hist_vol(closes: list[float], window: int = 20) -> float:
    if len(closes) < window + 1:
        return 0.15
    returns = [
        math.log(closes[i] / closes[i - 1])
        for i in range(len(closes) - window, len(closes))
        if closes[i - 1] > 0
    ]
    if len(returns) < 2:
        return 0.15
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(var * 252)


def _days_to_weekly_expiry(d: date) -> int:
    weekday = d.weekday()
    days = (3 - weekday) % 7
    return days if days > 0 else 7


# ── Data loading ─────────────────────────────────────────────────────────────

def _load_csv(csv_path: Path) -> list[dict]:
    if not csv_path.exists():
        return []
    rows: list[dict] = []
    with open(csv_path) as f:
        for r in csv.DictReader(f):
            rows.append({
                "date": r["date"],
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": int(float(r.get("volume", 0))),
            })
    return rows


def _load_option_prices(bhav_path: Path) -> dict[tuple, dict]:
    """Legacy CSV loader — kept for standalone/test use only."""
    if not bhav_path.exists():
        return {}

    raw: dict[tuple, list[dict]] = {}
    with open(bhav_path) as f:
        for r in csv.DictReader(f):
            key = (r["date"], int(float(r["strike"])), r["option_type"])
            entry = {
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "expiry": r["expiry"],
                "oi": int(float(r.get("oi", 0))),
            }
            if key not in raw:
                raw[key] = []
            raw[key].append(entry)

    lookup: dict[tuple, dict] = {}
    for key, contracts in raw.items():
        trade_date = key[0]
        nearest = min(
            contracts,
            key=lambda c: c["expiry"] if c["expiry"] >= trade_date else "9999",
        )
        lookup[key] = nearest

    return lookup


# ── Strike rounding ──────────────────────────────────────────────────────────

def _round_strike(spot: float, offset: float) -> float:
    return round((spot + offset) / 50) * 50


# ── Backtest ─────────────────────────────────────────────────────────────────

def run_backtest(
    csv_path: Path,
    lot_size: int,
    target_pct: float = 15.0,
    sl_pct: float = 5.0,
    backtest_start: date | None = None,
    option_prices: dict[tuple, dict] | None = None,
) -> dict[str, Any]:
    rows = _load_csv(csv_path)
    if not rows:
        return {"error": "No experiment CSV data found"}

    if option_prices is None:
        option_prices = {}

    start = backtest_start or date(2021, 1, 1)
    data = [r for r in rows if r["date"] >= str(start)]
    all_closes = [r["close"] for r in rows]

    entries: list[dict] = []
    cum_pnl = 0.0
    wins = 0
    losses = 0
    target_hits = 0
    sl_hits = 0
    time_exits = 0
    real_count = 0
    bsm_count = 0

    for day in data:
        idx_in_all = next(
            (j for j, r in enumerate(rows) if r["date"] == day["date"]), None
        )
        if idx_in_all is None:
            continue

        closes_upto = all_closes[: idx_in_all + 1]
        sigma = _hist_vol(closes_upto)

        spot_entry = day["open"]
        spot_high = day["high"]
        spot_low = day["low"]
        spot_exit = day["close"]

        call_strike = _round_strike(spot_entry, 100)
        put_strike = _round_strike(spot_entry, -100)

        dte = _days_to_weekly_expiry(date.fromisoformat(day["date"]))
        T_entry = max(dte / 365, 1 / 365)
        T_exit = max((dte - 1) / 365, 0.0001)

        call_key = (day["date"], int(call_strike), "CE")
        put_key = (day["date"], int(put_strike), "PE")
        call_real = option_prices.get(call_key)
        put_real = option_prices.get(put_key)

        if call_real and put_real and call_real["open"] > 0 and put_real["open"] > 0:
            price_source = "nse"
            call_premium_entry = call_real["open"]
            put_premium_entry = put_real["open"]
            call_premium_high = call_real["high"]
            put_premium_high = put_real["high"]
            call_premium_low = call_real["low"]
            put_premium_low = put_real["low"]
            call_premium_close = call_real["close"]
            put_premium_close = put_real["close"]
            real_count += 1
        else:
            price_source = "bsm"
            call_premium_entry = _bsm_call(spot_entry, call_strike, T_entry, RISK_FREE, sigma)
            put_premium_entry = _bsm_put(spot_entry, put_strike, T_entry, RISK_FREE, sigma)
            call_premium_high = _bsm_call(spot_high, call_strike, T_exit, RISK_FREE, sigma)
            put_premium_high = _bsm_put(spot_low, put_strike, T_exit, RISK_FREE, sigma)
            call_premium_low = _bsm_call(spot_low, call_strike, T_exit, RISK_FREE, sigma)
            put_premium_low = _bsm_put(spot_high, put_strike, T_exit, RISK_FREE, sigma)
            call_premium_close = _bsm_call(spot_exit, call_strike, T_exit, RISK_FREE, sigma)
            put_premium_close = _bsm_put(spot_exit, put_strike, T_exit, RISK_FREE, sigma)
            bsm_count += 1

        if call_premium_entry <= 0 or put_premium_entry <= 0:
            continue

        call_lots = 1
        put_lots = 1
        call_notional = call_premium_entry * lot_size
        put_notional = put_premium_entry * lot_size
        if call_notional > put_notional and put_notional > 0:
            put_lots = max(1, round(call_notional / put_notional))
        elif put_notional > call_notional and call_notional > 0:
            call_lots = max(1, round(put_notional / call_notional))

        call_entry_cost = call_premium_entry * lot_size * call_lots
        put_entry_cost = put_premium_entry * lot_size * put_lots
        total_entry_cost = call_entry_cost + put_entry_cost

        best_value = (
            call_premium_high * lot_size * call_lots
            + put_premium_high * lot_size * put_lots
        )
        best_pnl_pct = (best_value - total_entry_cost) / total_entry_cost * 100

        worst_value = (
            call_premium_low * lot_size * call_lots
            + put_premium_low * lot_size * put_lots
        )
        worst_pnl_pct = (worst_value - total_entry_cost) / total_entry_cost * 100

        exit_type = "time"
        if best_pnl_pct >= target_pct:
            exit_type = "target"
            target_hits += 1
        elif worst_pnl_pct <= -sl_pct:
            exit_type = "sl"
            sl_hits += 1
        else:
            time_exits += 1

        if exit_type == "target":
            exit_value = total_entry_cost * (1 + target_pct / 100)
            call_exit_val = call_premium_high * lot_size * call_lots
            put_exit_val = put_premium_high * lot_size * put_lots
            trigger_spot = spot_high
        elif exit_type == "sl":
            exit_value = total_entry_cost * (1 - sl_pct / 100)
            call_exit_val = call_premium_low * lot_size * call_lots
            put_exit_val = put_premium_low * lot_size * put_lots
            trigger_spot = spot_low
        else:
            call_exit_val = call_premium_close * lot_size * call_lots
            put_exit_val = put_premium_close * lot_size * put_lots
            exit_value = call_exit_val + put_exit_val
            trigger_spot = spot_exit

        call_pnl = call_exit_val - call_entry_cost
        put_pnl = put_exit_val - put_entry_cost
        winner = "call" if call_pnl >= put_pnl else "put"

        day_pnl = exit_value - total_entry_cost
        day_pnl_pct = (day_pnl / total_entry_cost * 100) if total_entry_cost else 0
        cum_pnl += day_pnl

        if day_pnl >= 0:
            wins += 1
        else:
            losses += 1

        entries.append({
            "date": day["date"],
            "nifty_open": round(spot_entry, 2),
            "nifty_close": round(spot_exit, 2),
            "call_strike": call_strike,
            "put_strike": put_strike,
            "call_premium": round(call_premium_entry, 2),
            "put_premium": round(put_premium_entry, 2),
            "call_lots": call_lots,
            "put_lots": put_lots,
            "lot_size": lot_size,
            "iv_pct": round(sigma * 100, 1),
            "entry_cost": round(total_entry_cost, 2),
            "exit_value": round(exit_value, 2),
            "call_pnl": round(call_pnl, 2),
            "put_pnl": round(put_pnl, 2),
            "winner": winner,
            "trigger_spot": round(trigger_spot, 2),
            "day_pnl": round(day_pnl, 2),
            "day_pnl_pct": round(day_pnl_pct, 2),
            "cum_pnl": round(cum_pnl, 2),
            "exit_type": exit_type,
            "price_source": price_source,
        })

    total_trades = wins + losses
    summary = {
        "period": f"{start} to {date.today()}",
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(wins / total_trades * 100, 1) if total_trades else 0,
        "total_pnl": round(cum_pnl, 2),
        "avg_pnl": round(cum_pnl / total_trades, 2) if total_trades else 0,
        "target_hits": target_hits,
        "sl_hits": sl_hits,
        "time_exits": time_exits,
        "target_pct": target_pct,
        "sl_pct": sl_pct,
        "best_day": max((e["day_pnl"] for e in entries), default=0),
        "worst_day": min((e["day_pnl"] for e in entries), default=0),
        "real_price_days": real_count,
        "bsm_price_days": bsm_count,
    }

    return {"summary": summary, "entries": entries}


def get_valid_contracts_from_repo(
    repo, lot_size: int,
) -> dict[str, Any]:
    """Return summary of real NSE option price coverage from DB."""
    count = repo.count()
    if count == 0:
        return {"error": "No NSE Bhav copy data — run import_bhav_csv first"}

    date_from, date_to = repo.date_range()
    return {
        "total_rows": count,
        "date_from": date_from,
        "date_to": date_to,
        "lot_size": lot_size,
    }
