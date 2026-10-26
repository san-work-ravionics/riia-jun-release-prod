"""F44 P3 — data integrity (``core/data_integrity.py``) and step 0, the full-history rewrite in
``services/data_refresh.py`` (design rev 1 A6, rev 3 N5, N10).

- the threshold comes from the instrument's own pre-``train_end`` history (no hand-set number)
- step 0 rewrites ONLY an instrument that fails; every other instrument keeps its file
- the rewrite marker invalidates the registered lineages (→ ``retrain_needed``) either way
- injected downloader; no network (socket guard)
"""
from __future__ import annotations

import json
import socket
from datetime import date
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

import rita.core.data_loader as data_loader
from rita.config import get_settings
from rita.core.data_integrity import check_window
from rita.repositories.model_artifact import REWRITE_MARKER, ModelArtifactRepository
from rita.services import data_refresh

TRAIN_END = date(2022, 12, 31)


def _close(jump_at=None, factor=86.0, seed=0, start="2020-01-01", end="2025-06-30"):
    """Random walk; the post-train_end bars are calmer than the pre-train_end ones, so only an
    injected jump can cross the instrument's own pre-train_end max."""
    idx = pd.bdate_range(start, end)
    rng = np.random.default_rng(seed)
    vol = np.where(idx <= pd.Timestamp(TRAIN_END), 0.012, 0.006)
    s = pd.Series(50 * np.cumprod(1 + rng.normal(0, 1, len(idx)) * vol), index=idx)
    if jump_at is not None:
        s[s.index >= pd.Timestamp(jump_at)] *= factor
    return s


# ── check_window ───────────────────────────────────────────────────────────────

def test_clean_series_passes():
    res = check_window(_close(), TRAIN_END)
    assert res.passed and res.threshold > 0 and res.detail() is None


def test_split_jump_after_train_end_fails_with_date_and_value():
    res = check_window(_close(jump_at="2024-11-12"), TRAIN_END)
    assert not res.passed
    assert res.failures[0][0] == date(2024, 11, 12)
    assert res.failures[0][1] == pytest.approx(np.log(86), abs=0.1)
    assert "2024-11-12" in res.detail() and "pre-train_end max" in res.detail()


def test_threshold_is_the_instruments_own_pre_train_end_max():
    s = _close()
    s[s.index >= pd.Timestamp("2021-06-01")] *= 1.5          # a +40 % day before train_end
    s[s.index >= pd.Timestamp("2024-03-01")] *= 1.3          # a +26 % day after it
    res = check_window(s, TRAIN_END)
    assert res.threshold == pytest.approx(np.log(1.5), abs=0.05)
    assert res.passed                                          # below the instrument's own max
    s2 = _close()
    s2[s2.index >= pd.Timestamp("2024-03-01")] *= 1.3
    assert not check_window(s2, TRAIN_END).passed              # above a calm instrument's max


def test_jump_before_train_end_only_is_not_a_window_failure():
    assert check_window(_close(jump_at="2021-03-01"), TRAIN_END).passed


def test_no_pre_train_end_history_fails_closed():
    res = check_window(_close(start="2023-02-01"), TRAIN_END)
    assert not res.passed and res.threshold is None


# ── step 0 ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def data_dirs(tmp_path, monkeypatch):
    raw, inp = tmp_path / "raw", tmp_path / "input"
    raw.mkdir()
    inp.mkdir()
    for s in {id(get_settings()): get_settings(), id(data_loader.settings): data_loader.settings}.values():
        monkeypatch.setattr(s.data, "raw_dir", str(raw))
        monkeypatch.setattr(s.data, "input_dir", str(inp))
    return raw


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("network access in a unit test")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


def _write_raw(raw, inst, close: pd.Series):
    d = raw / inst
    d.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame({"Close": close, "High": close, "Low": close, "Open": close,
                       "Volume": 1000}, index=close.index)
    df.index.name = "date"
    p = d / f"{inst.lower()}_daily.csv"
    df.to_csv(p)
    return p


