"""F42 P2 — symbol parser + Console parsers (synthetic data only)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from rita.services import console_parsers as cp
from rita.services.fno_symbol_parser import parse_symbol
from tests.unit import f42_p2_helpers as h


# ── symbol parser ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("sym,und,typ,strike,ym,exp", [
    ("NIFTY26OCT24500CE", "NIFTY", "CE", Decimal(24500), "2026-10", None),
    ("nifty26oct24500pe", "NIFTY", "PE", Decimal(24500), "2026-10", None),
    ("NIFTY2610724500CE", "NIFTY", "CE", Decimal(24500), "2026-01", date(2026, 1, 7)),
    ("NIFTY26O0724500CE", "NIFTY", "CE", Decimal(24500), "2026-10", date(2026, 10, 7)),
    ("BANKNIFTY26N1453000PE", "BANKNIFTY", "PE", Decimal(53000), "2026-11", date(2026, 11, 14)),
    ("NIFTY26D0324500CE", "NIFTY", "CE", Decimal(24500), "2026-12", date(2026, 12, 3)),
    ("NIFTY26OCTFUT", "NIFTY", "FUT", None, "2026-10", None),
    ("RELIANCE26OCT2900CE", "RELIANCE", "CE", Decimal(2900), "2026-10", None),
])
def test_symbol_patterns(sym, und, typ, strike, ym, exp):
    si = parse_symbol(sym)
    assert (si.underlying, si.instrument_type, si.strike, si.expiry_ym, si.opt_expiry) == \
        (und, typ, strike, ym, exp)
    assert si.parse_status == "ok"


def test_symbol_unparsed_never_raises():
    for s in ("???", "", "NIFTY", "12345"):
        si = parse_symbol(s)
        assert si.parse_status == "unparsed" and si.instrument_type == "UNKNOWN"
    assert parse_symbol("FOOBAR").underlying == "FOOBAR"


def test_symbol_alias_marks_fallback():
    si = parse_symbol("NIFTY26OCT24500CE", {"NIFTY": "NIFTY50"})
    assert si.underlying == "NIFTY50" and si.parse_status == "fallback"


# ── coercion / hash ────────────────────────────────────────────────────────────

def test_hash_stable_across_numeric_types():
    d = date(2026, 9, 1)
    a = cp.ledger_content_hash(d, "J", None, "x  Y", 12, 0)
    b = cp.ledger_content_hash(d, "j", None, " X y", 12.0, "0")
    c = cp.ledger_content_hash(d, "J", None, "x y", Decimal("12.00001"), "")
    assert a == b == c
    assert a != cp.ledger_content_hash(d, "J", None, "x y", 12.01, 0)


def test_to_decimal_rules():
    assert cp.to_decimal("(1,234.50)") == Decimal("-1234.50")
    assert cp.to_decimal("-") is None and cp.to_decimal("") is None
    for bad in ("nan", "inf", "abc"):
        with pytest.raises(ValueError):
            cp.to_decimal(bad)


# ── kind detection ─────────────────────────────────────────────────────────────

def test_detect_kinds():
    assert cp.detect_kind(cp.read_table(h.tradebook(), "a.csv", 1000)) == "tradebook"
    assert cp.detect_kind(cp.read_table(h.ledger(), "a.csv", 1000)) == "ledger"
    assert cp.detect_kind(cp.read_table(h.pnl_xlsx(), "a.xlsx", 1000)) == "pnl"
    assert cp.detect_kind({"csv": [["a", "b"], [1, 2]]}) is None


@pytest.mark.parametrize("offset", [1, 8, 30])
def test_pnl_header_offsets(offset):
    pf = cp.parse_file(h.pnl_xlsx(offset=offset), "p.xlsx", 10000)
    assert pf.kind == "pnl" and len(pf.records) == 2


def test_header_beyond_100_rows_not_found():
    with pytest.raises(cp.ParseFailure) as e:
        cp.parse_file(h.pnl_xlsx(offset=120), "p.xlsx", 10000)
    assert e.value.code == "unrecognised_file_kind"


def test_ambiguous_kind():
    rows = [h.TB_HEADER + h.LEDGER_HEADER]
    with pytest.raises(cp.ParseFailure) as e:
        cp.detect_kind({"csv": rows})
    assert e.value.code == "ambiguous_kind"


def test_empty_and_row_cap():
    with pytest.raises(cp.ParseFailure) as e:
        cp.read_table(b"", "a.csv", 10)
    assert e.value.code == "empty_file"
    with pytest.raises(cp.ParseFailure) as e:
        cp.read_table(h.tradebook([h.tb_row(tid=f"T{i}") for i in range(20)]), "a.csv", 10)
    assert e.value.code == "unreadable"


# ── tradebook ──────────────────────────────────────────────────────────────────

def test_tradebook_happy_derived_and_period():
    pf = cp.parse_file(h.tradebook(bom=True), "t.csv", 1000)
    assert pf.rows_parsed == 3 and len(pf.records) == 3 and not pf.errors
    r = pf.records[0]
    assert (r["underlying"], r["instrument_type"], r["expiry_ym"]) == ("NIFTY", "CE", "2026-10")
    assert r["opt_expiry"] == date(2026, 10, 27) and r["trade_type"] == "buy"
    assert (pf.period_from, pf.period_to) == (date(2026, 6, 15), date(2026, 10, 2))


def test_tradebook_row_rejections_keep_other_rows():
    rows = [
        h.tb_row(tid="A", oid="1"),
        h.tb_row(tid="B", oid="1", d="not-a-date"),
        h.tb_row(tid="C", oid="1", qty=0),
        h.tb_row(tid="D", oid="1", price="abc"),
        h.tb_row(tid="E", oid="1", side="hold"),
        h.tb_row(tid="", oid="1"),
        h.tb_row(tid="G", oid="1", price=-1),
    ]
    pf = cp.parse_file(h.tradebook(rows), "t.csv", 1000)
    assert len(pf.records) == 1 and pf.rows_rejected == 6
    assert {e.code for e in pf.errors} == {"invalid_date", "invalid_quantity", "invalid_number",
                                           "invalid_trade_type", "missing_key"}
    assert all("not-a-date" not in e.message for e in pf.errors)  # no cell values echoed


def test_tradebook_coercions():
    rows = [h.tb_row(tid="A", d="05-10-2026", qty="-1,150", price="1,234.50")]
    pf = cp.parse_file(h.tradebook(rows), "t.csv", 1000)
    r = pf.records[0]
    assert r["trade_date"] == date(2026, 10, 5) and r["quantity"] == 1150
    assert r["price"] == Decimal("1234.50")
    assert any("negative quantity" in w for w in pf.warnings)


def test_tradebook_in_file_duplicates_and_trade_id_collision():
    rows = [h.tb_row(tid="A", oid="1"), h.tb_row(tid="A", oid="1"),
            h.tb_row(tid="A", oid="1", price=999), h.tb_row(tid="A", oid="2")]
    pf = cp.parse_file(h.tradebook(rows), "t.csv", 1000)
    assert len(pf.records) == 2 and pf.duplicates_in_file == 2
    assert any("differing content" in w for w in pf.warnings)


def test_tradebook_missing_columns():
    bad = h.csv_bytes([c for c in h.TB_HEADER if c != "price"], [])
    # still detected as tradebook (has trade_id/order_id/trade_type) but price missing
    with pytest.raises(cp.ParseFailure) as e:
        cp.parse_file(bad, "t.csv", 100)
    assert e.value.code == "missing_columns"


def test_tradebook_semicolon_and_unknown_symbol():
    rows = [h.tb_row(symbol="WEIRD-THING", tid="A")]
    pf = cp.parse_file(h.csv_bytes(h.TB_HEADER, rows, delimiter=";"), "t.csv", 100)
    assert pf.records[0]["parse_status"] == "unparsed"
    assert any("unrecognised symbol" in w for w in pf.warnings)


# ── ledger ─────────────────────────────────────────────────────────────────────

def test_ledger_occurrence_and_blanks():
    pf = cp.parse_file(h.ledger(), "l.csv", 1000)
    a, b, c = pf.records
    assert (a["occurrence"], b["occurrence"]) == (0, 1) and a["content_hash"] == b["content_hash"]
    assert a["debit"] == 0 and c["credit"] == 0 and c["net_balance"] is None
    assert (pf.period_from, pf.period_to) == (date(2026, 9, 1), date(2026, 9, 2))


# ── pnl ────────────────────────────────────────────────────────────────────────

def test_pnl_parse_sections_period_and_other_dc():
    pf = cp.parse_file(h.pnl_xlsx(extra_sheet=True), "p.xlsx", 10000)
    assert (pf.period_from, pf.period_to) == (date(2026, 4, 1), date(2026, 10, 5))
    got = {(c["section"], c["item"]): c["amount"] for c in pf.charges}
    assert got[("summary", "Charges")] == Decimal("1234.5")
    assert got[("summary", "Other Credit & Debit")] == Decimal("-50.25")
    assert got[("charges", "Brokerage")] == 20
    assert got[("other_dc", "Fake DP charge")] == Decimal("-15.0")
    assert any("Ignored sheets" in w for w in pf.warnings)
    assert pf.records[1]["realized_pnl"] == Decimal("-40.5")


def test_pnl_missing_period_is_hard_error():
    with pytest.raises(cp.ParseFailure) as e:
        cp.parse_file(h.pnl_xlsx(period=None), "p.xlsx", 10000)
    assert e.value.code == "period_not_found"


def test_pnl_missing_other_sheet_only_warns():
    pf = cp.parse_file(h.pnl_xlsx(other=False), "p.xlsx", 10000)
    assert len(pf.records) == 2 and any("not found" in w for w in pf.warnings)
