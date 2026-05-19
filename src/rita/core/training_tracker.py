"""RITA Core — Training Round Tracker (ported from poc/rita-cowork-demo)

Records metrics for each training/evaluation run so model improvement can be
visualised over successive fine-tuning cycles in the Training Progress tab.

Output file: <output_dir>/training_history.csv

Each row represents one complete pipeline run (Steps 1-8).
Round numbers are assigned sequentially; re-runs with a loaded (not retrained)
model are recorded separately so the analyst can compare evaluation stability.
"""

from __future__ import annotations

import os
from datetime import datetime

import pandas as pd
import structlog

log = structlog.get_logger()

HISTORY_FILE = "training_history.csv"

COLUMNS = [
    "round",
    "timestamp",
    "timesteps",
    "source",                  # "trained" | "loaded_existing"
    # Validation metrics (2023-2024)
    "val_sharpe",
    "val_mdd_pct",
    "val_cagr_pct",
    "val_constraints_met",
    # Backtest metrics (2025+)
    "backtest_sharpe",
    "backtest_mdd_pct",
    "backtest_return_pct",
    "backtest_cagr_pct",
    "backtest_trade_count",
    "backtest_constraints_met",
    "notes",
]


class TrainingTracker:
    """
    Appends one row per pipeline run to training_history.csv.

    Usage:
        tracker = TrainingTracker(output_dir)
        round_num = tracker.record_round(training_metrics, val_metrics, backtest_metrics)
        history   = tracker.load_history()   # → pd.DataFrame
    """

    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.history_path = os.path.join(output_dir, HISTORY_FILE)
        os.makedirs(output_dir, exist_ok=True)

    # ─── Write ────────────────────────────────────────────────────────────────

    def record_round(
        self,
        training_metrics: dict,
        val_metrics: dict,
        backtest_metrics: dict,
        notes: str = "",
    ) -> int:
        """
        Append a new round to the history CSV.

        Args:
            training_metrics : dict with keys: timesteps_trained, source, seed (optional),
                               n_seeds_tried (optional)
            val_metrics      : dict with keys: sharpe_ratio, max_drawdown_pct,
                               portfolio_cagr_pct, constraints_met
            backtest_metrics : dict with keys: sharpe_ratio, max_drawdown_pct,
                               portfolio_total_return_pct, portfolio_cagr_pct,
                               total_trades, constraints_met
            notes            : free-text label (e.g., "run_id=abc12345")

        Returns:
            The round number just recorded (1-based).
        """
        history = self.load_history()
        round_num = len(history) + 1

        def _f(d: dict, key: str, default: float = 0.0) -> float:
            return round(float(d.get(key, default)), 4)

        row = {
            "round": round_num,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "timesteps": int(training_metrics.get("timesteps_trained", 0)),
            "source": training_metrics.get("source", "trained"),
            "val_sharpe": _f(val_metrics, "sharpe_ratio"),
            "val_mdd_pct": _f(val_metrics, "max_drawdown_pct"),
            "val_cagr_pct": _f(val_metrics, "portfolio_cagr_pct"),
            "val_constraints_met": bool(val_metrics.get("constraints_met", False)),
            "backtest_sharpe": _f(backtest_metrics, "sharpe_ratio"),
            "backtest_mdd_pct": _f(backtest_metrics, "max_drawdown_pct"),
            "backtest_return_pct": _f(backtest_metrics, "portfolio_total_return_pct"),
            "backtest_cagr_pct": _f(backtest_metrics, "portfolio_cagr_pct"),
            "backtest_trade_count": int(backtest_metrics.get("total_trades", 0)),
            "backtest_constraints_met": bool(backtest_metrics.get("constraints_met", False)),
            "notes": notes,
        }

        new_df = pd.DataFrame([row], columns=COLUMNS)
        if history.empty:
            updated = new_df
        else:
            updated = pd.concat([history, new_df], ignore_index=True)

        updated.to_csv(self.history_path, index=False)

        log.info(
            "training_tracker.round_recorded",
            round=round_num,
            val_sharpe=row["val_sharpe"],
            backtest_sharpe=row["backtest_sharpe"],
        )
        return round_num

    # ─── Read ─────────────────────────────────────────────────────────────────

    def load_history(self) -> pd.DataFrame:
        """Return the full training history DataFrame (empty if no file yet)."""
        if os.path.exists(self.history_path):
            try:
                return pd.read_csv(self.history_path)
            except Exception:
                pass
        return pd.DataFrame(columns=COLUMNS)

    def get_round_count(self) -> int:
        """Return the number of recorded training rounds."""
        return len(self.load_history())

    def get_latest_round(self) -> dict | None:
        """Return the most recent round as a dict, or None if no history exists."""
        history = self.load_history()
        return history.iloc[-1].to_dict() if not history.empty else None
