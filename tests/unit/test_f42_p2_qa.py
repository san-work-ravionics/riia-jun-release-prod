"""F42 P2 - QA edge-case, contract and design-conformance tests (synthetic fixtures only).

Complements test_f42_p2_{parsers,service,api,advisories,static_migration}.py: only cases the
design (section 7 / 9) lists that those files do not already pin down.
"""
from __future__ import annotations

import io
import os
import re
import sqlite3
import subprocess
import sys
import zipfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import openpyxl
import pytest
from sqlalchemy import func, select

from rita.config import get_settings
from rita.models.fno_import import (
    FnoImportRunModel as Run, FnoLedgerEntryModel as Ledger, FnoPnlChargeModel as Charge,
    FnoPnlLineModel as Line, FnoTradeModel as Trade,
)
from rita.schemas import fno_console_import as S
from rita.services import console_parsers as cp
from rita.services.fno_import_service import FnoImportReadService, FnoImportService, UploadInput
from rita.services.fno_symbol_parser import parse_symbol
from tests.unit import f42_p2_helpers as h

_ROOT = Path(__file__).resolve().parents[2]
_JS = (_ROOT / "dashboard/js/fno/trade-import.js").read_text()
_HTML = (_ROOT / "dashboard/fno.html").read_text()
_MAIN = (_ROOT / "dashboard/js/fno/main.js").read_text()
_UP = "/api/v1/workflow/fno/console-import"
_ST = "/api/v1/experience/fno/trade-analysis/import-status"
_TR = "/api/v1/experience/fno/trade-analysis/imported-trades"


def _n(db, model, user=None):
    q = select(func.count()).select_from(model)
    if user:
        q = q.where(model.user_id == user)
    return db.scalar(q)


def _imp(db, name, data, user="u1"):
    return FnoImportService(db).import_files(user, [UploadInput(name, data)]).files[0]


# -- 1. wrong kind / detection by content / empty / header-only -----------------------

def test_kind_detected_by_content_not_file_name(db_session):
    r = _imp(db_session, "tradebook_FAKE.csv", h.ledger())
    assert (r.kind, r.status) == ("ledger", "ok")
    r = _imp(db_session, "ledger_FAKE.CSV", h.tradebook())
    assert (r.kind, r.status) == ("tradebook", "ok")
    r = _imp(db_session, "whatever.xlsx", h.pnl_xlsx())
    assert r.kind == "pnl"


def test_unrecognised_csv_fails_with_audit_row_and_no_data(db_session):
    r = _imp(db_session, "x.csv", b"foo,bar\n1,2\n3,4\n")
    assert r.status == "failed" and r.kind is None and r.errors[0].code == "unrecognised_file_kind"
    run = db_session.scalars(select(Run)).one()
    assert run.kind == "unknown" and run.status == "failed" and run.rows_inserted == 0
    assert _n(db_session, Trade) == _n(db_session, Ledger) == _n(db_session, Line) == 0


def test_empty_file_failed_header_only_ok_with_warning(db_session):
    r = _imp(db_session, "e.csv", b"")
    assert r.status == "failed" and r.errors[0].code == "empty_file"
    r = _imp(db_session, "t.csv", h.csv_bytes(h.TB_HEADER, []))
    assert (r.status, r.rows_parsed, r.inserted, r.kind) == ("ok", 0, 0, "tradebook")
    assert any("no data rows" in w for w in r.warnings)
    r = _imp(db_session, "l.csv", h.csv_bytes(h.LEDGER_HEADER, []))
    assert (r.status, r.rows_parsed, r.kind) == ("ok", 0, "ledger")
    assert r.period.from_ is None and r.period.to is None


def test_whitespace_only_file_not_a_500(db_session):
    assert _imp(db_session, "w.csv", b"\n\n   \n").status == "failed"


# -- 2. duplicates / overlap / key semantics -------------------------------------------

def test_in_file_duplicates_counted_as_skipped(db_session):
    rows = [h.tb_row(tid="A"), h.tb_row(tid="A"), h.tb_row(tid="B")]
    r = _imp(db_session, "t.csv", h.tradebook(rows))
    assert (r.inserted, r.skipped_duplicates, r.rows_parsed, r.status) == (2, 1, 3, "ok")


def test_overlapping_tradebooks_zero_dups_on_reimport(db_session):
    a = h.tradebook([h.tb_row(tid=t, oid="O" + t) for t in "123"])
    b = h.tradebook([h.tb_row(tid=t, oid="O" + t) for t in "234"])
    assert _imp(db_session, "a.csv", a).inserted == 3
    rb = _imp(db_session, "b.csv", b)
    assert (rb.inserted, rb.skipped_duplicates) == (1, 2)
    for data in (a, b, a, b):
        r = _imp(db_session, "x.csv", data)
        assert r.inserted == 0 and r.skipped_duplicates == 3
    assert _n(db_session, Trade) == 4


