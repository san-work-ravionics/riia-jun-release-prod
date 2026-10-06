"""F42 P5 - FnoSampleService + POST console-import/sample + import-status.sample block.

Synthetic only (the committed SAMPLE_* files and the fake P2 helper files); never live-data/."""
from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from rita.config import get_settings
from rita.database import Base
from rita.models.fno_import import (
    FnoImportRunModel as Run, FnoLedgerEntryModel as Ledger, FnoPnlLineModel as Line,
    FnoTradeModel as Trade,
)
from rita.repositories.fno_import import FnoImportRunRepo
from rita.repositories.fno_sample_files import FnoSampleFileRepo
from rita.schemas.fno_console_import import ImportStatusResponse, SampleLoadResponse
from rita.services import fno_sample_service as sample_mod
from rita.services.fno_import_service import FnoImportReadService, FnoImportService, UploadInput
from rita.services.fno_sample_service import FnoSampleService, lock_for
from tests.unit import f42_p2_helpers as p2
from tests.unit import f42_p5_helpers as h

_UP = "/api/v1/workflow/fno/console-import"
_SAMPLE = _UP + "/sample"
_ST = "/api/v1/experience/fno/trade-analysis/import-status"


@pytest.fixture(autouse=True)
def _input_dir(monkeypatch):
    """Resolve data.input_dir to the repo regardless of the pytest working directory."""
    monkeypatch.setattr(get_settings().data, "input_dir", str(h.REPO / "data" / "input"))


def _repo() -> FnoSampleFileRepo:
    return FnoSampleFileRepo.from_settings()


def _svc(db) -> FnoSampleService:
    return FnoSampleService(db, _repo())


def _counts(db, uid: str) -> dict:
    return {m.__tablename__: db.scalar(select(func.count()).select_from(m).where(m.user_id == uid))
            for m in (Trade, Ledger, Line, Run)}


def _real_import(db, uid: str):
    return FnoImportService(db).import_files(uid, [UploadInput("tb.csv", p2.tradebook())])


def _status(db, uid: str):
    return FnoImportReadService(db, _repo()).status(uid)


# ── service ────────────────────────────────────────────────────────────────────

def test_load_empty_user_creates_three_sample_runs(db_session):
    r = _svc(db_session).load("u1")
    assert r.status == "loaded" and r.reason is None and r.totals.files_failed == 0
    assert [f.status for f in r.files] == ["ok", "ok", "ok"]
    runs = list(db_session.scalars(select(Run).where(Run.user_id == "u1")))
    assert len(runs) == 3 and all(x.file_name.startswith("SAMPLE_") and x.status == "ok" for x in runs)
    assert r.window.from_ == "2026-07-01" and r.window.to == "2026-09-18"
    s = _status(db_session, "u1")
    assert s.has_data and s.sample.loaded and not s.sample.offer and not s.sample.can_load
    assert s.sample.window.from_ == "2026-07-01" and s.sample.file_prefix == "SAMPLE_"
    assert db_session.scalar(select(func.count()).select_from(Trade).where(Trade.user_id == "u1")) == 352


def test_second_load_is_already_loaded_with_window_and_no_writes(db_session):
    _svc(db_session).load("u1")
    before = _counts(db_session, "u1")
    r = _svc(db_session).load("u1")
    assert r.status == "already_loaded" and r.reason is None
    assert r.window is not None and r.window.from_ == "2026-07-01"
    assert r.files == [] and r.totals.model_dump() == {k: 0 for k in r.totals.model_dump()}
    assert _counts(db_session, "u1") == before


def test_user_with_own_data_is_refused_and_nothing_added(db_session):
    _real_import(db_session, "u1")
    before = _counts(db_session, "u1")
    r = _svc(db_session).load("u1")
    assert (r.status, r.reason) == ("refused", "has_own_data") and r.files == []
    assert _counts(db_session, "u1") == before
    s = _status(db_session, "u1")
    assert s.has_data and not s.sample.loaded and not s.sample.offer


