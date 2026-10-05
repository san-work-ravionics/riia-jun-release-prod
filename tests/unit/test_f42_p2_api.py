"""F42 P2 — upload/delete/status/imported-trades routes (TestClient, auth overridden)."""
from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from rita.config import get_settings
from rita.schemas.fno_console_import import (
    FnoImportResponse, ImportedTradesResponse, ImportStatusResponse, PurgeResponse,
)
from tests.unit import f42_p2_helpers as h

_UP = "/api/v1/workflow/fno/console-import"
_ST = "/api/v1/experience/fno/trade-analysis/import-status"
_TR = "/api/v1/experience/fno/trade-analysis/imported-trades"


@pytest.fixture()
def user(client):
    from rita.auth import get_current_user
    from rita.main import app

    u = MagicMock()
    u.id = "u-api"
    app.dependency_overrides[get_current_user] = lambda: u
    yield u
    app.dependency_overrides.pop(get_current_user, None)


def _post(client, *files):
    return client.post(_UP, files=[("files", f) for f in files])


def test_requires_auth(client):
    assert client.get(_ST).status_code == 401
    assert client.post(_UP, files=[("files", ("a.csv", b"x"))]).status_code == 401
    assert client.delete(_UP + "?confirm=true").status_code == 401


def test_post_mixed_files_shape(client, user):
    r = _post(client, ("tb.csv", h.tradebook(), "text/csv"), ("bad.csv", b"a,b\n1,2\n", "text/csv"),
              ("p.xlsx", h.pnl_xlsx(), "application/octet-stream"))
    assert r.status_code == 200
    body = r.json()
    assert set(body) == set(FnoImportResponse.model_fields)
    f = body["files"][0]
    assert set(f) == {"file_name", "kind", "status", "rows_parsed", "inserted", "updated",
                      "skipped_duplicates", "rejected", "period", "warnings", "errors",
                      "import_run_id"}
    assert set(f["period"]) == {"from", "to"} and f["period"]["from"] == "2026-06-15"
    assert [x["status"] for x in body["files"]] == ["ok", "failed", "ok"]
    assert body["files"][1]["errors"][0]["code"] == "unrecognised_file_kind"
    assert body["totals"]["files_failed"] == 1 and body["totals"]["inserted"] > 3


def test_post_validation_errors(client, user):
    assert client.post(_UP).status_code == 422
    cfg = get_settings().trade_analysis
    many = [("f%d.csv" % i, h.tradebook()) for i in range(cfg.import_max_files + 1)]
    assert _post(client, *many).status_code == 413
    r = _post(client, ("a.txt", b"x"), ("b.xls", b"x"), ("fake.csv", b"PK\x03\x04zip"),
              ("fake.xlsx", b"plain"))
    assert [f["errors"][0]["code"] for f in r.json()["files"]] == \
        ["unsupported_extension", "unsupported_extension", "bad_file_type", "bad_file_type"]


def test_post_size_limits(client, user, monkeypatch):
    cfg = get_settings().trade_analysis
    monkeypatch.setattr(cfg, "import_max_file_bytes", 100)
    r = _post(client, ("big.csv", b"x" * 500))
    assert r.json()["files"][0]["errors"][0]["code"] == "file_too_large"
    monkeypatch.setattr(cfg, "import_max_total_bytes", 150)
    assert _post(client, ("a.csv", b"x" * 90), ("b.csv", b"x" * 90)).status_code == 413
    monkeypatch.setattr(cfg, "import_max_total_bytes", 10)
    assert _post(client, ("c.csv", b"x" * 90)).status_code == 413   # early Content-Length check


def test_traversal_filename_creates_nothing(client, user, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = _post(client, ("../../evil.csv", h.tradebook(), "text/csv"))
    assert r.json()["files"][0]["file_name"] == "evil.csv"
    assert list(tmp_path.iterdir()) == [] and not os.path.exists("/evil.csv")


def test_status_empty_then_filled_and_trades(client, user):
    r = client.get(_ST)
    assert r.status_code == 200
    s = r.json()
    assert set(s) == set(ImportStatusResponse.model_fields) and s["has_data"] is False
    assert s["trades"]["count"] == 0 and s["trades"]["first_date"] is None
    assert set(s["limits"]) == {"max_file_bytes", "max_files", "max_total_bytes",
                                "allowed_extensions"}
    _post(client, ("tb.csv", h.tradebook()), ("p.xlsx", h.pnl_xlsx()), ("l.csv", h.ledger()))
    s = client.get(_ST).json()
    assert s["has_data"] and s["trades"]["count"] == 3 and s["trades"]["in_scope_count"] == 2
    assert s["pnl"]["periods"] == [{"from": "2026-04-01", "to": "2026-10-05"}]
    assert s["ledger"]["count"] == 3 and len(s["recent_runs"]) == 3
    assert s["last_imports"]["ledger"]["kind"] == "ledger"

    t = client.get(_TR).json()
    assert set(t) == set(ImportedTradesResponse.model_fields)
    assert t["total"] == 2 and t["filter"]["date_from"] == "2026-07-01"
    assert set(t["items"][0]) == {"trade_date", "order_execution_time", "symbol", "underlying",
                                  "instrument_type", "strike", "expiry_date", "trade_type",
                                  "quantity", "price", "trade_id", "order_id"}
    assert client.get(_TR + "?include_fut=true&date_from=2026-06-01").json()["total"] == 3
    assert client.get(_TR + "?page_size=1&page=2").json()["items"][0]["trade_id"] == "T1"
    for bad in ("page=0", "page_size=201", "underlying=XYZ", "expiry_month=13", "side=hold"):
        assert client.get(_TR + "?" + bad).status_code == 422


def test_other_user_sees_nothing(client, user):
    from rita.auth import get_current_user
    from rita.main import app

    _post(client, ("tb.csv", h.tradebook()))
    other = MagicMock()
    other.id = "someone-else"
    app.dependency_overrides[get_current_user] = lambda: other
    assert client.get(_ST).json()["has_data"] is False
    assert client.get(_TR).json()["total"] == 0
    assert client.delete(_UP + "?confirm=true").json()["deleted"]["personal_fno_trades"] == 0
    app.dependency_overrides[get_current_user] = lambda: user
    assert client.get(_ST).json()["trades"]["count"] == 3


def test_delete_requires_confirm_and_counts(client, user):
    _post(client, ("tb.csv", h.tradebook()), ("l.csv", h.ledger()))
    assert client.delete(_UP).status_code == 422
    assert client.delete(_UP + "?confirm=true&kind=bogus").status_code == 422
    r = client.delete(_UP + "?confirm=true&kind=tradebook")
    assert set(r.json()) == set(PurgeResponse.model_fields)
    d = r.json()["deleted"]
    assert d["personal_fno_trades"] == 3 and d["personal_fno_import_runs"] == 1
    d = client.delete(_UP + "?confirm=true").json()["deleted"]
    assert d["personal_fno_ledger_entries"] == 3 and d["personal_fno_import_runs"] == 1


def test_experience_gets_never_commit(client, user, db_session, monkeypatch):
    commits = []
    monkeypatch.setattr(db_session, "commit", lambda: commits.append(1))
    assert client.get(_ST).status_code == 200 and client.get(_TR).status_code == 200
    assert commits == []