def test_same_trade_id_diff_order_kept_and_diff_date_kept(db_session):
    rows = [h.tb_row(tid="A", oid="1", d="2026-10-01"), h.tb_row(tid="A", oid="2", d="2026-10-01"),
            h.tb_row(tid="A", oid="1", d="2026-10-02")]
    r = _imp(db_session, "t.csv", h.tradebook(rows))
    assert r.inserted == 3 and r.skipped_duplicates == 0
    assert _imp(db_session, "t.csv", h.tradebook(rows)).inserted == 0


def test_same_key_other_user_is_independent(db_session):
    assert _imp(db_session, "t.csv", h.tradebook(), user="a").inserted == 3
    assert _imp(db_session, "t.csv", h.tradebook(), user="b").inserted == 3


# -- 3. P&L variants -------------------------------------------------------------------

@pytest.mark.parametrize("offset", [1, 3, 12, 40])
def test_pnl_header_offset_service(db_session, offset):
    r = _imp(db_session, f"p{offset}.xlsx", h.pnl_xlsx(offset=offset, extra_sheet=True))
    assert r.status == "ok" and any("Ignored sheets" in w for w in r.warnings)
    assert _n(db_session, Line) == 2


def test_pnl_identical_reimport_idempotent_counts(db_session):
    _imp(db_session, "p.xlsx", h.pnl_xlsx())
    lines, charges = _n(db_session, Line), _n(db_session, Charge)
    r = _imp(db_session, "p.xlsx", h.pnl_xlsx())
    assert (_n(db_session, Line), _n(db_session, Charge)) == (lines, charges)
    assert r.updated > 0 and r.inserted == 0


def test_pnl_different_periods_side_by_side_and_status_lists_both(db_session):
    _imp(db_session, "a.xlsx", h.pnl_xlsx(period=("2026-04-01", "2026-06-30")))
    _imp(db_session, "b.xlsx", h.pnl_xlsx(period=("2026-07-01", "2026-10-05")))
    st = FnoImportReadService(db_session).status("u1")
    assert st.pnl.line_count == 4 and len(st.pnl.periods) == 2


def test_pnl_extreme_number_row_partial_keeps_old(db_session):
    _imp(db_session, "p.xlsx", h.pnl_xlsx())
    r = _imp(db_session, "p2.xlsx", h.pnl_xlsx(symbols=[("NIFTY26OCT24000CE", "1e99999"),
                                                         ("NIFTY26NOV24000CE", 3.0)]))
    assert r.status == "partial" and r.rejected == 1
    ce = db_session.scalars(select(Line).where(Line.symbol == "NIFTY26OCT24000CE")).one()
    assert ce.realized_pnl == 100.0


def test_pnl_csv_variant_parses():
    import csv
    rows = [[], ["P&L Statement for F&O from 2026-04-01 to 2026-10-05"], ["Charges", "10"],
            [], h.PNL_HEADER,
            ["NIFTY26OCT24000CE", "", "75", "1", "2", "5", "", "", "0", "", "0", "0", "0"]]
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    pf = cp.parse_file(buf.getvalue().encode(), "p.csv", 1000)
    assert pf.kind == "pnl" and len(pf.records) == 1


# -- sheet-dimension regression: read-only mode must not truncate rows ------------------

