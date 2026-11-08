"""``scripts/refresh_fx.py`` — the skill-run entry point for ``data_refresh.refresh_fx`` (org.md section 3:
FX rates are fetched only in a refresh-skill run, never from request code).  The script must open and close
its own DB session, print the per-pair results as JSON, and exit non-zero when a pair failed.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "refresh_fx.py"


def _load():
    spec = importlib.util.spec_from_file_location("refresh_fx_script", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Session:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _run(monkeypatch, results):
    mod = _load()
    session = _Session()
    seen = {}
    monkeypatch.setattr(mod, "SessionLocal", lambda: session)

    def fake_refresh(db):
        seen["db"] = db
        return results

    monkeypatch.setattr(mod, "refresh_fx", fake_refresh)
    return mod, session, seen


def test_prints_the_results_and_exits_zero_when_every_pair_is_ok(monkeypatch, capsys):
    results = [{"pair": "FX_EURINR", "ticker": "EURINR=X", "rows_inserted": 284, "status": "ok", "error": None},
               {"pair": "FX_EURUSD", "ticker": "EURUSD=X", "rows_inserted": 0, "status": "current", "error": None}]
    mod, session, seen = _run(monkeypatch, results)
    assert mod.main() == 0
    assert seen["db"] is session and session.closed
    assert json.loads(capsys.readouterr().out) == results


def test_exits_non_zero_when_a_pair_failed_but_still_reports_all_pairs(monkeypatch, capsys):
    results = [{"pair": "FX_EURINR", "ticker": "EURINR=X", "rows_inserted": 0, "status": "error", "error": "boom"},
               {"pair": "FX_EURUSD", "ticker": "EURUSD=X", "rows_inserted": 5, "status": "ok", "error": None}]
    mod, session, _ = _run(monkeypatch, results)
    assert mod.main() == 1
    assert session.closed
    assert [r["pair"] for r in json.loads(capsys.readouterr().out)] == ["FX_EURINR", "FX_EURUSD"]


def test_the_session_is_closed_even_when_the_refresh_raises(monkeypatch):
    mod = _load()
    session = _Session()
    monkeypatch.setattr(mod, "SessionLocal", lambda: session)

    def boom(_db):
        raise RuntimeError("network down")

    monkeypatch.setattr(mod, "refresh_fx", boom)
    with pytest.raises(RuntimeError):
        mod.main()
    assert session.closed


def test_request_reachable_refresh_all_never_fetches_fx():
    """org.md section 3: ``refresh_all`` is also reachable from a request (instrument onboarding), so FX
    must only be fetched by the skill-run script, never by it."""
    import inspect

    from rita.services import data_refresh

    assert "refresh_fx" not in inspect.getsource(data_refresh.refresh_all)
    api = Path(__file__).resolve().parents[2] / "src" / "rita" / "api"
    assert [p.name for p in api.rglob("*.py") if "refresh_fx(" in p.read_text(encoding="utf-8")] == []