class _Downloader:
    def __init__(self, close: pd.Series):
        self.close = close
        self.calls: list[tuple] = []

    def __call__(self, ticker, **kw):
        self.calls.append((ticker, kw))
        c = self.close
        cols = pd.MultiIndex.from_tuples([(f, ticker) for f in ("Close", "High", "Low", "Open", "Volume")])
        return pd.DataFrame(np.column_stack([c, c, c, c, np.full(len(c), 5.0)]), index=c.index,
                            columns=cols)


def test_rewrite_only_for_a_failing_instrument_and_marker(data_dirs, no_network):
    clean = _close(seed=1)
    broken = _close(seed=2, jump_at="2024-11-12")
    p_ok = _write_raw(data_dirs, "OKI", clean)
    p_bad = _write_raw(data_dirs, "BRK", broken)
    before_ok = p_ok.read_bytes()

    dl_ok = _Downloader(clean)
    assert data_refresh.rewrite_history_if_broken("OKI", "OKI.X", downloader=dl_ok) == \
        {"instrument": "OKI", "checked": True, "rewritten": False}
    assert dl_ok.calls == [] and p_ok.read_bytes() == before_ok
    assert not (data_dirs / "OKI" / REWRITE_MARKER).exists()

    fixed = _close(seed=2)
    dl = _Downloader(fixed)
    res = data_refresh.rewrite_history_if_broken("BRK", "BRK.X", downloader=dl)
    assert res["rewritten"] and res["integrity_after_passed"]
    (ticker, kw), = dl.calls
    assert ticker == "BRK.X" and kw["auto_adjust"] is True
    assert kw["start"] == str(broken.index[0].date())          # full history
    stored = pd.read_csv(p_bad, index_col=0, parse_dates=True)["Close"]
    assert np.allclose(stored.to_numpy(), fixed.to_numpy())
    marker = json.loads((data_dirs / "BRK" / REWRITE_MARKER).read_text())
    assert marker["lineages_invalidated"] == ["f34p25"]
    assert marker["integrity_after_passed"] is True and "2024-11-12" in marker["integrity_before"]["f34p25"]
    # the repository reads it back (→ retrain_needed in the service)
    repo = ModelArtifactRepository(data_dirs, data_dirs)
    assert repo.rewrite_marker("BRK")["reason"] == "data_integrity"
    assert repo.rewrite_marker("OKI") is None


def test_rewrite_that_is_still_broken_is_recorded(data_dirs, no_network):
    broken = _close(seed=3, jump_at="2024-12-06", factor=0.015)
    _write_raw(data_dirs, "ATX", broken)
    res = data_refresh.rewrite_history_if_broken("ATX", "ATX.PA", downloader=_Downloader(broken))
    assert res["rewritten"] and res["integrity_after_passed"] is False
    marker = json.loads((data_dirs / "ATX" / REWRITE_MARKER).read_text())
    assert marker["integrity_after_passed"] is False and marker["integrity_after"]["f34p25"]
    assert marker["lineages_invalidated"] == ["f34p25"]       # excluded either way (N10)


def test_refresh_all_runs_step0_after_the_append_and_never_aborts():
    calls = []

    def _gap(inst, _db):
        return {"instrument_id": inst, "last_date": date(2026, 10, 1), "gap_days": 3,
                "yf_ticker": data_refresh.YF_TICKER_MAP.get(inst)}

    def _rewrite(inst, ticker):
        calls.append(inst)
        if inst == "ATO":
            raise RuntimeError("download failed")
        return {"rewritten": False}

    with patch.object(data_refresh, "check_gap", side_effect=_gap), \
            patch.object(data_refresh, "fetch_and_write_raw", return_value=(None, 2)) as fetch, \
            patch.object(data_refresh, "rewrite_history_if_broken", side_effect=_rewrite), \
            patch.object(data_refresh, "rebuild_input"), \
            patch.object(data_refresh, "upsert_cache_delta", return_value=2):
        results = data_refresh.refresh_all(db=None)
    expected = sorted(set(data_refresh.YF_TICKER_MAP) - data_refresh.SKIP_INSTRUMENTS)
    assert calls == expected and fetch.call_count == len(expected)
    assert all(r["status"] == "ok" for r in results)            # ATO's step-0 failure is logged only