def _multi_sheet_pnl_xlsx(tmp_path: Path, wrong_dimension: bool) -> bytes:
    """Multi-sheet P&L: summary block, charges table, 'Symbol' header in column B at row 38."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "F&O"
    ws.append([None, "P&L Statement for F&O from 2026-04-01 to 2026-10-05"])
    for _ in range(3):
        ws.append([])
    for label, val in (("Charges", 1234.5), ("Other Credit & Debit", -50.25),
                       ("Realized P&L", 9999.0), ("Unrealized P&L", -10.0)):
        ws.append([None, label, val])
    for _ in range(14 - 8):  # rows 1-8 written so far; blank rows up to 13
        ws.append([])
    for label, val in (("Brokerage", 20), ("Exchange Transaction Charges", 5), ("STT", 7)):
        ws.append([None, label, val])
    for _ in range(37 - 16):  # header lands on row 38
        ws.append([])
    ws.append([None] + h.PNL_HEADER)
    for sym, pnl in (("NIFTY26OCT24000CE", 100.0), ("NIFTY26OCT24000PE", -40.5),
                     ("BANKNIFTY26NOV50000CE", 12.0)):
        ws.append([None, sym, "", 75, 1000.0, 1100.0, pnl, 1.5, 10.0, 0, "", 0, 0.0, 0.0])
    o = wb.create_sheet("Other Debits and Credits")
    o.append(["Date", "Particulars", "Amount"])
    o.append([date(2026, 5, 5), "Fake DP charge", -15.0])
    src = tmp_path / "orig.xlsx"
    wb.save(src)
    if not wrong_dimension:
        return src.read_bytes()
    out = io.BytesIO()
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.startswith("xl/worksheets/sheet"):
                data, n = re.subn(rb'<dimension ref="[^"]*"\s*/>', b'<dimension ref="A1"/>', data)
                assert n == 1, item.filename
            zout.writestr(item, data)
    return out.getvalue()


def test_pnl_workbook_with_wrong_declared_dimension_not_truncated(tmp_path):
    """A workbook whose declared sheet dimension is wrong must not be truncated in read-only mode."""
    raw = _multi_sheet_pnl_xlsx(tmp_path, wrong_dimension=True)
    sheets = cp.read_table(raw, "pnl.xlsx", 100000)
    assert len(sheets["F&O"]) >= 41
    pf = cp.parse_file(raw, "pnl.xlsx", 100000)
    assert pf.kind == "pnl"
    assert [r["symbol"] for r in pf.records] == [
        "NIFTY26OCT24000CE", "NIFTY26OCT24000PE", "BANKNIFTY26NOV50000CE"]
    assert (pf.period_from, pf.period_to) == (date(2026, 4, 1), date(2026, 10, 5))
    assert any(c["section"] == "other_dc" for c in pf.charges)


def test_pnl_workbook_with_correct_dimension_parses(tmp_path):
    pf = cp.parse_file(_multi_sheet_pnl_xlsx(tmp_path, wrong_dimension=False), "pnl.xlsx", 100000)
    assert pf.kind == "pnl" and len(pf.records) == 3
    assert any(c["section"] == "other_dc" for c in pf.charges)


# -- 4. ledger -------------------------------------------------------------------------

def test_ledger_hash_float_decimal_str_stability():
    d = date(2026, 9, 1)
    hs = {cp.ledger_content_hash(d, "J", "", "p", v, 0)
          for v in (0.1 + 0.2, "0.3", Decimal("0.30"), 0.3)}
    assert len(hs) == 1
    assert cp.normalise_money(-0.00001) == "0.0000"
    assert cp.ledger_content_hash(d, "J", "", "p", 5, 0) != cp.ledger_content_hash(d, "J", "", "p", 0, 5)


def test_ledger_identical_repeated_rows_across_files(db_session):
    row = ["Fake X", "2026-09-01", "", "Journal", "10", "", ""]
    other = ["Fake Y", "2026-09-03", "", "Journal", "", "4", ""]
    assert _imp(db_session, "l.csv", h.ledger([row, row, row])).inserted == 3
    r = _imp(db_session, "l2.csv", h.ledger([row, row, other]))
    assert r.inserted == 1 and r.skipped_duplicates == 2
    assert _n(db_session, Ledger) == 4


def test_ledger_net_balance_change_is_not_a_new_row(db_session):
    a = ["Fake X", "2026-09-01", "", "Journal", "10", "", "100"]
    b = ["Fake X", "2026-09-01", "", "Journal", "10", "", "999"]
    _imp(db_session, "l.csv", h.ledger([a]))
    assert _imp(db_session, "l.csv", h.ledger([b])).inserted == 0


def test_ledger_bad_date_and_undated_rows_partial(db_session):
    rows = [["Fake X", "2026-09-01", "", "J", "1", "", ""],
            ["Opening balance", "", "", "", "", "", "5"],
            ["Fake Z", "31-02-2026", "", "J", "1", "", ""]]
    r = _imp(db_session, "l.csv", h.ledger(rows))
    assert (r.status, r.inserted, r.rejected) == ("partial", 1, 2)
    assert {e.code for e in r.errors} == {"invalid_date"}


def test_ledger_extreme_number_rejected_not_500(db_session):
    r = _imp(db_session, "l.csv", h.ledger([["X", "2026-09-01", "", "J", "1e99999", "", ""],
                                            ["Y", "2026-09-01", "", "J", "1", "", ""]]))
    assert (r.status, r.inserted, r.rejected) == ("partial", 1, 1)


# -- 5. coercion: dates / qty -----------------------------------------------------------

@pytest.mark.parametrize("bad", ["1980-01-01", "2099-01-01", "2026-13-40", "yesterday"])
def test_tradebook_bad_dates_rejected(bad):
    pf = cp.parse_file(h.tradebook([h.tb_row(tid="A", d=bad), h.tb_row(tid="B")]), "t.csv", 100)
    assert pf.rows_rejected == 1 and len(pf.records) == 1
    assert pf.errors[0].code == "invalid_date" and bad not in pf.errors[0].message


@pytest.mark.parametrize("val", ["05-10-2026", "05/10/2026", "05-Oct-2026", "2026-10-05"])
def test_date_formats(val):
    assert cp.to_date(val) == date(2026, 10, 5)


def test_excel_serial_and_datetime_values():
    assert cp.to_date(46300).year == 2026
    assert cp.to_datetime(datetime(2026, 10, 5, 9, 15)) == datetime(2026, 10, 5, 9, 15)
    assert cp.to_date(date(2026, 10, 5)) == date(2026, 10, 5)


def test_negative_qty_with_missing_side_infers_sell_and_abs_stored():
    pf = cp.parse_file(h.tradebook([h.tb_row(tid="A", side="", qty=-150),
                                    h.tb_row(tid="B", side="buy", qty=-75)]), "t.csv", 100)
    a, b = pf.records
    assert (a["trade_type"], a["quantity"]) == ("sell", 150)
    assert (b["trade_type"], b["quantity"]) == ("buy", 75)


def test_extreme_quantity_and_price_rejected_via_service(db_session):
    r = _imp(db_session, "t.csv", h.tradebook([h.tb_row(tid="A", qty="1e500000"),
                                               h.tb_row(tid="B", price="1e30"), h.tb_row(tid="C")]))
    assert (r.status, r.inserted, r.rejected) == ("partial", 1, 2)


def test_unparseable_execution_time_stored_null_with_warning():
    row = h.tb_row(tid="A")
    row[12] = "garbage"
    pf = cp.parse_file(h.tradebook([row]), "t.csv", 100)
    assert pf.records[0]["order_execution_time"] is None
    assert any("order_execution_time" in w for w in pf.warnings)


def test_csv_encodings_latin1_crlf_thousands():
    pf = cp.parse_file(h.tradebook([h.tb_row(tid="A", price="1,234.50")]), "t.csv", 100)
    assert pf.records[0]["price"] == Decimal("1234.50")
    bad = (b"particulars,posting_date,cost_center,voucher_type,debit,credit,net_balance\r\n"
           b"\xe9x,2026-09-01,,J,1,,\r\n")
    assert cp.parse_file(bad, "l.csv", 100).records[0]["particulars"].endswith("x")


# -- 6. symbol table --------------------------------------------------------------------

@pytest.mark.parametrize("sym,ym,exp", [
    ("NIFTY2610124000CE", "2026-01", date(2026, 1, 1)),
    ("NIFTY2692324000CE", "2026-09", date(2026, 9, 23)),
    ("NIFTY26O1424000PE", "2026-10", date(2026, 10, 14)),
    ("NIFTY26N1824000PE", "2026-11", date(2026, 11, 18)),
    ("NIFTY26D2924000PE", "2026-12", date(2026, 12, 29)),
    ("  nifty26o0724000ce ", "2026-10", date(2026, 10, 7)),
])
def test_weekly_symbols(sym, ym, exp):
    si = parse_symbol(sym)
    assert (si.underlying, si.strike, si.expiry_ym, si.opt_expiry, si.parse_status) == \
        ("NIFTY", Decimal(24000), ym, exp, "ok")


def test_weekly_not_confused_with_monthly_and_bad_day():
    m, w = parse_symbol("NIFTY26OCT24000CE"), parse_symbol("NIFTY26O0724000CE")
    assert m.opt_expiry is None and w.opt_expiry == date(2026, 10, 7)
    assert m.strike == w.strike == Decimal(24000)
    bad = parse_symbol("NIFTY2623124000CE")
    assert bad.opt_expiry is None and bad.expiry_ym == "2026-02" and bad.parse_status == "ok"


@pytest.mark.parametrize("sym", ["NIFTY 50", "NIFTYBEES", "26OCT24000CE", "NIFTY26OCT24000XX", "!!", None])
def test_unparseable_symbols_fall_back(sym):
    si = parse_symbol(sym)
    assert si.instrument_type == "UNKNOWN" and si.parse_status == "unparsed" and si.strike is None


def test_unparseable_symbol_row_is_stored_not_rejected(db_session):
    r = _imp(db_session, "t.csv", h.tradebook([h.tb_row(symbol="NIFTYBEES", tid="A")]))
    assert (r.status, r.inserted, r.rejected) == ("ok", 1, 0)
    t = db_session.scalars(select(Trade)).one()
    assert (t.instrument_type, t.parse_status) == ("UNKNOWN", "unparsed")
    assert FnoImportReadService(db_session).status("u1").trades.unparsed_count == 1


def test_symbol_alias_applies_in_import(db_session, monkeypatch):
    monkeypatch.setattr(get_settings().trade_analysis, "symbol_aliases", {"NIFTY": "NIFTY"})
    _imp(db_session, "t.csv", h.tradebook([h.tb_row(tid="A")]))
    assert db_session.scalars(select(Trade)).one().parse_status == "fallback"


# -- 7. read-time scope -----------------------------------------------------------------

def test_expiry_year_config_and_date_from_default(db_session, monkeypatch):
    _imp(db_session, "t.csv", h.tradebook([
        h.tb_row(tid="1"), h.tb_row(tid="2", symbol="NIFTY27OCT24000CE", exp="2027-10-26"),
        h.tb_row(tid="3", d="2026-06-30")]))
    rd = FnoImportReadService(db_session)
    kw = dict(underlying="ALL", include_fut=False, expiry_month=None, date_from=None, date_to=None,
              side=None, sort="trade_date_desc", page=1, page_size=50)
    assert {i.trade_id for i in rd.trades("u1", **kw).items} == {"1"}
    assert rd.trades("u1", **kw).filter.date_from == "2026-07-01"
    monkeypatch.setattr(get_settings().trade_analysis, "expiry_year", 2027)
    assert {i.trade_id for i in rd.trades("u1", **kw).items} == {"2"}


def test_date_to_and_month_outside_config(db_session):
    _imp(db_session, "t.csv", h.tradebook([h.tb_row(tid="1", d="2026-10-01"),
                                           h.tb_row(tid="2", d="2026-10-03")]))
    rd = FnoImportReadService(db_session)
    kw = dict(underlying="ALL", include_fut=False, expiry_month=None, date_from=None,
              side=None, sort="trade_date_asc", page=1, page_size=50)
    assert [i.trade_id for i in rd.trades("u1", date_to=date(2026, 10, 2), **kw).items] == ["1"]
    assert rd.trades("u1", date_to=None, **{**kw, "expiry_month": 12}).total == 0


def test_page_beyond_last_returns_empty_not_error(db_session):
    _imp(db_session, "t.csv", h.tradebook([h.tb_row(tid="1")]))
    r = FnoImportReadService(db_session).trades("u1", "ALL", False, None, None, None, None,
                                                "trade_date_desc", 5, 50)
    assert r.items == [] and r.total == 1 and r.total_pages == 1


# -- 8. API: limits, isolation, auth ----------------------------------------------------

@pytest.fixture()
def users(client):
    from rita.auth import get_current_user
    from rita.main import app

    a, b = MagicMock(), MagicMock()
    a.id, b.id = "user-a", "user-b"
    cur = {"u": a}
    app.dependency_overrides[get_current_user] = lambda: cur["u"]

    def as_(name):
        cur["u"] = a if name == "a" else b
    yield as_
    app.dependency_overrides.pop(get_current_user, None)


def _post(client, *files):
    return client.post(_UP, files=[("files", f) for f in files])


def test_api_two_user_isolation_read_and_purge(client, users):
    users("a")
    _post(client, ("t.csv", h.tradebook()), ("l.csv", h.ledger()))
    users("b")
    assert client.get(_ST).json()["has_data"] is False
    assert client.get(_TR + "?include_fut=true&date_from=2000-01-01").json()["total"] == 0
    _post(client, ("t.csv", h.tradebook([h.tb_row(tid="ONLYB")])))
    assert client.delete(_UP + "?confirm=true").json()["deleted"]["personal_fno_trades"] == 1
    users("a")
    s = client.get(_ST).json()
    assert s["trades"]["count"] == 3 and s["ledger"]["count"] == 3
    ids = {i["trade_id"] for i in
           client.get(_TR + "?include_fut=true&date_from=2000-01-01").json()["items"]}
    assert ids == {"T1", "T2", "T3"}
    assert client.delete(_UP + "?confirm=true&kind=ledger").json()["deleted"]["personal_fno_trades"] == 0
    assert client.get(_ST).json()["trades"]["count"] == 3


def test_api_purge_then_reimport_restores(client, users):
    users("a")
    _post(client, ("t.csv", h.tradebook()))
    client.delete(_UP + "?confirm=true")
    s = client.get(_ST).json()
    assert s["has_data"] is False and s["recent_runs"] == []
    assert _post(client, ("t.csv", h.tradebook())).json()["totals"]["inserted"] == 3


def test_api_all_endpoints_require_auth(client):
    assert client.get(_TR).status_code == 401
    assert client.get(_ST).status_code == 401
    assert client.delete(_UP).status_code in (401, 422)
    assert client.post(_UP).status_code in (401, 422)


def test_api_xlsx_bomb_reported_in_payload(client, users):
    users("a")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/worksheets/sheet1.xml", b"0" * 8_000_000)
    r = _post(client, ("bomb.xlsx", buf.getvalue()))
    assert r.status_code == 200
    f = r.json()["files"][0]
    assert f["status"] == "failed" and f["errors"][0]["code"] in ("xlsx_suspicious", "xlsx_too_large")


def test_api_corrupt_xlsx_and_extreme_rows_never_500(client, users):
    users("a")
    r = _post(client, ("c.xlsx", b"PK\x03\x04garbage"),
              ("t.csv", h.tradebook([h.tb_row(tid="A", qty="1e500000")])),
              ("l.csv", h.ledger([["X", "2026-09-01", "", "J", "1e99999", "", ""]])))
    assert r.status_code == 200
    assert [f["status"] for f in r.json()["files"]] == ["failed", "failed", "failed"]


def test_api_pagination_bounds(client, users):
    users("a")
    _post(client, ("t.csv", h.tradebook([h.tb_row(tid=str(i)) for i in range(5)])))
    j = client.get(_TR + "?page_size=2&page=3").json()
    assert (j["total"], j["total_pages"], len(j["items"])) == (5, 3, 1)
    assert client.get(_TR + "?page_size=200").status_code == 200
    assert client.get(_TR + "?page_size=0").status_code == 422
    assert client.get(_TR + "?sort=bogus").status_code == 422
    asc = [i["trade_id"] for i in client.get(_TR + "?sort=trade_date_asc").json()["items"]]
    assert len(asc) == 5 and len(set(asc)) == 5


def test_api_get_does_not_write(client, users, db_session):
    users("a")
    _post(client, ("t.csv", h.tradebook()))
    before = (_n(db_session, Run), _n(db_session, Trade))
    flushed = []
    from sqlalchemy import event
    event.listen(db_session, "before_flush", lambda *a: flushed.append(1))
    client.get(_ST)
    client.get(_TR)
    assert flushed == [] and (_n(db_session, Run), _n(db_session, Trade)) == before


# -- 9. static hygiene ------------------------------------------------------------------

_NEW_PY = ["models/fno_import.py", "repositories/fno_import.py", "services/console_parsers.py",
           "services/fno_symbol_parser.py", "services/fno_import_service.py",
           "api/v1/workflow/fno_console_import.py", "api/experience/fno_trade_import.py",
           "schemas/fno_console_import.py"]


def test_static_no_print_lot_literal_or_row_logging():
    for f in _NEW_PY:
        src = (_ROOT / "src/rita" / f).read_text()
        assert "print(" not in src, f
        assert not re.search(r"\b(lot|lots|lot_size)\b\s*[=:]\s*\d+", src, re.I), f
        assert not re.search(r"log\.\w+\([^)]*(row|record|particulars|symbol)=", src), f


def test_static_routers_layering():
    wf = (_ROOT / "src/rita/api/v1/workflow/fno_console_import.py").read_text()
    ex = (_ROOT / "src/rita/api/experience/fno_trade_import.py").read_text()
    for src in (wf, ex):
        assert "rita.repositories" not in src and ".commit(" not in src
    assert "user_id" not in wf.replace("current_user.id", "")


def test_static_repos_never_commit_and_take_user_id():
    src = (_ROOT / "src/rita/repositories/fno_import.py").read_text()
    assert ".commit(" not in src and "print(" not in src
    for name, args in re.findall(r"    def ([a-z_]+)\(self,([^)]*)\)", src):
        if name.startswith("_") or name == "add":
            continue
        assert "user_id" in args, name


def test_static_no_filesystem_writes_in_service_and_parsers():
    for f in ("services/fno_import_service.py", "services/console_parsers.py",
              "api/v1/workflow/fno_console_import.py"):
        src = (_ROOT / "src/rita" / f).read_text()
        assert not re.search(r"\bopen\(|write_bytes|write_text|NamedTemporaryFile|shutil|Path\(", src), f


_SAFE_EXPR = re.compile(r"^_(esc|dash|num|range)\(")
_NON_FILE = {"_TRADES", "_UPLOAD", "_files.length", "_tradesQuery()", "c", "cols", "empty", "k",
             "maxFiles"}


def test_js_every_interpolation_is_escaped_or_not_file_derived():
    js = re.sub(r"//[^\n]*", "", _JS)
    exprs = re.findall(r"\$\{((?:[^{}]|\{[^{}]*\})*)\}", js)
    assert len(exprs) > 25
    for e in exprs:
        if _SAFE_EXPR.match(e) or e in _NON_FILE:
            continue
        if e == "e.row != null ? ' @row ' + _esc(e.row) : ''":
            continue
        if "`" in e:
            inner = re.findall(r"\$\{([^{}]*)\}", e)
            assert inner and all(_SAFE_EXPR.match(i) for i in inner), e
            continue
        if e == "f.name":  # only used for the banner (textContent), never innerHTML
            assert "problems.push(`${f.name}" in js
            continue
        pytest.fail(f"unescaped interpolation: {e}")
    assert "textContent" in _JS and "eval(" not in _JS and "document.write" not in _JS


def test_js_inner_html_only_with_escaped_or_static_content():
    for m in re.finditer(r"innerHTML\s*=\s*([^;]+);", _JS):
        assert "_esc(" in m.group(1) or "'<option" in m.group(1), m.group(1)


def test_js_api_upload_helper_contract():
    api = (_ROOT / "dashboard/js/shared/api.js").read_text()
    up = api[api.index("export async function apiUpload"):api.index("export async function apiFetch")]
    assert "Content-Type" not in up and "JSON.stringify" not in up
    assert "sessionStorage.getItem('auth_token')" in up and "Bearer" in up
    assert "removeItem('auth_token')" in up and "r.status === 401" in up
    assert "body: formData" in up
    assert "apiUpload(_UPLOAD, fd)" in _JS and "'Content-Type'" not in _JS


def test_js_loader_hook_in_trade_analysis():
    ta = (_ROOT / "dashboard/js/fno/trade-analysis.js").read_text()
    assert "import { loadImportPanel } from './trade-import.js'" in ta
    body = ta[ta.index("export async function loadTradeAnalysis"):]
    assert "loadImportPanel()" in body[:400]


# -- 10. DOM contract -------------------------------------------------------------------

def test_dom_ids_unique_present_and_used():
    html_ids = re.findall(r'id="(ta-imp-[a-z-]+)"', _HTML)
    assert len(html_ids) == len(set(html_ids)), "duplicate ta-imp-* id"
    used = set(re.findall(r"""['"`](ta-imp-[a-z-]+)['"`]""", _JS)) | \
        {f"ta-imp-cov-{k}" for k in ("first", "last", "trades", "inscope", "ledger", "pnl")}
    assert used <= set(html_ids), used - set(html_ids)
    assert set(html_ids) - used <= {"ta-imp-delete-btn"}
    sec = _HTML[_HTML.index('id="page-trade-analysis"'):]
    assert all(f'id="{i}"' in sec for i in html_ids)