def test_missing_sample_files_refused_nothing_written(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings().trade_analysis, "sample_dir", "does/not/exist")
    r = _svc(db_session).load("u1")
    assert (r.status, r.reason) == ("refused", "sample_files_missing")
    assert _counts(db_session, "u1") == {"personal_fno_trades": 0, "personal_fno_ledger_entries": 0,
                                         "personal_fno_pnl_lines": 0, "personal_fno_import_runs": 0}
    s = _status(db_session, "u1")
    assert s.sample.offer and not s.sample.can_load and s.sample.unavailable_reason == "sample_files_missing"


def test_readiness_reports_each_missing_or_empty_file(tmp_path):
    repo = FnoSampleFileRepo(tmp_path)
    assert not repo.readiness().ok and len(repo.readiness().missing) == 3
    (tmp_path / "SAMPLE_tradebook.csv").write_bytes(b"x")
    (tmp_path / "SAMPLE_ledger.csv").write_bytes(b"")           # empty = missing
    assert sorted(repo.readiness().missing) == ["SAMPLE_ledger.csv", "SAMPLE_pnl.csv"]
    ok = FnoSampleFileRepo(h.SAMPLE_DIR)
    assert ok.readiness().ok and set(ok.readiness().sizes) == set(h.NAMES.values())
    capped = FnoSampleFileRepo(h.SAMPLE_DIR, max_file_bytes=100)
    assert not capped.readiness().ok


def test_sample_disabled_kill_switch(db_session, monkeypatch):
    monkeypatch.setattr(get_settings().trade_analysis, "sample_enabled", False)
    r = _svc(db_session).load("u1")
    assert (r.status, r.reason) == ("refused", "sample_disabled")
    s = _status(db_session, "u1")
    assert not s.sample.enabled and not s.sample.offer and not s.sample.can_load
    assert _counts(db_session, "u1")["personal_fno_trades"] == 0


def _break_pnl_import(monkeypatch):
    """Make the third file (P&L) fail inside the real import service."""
    real = FnoImportService._persist
    calls = {"n": 0}

    def flaky(self, user_id, name, sha, size, parsed):
        calls["n"] += 1
        if parsed.kind == "pnl":
            raise RuntimeError("boom")
        return real(self, user_id, name, sha, size, parsed)

    monkeypatch.setattr(FnoImportService, "_persist", flaky)


def test_forced_failure_leaves_zero_rows_and_keeps_unrelated_history(db_session, monkeypatch):
    # an earlier failed REAL upload (audit row, no data): must survive the failed sample load
    FnoImportService(db_session).import_files("u1", [UploadInput("junk.csv", b"a,b\n1,2\n")])
    keep = db_session.scalar(select(func.count()).select_from(Run).where(Run.user_id == "u1"))
    assert keep == 1 and not _status(db_session, "u1").has_data
    assert _status(db_session, "u1").sample.offer                     # failed run does not hide the offer
    _break_pnl_import(monkeypatch)
    r = _svc(db_session).load("u1")
    assert (r.status, r.reason) == ("refused", "sample_failed")
    assert "boom" not in r.message and "cleanup" not in r.message
    c = _counts(db_session, "u1")
    assert c["personal_fno_trades"] == c["personal_fno_ledger_entries"] == c["personal_fno_pnl_lines"] == 0
    names = [x.file_name for x in db_session.scalars(select(Run).where(Run.user_id == "u1"))]
    assert names == ["junk.csv"]                                      # only this load's runs were deleted


def test_failed_real_upload_then_sample_load_is_loaded(db_session):
    FnoImportService(db_session).import_files("u1", [UploadInput("junk.csv", b"a,b\n1,2\n")])
    r = _svc(db_session).load("u1")
    assert r.status == "loaded"
    s = _status(db_session, "u1")
    assert s.sample.loaded and not s.sample.offer                     # failed runs are ignored by the rule


def test_forced_cleanup_failure_still_refuses_with_incomplete_message(db_session, monkeypatch):
    _break_pnl_import(monkeypatch)

    def bad_delete(self, user_id, ids):
        raise RuntimeError("cleanup boom")

    monkeypatch.setattr(FnoImportRunRepo, "delete_ids", bad_delete)
    r = _svc(db_session).load("u1")
    assert (r.status, r.reason) == ("refused", "sample_failed")
    assert "cleanup was incomplete" in r.message and "Delete my imported data" in r.message
    assert "boom" not in r.message


