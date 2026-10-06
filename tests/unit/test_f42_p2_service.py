"""F42 P2 — FnoImportService / read service on in-memory SQLite (synthetic data only)."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy import func, select

from rita.models.fno_import import (
    FnoImportRunModel as Run, FnoLedgerEntryModel as Ledger, FnoPnlChargeModel as Charge,
    FnoPnlLineModel as Line, FnoTradeModel as Trade,
)
from rita.services.fno_import_service import (
    FnoImportReadService, FnoImportService, UploadInput, sanitize_file_name,
)
from tests.unit import f42_p2_helpers as h


def _n(db, model, user=None):
    q = select(func.count()).select_from(model)
    if user:
        q = q.where(model.user_id == user)
    return db.scalar(q)


def _imp(db, name, data, user="u1"):
    return FnoImportService(db).import_files(user, [UploadInput(name, data)]).files[0]


def test_tradebook_idempotent_and_overlap(db_session):
    r1 = _imp(db_session, "tb.csv", h.tradebook())
    assert (r1.status, r1.inserted, r1.skipped_duplicates, r1.kind) == ("ok", 3, 0, "tradebook")
    r2 = _imp(db_session, "tb.csv", h.tradebook())
    assert (r2.inserted, r2.skipped_duplicates, r2.status) == (0, 3, "ok")
    overlap = h.tradebook([h.tb_row(tid="T1", oid="O1"), h.tb_row(tid="T9", oid="O9")])
    r3 = _imp(db_session, "tb2.csv", overlap)
    assert (r3.inserted, r3.skipped_duplicates) == (1, 1)
    assert _n(db_session, Trade) == 4 and _n(db_session, Run) == 3


def test_same_trade_id_different_order_id_both_kept(db_session):
    r = _imp(db_session, "t.csv", h.tradebook([h.tb_row(tid="A", oid="1"), h.tb_row(tid="A", oid="2")]))
    assert r.inserted == 2


def test_derived_fields_persisted(db_session):
    _imp(db_session, "tb.csv", h.tradebook())
    t = db_session.scalars(select(Trade).where(Trade.trade_id == "T3")).one()
    assert (t.underlying, t.instrument_type, t.expiry_ym) == ("BANKNIFTY", "FUT", "2026-11")
    assert t.price == 100.5 or isinstance(t.price, float)


def test_ledger_count_based_dedupe(db_session):
    rows = [["Fake X", "2026-09-01", "", "Journal", "10", "", ""]] * 2
    assert _imp(db_session, "l.csv", h.ledger(rows)).inserted == 2
    assert _imp(db_session, "l.csv", h.ledger(rows)).inserted == 0
    assert _imp(db_session, "l.csv", h.ledger(rows + rows[:1])).inserted == 1   # 3 vs 2
    assert _imp(db_session, "l.csv", h.ledger(rows[:1])).inserted == 0          # 1 vs 3
    assert _n(db_session, Ledger) == 3


def test_pnl_same_period_replaces_and_other_period_coexists(db_session):
    r1 = _imp(db_session, "p.xlsx", h.pnl_xlsx())
    assert r1.status == "ok" and r1.updated == 0 and r1.inserted > 0
    assert _n(db_session, Line) == 2 and _n(db_session, Charge) == 6
    restated = h.pnl_xlsx(symbols=[("NIFTY26OCT24000CE", 55.0), ("NIFTY26NOV24000CE", 1.0)])
    r2 = _imp(db_session, "p.xlsx", restated)
    assert r2.updated > 0 and any("Replaced existing" in w for w in r2.warnings)
    syms = {s for (s,) in db_session.execute(select(Line.symbol))}
    assert syms == {"NIFTY26OCT24000CE", "NIFTY26NOV24000CE"}  # stale PE gone
    _imp(db_session, "p2.xlsx", h.pnl_xlsx(period=("2026-07-01", "2026-10-05")))
    assert _n(db_session, Line) == 4
    sentinel = db_session.scalars(select(Charge).where(Charge.section == "summary")).first()
    assert sentinel.entry_date == date(1970, 1, 1)


def test_failed_files_leave_audit_row_and_do_not_affect_others(db_session):
    res = FnoImportService(db_session).import_files("u1", [
        UploadInput("bad.csv", b"a,b\n1,2\n"),
        UploadInput("good.csv", h.tradebook()),
        UploadInput("x.txt", b"hello"),
        UploadInput("big.csv", b"", too_large=True),
        UploadInput("fake.xlsx", b"not a zip"),
        UploadInput("empty.csv", b""),
    ])
    codes = [(f.status, f.errors[0].code if f.errors else None) for f in res.files]
    assert codes == [("failed", "unrecognised_file_kind"), ("ok", None),
                     ("failed", "unsupported_extension"), ("failed", "file_too_large"),
                     ("failed", "bad_file_type"), ("failed", "empty_file")]
    assert res.totals.files_failed == 5 and res.totals.inserted == 3
    assert _n(db_session, Run) == 6 and _n(db_session, Trade) == 3
    assert db_session.scalars(select(Run).where(Run.file_name == "bad.csv")).one().status == "failed"


def test_all_rows_rejected_is_failed_and_commits_nothing(db_session):
    r = _imp(db_session, "t.csv", h.tradebook([h.tb_row(tid="A", d="bad")]))
    assert r.status == "failed" and r.rejected == 1 and _n(db_session, Trade) == 0


def test_partial_status_keeps_valid_rows(db_session):
    r = _imp(db_session, "t.csv", h.tradebook([h.tb_row(tid="A"), h.tb_row(tid="B", d="bad")]))
    assert (r.status, r.inserted, r.rejected) == ("partial", 1, 1)
    # corrected re-import inserts only the missing row
    r2 = _imp(db_session, "t.csv", h.tradebook([h.tb_row(tid="A"), h.tb_row(tid="B")]))
    assert (r2.inserted, r2.skipped_duplicates, r2.status) == (1, 1, "ok")


def test_forced_failure_mid_file_rolls_back_rows_keeps_audit(db_session):
    with patch("rita.services.fno_import_service.FnoTradeRepo.insert_new",
               side_effect=RuntimeError("boom")):
        r = _imp(db_session, "t.csv", h.tradebook())
    assert r.status == "failed" and r.errors[0].code == "import_failed"
    assert _n(db_session, Trade) == 0 and _n(db_session, Run) == 1
    assert _imp(db_session, "t.csv", h.tradebook()).inserted == 3


def test_user_scoping_and_purge(db_session):
    for u in ("u1", "u2"):
        _imp(db_session, "t.csv", h.tradebook(), user=u)
        _imp(db_session, "l.csv", h.ledger(), user=u)
        _imp(db_session, "p.xlsx", h.pnl_xlsx(), user=u)
    assert _n(db_session, Trade, "u1") == _n(db_session, Trade, "u2") == 3
    svc = FnoImportService(db_session)
    c = svc.purge("u1", "tradebook").deleted
    assert c.personal_fno_trades == 3 and c.personal_fno_ledger_entries == 0
    assert _n(db_session, Ledger, "u1") == 3 and _n(db_session, Trade, "u2") == 3
    c = svc.purge("u1").deleted
    assert c.personal_fno_ledger_entries == 3 and c.personal_fno_pnl_lines == 2
    assert _n(db_session, Run, "u1") == 0 and _n(db_session, Run, "u2") == 3
    assert FnoImportReadService(db_session).status("u1").has_data is False


def test_read_status_and_scope_filters(db_session):
    rows = [
        h.tb_row(tid="1", d="2026-10-01"),                                   # in scope
        h.tb_row(tid="2", d="2026-06-15"),                                   # before date_from
        h.tb_row(tid="3", symbol="NIFTY26AUG24000CE", d="2026-10-01", exp="2026-08-25"),  # Aug (in scope since expiry_months widened to Apr-Nov, F42 P4)
        h.tb_row(tid="4", symbol="NIFTY27OCT24000CE", d="2026-10-01", exp="2027-10-26"),  # 2027
        h.tb_row(tid="5", symbol="RELIANCE26OCT2900CE", d="2026-10-01"),     # other underlying
        h.tb_row(tid="6", symbol="BANKNIFTY26OCTFUT", d="2026-10-01"),       # fut
        h.tb_row(tid="7", symbol="BANKNIFTY26NOV50000PE", d="2026-10-02", side="sell", exp=""),
    ]
    _imp(db_session, "t.csv", h.tradebook(rows))
    rd = FnoImportReadService(db_session)
    st = rd.status("u1")
    assert st.has_data and st.trades.count == 7 and st.trades.in_scope_count == 3
    assert st.trades.fut_count == 1 and st.limits.max_files == 10
    assert st.last_imports.tradebook.rows_inserted == 7 and st.last_imports.pnl is None

    def q(**kw):
        a = dict(underlying="ALL", include_fut=False, expiry_month=None, date_from=None,
                 date_to=None, side=None, sort="trade_date_desc", page=1, page_size=50)
        a.update(kw)
        return rd.trades("u1", **a)

    assert {i.trade_id for i in q().items} == {"1", "3", "7"}   # symbol-only month fallback for 7
    assert {i.trade_id for i in q(include_fut=True).items} == {"1", "3", "6", "7"}
    assert {i.trade_id for i in q(underlying="BANKNIFTY").items} == {"7"}
    assert {i.trade_id for i in q(expiry_month=11).items} == {"7"}
    assert {i.trade_id for i in q(expiry_month=8).items} == {"3"} and q(expiry_month=8).filter.expiry_months == [8]
    assert {i.trade_id for i in q(date_from=date(2026, 6, 1)).items} == {"1", "2", "3", "7"}
    assert {i.trade_id for i in q(side="sell").items} == {"7"}
    asc = q(sort="trade_date_asc", date_from=date(2026, 6, 1)).items
    assert {i.trade_id for i in asc} == {"1", "2", "3", "7"} and asc[0].trade_id == "2" and asc[-1].trade_id == "7"
    dates = [i.trade_date for i in asc]
    assert dates == sorted(dates)                  # 1 and 3 tie on 2026-10-01, so only the date order is pinned
    assert q(expiry_month=3).total == 0 and q(expiry_month=3).filter.expiry_months == [3]   # out-of-config month probe
    p = q(date_from=date(2026, 6, 1), page_size=2, page=2)
    assert p.total == 4 and p.total_pages == 2 and len(p.items) == 2


def test_sanitize_file_name():
    assert sanitize_file_name("../../etc/x.csv") == "x.csv"
    assert sanitize_file_name("C:\\a\\b<c>.csv") == "b_c_.csv"
    assert sanitize_file_name("") == "file" and len(sanitize_file_name("a" * 500)) == 200