def test_inline_handlers_map_to_bindings():
    handlers = set(re.findall(r'on(?:click|change)="(taImp\w+)\(', _HTML))
    bound = set(re.findall(r"window\.(taImp\w+)\s*=", _MAIN))
    assert handlers <= bound and bound == {"taImpFilesChosen", "taImpUpload", "taImpSetFilter",
                                           "taImpPage", "taImpRefresh", "taImpDelete"}


# -- 11. API <-> frontend field contract ------------------------------------------------

def _names(model) -> set[str]:
    out = set(model.model_fields)
    out |= {f.alias for f in model.model_fields.values() if f.alias}
    out.discard("from_")
    return out


_PREFIX = {
    "s": [S.ImportStatusResponse], "t": [S.TradesCoverage, S.ImportedTradeRow],
    "p": [S.PnlCoverage], "l": [S.LedgerCoverage], "sc": [S.ImportScope],
    "li": [S.LastImports], "r": [S.ImportRunSummary], "x": [S.PnlPeriod],
    "d": [S.ImportedTradesResponse], "res": [S.FnoImportResponse],
    "f": [S.FileResult], "e": [S.RowErrorOut], "_limits": [S.ImportLimits],
}
_NON_SCHEMA = {"f": {"name", "size"}}


def test_every_property_js_reads_exists_in_schema():
    js = re.sub(r"//[^\n]*", "", _JS)
    for var, models in _PREFIX.items():
        allowed = set().union(*[_names(m) for m in models]) | _NON_SCHEMA.get(var, set())
        reads = set(re.findall(rf"(?<![\w.]){re.escape(var)}\.([A-Za-z_]+)\b", js))
        reads -= {"length", "map", "join", "push", "filter", "slice", "includes", "value", "checked"}
        assert reads <= allowed, (var, reads - allowed)