def test_sample_rule_ignores_failed_runs_and_requires_sample_trade_ids(db_session):
    # data imported under a RESERVED name but with real-looking (non-SMP) ids is NOT the sample
    FnoImportService(db_session).import_files(
        "u1", [UploadInput("SAMPLE_tradebook.csv", p2.tradebook())], allow_reserved=True)
    s = _status(db_session, "u1")
    assert s.has_data and not s.sample.loaded and not s.sample.offer


def test_partial_delete_keeps_sample_loaded_full_delete_reoffers(db_session):
    _svc(db_session).load("u1")
    FnoImportService(db_session).purge("u1", "ledger")
    s = _status(db_session, "u1")
    assert s.sample.loaded and not s.sample.offer                     # tradebook + P&L runs remain
    FnoImportService(db_session).purge("u1")
    s = _status(db_session, "u1")
    assert not s.has_data and not s.sample.loaded and s.sample.offer and s.sample.can_load
    r = _svc(db_session).load("u1")                                   # identical rows, new run rows
    assert r.status == "loaded"
    assert db_session.scalar(select(func.count()).select_from(Trade).where(Trade.user_id == "u1")) == 352


def test_two_users_are_isolated(db_session):
    _svc(db_session).load("u1")
    _real_import(db_session, "u2")
    assert _status(db_session, "u1").sample.loaded and not _status(db_session, "u2").sample.loaded
    assert _svc(db_session).load("u2").reason == "has_own_data"
    assert _counts(db_session, "u2")["personal_fno_trades"] == 3
    assert _svc(db_session).load("u3").status == "loaded"
    assert _counts(db_session, "u3")["personal_fno_trades"] == 352


def test_reserved_file_name_rejected_for_real_uploads(db_session):
    r = FnoImportService(db_session).import_files(
        "u1", [UploadInput("SAMPLE_mine.csv", p2.tradebook()), UploadInput("sample_other.CSV", p2.tradebook())])
    assert [f.status for f in r.files] == ["failed", "failed"]
    assert all(f.errors[0].code == "reserved_file_name" for f in r.files)
    s = _status(db_session, "u1")
    assert not s.has_data and not s.sample.loaded and s.sample.offer
    assert _counts(db_session, "u1")["personal_fno_trades"] == 0


# ── concurrency ────────────────────────────────────────────────────────────────

def test_striped_lock_registry_is_bounded_and_stable():
    assert len(sample_mod._LOCKS) == 64
    assert lock_for("alice") is lock_for("alice")
    assert all(lock_for(f"user-{i}") in sample_mod._LOCKS for i in range(500))


