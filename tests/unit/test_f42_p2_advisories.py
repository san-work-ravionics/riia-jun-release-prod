"""F42 P2 code-review advisory fixes (synthetic data only)."""
from __future__ import annotations

import io
import time
import zipfile
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import func, select

from rita.models.fno_import import FnoImportRunModel as Run, FnoPnlLineModel as Line
from rita.services import console_parsers as cp
from rita.services.fno_import_service import FnoImportService, UploadInput
from tests.unit import f42_p2_helpers as h


def _imp(db, name, data, user="u1"):
    return FnoImportService(db).import_files(user, [UploadInput(name, data)]).files[0]


def test_extreme_exponents_rejected_fast():
    t0 = time.time()
    for bad in ("1e500000", "1e99999", "9" * 200, 10 ** 200):
        with pytest.raises(ValueError):
            cp.to_decimal(bad)
    assert time.time() - t0 < 1
    pf = cp.parse_file(h.tradebook([h.tb_row(tid="A", qty="1e500000"), h.tb_row(tid="B")]), "t.csv", 99)
    assert pf.rows_rejected == 1 and len(pf.records) == 1
    pl = cp.parse_file(h.ledger([["X", "2026-09-01", "", "J", "1e99999", "", ""]]), "l.csv", 99)
    assert pl.rows_rejected == 1 and pl.errors[0].code == "invalid_number"


def test_unexpected_parse_exception_is_audited_not_500(db_session):
    with patch("rita.services.fno_import_service.parse_file", side_effect=ArithmeticError("x")):
        r = _imp(db_session, "t.csv", h.tradebook())
    assert r.status == "failed" and r.errors[0].code == "unreadable"
    assert db_session.scalar(select(func.count()).select_from(Run)) == 1


def test_xlsx_zip_bomb_guards(db_session):
    big = io.BytesIO()
    with zipfile.ZipFile(big, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("a.xml", b"0" * 5_000_000)
    with pytest.raises(cp.ParseFailure) as e:
        cp.check_xlsx_zip(big.getvalue(), 10_000_000, 100)
    assert e.value.code == "xlsx_suspicious"
    with pytest.raises(cp.ParseFailure) as e:
        cp.check_xlsx_zip(big.getvalue(), 1_000_000, 10_000)
    assert e.value.code == "xlsx_too_large"
    r = _imp(db_session, "b.xlsx", big.getvalue())
    assert r.status == "failed" and r.errors[0].code in ("xlsx_suspicious", "xlsx_too_large")
    cp.check_xlsx_zip(h.pnl_xlsx(), 10_000_000, 100)  # normal workbook passes


def test_missing_content_length_rejected(client):
    from rita.auth import get_current_user
    from rita.main import app

    u = MagicMock()
    u.id = "u"
    app.dependency_overrides[get_current_user] = lambda: u
    try:
        def gen():
            yield b"--x--"
        r = client.post("/api/v1/workflow/fno/console-import", content=gen(),
                        headers={"content-type": "multipart/form-data; boundary=x"})
        assert r.status_code == 411
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_pnl_partial_or_empty_file_does_not_delete(db_session):
    _imp(db_session, "p.xlsx", h.pnl_xlsx())
    n = lambda: db_session.scalar(select(func.count()).select_from(Line))  # noqa: E731
    assert n() == 2
    empty = _imp(db_session, "p.xlsx", h.pnl_xlsx(symbols=[]))
    assert n() == 2 and any("kept" in w for w in empty.warnings) and empty.updated == 0
    partial_bytes = h.pnl_xlsx(symbols=[("NIFTY26OCT24000CE", "abc"), ("NIFTY26NOV24000CE", 5.0)])
    part = _imp(db_session, "p.xlsx", partial_bytes)
    assert part.status == "partial" and any("kept" in w for w in part.warnings)
    syms = {s for (s,) in db_session.execute(select(Line.symbol))}
    assert syms == {"NIFTY26OCT24000CE", "NIFTY26OCT24000PE", "NIFTY26NOV24000CE"}
    # the existing CE row was not touched
    ce = db_session.scalars(select(Line).where(Line.symbol == "NIFTY26OCT24000CE")).one()
    assert ce.realized_pnl == 100.0


def test_purge_all_removes_unknown_runs_kind_scoped_keeps_them(db_session):
    svc = FnoImportService(db_session)
    _imp(db_session, "bad.csv", b"a,b\n1,2\n")
    _imp(db_session, "t.csv", h.tradebook())
    svc.purge("u1", "tradebook")
    kinds = {k for (k,) in db_session.execute(select(Run.kind))}
    assert kinds == {"unknown"}
    d = svc.purge("u1").deleted
    assert d.personal_fno_import_runs == 1
    assert db_session.scalar(select(func.count()).select_from(Run)) == 0


def test_tz_aware_datetime_converted_to_ist():
    utc = datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc)
    assert cp.to_datetime(utc) == datetime(2026, 10, 1, 9, 30)
    naive = datetime(2026, 10, 1, 9, 30)
    assert cp.to_datetime(naive) == naive
    plus = datetime(2026, 10, 1, 9, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert cp.to_datetime(plus) == naive


def test_delimiter_sniff_uses_several_lines():
    # first line has a stray comma in a title cell; later lines are tab-delimited
    raw = b"Title, with comma\ntrade_id\torder_id\ttrade_type\nA\tB\tbuy\nC\tD\tsell\n"
    rows = cp.read_table(raw, "t.csv", 100)["csv"]
    assert rows[1] == ["trade_id", "order_id", "trade_type"]


def test_js_escapes_quotes_and_date_hint():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    js = (root / "dashboard/js/fno/trade-import.js").read_text()
    assert "&quot;" in js and "&#39;" in js and "ta-imp-from-hint" in js
    assert 'id="ta-imp-from-hint"' in (root / "dashboard/fno.html").read_text()