def test_route_output_keys_match_schema(client, users):
    users("a")
    j = _post(client, ("t.csv", h.tradebook()), ("p.xlsx", h.pnl_xlsx()),
              ("l.csv", h.ledger())).json()
    assert set(j["totals"]) == set(S.ImportTotals.model_fields)
    for f in j["files"]:
        assert set(f) == set(S.FileResult.model_fields) and set(f["period"]) == {"from", "to"}
    bad = _post(client, ("b.csv", b"a,b\n1,2\n")).json()["files"][0]
    assert set(bad["errors"][0]) == set(S.RowErrorOut.model_fields) and bad["kind"] is None
    s = client.get(_ST).json()
    assert set(s["scope"]) == set(S.ImportScope.model_fields)
    assert set(s["limits"]) == set(S.ImportLimits.model_fields)
    assert set(s["trades"]) == set(S.TradesCoverage.model_fields)
    assert set(s["pnl"]) == set(S.PnlCoverage.model_fields)
    assert all(set(x) == {"from", "to"} for x in s["pnl"]["periods"])
    assert set(s["ledger"]) == set(S.LedgerCoverage.model_fields)
    assert set(s["last_imports"]) == {"tradebook", "pnl", "ledger"}
    for run in s["recent_runs"] + list(s["last_imports"].values()):
        assert set(run) == set(S.ImportRunSummary.model_fields)
    assert s["scope"]["date_from"] == "2026-07-01" and s["scope"]["expiry_months"] == [9, 10, 11]
    t = client.get(_TR).json()
    assert set(t["filter"]) == set(S.ImportedTradesFilter.model_fields)
    assert set(t["items"][0]) == set(S.ImportedTradeRow.model_fields)
    it = t["items"][0]
    assert isinstance(it["quantity"], int) and isinstance(it["price"], float)
    assert re.match(r"\d{4}-\d{2}-\d{2}", it["trade_date"])


