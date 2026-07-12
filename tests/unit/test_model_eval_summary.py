"""Unit tests for the F34 Phase 2.5 model-eval-summary endpoint — QA.

Covers GET /api/v1/experience/rita/model-eval-summary and the instrument
parameter added to GET /api/v1/experience/rita/backtest-daily.

Tests cover (Architect edge-case list, task-brief-20260712-0750):
- Happy path: rows sorted backtest_sharpe desc, gate_pass computed server-side
  (sharpe 1.2 / mdd -8 -> True; below-gate row -> False)
- Edge cases 1-2: missing/empty training_history.csv -> has_history False,
  null metrics, gate_pass null; endpoint must not 500
- Nulls-last sort: null backtest_sharpe rows after real values, alphabetical
  among themselves
- Edge case 6: NaN/malformed numeric cells coerced to null
- Edge case 7 (regression): backtest-daily with no instrument param preserves
  active-instrument behaviour; with param, active-instrument lookup is skipped
- API-frontend contract: every field model-eval.js reads exists in the schema

All filesystem/TrainingTracker access is mocked — no dependence on real
models/ contents. Patch targets are the names as imported into the route
module (rita.api.experience.rita).
"""

from __future__ import annotations

import math

import pandas as pd
import pytest
from unittest.mock import MagicMock, patch

from rita.schemas.model_eval_summary import (
    ModelEvalSummaryResponse,
    ModelEvalSummaryRow,
)

SUMMARY_URL = "/api/v1/experience/rita/model-eval-summary"
BACKTEST_URL = "/api/v1/experience/rita/backtest-daily"

ROUTE = "rita.api.experience.rita"


# ---------------------------------------------------------------------------
# Helpers — synthetic training_history rows (dict shape of df.iloc[-1].to_dict())
# ---------------------------------------------------------------------------

