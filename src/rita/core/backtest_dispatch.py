"""Backtest dispatch — historical strategy evaluation using a trained DDQN model.

Pipeline:
  1. Locate the trained model zip from config.model_version + instrument.
  2. Load OHLCV data and compute technical indicators.
  3. Filter to the requested date range.
  4. Load the model and run a deterministic episode.
  5. Build BacktestOutcome with per-day DailyResult entries.

Raises ValueError (not silently falls back to fake data) if:
  - No model file is found for the given model_version + instrument.
  - The date-filtered DataFrame has fewer than 30 rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


# ---------------------------------------------------------------------------
# Configuration & result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class BacktestConfig:
    run_id: str
    start_date: date
    end_date: date
    model_version: str
    strategy_params: str | None
    instrument: str = "NIFTY"


@dataclass
class DailyResult:
    date: date
    portfolio_value: float
    benchmark_value: float
    allocation: float
    close_price: float


@dataclass
class BacktestOutcome:
    total_return: float
    sharpe_ratio: float
    max_drawdown: float
    total_trades: int = 0
    daily_results: list[DailyResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Real backtest implementation
# ---------------------------------------------------------------------------

_MIN_ROWS = 30


def run_backtest(config: BacktestConfig) -> BacktestOutcome:
    """Run a historical backtest using the saved DDQN model.

    Steps:
        1. Locate model zip: models/{INSTRUMENT}/{model_version}*.zip
        2. Load OHLCV CSV and compute indicators.
        3. Filter by config.start_date .. config.end_date.
        4. Load model, run deterministic episode.
        5. Build and return BacktestOutcome.

    Raises:
        ValueError: if no model file is found or the date range yields < 30 rows.
    """
    from rita.core.data_loader import load_instrument_data, model_dir
    from rita.core.technical_analyzer import calculate_indicators
    from rita.core import trading_env

    instrument = config.instrument.upper()

    # ── 1. Locate model file ─────────────────────────────────────────────────
    mdir = model_dir(instrument)
    candidates: list[Path] = []

    if config.model_version.lower() == "latest":
        # Pick the most recently modified zip in the instrument directory
        candidates = sorted(mdir.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    else:
        exact = mdir / f"{config.model_version}.zip"
        if exact.exists():
            candidates = [exact]
        else:
            candidates = sorted(mdir.glob(f"{config.model_version}*.zip"))

    if not candidates:
        raise ValueError(
            f"No model file found for model_version='{config.model_version}' "
            f"in {mdir}. Train a model first."
        )
    model_path = str(candidates[0])

    # ── 2. Load OHLCV (primary CSV + manual supplement if present) ───────────
    # load_instrument_data() appends e.g. nifty_manual.csv so backtests can
    # reach 2026 dates even though merged.csv ends at 2025-12-31.
    # Pre-filtering before calculate_indicators() avoids running the expensive
    # trend_score computation on the full history (e.g. 4,500+ rows for BANKNIFTY)
    # when only ~250 rows are needed for a 1-year backtest.
    # Warmup of 250 rows covers EMA-200 (200) + trend_score window (20) + margin.
    _WARMUP_ROWS = 250
    df_raw = load_instrument_data(instrument)
    start_idx = df_raw.index.searchsorted(str(config.start_date))
    buffer_start = max(0, start_idx - _WARMUP_ROWS)
    df = calculate_indicators(df_raw.iloc[buffer_start:])

    # ── 3. Filter to exact date range ────────────────────────────────────────
    start_ts = str(config.start_date)
    end_ts = str(config.end_date)
    filtered = df.loc[start_ts:end_ts]

    if len(filtered) < _MIN_ROWS:
        raise ValueError(
            f"Date range {config.start_date} – {config.end_date} yields only "
            f"{len(filtered)} rows for {instrument} (minimum {_MIN_ROWS}). "
            "Widen the date range or verify the data."
        )

    # ── 4. Load model + run episode ──────────────────────────────────────────
    model = trading_env.load_agent(model_path)
    episode = trading_env.run_episode(model, filtered)

    perf = episode["performance"]
    total_return = perf["portfolio_total_return_pct"] / 100.0
    sharpe_ratio = perf["sharpe_ratio"]
    max_drawdown = perf["max_drawdown_pct"] / 100.0
    total_trades = int(perf.get("total_trades", 0))

    # ── 5. Build DailyResult list ────────────────────────────────────────────
    portfolio_values: list[float] = episode["portfolio_values"]
    benchmark_values: list[float] = episode["benchmark_values"]
    allocations: list[float] = episode["allocations"]
    close_prices: list[float] = episode["close_prices"]
    dates = episode["dates"]

    # allocations has one entry per transition (len = len-1 of values arrays),
    # pad the first day with 0.0 so all lists align.
    alloc_padded = [0.0] + list(allocations)

    daily_results: list[DailyResult] = []
    n = len(portfolio_values)
    for i in range(n):
        ts = dates[i]
        day_date: date = ts.date() if hasattr(ts, "date") else ts
        daily_results.append(
            DailyResult(
                date=day_date,
                portfolio_value=round(portfolio_values[i], 6),
                benchmark_value=round(benchmark_values[i], 6),
                allocation=alloc_padded[i] if i < len(alloc_padded) else 0.0,
                close_price=round(close_prices[i], 2),
            )
        )

    return BacktestOutcome(
        total_return=round(total_return, 6),
        sharpe_ratio=round(sharpe_ratio, 6),
        max_drawdown=round(max_drawdown, 6),
        total_trades=total_trades,
        daily_results=daily_results,
    )