# -- 12. design conformance (model / migration / routes / config) -----------------------

_DESIGN = {
    "personal_fno_import_runs": {"id", "user_id", "kind", "file_name", "file_sha256", "file_size",
                                 "period_from", "period_to", "rows_parsed", "rows_inserted",
                                 "rows_updated", "rows_skipped", "rows_rejected", "status",
                                 "error_summary", "created_at"},
    "personal_fno_trades": {"id", "user_id", "import_run_id", "symbol", "isin", "trade_date",
                            "exchange", "segment", "series", "trade_type", "auction", "quantity",
                            "price", "trade_id", "order_id", "order_execution_time", "expiry_date",
                            "underlying", "instrument_type", "strike", "opt_expiry", "expiry_ym",
                            "parse_status", "created_at"},
    "personal_fno_pnl_lines": {"id", "user_id", "import_run_id", "symbol", "isin", "period_from",
                               "period_to", "quantity", "buy_value", "sell_value", "realized_pnl",
                               "realized_pnl_pct", "prev_close_price", "open_quantity",
                               "open_quantity_type", "open_value", "unrealized_pnl",
                               "unrealized_pnl_pct", "underlying", "instrument_type", "strike",
                               "opt_expiry", "expiry_ym", "created_at"},
    "personal_fno_pnl_charges": {"id", "user_id", "import_run_id", "period_from", "period_to",
                                 "section", "item", "entry_date", "amount", "created_at"},
    "personal_fno_ledger_entries": {"id", "user_id", "import_run_id", "particulars", "posting_date",
                                    "cost_center", "voucher_type", "debit", "credit", "net_balance",
                                    "content_hash", "occurrence", "created_at"},
}
_UNIQUES = {
    "personal_fno_trades": ["user_id", "trade_id", "order_id", "trade_date"],
    "personal_fno_pnl_lines": ["user_id", "symbol", "period_from", "period_to"],
    "personal_fno_pnl_charges": ["user_id", "section", "item", "period_from", "period_to",
                                 "entry_date"],
    "personal_fno_ledger_entries": ["user_id", "posting_date", "content_hash", "occurrence"],
}