def _history_row(
    backtest_sharpe=0.5,
    backtest_mdd_pct=-12.0,
    val_sharpe=0.4,
    timestamp="2026-07-12 09:14:02",
    source="trained",
    round_num=3,
    **overrides,
):
    row = {
        "round": round_num,
        "timestamp": timestamp,
        "timesteps": 50000,
        "source": source,
        "val_sharpe": val_sharpe,
        "val_mdd_pct": -14.2,
        "val_cagr_pct": 8.3,
        "val_constraints_met": False,
        "backtest_sharpe": backtest_sharpe,
        "backtest_mdd_pct": backtest_mdd_pct,
        "backtest_return_pct": 6.4,
        "backtest_cagr_pct": 5.1,
        "backtest_trade_count": 42,
        "backtest_constraints_met": False,
        "notes": "",
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# Happy path — all instruments have history
# ---------------------------------------------------------------------------

class TestSummaryHappyPath:
    """All instruments have a latest round; gate + sort computed server-side."""

    @patch(f"{ROUTE}.load_latest_round")
    @patch(f"{ROUTE}.list_instrument_ids")
    def test_gate_pass_true_and_false(self, mock_ids, mock_latest, client):
        """sharpe 1.2 / mdd -8 -> gate_pass True; sharpe 0.5 / mdd -12 -> False."""
        mock_ids.return_value = ["ASML", "SBIN"]
        mock_latest.side_effect = lambda inst: {
            "ASML": _history_row(backtest_sharpe=1.2, backtest_mdd_pct=-8.0),
            "SBIN": _history_row(backtest_sharpe=0.5, backtest_mdd_pct=-12.0),
        }[inst]

        resp = client.get(SUMMARY_URL)

        assert resp.status_code == 200
        body = resp.json()
        by_inst = {r["instrument"]: r for r in body["rows"]}
        assert by_inst["ASML"]["gate_pass"] is True
        assert by_inst["SBIN"]["gate_pass"] is False
        assert by_inst["ASML"]["has_history"] is True
        assert by_inst["SBIN"]["has_history"] is True

    @patch(f"{ROUTE}.load_latest_round")
    @patch(f"{ROUTE}.list_instrument_ids")
    def test_rows_sorted_backtest_sharpe_desc(self, mock_ids, mock_latest, client):
        """Rows come back sorted by backtest_sharpe descending, not input order."""
        mock_ids.return_value = ["AEX", "ASML", "SBIN"]
        sharpe = {"AEX": 0.3, "ASML": 1.2, "SBIN": 0.947}
        mock_latest.side_effect = lambda inst: _history_row(
            backtest_sharpe=sharpe[inst], backtest_mdd_pct=-8.0
        )

        body = client.get(SUMMARY_URL).json()

        assert [r["instrument"] for r in body["rows"]] == ["ASML", "SBIN", "AEX"]
        sharpes = [r["backtest_sharpe"] for r in body["rows"]]
        assert sharpes == sorted(sharpes, reverse=True)

    @patch(f"{ROUTE}.load_latest_round")
    @patch(f"{ROUTE}.list_instrument_ids")
    def test_gate_boundary_values_pass(self, mock_ids, mock_latest, client):
        """Gate is inclusive: sharpe exactly 1.0 and |mdd| exactly 10 -> True."""
        mock_ids.return_value = ["NIFTY"]
        mock_latest.return_value = _history_row(
            backtest_sharpe=1.0, backtest_mdd_pct=-10.0
        )

        body = client.get(SUMMARY_URL).json()

        assert body["rows"][0]["gate_pass"] is True

    @patch(f"{ROUTE}.load_latest_round")
    @patch(f"{ROUTE}.list_instrument_ids")
    def test_row_field_values_mapped_from_history(self, mock_ids, mock_latest, client):
        """CSV columns map to schema fields (incl. backtest_trade_count -> trade_count)."""
        mock_ids.return_value = ["SBIN"]
        mock_latest.return_value = _history_row(
            backtest_sharpe=0.947, backtest_mdd_pct=-12.1,
            timestamp="2026-07-12 09:14:02", source="trained", round_num=3,
        )

        row = client.get(SUMMARY_URL).json()["rows"][0]

        assert row["instrument"] == "SBIN"
        assert row["last_trained"] == "2026-07-12 09:14:02"
        assert row["timesteps"] == 50000
        assert row["val_sharpe"] == 0.4
        assert row["val_mdd_pct"] == -14.2
        assert row["val_cagr_pct"] == 8.3
        assert row["backtest_sharpe"] == 0.947
        assert row["backtest_mdd_pct"] == -12.1
        assert row["backtest_return_pct"] == 6.4
        assert row["trade_count"] == 42
        assert row["source"] == "trained"
        assert row["round"] == 3
        assert row["gate_pass"] is False


# ---------------------------------------------------------------------------
# Edge cases 1-2 — missing/empty training_history.csv
# ---------------------------------------------------------------------------

class TestSummaryMissingHistory:
    """Missing or empty history -> null-metrics row, never a 500."""

    @patch(f"{ROUTE}.load_latest_round")
    @patch(f"{ROUTE}.list_instrument_ids")
    def test_missing_history_null_row(self, mock_ids, mock_latest, client):
        """load_latest_round None -> has_history False, null metrics, gate_pass null."""
        mock_ids.return_value = ["ATO"]
        mock_latest.return_value = None

        resp = client.get(SUMMARY_URL)

        assert resp.status_code == 200
        row = resp.json()["rows"][0]
        assert row["instrument"] == "ATO"
        assert row["has_history"] is False
        assert row["gate_pass"] is None
        for field in ("last_trained", "timesteps", "val_sharpe", "val_mdd_pct",
                      "val_cagr_pct", "backtest_sharpe", "backtest_mdd_pct",
                      "backtest_return_pct", "trade_count", "source", "round"):
            assert row[field] is None, f"{field} should be null for missing history"

    @patch(f"{ROUTE}.load_latest_round")
    @patch(f"{ROUTE}.list_instrument_ids")
    def test_one_bad_instrument_does_not_500(self, mock_ids, mock_latest, client):
        """One instrument raising must not break the whole table (per-row guard)."""
        mock_ids.return_value = ["ASML", "ATO"]

        def _latest(inst):
            if inst == "ATO":
                raise OSError("corrupt CSV")
            return _history_row(backtest_sharpe=1.2, backtest_mdd_pct=-8.0)

        mock_latest.side_effect = _latest

        resp = client.get(SUMMARY_URL)

        assert resp.status_code == 200
        by_inst = {r["instrument"]: r for r in resp.json()["rows"]}
        assert by_inst["ASML"]["gate_pass"] is True
        assert by_inst["ATO"]["has_history"] is False
        assert by_inst["ATO"]["gate_pass"] is None

    @patch(f"{ROUTE}.load_latest_round")
    @patch(f"{ROUTE}.list_instrument_ids")
    def test_no_instruments_configured(self, mock_ids, mock_latest, client):
        """Empty config dir -> empty rows list, still 200."""
        mock_ids.return_value = []

        resp = client.get(SUMMARY_URL)

        assert resp.status_code == 200
        assert resp.json()["rows"] == []
        mock_latest.assert_not_called()


# ---------------------------------------------------------------------------
# Nulls-last sort
# ---------------------------------------------------------------------------

class TestSummaryNullsLastSort:
    """Rows with null backtest_sharpe sort after real values."""

    @patch(f"{ROUTE}.load_latest_round")
    @patch(f"{ROUTE}.list_instrument_ids")
    def test_null_sharpe_sorts_last(self, mock_ids, mock_latest, client):
        """No-history instrument lands after every real-sharpe row."""
        mock_ids.return_value = ["ATO", "ASML", "SBIN"]

        def _latest(inst):
            if inst == "ATO":
                return None  # no history -> null backtest_sharpe
            return _history_row(
                backtest_sharpe={"ASML": 1.2, "SBIN": 0.947}[inst],
                backtest_mdd_pct=-8.0,
            )

        mock_latest.side_effect = _latest

        body = client.get(SUMMARY_URL).json()

        assert [r["instrument"] for r in body["rows"]] == ["ASML", "SBIN", "ATO"]

    @patch(f"{ROUTE}.load_latest_round")
    @patch(f"{ROUTE}.list_instrument_ids")
    def test_multiple_nulls_alphabetical(self, mock_ids, mock_latest, client):
        """Null-sharpe rows are alphabetical among themselves (design §2a)."""
        mock_ids.return_value = ["IXIC", "AEX", "DJI", "SBIN"]

        def _latest(inst):
            if inst == "SBIN":
                return _history_row(backtest_sharpe=0.947, backtest_mdd_pct=-12.0)
            return None

        mock_latest.side_effect = _latest

        body = client.get(SUMMARY_URL).json()

        assert [r["instrument"] for r in body["rows"]] == ["SBIN", "AEX", "DJI", "IXIC"]

    @patch(f"{ROUTE}.load_latest_round")
    @patch(f"{ROUTE}.list_instrument_ids")
    def test_negative_sharpe_sorts_before_null(self, mock_ids, mock_latest, client):
        """A real negative sharpe still precedes a null one."""
        mock_ids.return_value = ["ATO", "BANKNIFTY"]

        def _latest(inst):
            if inst == "BANKNIFTY":
                return _history_row(backtest_sharpe=-0.183, backtest_mdd_pct=-9.0)
            return None

        mock_latest.side_effect = _latest

        body = client.get(SUMMARY_URL).json()

        assert [r["instrument"] for r in body["rows"]] == ["BANKNIFTY", "ATO"]


# ---------------------------------------------------------------------------
# Edge case 6 — NaN / malformed numeric cells
# ---------------------------------------------------------------------------

class TestSummaryNanCoercion:
    """NaN and non-numeric cells coerce to null; gate_pass null when inputs null."""

    @patch(f"{ROUTE}.load_latest_round")
    @patch(f"{ROUTE}.list_instrument_ids")
    def test_nan_metrics_become_null(self, mock_ids, mock_latest, client):
        mock_ids.return_value = ["DJI"]
        mock_latest.return_value = _history_row(
            backtest_sharpe=math.nan,
            backtest_mdd_pct=-8.0,
            val_sharpe=math.nan,
        )

        row = client.get(SUMMARY_URL).json()["rows"][0]

        assert row["backtest_sharpe"] is None
        assert row["val_sharpe"] is None
        assert row["gate_pass"] is None  # NaN sharpe -> gate undecidable
        assert row["has_history"] is True  # a round exists, metrics are just bad

    @patch(f"{ROUTE}.load_latest_round")
    @patch(f"{ROUTE}.list_instrument_ids")
    def test_malformed_string_cell_becomes_null(self, mock_ids, mock_latest, client):
        mock_ids.return_value = ["IXIC"]
        mock_latest.return_value = _history_row(
            backtest_sharpe="not-a-number", backtest_mdd_pct=-8.0
        )

        resp = client.get(SUMMARY_URL)

        assert resp.status_code == 200
        row = resp.json()["rows"][0]
        assert row["backtest_sharpe"] is None
        assert row["gate_pass"] is None


# ---------------------------------------------------------------------------
# load_latest_round core helper — real filesystem via tmp_path (no models/ dep)
# ---------------------------------------------------------------------------

class TestLoadLatestRoundHelper:
    """rita.core.training_tracker.load_latest_round against a temp model dir."""

    def _settings_for(self, tmp_path):
        settings = MagicMock()
        settings.model.path = str(tmp_path)
        return settings

    def test_missing_csv_returns_none(self, tmp_path):
        from rita.core.training_tracker import load_latest_round

        with patch("rita.config.get_settings", return_value=self._settings_for(tmp_path)):
            assert load_latest_round("GHOST") is None

    def test_header_only_csv_returns_none(self, tmp_path):
        from rita.core.training_tracker import COLUMNS, HISTORY_FILE, load_latest_round

        inst_dir = tmp_path / "EMPTYINST"
        inst_dir.mkdir()
        pd.DataFrame(columns=COLUMNS).to_csv(inst_dir / HISTORY_FILE, index=False)

        with patch("rita.config.get_settings", return_value=self._settings_for(tmp_path)):
            assert load_latest_round("EMPTYINST") is None

    def test_latest_row_returned(self, tmp_path):
        from rita.core.training_tracker import COLUMNS, HISTORY_FILE, load_latest_round

        inst_dir = tmp_path / "SBIN"
        inst_dir.mkdir()
        rows = [
            _history_row(backtest_sharpe=0.1, round_num=1),
            _history_row(backtest_sharpe=0.947, round_num=2),
        ]
        pd.DataFrame(rows, columns=COLUMNS).to_csv(inst_dir / HISTORY_FILE, index=False)

        with patch("rita.config.get_settings", return_value=self._settings_for(tmp_path)):
            latest = load_latest_round("sbin")  # lowercase input -> uppercased dir

        assert latest is not None
        assert latest["round"] == 2
        assert latest["backtest_sharpe"] == 0.947


# ---------------------------------------------------------------------------
# Edge case 7 — backtest-daily instrument param regression
# ---------------------------------------------------------------------------

class TestBacktestDailyInstrumentParam:
    """instrument=None preserves active-instrument behaviour (performance.js)."""

    @patch(f"{ROUTE}.BacktestResultsRepository")
    @patch(f"{ROUTE}.BacktestRunsRepository")
    @patch(f"{ROUTE}._get_active_instrument_id")
    def test_no_param_uses_active_instrument(
        self, mock_active, mock_runs_cls, mock_results_cls, client
    ):
        """No instrument param -> active-instrument lookup runs (prior behaviour)."""
        mock_active.return_value = "NIFTY"
        runs_repo = MagicMock()
        runs_repo.read_all.return_value = []
        mock_runs_cls.return_value = runs_repo

        resp = client.get(BACKTEST_URL)

        assert resp.status_code == 200
        assert resp.json() == []
        mock_active.assert_called_once()

    @patch(f"{ROUTE}.BacktestResultsRepository")
    @patch(f"{ROUTE}.BacktestRunsRepository")
    @patch(f"{ROUTE}._get_active_instrument_id")
    def test_param_skips_active_instrument_lookup(
        self, mock_active, mock_runs_cls, mock_results_cls, client
    ):
        """instrument=sbin -> uppercased filter, active-instrument lookup skipped."""
        run = MagicMock()
        run.status = "complete"
        run.instrument = "SBIN"
        run.run_id = "run-1"
        run.ended_at = "2026-07-12"
        run.recorded_at = "2026-07-12"
        runs_repo = MagicMock()
        runs_repo.read_all.return_value = [run]
        mock_runs_cls.return_value = runs_repo

        result = MagicMock()
        result.run_id = "run-1"
        result.date = "2026-07-01"
        result.portfolio_value = 101.5
        result.benchmark_value = 100.2
        result.allocation = 0.6
        result.close_price = 250.0
        results_repo = MagicMock()
        results_repo.read_all.return_value = [result]
        mock_results_cls.return_value = results_repo

        resp = client.get(BACKTEST_URL, params={"instrument": "sbin"})

        assert resp.status_code == 200
        mock_active.assert_not_called()
        body = resp.json()
        assert len(body) == 1
        # Plot contract fields read by model-eval.js _renderEvalPlots
        assert body[0] == {
            "date": "2026-07-01",
            "portfolio_value": 101.5,
            "benchmark_value": 100.2,
            "allocation": 0.6,
            "close_price": 250.0,
        }

    @patch(f"{ROUTE}.BacktestResultsRepository")
    @patch(f"{ROUTE}.BacktestRunsRepository")
    @patch(f"{ROUTE}._get_active_instrument_id")
    def test_param_with_no_runs_returns_empty_list(
        self, mock_active, mock_runs_cls, mock_results_cls, client
    ):
        """Edge case 4: instrument with no backtest run -> [] (JS empty state)."""
        runs_repo = MagicMock()
        runs_repo.read_all.return_value = []
        mock_runs_cls.return_value = runs_repo

        resp = client.get(BACKTEST_URL, params={"instrument": "ASRNL"})

        assert resp.status_code == 200
        assert resp.json() == []
        mock_active.assert_not_called()


# ---------------------------------------------------------------------------
# API-frontend contract — schema fields vs model-eval.js reads
# ---------------------------------------------------------------------------

class TestApiFrontendContract:
    """Every field model-eval.js reads must exist in the Pydantic schema."""

    # From dashboard/js/rita/model-eval.js:
    #   data.rows (39/54), data.val_window / data.backtest_window /
    #   data.gate_rule (60)
    JS_RESPONSE_READS = {"rows", "val_window", "backtest_window", "gate_rule"}

    # Per-row reads: r.has_history (62/95), r.instrument (63/66/67/97),
    #   r.source / r.round (64-65), r.last_trained (68), r.timesteps (69),
    #   r.val_sharpe (70), r.val_mdd_pct (71), r.val_cagr_pct (72),
    #   r.backtest_sharpe (73), r.backtest_mdd_pct (74),
    #   r.backtest_return_pct (75), r.trade_count (76), r.gate_pass (77)
    JS_ROW_READS = {
        "instrument", "last_trained", "timesteps",
        "val_sharpe", "val_mdd_pct", "val_cagr_pct",
        "backtest_sharpe", "backtest_mdd_pct", "backtest_return_pct",
        "trade_count", "gate_pass", "source", "round", "has_history",
    }

    def test_response_schema_covers_js_reads(self):
        schema_fields = set(ModelEvalSummaryResponse.model_fields)
        missing = self.JS_RESPONSE_READS - schema_fields
        assert not missing, f"JS reads fields missing from response schema: {missing}"

    def test_row_schema_covers_js_reads(self):
        schema_fields = set(ModelEvalSummaryRow.model_fields)
        missing = self.JS_ROW_READS - schema_fields
        assert not missing, f"JS reads fields missing from row schema: {missing}"

    def test_row_schema_has_no_extra_undocumented_fields(self):
        """Schema and JS reads match exactly — no dead fields either way."""
        assert set(ModelEvalSummaryRow.model_fields) == self.JS_ROW_READS

    @patch(f"{ROUTE}.load_latest_round")
    @patch(f"{ROUTE}.list_instrument_ids")
    def test_serialized_row_always_emits_every_key(self, mock_ids, mock_latest, client):
        """Optional fields serialize as null, never absent -> no undefined in JS."""
        mock_ids.return_value = ["ASML", "ATO"]
        mock_latest.side_effect = lambda inst: (
            _history_row(backtest_sharpe=1.2, backtest_mdd_pct=-8.0)
            if inst == "ASML" else None
        )

        body = client.get(SUMMARY_URL).json()

        assert set(body) >= self.JS_RESPONSE_READS
        for row in body["rows"]:
            assert set(row) == self.JS_ROW_READS, (
                f"row keys mismatch for {row.get('instrument')}"
            )