def test_two_threads_for_one_user_insert_once(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    maker = sessionmaker(bind=eng)
    out: list[str] = []
    start = threading.Barrier(2)

    def go():
        db = maker()
        try:
            start.wait()
            out.append(FnoSampleService(db, _repo()).load("racer").status)
        finally:
            db.close()

    ts = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(out) == ["already_loaded", "loaded"]
    db = maker()
    assert db.scalar(select(func.count()).select_from(Trade).where(Trade.user_id == "racer")) == 352
    assert db.scalar(select(func.count()).select_from(Run).where(Run.user_id == "racer")) == 3
    db.close()


# ── HTTP ───────────────────────────────────────────────────────────────────────

@pytest.fixture()
def user(client):
    from rita.auth import get_current_user
    from rita.main import app

    u = MagicMock()
    u.id = "u-api"
    app.dependency_overrides[get_current_user] = lambda: u
    yield u
    app.dependency_overrides.pop(get_current_user, None)


def test_post_sample_requires_auth(client):
    assert client.post(_SAMPLE).status_code == 401


def test_post_sample_empty_body_load_status_and_idempotence(client, user):
    r = client.post(_SAMPLE)                                   # no body, no files, no query
    assert r.status_code == 200
    body = r.json()
    assert set(body) == set(SampleLoadResponse.model_fields)
    assert body["status"] == "loaded" and body["reason"] is None
    assert body["window"] == {"from": "2026-07-01", "to": "2026-09-18"}
    assert [f["file_name"] for f in body["files"]] == ["SAMPLE_tradebook.csv", "SAMPLE_ledger.csv", "SAMPLE_pnl.csv"]
    st = client.get(_ST).json()
    assert set(st) == set(ImportStatusResponse.model_fields)
    assert st["sample"]["loaded"] is True and st["sample"]["offer"] is False
    assert st["sample"]["window"] == {"from": "2026-07-01", "to": "2026-09-18"}
    again = client.post(_SAMPLE).json()
    assert again["status"] == "already_loaded" and again["files"] == []


def test_real_upload_while_sample_loaded_is_409_then_delete_reoffers(client, user):
    client.post(_SAMPLE)
    r = client.post(_UP, files=[("files", ("tb.csv", p2.tradebook(), "text/csv"))])
    assert r.status_code == 409 and "Remove it before importing" in r.json()["detail"]
    assert client.delete(_UP + "?confirm=true").status_code == 200
    st = client.get(_ST).json()
    assert st["has_data"] is False and st["sample"]["loaded"] is False
    assert st["sample"]["offer"] is True and st["sample"]["can_load"] is True
    ok = client.post(_UP, files=[("files", ("tb.csv", p2.tradebook(), "text/csv"))])
    assert ok.status_code == 200 and ok.json()["files"][0]["status"] == "ok"


def test_upload_named_with_reserved_prefix_is_a_file_failure(client, user):
    r = client.post(_UP, files=[("files", ("SAMPLE_x.csv", p2.tradebook(), "text/csv"))])
    assert r.status_code == 200
    f = r.json()["files"][0]
    assert f["status"] == "failed" and f["errors"][0]["code"] == "reserved_file_name"
    assert client.get(_ST).json()["sample"]["loaded"] is False


def test_post_sample_refusals_are_http_200(client, user, monkeypatch):
    client.post(_UP, files=[("files", ("tb.csv", p2.tradebook(), "text/csv"))])
    r = client.post(_SAMPLE)
    assert r.status_code == 200 and (r.json()["status"], r.json()["reason"]) == ("refused", "has_own_data")
    monkeypatch.setattr(get_settings().trade_analysis, "sample_enabled", False)
    r = client.post(_SAMPLE)
    assert r.status_code == 200 and r.json()["reason"] == "sample_disabled"


def test_import_status_sample_block_for_new_user(client, user):
    sm = client.get(_ST).json()["sample"]
    assert sm == {"enabled": True, "loaded": False, "offer": True, "can_load": True,
                  "unavailable_reason": None, "window": None, "file_prefix": "SAMPLE_"}


def test_round_trip_every_panel_endpoint_returns_content(client, user, db_session):
    """Load the sample through the HTTP endpoint, then read EVERY analytics endpoint: each one
    returns real content (the empty-state reason is gone) - the sample is demo-able end to end."""
    h.seed_spot(db_session)                                 # spot cache = the pinned public closes
    assert client.post(_SAMPLE).json()["status"] == "loaded"
    base = "/api/v1/experience/fno/trade-analysis/analytics/"
    checks = {
        "foundation": lambda b: b["reconciliation"]["rows"] and b["fifo_totals"]["closed_trades"] > 50,
        "overtrading": lambda b: b["winloss"]["n"] > 50 and b["bursts"]["count"] >= 1,
        "buildup": lambda b: b["chain_totals"]["count"] > 50 and b["events"]["close"] > 50,
        "market-turn": lambda b: b["kpis"]["n_turn_days"] >= 1 and b["series"],
        "margin-trap": lambda b: b["cash"]["min"] is not None and b["cash_series"],
        "suggestions": lambda b: any(r["status"] == "applicable" for r in b["rules"]),
        "spot-vs-pnl": lambda b: all(u["available"] for u in b["underlyings"]) and b["underlyings"],
    }
    for panel, ok in checks.items():
        r = client.get(base + panel)
        assert r.status_code == 200, panel
        body = r.json()
        assert body["available"] is True and not body["reason"], panel
        assert ok(body), panel
    imported = client.get("/api/v1/experience/fno/trade-analysis/imported-trades").json()
    assert imported["total"] == 352 and all(t["trade_id"].startswith("SMP") for t in imported["items"])