def test_model_matches_design_columns_and_uniques():
    from rita.database import Base
    import rita.models  # noqa: F401

    for table, cols in _DESIGN.items():
        t = Base.metadata.tables[table]
        assert {c.name for c in t.columns} == cols, table
        assert t.c.user_id.nullable is False and not t.c.user_id.foreign_keys
        if table != "personal_fno_import_runs":
            assert [fk.target_fullname for fk in t.c.import_run_id.foreign_keys] == \
                ["personal_fno_import_runs.id"]
    for table, ucols in _UNIQUES.items():
        t = Base.metadata.tables[table]
        got = [[c.name for c in u.columns] for u in t.constraints
               if u.__class__.__name__ == "UniqueConstraint"]
        assert ucols in got, table
    assert Base.metadata.tables["personal_fno_pnl_charges"].c.entry_date.nullable is False


def test_routes_registered_with_design_paths_and_methods():
    from rita.main import app

    got = {(m, r.path) for r in app.routes for m in getattr(r, "methods", set())}
    assert ("POST", "/api/v1/workflow/fno/console-import") in got
    assert ("DELETE", "/api/v1/workflow/fno/console-import") in got
    assert ("GET", "/api/v1/experience/fno/trade-analysis/import-status") in got
    assert ("GET", "/api/v1/experience/fno/trade-analysis/imported-trades") in got


def test_config_defaults_match_design():
    c = get_settings().trade_analysis
    assert c.date_from == date(2026, 7, 1) and c.expiry_months == [9, 10, 11]
    assert c.underlyings == ["NIFTY", "BANKNIFTY"]
    assert c.import_max_file_bytes == 10 * 1024 * 1024
    assert c.import_max_total_bytes == 25 * 1024 * 1024
    assert c.import_max_files == 10 and c.import_allowed_extensions == [".csv", ".xlsx"]


def _alembic(db: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db}", "RITA_ENV": "development",
           "PYTHONPATH": str(_ROOT / "src")}
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=_ROOT, env=env,
                          capture_output=True, text=True, timeout=300)


def test_migration_schema_equals_design_single_head_and_reversible(tmp_path):
    db = tmp_path / "m.db"
    assert _alembic(db, "upgrade", "head").returncode == 0
    heads = _alembic(db, "heads")
    assert heads.stdout.count("(head)") == 1 and "20261006_f42_console_import" in heads.stdout
    con = sqlite3.connect(db)
    try:
        for table, cols in _DESIGN.items():
            info = list(con.execute(f"pragma table_info({table})"))
            assert {r[1] for r in info} == cols, table
            assert "user_id" in {r[1] for r in info if r[3]}
        found = set()
        for table in _UNIQUES:
            for _, name, uniq, *_ in con.execute(f"pragma index_list({table})"):
                if uniq:
                    found.add((table, frozenset(r[2] for r in con.execute(f"pragma index_info({name})"))))
        for table, ucols in _UNIQUES.items():
            assert (table, frozenset(ucols)) in found, table
    finally:
        con.close()
    assert _alembic(db, "downgrade", "-1").returncode == 0
    con = sqlite3.connect(db)
    left = {r[0] for r in con.execute("select name from sqlite_master where name like 'personal_fno%'")}
    con.close()
    assert left == set()
    assert _alembic(db, "upgrade", "head").returncode == 0
    assert _alembic(db, "upgrade", "head").returncode == 0


def test_every_new_table_name_has_table_prefix():
    from rita.database import Base
    import rita.models  # noqa: F401

    new = [n for n in Base.metadata.tables if "fno_import" in n or n.startswith("personal_")]
    assert new and all(n.startswith("personal_") for n in new)
