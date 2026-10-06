"""F42 P5 - independent QA probes for "Load sample data" (synthetic data only, never live-data/).

Complements (does not repeat) the Engineer's three P5 test files:
  A. headline numbers recomputed straight from the committed CSVs with a from-scratch FIFO (no
     rita analytics code), cross-checked against design section 6.8 bands and against the cash
     ledger / P&L sheet / analytics services;
  B. CSV well-formedness probed with plain `csv` (ids, expiry/strike sanity, trading days, LF...);
  C. generator determinism under different hash seeds / cwd and a runtime file-access spy;
  D. endpoint matrix over HTTP with failure injection, scoping, concurrency and file-missing variants;
  E. JS contract: static checks plus a node harness with an <img onerror> payload;
  F. personal-data scan.
"""
from __future__ import annotations

import ast
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import threading
from collections import defaultdict
from datetime import date, datetime
from functools import lru_cache
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
from rita.repositories.fno_import import FnoTradeRepo
from rita.repositories.fno_sample_files import FnoSampleFileRepo
from rita.services.console_parsers import parse_file
from rita.services.fno_import_service import FnoImportService
from rita.services.fno_sample_service import FnoSampleService
from tests.unit import f42_p2_helpers as p2
from tests.unit import f42_p5_helpers as h

CFG = get_settings().trade_analysis
LOTS = {"NIFTY": get_settings().instruments.nifty.lot_size,
        "BANKNIFTY": get_settings().instruments.banknifty.lot_size}
GEN = h.REPO / "scripts" / "generate_fno_sample.py"
UP = "/api/v1/workflow/fno/console-import"
SAMPLE = UP + "/sample"
ST = "/api/v1/experience/fno/trade-analysis/import-status"
AN = "/api/v1/experience/fno/trade-analysis/analytics/"
PANELS = ["foundation", "overtrading", "buildup", "market-turn", "margin-trap", "suggestions", "spot-vs-pnl"]
AS_OF = h.TODAY
W_FROM, W_TO = h.WINDOW

_WEEKLY = re.compile(r"^(BANKNIFTY|NIFTY)(\d{2})([1-9OND])(\d{2})(\d+)(CE|PE)$")
_MONTHLY = re.compile(r"^(BANKNIFTY|NIFTY)(\d{2})([A-Z]{3})(\d+)(CE|PE)$")
_MCODE = {**{str(i): i for i in range(1, 10)}, "O": 10, "N": 11, "D": 12}
_MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


# ═══ independent readers / FIFO (no rita analytics code) ═══════════════════════

def _read(name: str) -> list[dict]:
    with (h.SAMPLE_DIR / h.NAMES[name]).open(newline="") as f:
        return list(csv.DictReader(f))


@lru_cache(maxsize=1)
def _tb() -> tuple:
    return tuple(_read("tradebook"))


@lru_cache(maxsize=1)
def _closes() -> dict:
    with h.FIXTURE.open(newline="") as f:
        rows = list(csv.DictReader(f))
    return {"dates": [r["date"] for r in rows],
            "NIFTY": {r["date"]: float(r["nifty_close"]) for r in rows},
            "BANKNIFTY": {r["date"]: float(r["banknifty_close"]) for r in rows}}


def _und(sym: str) -> str:
    return "BANKNIFTY" if sym.startswith("BANKNIFTY") else "NIFTY"


def _parse_sym(sym: str):
    """-> (underlying, expiry_year, expiry_month, expiry_day|None, strike, cp) or None."""
    m = _WEEKLY.match(sym)
    if m:
        return m[1], 2000 + int(m[2]), _MCODE[m[3]], int(m[4]), int(m[5]), m[6]
    m = _MONTHLY.match(sym)
    if m and m[3] in _MON:
        return m[1], 2000 + int(m[2]), _MON.index(m[3]) + 1, None, int(m[4]), m[5]
    return None


@lru_cache(maxsize=1)
def _fifo() -> dict:
    """From-scratch FIFO, grouping closed trades by (symbol, closing order, close date)."""
    rows = sorted(_tb(), key=lambda r: (r["trade_date"], r["order_execution_time"], r["order_id"],
                                        r["trade_id"], r["symbol"]))
    books: dict[str, list[list]] = defaultdict(list)
    side: dict[str, int] = {}
    per_trade: dict[tuple, float] = defaultdict(float)
    per_trade_time: dict[tuple, str] = {}
    sym_real: dict[str, float] = defaultdict(float)
    for r in rows:
        s, sg, q, px = r["symbol"], 1 if r["trade_type"] == "buy" else -1, int(r["quantity"]), float(r["price"])
        lots = books[s]
        sd = side.get(s, 0) if lots else 0
        rem = q
        if lots and sd != sg:
            while rem > 0 and lots:
                take = min(rem, lots[0][0])
                pnl = take * (px - lots[0][1]) * sd
                k = (s, r["order_id"], r["trade_date"])
                per_trade[k] += pnl
                per_trade_time[k] = r["order_execution_time"]
                sym_real[s] += pnl
                rem -= take
                lots[0][0] -= take
                if lots[0][0] == 0:
                    lots.pop(0)
        if rem > 0:
            lots.append([rem, px, r["expiry_date"], r["symbol"]])
            side[s] = sg
    residual = {s: {"side": side[s], "lots": [tuple(x) for x in lots]} for s, lots in books.items() if lots}
    return {"trades": per_trade, "times": per_trade_time, "sym_real": dict(sym_real), "residual": residual}


def _intrinsic(sym: str, spot: float) -> float:
    _, _, _, _, strike, cp = _parse_sym(sym)
    return max(spot - strike, 0.0) if cp == "CE" else max(strike - spot, 0.0)


@lru_cache(maxsize=1)
def _expiry_book() -> dict:
    """Residual lots split into expiry-held (expiry < as-of) and still-open (expiry > as-of)."""
    held, still_open, est_by_sym = {}, {}, {}
    cl = _closes()
    for s, d in _fifo()["residual"].items():
        exp = date.fromisoformat(d["lots"][0][2])
        if exp < AS_OF:
            spot = cl[_und(s)][exp.isoformat()]
            est = sum(lt[0] * (_intrinsic(s, spot) - lt[1]) * d["side"] for lt in d["lots"])
            held[s] = {"side": d["side"], "intrinsic": _intrinsic(s, spot), "est": est,
                       "settle": d["side"] * sum(lt[0] for lt in d["lots"]) * _intrinsic(s, spot),
                       "expiry": exp}
            est_by_sym[s] = est
        else:
            still_open[s] = d
    return {"held": held, "open": still_open, "est": est_by_sym}


def _pnl_sheet() -> dict:
    with (h.SAMPLE_DIR / h.NAMES["pnl"]).open(newline="") as f:
        rows = list(csv.reader(f))
    hdr = next(i for i, r in enumerate(rows) if r and r[0] == "Symbol")
    summary = {r[1]: float(r[2]) for r in rows[:hdr] if len(r) >= 3 and r[1] and r[2]}
    body = [r for r in rows[hdr + 1:] if r and r[0]]
    return {"summary": summary, "rows": body, "hdr": rows[hdr], "all": rows[:hdr]}


@lru_cache(maxsize=1)
def _ledger() -> dict:
    rows = _read("ledger")
    bal, closing, daily, seq = 0.0, {}, defaultdict(float), []
    for r in rows:
        net = float(r["credit"] or 0) - float(r["debit"] or 0)
        bal += net
        assert abs(bal - float(r["net_balance"])) < 0.011, r
        closing[r["posting_date"]] = bal
        daily[r["posting_date"]] += net
        seq.append(bal)
    return {"rows": rows, "closing": closing, "daily": dict(daily), "final": bal, "seq": seq}


# ═══ A. independent recomputation of the headline numbers ══════════════════════

def test_qa_closed_trade_stats_match_design_targets():
    tr = list(_fifo()["trades"].values())
    wins, losses = [x for x in tr if x > 0], [x for x in tr if x < 0]
    assert 78 <= len(tr) <= 82
    assert 34 <= len(wins) <= 38 and 42.0 <= 100.0 * len(wins) / len(tr) <= 48.0
    assert 2850 <= sum(wins) / len(wins) <= 3150
    assert 3100 <= -sum(losses) / len(losses) <= 3420
    assert len(wins) + len(losses) == len(tr)                    # no break-evens


def test_qa_measured_realised_gross_in_band_and_equals_sum_of_symbols():
    tr = list(_fifo()["trades"].values())
    measured = sum(tr)
    assert -40000 <= measured <= -31000
    assert abs(measured - sum(_fifo()["sym_real"].values())) < 1.0


def test_qa_charges_net_and_profit_factor():
    sheet = _pnl_sheet()
    charges = sheet["summary"]["Charges"]
    breakdown = sum(float(r[2]) for r in sheet["all"]
                    if len(r) >= 3 and r[1] in ("Brokerage", "Exchange Transaction Charges", "Clearing Charges",
                                                "GST", "STT/CTT", "SEBI Turnover Fees", "Stamp Duty"))
    assert 9000 <= charges <= 10000
    assert abs(charges - breakdown) <= 0.05, "summary Charges must equal the sum of the breakdown lines"
    tr = list(_fifo()["trades"].values())
    net = sum(tr) - charges
    assert -50000 <= net <= -40000
    wins, losses = sum(x for x in tr if x > 0), -sum(x for x in tr if x < 0)
    assert 0.70 <= wins / losses <= 0.80                          # design 0.75


def test_qa_expiry_held_symbols_and_estimate():
    book = _expiry_book()
    assert len(book["held"]) == 3
    short_worthless = [s for s, v in book["held"].items() if v["side"] == -1 and v["intrinsic"] == 0]
    short_itm = [s for s, v in book["held"].items() if v["side"] == -1 and v["intrinsic"] > 0]
    assert len(short_worthless) == 2 and len(short_itm) == 1
    assert all(book["held"][s]["est"] > 0 for s in short_worthless)
    assert book["held"][short_itm[0]]["est"] < 0
    assert -1000 <= sum(book["est"].values()) <= 4000
    assert len(book["open"]) == 2                                 # two positions open at the window end


def test_qa_sheet_reconciles_per_symbol_with_independent_fifo():
    sheet, real, book = _pnl_sheet(), _fifo()["sym_real"], _expiry_book()
    hdr = sheet["hdr"]
    assert hdr[:6] == ["Symbol", "ISIN", "Quantity", "Buy Value", "Sell Value", "Realized P&L"]
    seen = set()
    for r in sheet["rows"]:
        s = r[0]
        seen.add(s)
        expect = real.get(s, 0.0) + book["est"].get(s, 0.0)
        assert abs(float(r[5]) - expect) <= 1.0, f"{s}: sheet {r[5]} vs independent {expect}"
        if s not in book["held"]:
            assert abs(float(r[5]) - real.get(s, 0.0)) <= 1.0     # closed symbols: gap 0 without estimate
    assert seen == {r["symbol"] for r in _tb()}, "sheet and tradebook must cover the same symbols"
    assert abs(sum(float(r[5]) for r in sheet["rows"]) - sheet["summary"]["Realized P&L"]) <= 1.0
    assert abs(sheet["summary"]["Realized P&L"] - (sum(real.values()) + sum(book["est"].values()))) <= 1.0


def test_qa_sheet_buy_sell_values_and_open_positions_match_tradebook():
    buy, sell = defaultdict(float), defaultdict(float)
    for r in _tb():
        v = int(r["quantity"]) * float(r["price"])
        (buy if r["trade_type"] == "buy" else sell)[r["symbol"]] += v
    sheet = _pnl_sheet()
    open_syms = _expiry_book()["open"]
    unreal = 0.0
    for r in sheet["rows"]:
        s = r[0]
        assert abs(float(r[3]) - buy[s]) <= 0.01 and abs(float(r[4]) - sell[s]) <= 0.01, s
        oq = int(r[8])
        if s in open_syms:
            lots = open_syms[s]["lots"]
            assert oq == sum(lt[0] for lt in lots), s
            assert r[9] == ("Long" if open_syms[s]["side"] == 1 else "Short")
            assert abs(float(r[10]) - sum(lt[0] * lt[1] for lt in lots)) <= 0.01
            unreal += float(r[11])
        else:
            assert oq == 0 and float(r[11]) == 0.0, s
    assert abs(unreal - sheet["summary"]["Unrealized P&L"]) <= 0.05


def test_qa_ledger_cash_path_matches_design_story():
    lg = _ledger()
    thr = CFG.low_cash_threshold_inr
    closing = lg["closing"]
    assert min(lg["seq"]) > 0 and min(closing.values()) > 0       # never negative, intra-day or at close
    assert 8000 <= min(closing.values()) <= 20000
    assert 8 <= sum(1 for v in closing.values() if v < thr) <= 14
    # consecutive trading days (fixture calendar) with a net outflow
    days = [d for d in _closes()["dates"] if W_FROM.isoformat() <= d <= W_TO.isoformat()]
    run = best = 0
    for d in days:
        run = run + 1 if lg["daily"].get(d, 0.0) < 0 else 0
        best = max(best, run)
    assert best >= 5
    # funding events: opening + two 100k top-ups on window trading days #8 and #30
    receipts = [(days.index(r["posting_date"]) + 1, float(r["credit"])) for r in lg["rows"]
                if r["voucher_type"] == "Bank Receipts"]
    assert receipts == [(1, 200000.0), (8, 100000.0), (30, 100000.0)]


def test_qa_ledger_reconciles_with_tradebook_charges_and_expiry_settlement():
    """sum(book vouchers) == premium flows - sheet charges - expiry settlement; other credit/debit
    in the sheet == journal entries; final balance == opening + credits - debits."""
    lg, sheet, book = _ledger(), _pnl_sheet(), _expiry_book()
    premium = sum((1 if r["trade_type"] == "sell" else -1) * int(r["quantity"]) * float(r["price"]) for r in _tb())
    settle = sum(v["settle"] for v in book["held"].values())      # negative for short ITM
    book_net = sum(float(r["credit"] or 0) - float(r["debit"] or 0)
                   for r in lg["rows"] if r["voucher_type"] == "Book Voucher")
    assert abs(book_net - (premium - sheet["summary"]["Charges"] + settle)) <= 1.0
    journals = sum(float(r["credit"] or 0) - float(r["debit"] or 0)
                   for r in lg["rows"] if r["voucher_type"] == "Journal Entry")
    assert abs(journals - sheet["summary"]["Other Credit & Debit"]) <= 0.01
    credits = sum(float(r["credit"] or 0) for r in lg["rows"])
    debits = sum(float(r["debit"] or 0) for r in lg["rows"])
    assert abs(lg["final"] - (credits - debits)) <= 0.01


def test_qa_market_facts_recomputed_from_pinned_closes_equal_14_and_6():
    thr = CFG.turn_threshold_pct
    cl = _closes()
    big = turn = 0
    for u in ("NIFTY", "BANKNIFTY"):
        ds = cl["dates"]
        prev_ret = None
        for i in range(1, len(ds)):
            ret = (cl[u][ds[i]] / cl[u][ds[i - 1]] - 1) * 100
            if W_FROM.isoformat() <= ds[i] <= W_TO.isoformat() and abs(ret) >= thr:
                big += 1
                if prev_ret is not None and prev_ret * ret < 0:
                    turn += 1
            prev_ret = ret
    assert (big, turn) == (14, 6)


def test_qa_trading_days_and_expiries_are_consistent_with_closes_fixture():
    days = {d for d in _closes()["dates"] if W_FROM.isoformat() <= d <= W_TO.isoformat()}
    assert len(days) == 57
    assert {r["trade_date"] for r in _tb()} <= days
    # expiry-held symbols expire on days that have a spot close (needed for the estimate)
    for s, v in _expiry_book()["held"].items():
        assert v["expiry"].isoformat() in _closes()[_und(s)], s


def test_qa_independent_numbers_agree_with_real_analytics_services():
    """Cross-check: the product's panels show the same numbers my from-scratch computation does."""
    from sqlalchemy.pool import StaticPool

    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    try:
        h.seed_spot(db)
        assert h.load_files(db, "qa").totals.files_failed == 0
        p = h.panels(db, "qa", include_est=False)
        wl = p["overtrading"].model_dump()["winloss"]
        tr = list(_fifo()["trades"].values())
        assert wl["n"] == len(tr) and wl["wins"] == sum(1 for x in tr if x > 0)
        assert abs(wl["pnl"] - sum(tr)) <= 1.0
        mt = p["market-turn"].model_dump()["kpis"]
        assert (mt["n_big_move_days"], mt["n_turn_days"]) == (14, 6)
        mg = p["margin-trap"].model_dump()["cash"]
        assert abs(mg["min"] - min(_ledger()["closing"].values())) <= 0.01
        assert mg["days_negative"] == 0
        est = p["foundation"].model_dump()["fifo_totals"]["estimated_pnl"]
        assert abs(est - sum(_expiry_book()["est"].values())) <= 1.0
        recon = p["foundation"].model_dump()["reconciliation"]["rows"]
        assert sum(1 for r in recon if not r["within_tolerance"]) == 3
        assert all(r["within_tolerance_with_estimate"] for r in recon)
    finally:
        db.close()
        eng.dispose()


# ═══ B. CSV well-formedness ════════════════════════════════════════════════════

def test_qa_files_are_lf_utf8_no_bom_with_final_newline():
    for n in h.NAMES.values():
        raw = (h.SAMPLE_DIR / n).read_bytes()
        assert b"\r" not in raw, f"{n} must use LF line endings"
        assert not raw.startswith(b"\xef\xbb\xbf")
        assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
        raw.decode("ascii")
        assert b"\t" not in raw
    assert sum((h.SAMPLE_DIR / n).stat().st_size for n in h.NAMES.values()) < 200 * 1024


def test_qa_every_file_is_accepted_by_real_parser_with_zero_rejects_even_with_crlf():
    cfg = CFG
    expect = {"tradebook": "tradebook", "ledger": "ledger", "pnl": "pnl"}
    for kind, name in h.NAMES.items():
        raw = (h.SAMPLE_DIR / name).read_bytes()
        for variant in (raw, raw.replace(b"\n", b"\r\n")):
            pf = parse_file(variant, name, cfg.import_max_rows, cfg.symbol_aliases)
            assert pf.kind == expect[kind] and pf.rows_rejected == 0 and not pf.errors, (name, pf.errors[:2])
    tb = parse_file((h.SAMPLE_DIR / h.NAMES["tradebook"]).read_bytes(), "x.csv", cfg.import_max_rows, cfg.symbol_aliases)
    assert tb.rows_parsed == len(_tb()) == len(tb.records) and tb.duplicates_in_file == 0


def test_qa_tradebook_ids_unique_and_orders_are_consistent():
    rows = _tb()
    tids = [r["trade_id"] for r in rows]
    assert len(set(tids)) == len(tids)
    assert all(re.fullmatch(r"SMP\d{8}", t) for t in tids)
    assert all(re.fullmatch(r"SMP\d{12}", r["order_id"]) for r in rows)
    assert len({(r["trade_id"], r["order_id"], r["trade_date"]) for r in rows}) == len(rows)
    by_order = defaultdict(set)
    for r in rows:
        by_order[r["order_id"]].add((r["symbol"], r["trade_type"], r["trade_date"]))
    assert all(len(v) == 1 for v in by_order.values()), "an order must be one symbol, one side, one day"


def test_qa_tradebook_symbols_expiry_strikes_lots_and_times_are_sane():
    cl = _closes()
    days = set(cl["dates"])
    for r in _tb():
        p = _parse_sym(r["symbol"])
        assert p, r["symbol"]
        und, ey, em, ed, strike, cp = p
        exp = date.fromisoformat(r["expiry_date"])
        td = date.fromisoformat(r["trade_date"])
        assert (exp.year, exp.month) == (ey, em) and (ed is None or exp.day == ed), r["symbol"]
        assert exp.weekday() < 5 and em in CFG.expiry_months and ey == CFG.expiry_year
        assert W_FROM <= td <= W_TO and r["trade_date"] in days and td.weekday() < 5
        assert strike % (50 if und == "NIFTY" else 100) == 0
        spot = cl[und][r["trade_date"]]
        assert abs(strike / spot - 1) <= 0.15, "strike must be near the day's close"
        q = int(r["quantity"])
        assert q > 0 and q % LOTS[und] == 0
        px = float(r["price"])
        assert px > 0 and round(px * 20) == round(px * 20, 6) and px < 0.1 * spot
        assert px >= _intrinsic(r["symbol"], spot) - 0.01 * spot, "premium below intrinsic"
        assert (r["exchange"], r["segment"], r["series"], r["auction"]) == ("NFO", "FO", "OPT", "false")
        assert r["isin"] == "" and r["trade_type"] in ("buy", "sell")
        t = datetime.fromisoformat(r["order_execution_time"])
        assert t.date() == td and (9, 15) <= (t.hour, t.minute) <= (15, 30)   # NSE session


def test_qa_no_fill_is_dated_after_its_contract_expiry():
    late = [(r["symbol"], r["trade_date"], r["expiry_date"]) for r in _tb() if r["trade_date"] > r["expiry_date"]]
    assert not late, late


def test_qa_execution_times_inside_design_window_0920_1525():
    for r in _tb():
        t = datetime.fromisoformat(r["order_execution_time"])
        assert (9, 20) <= (t.hour, t.minute) <= (15, 25), r["order_execution_time"]


def test_qa_ledger_rows_are_tagged_dated_inside_window_and_unique():
    rows = _read("ledger")
    assert list(rows[0]) == ["particulars", "posting_date", "cost_center", "voucher_type", "debit", "credit", "net_balance"]
    assert all(r["particulars"].startswith("SAMPLE ") for r in rows)
    assert all(W_FROM.isoformat() <= r["posting_date"] <= W_TO.isoformat() for r in rows)
    assert all(bool(r["debit"]) != bool(r["credit"]) for r in rows), "exactly one of debit/credit per row"
    keys = [(r["posting_date"], r["particulars"], r["voucher_type"], r["debit"], r["credit"]) for r in rows]
    assert len(set(keys)) == len(keys)
    assert [r["posting_date"] for r in rows] == sorted(r["posting_date"] for r in rows)


def test_qa_pnl_sheet_header_period_and_labels():
    sheet = _pnl_sheet()
    first = [r for r in csv.reader((h.SAMPLE_DIR / h.NAMES["pnl"]).open(newline=""))]
    assert any(re.search(r"from 2026-07-01 to 2026-09-18", " ".join(r)) for r in first[:6])
    assert {"Charges", "Other Credit & Debit", "Realized P&L", "Unrealized P&L"} <= set(sheet["summary"])
    assert sheet["rows"] and all(r[0].upper().startswith(("NIFTY", "BANKNIFTY")) for r in sheet["rows"])
    assert len({r[0] for r in sheet["rows"]}) == len(sheet["rows"])
    assert "thousands" not in str(sheet["summary"])
    assert not any("," in c for r in sheet["rows"] for c in r), "plain numbers, no thousands separators"


# ═══ C. generator determinism / isolation ══════════════════════════════════════

def _gen(out, hashseed: str = "0", cwd=None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH",)}
    env["PYTHONHASHSEED"] = hashseed
    return subprocess.run(
        [sys.executable, str(GEN), "--nifty-lot", str(LOTS["NIFTY"]), "--banknifty-lot", str(LOTS["BANKNIFTY"]),
         "--out", str(out)], cwd=cwd, env=env, capture_output=True, text=True, timeout=120, check=True)


def test_qa_generator_twice_with_different_hash_seeds_and_cwd_is_byte_identical(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _gen(a, "1")
    _gen(b, "98765", cwd=elsewhere)
    for n in h.NAMES.values():
        assert (a / n).read_bytes() == (b / n).read_bytes(), f"{n} is not deterministic"
        assert (a / n).read_bytes() == (h.SAMPLE_DIR / n).read_bytes(), f"{n} drifted from the committed file"


def test_qa_generator_reads_only_the_closes_fixture(tmp_path):
    spy = tmp_path / "spy.py"
    log = tmp_path / "log.json"
    spy.write_text(textwrap.dedent(f"""
        import builtins, io, json, os, runpy, sys
        seen = []
        _real = builtins.open
        def _spy(f, mode="r", *a, **k):
            seen.append(["open", os.fspath(f) if not isinstance(f, int) else str(f), mode])
            return _real(f, mode, *a, **k)
        builtins.open = _spy
        io.open = _spy
        _ls, _sd = os.listdir, os.scandir
        os.listdir = lambda p=".": (seen.append(["listdir", os.fspath(p), "r"]), _ls(p))[1]
        os.scandir = lambda p=".": (seen.append(["scandir", os.fspath(p), "r"]), _sd(p))[1]
        sys.argv = [{str(GEN)!r}, "--nifty-lot", "{LOTS['NIFTY']}", "--banknifty-lot", "{LOTS['BANKNIFTY']}",
                    "--out", {str(tmp_path / 'out')!r}]
        try:
            runpy.run_path({str(GEN)!r}, run_name="__main__")
        except SystemExit:
            pass
        json.dump(seen, _real({str(log)!r}, "w"))
    """))
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    subprocess.run([sys.executable, str(spy)], cwd=tmp_path, env=env, check=True, capture_output=True, timeout=120)
    seen = json.loads(log.read_text())
    noise = (sys.prefix, sys.base_prefix, str(tmp_path / "spy.py"), str(GEN))
    ours = [(k, p, m) for k, p, m in seen
            if not any(p.startswith(n) for n in noise) and not p.endswith((".pyc", ".so", ".dylib"))
            and "site-packages" not in p and "/lib/python" not in p]
    reads = {os.path.realpath(p) for k, p, m in ours if not any(c in m for c in "wax+")}
    writes = {os.path.realpath(p) for k, p, m in ours if any(c in m for c in "wax+")}
    assert reads <= {os.path.realpath(h.FIXTURE)}, f"generator read something besides the fixture: {reads}"
    assert os.path.realpath(h.FIXTURE) in reads
    out = os.path.realpath(tmp_path / "out")
    assert all(w.startswith(out) for w in writes), f"generator wrote outside --out: {writes}"
    assert not any("live-data" in p for _, p, _ in seen)


def test_qa_generator_imports_stdlib_only_and_has_no_network_or_db_calls():
    src = GEN.read_text()
    tree = ast.parse(src)
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            mods.add(n.module.split(".")[0])
    assert mods <= set(sys.stdlib_module_names) | {"__future__"}, mods
    assert not ({"socket", "urllib", "http", "requests", "sqlite3", "subprocess", "rita"} & mods)
    literals = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert not [s for s in literals if "live-data" in s or "/Users/" in s or "rita_output" in s]
    assert "print(" not in re.sub(r'"""[\s\S]*?"""', "", src), "org.md 2: no print() in scripts under src-like rules"


def test_qa_closes_fixture_is_public_numeric_only_and_covers_window():
    with h.FIXTURE.open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0]) == ["date", "nifty_close", "banknifty_close"]
    ds = [r["date"] for r in rows]
    assert ds == sorted(set(ds)) and ds[0] <= "2026-06-30" and ds[-1] >= W_TO.isoformat()
    assert all(date.fromisoformat(d).weekday() < 5 for d in ds)
    assert all(15000 < float(r["nifty_close"]) < 40000 and 30000 < float(r["banknifty_close"]) < 90000 for r in rows)


# ═══ F. personal-data scan ═════════════════════════════════════════════════════

_PII = {
    "pan": re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"),
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "phone": re.compile(r"(?<![\d.])(?:\+?91[- ]?)?[6-9]\d{9}(?![\d.])"),
    "isin": re.compile(r"\bIN[EF][0-9A-Z]{9}\b"),
    "aadhaar": re.compile(r"\b\d{4}\s\d{4}\s\d{4}\b"),
    "zerodha_client_id": re.compile(r"\b[A-Z]{2}\d{4}\b|\b[A-Z]{3}\d{3}\b"),
    "uuid": re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"),
    "ifsc_or_account": re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b|\b\d{11,18}\b"),
}


def _pii_hits(text: str) -> dict:
    text = re.sub(r"SMP\d+", "SMP", text)                         # synthetic ids are digit runs by design
    text = re.sub(r"\b(?:BANK)?NIFTY[0-9A-Z]*\b", "SYM", text)    # contract symbols like NIFTY2672824500CE
    return {k: m for k, rx in _PII.items() if (m := rx.findall(text))}


@pytest.mark.parametrize("path", [h.SAMPLE_DIR / n for n in h.NAMES.values()] + [h.FIXTURE, GEN],
                         ids=lambda p: p.name)
def test_qa_no_personal_identifiers_in_committed_sample_assets(path):
    assert _pii_hits(path.read_text()) == {}


def test_qa_pnl_title_block_is_explicitly_synthetic():
    head = (h.SAMPLE_DIR / h.NAMES["pnl"]).read_text().splitlines()[:3]
    assert any("SAMPLE" in x.upper() or "synthetic" in x.lower() for x in head)
    assert not any(re.search(r"client id\s*,\s*[A-Z]{2}\d", x, re.I) for x in head)


# ═══ D. endpoint matrix ════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _input_dir(monkeypatch):
    monkeypatch.setattr(get_settings().data, "input_dir", str(h.REPO / "data" / "input"))


@pytest.fixture()
def who(client):
    """Switch the authenticated user between calls: who('A'); client.post(...)."""
    from rita.auth import get_current_user
    from rita.main import app

    cur = {"id": "qa-a"}

    def dep():
        u = MagicMock()
        u.id = cur["id"]
        return u

    app.dependency_overrides[get_current_user] = dep
    yield lambda uid: cur.__setitem__("id", uid)
    app.dependency_overrides.pop(get_current_user, None)


def _count(db, model, uid) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(model).where(model.user_id == uid))


def _rows_all(db, uid) -> dict:
    return {"trades": _count(db, Trade, uid), "ledger": _count(db, Ledger, uid),
            "pnl": _count(db, Line, uid), "runs": _count(db, Run, uid)}


def _run_names(db, uid) -> list[str]:
    db.expire_all()
    return sorted(db.scalars(select(Run.file_name).where(Run.user_id == uid)))


def _junk_upload(client):
    return client.post(UP, files=[("files", ("junk.csv", b"a,b\n1,2\n", "text/csv"))])


def test_qa_http_load_then_second_call_writes_nothing_and_status_flags(client, who, db_session):
    who("qa-a")
    r = client.post(SAMPLE).json()
    assert r["status"] == "loaded" and r["totals"]["inserted"] == 352 + 63 + 90
    before = _rows_all(db_session, "qa-a")
    again = client.post(SAMPLE).json()
    assert again["status"] == "already_loaded" and again["totals"]["inserted"] == 0
    assert _rows_all(db_session, "qa-a") == before == {"trades": 352, "ledger": 63, "pnl": 79, "runs": 3}
    s = client.get(ST).json()
    assert s["sample"]["loaded"] and not s["sample"]["offer"] and not s["sample"]["can_load"]


def test_qa_http_user_with_own_data_refused_for_each_single_kind(client, who, db_session):
    who("qa-a")
    uploads = {"tradebook": ("tb.csv", p2.tradebook()), "ledger": ("lg.csv", p2.ledger())}
    for kind, (name, data) in uploads.items():
        who(f"own-{kind}")
        assert client.post(UP, files=[("files", (name, data, "text/csv"))]).json()["files"][0]["status"] == "ok"
        before = _rows_all(db_session, f"own-{kind}")
        r = client.post(SAMPLE).json()
        assert (r["status"], r["reason"]) == ("refused", "has_own_data"), kind
        assert _rows_all(db_session, f"own-{kind}") == before
        s = client.get(ST).json()["sample"]
        assert not s["loaded"] and not s["offer"]


def test_qa_http_real_upload_while_loaded_is_409_even_when_named_with_reserved_prefix(client, who, db_session):
    who("qa-a")
    client.post(SAMPLE)
    before = _rows_all(db_session, "qa-a")
    for name in ("mine.csv", "SAMPLE_x.csv"):
        r = client.post(UP, files=[("files", (name, p2.tradebook(), "text/csv"))])
        assert r.status_code == 409, name
    assert _rows_all(db_session, "qa-a") == before


@pytest.mark.parametrize("name", ["SAMPLE_x.csv", "sample_x.csv", "Sample_X.CSV", " SAMPLE_x.csv",
                                  "C:\\fake\\SAMPLE_x.csv", "../../SAMPLE_tradebook.csv", "dir/sample_ledger.csv"])
def test_qa_http_reserved_names_cannot_be_spoofed_by_a_real_upload(client, who, db_session, name):
    who("qa-a")
    r = client.post(UP, files=[("files", (name, p2.tradebook(), "text/csv"))])
    assert r.status_code == 200
    f = r.json()["files"][0]
    assert f["status"] == "failed" and f["errors"][0]["code"] == "reserved_file_name"
    s = client.get(ST).json()
    assert not s["has_data"] and not s["sample"]["loaded"] and s["sample"]["offer"]
    assert _count(db_session, Trade, "qa-a") == 0


def test_qa_http_reserved_name_is_failed_per_file_while_siblings_still_import_as_real_data(client, who):
    who("qa-a")
    r = client.post(UP, files=[("files", ("SAMPLE_a.csv", p2.tradebook(), "text/csv")),
                               ("files", ("real.csv", p2.tradebook(), "text/csv"))]).json()
    assert [f["status"] for f in r["files"]] == ["failed", "ok"]
    s = client.get(ST).json()
    assert s["has_data"] and not s["sample"]["loaded"], "a real sibling must never look like the sample"
    assert client.post(SAMPLE).json()["reason"] == "has_own_data"


def test_qa_http_remove_sample_with_delete_then_real_upload_then_sample_refused(client, who, db_session):
    who("qa-a")
    client.post(SAMPLE)
    assert client.delete(UP + "?confirm=true").status_code == 200
    assert _rows_all(db_session, "qa-a") == {"trades": 0, "ledger": 0, "pnl": 0, "runs": 0}
    s = client.get(ST).json()["sample"]
    assert s["offer"] and s["can_load"] and not s["loaded"]
    ok = client.post(UP, files=[("files", ("tb.csv", p2.tradebook(), "text/csv"))])
    assert ok.status_code == 200 and ok.json()["files"][0]["status"] == "ok"
    assert client.post(SAMPLE).json()["reason"] == "has_own_data"
    assert client.post(UP, files=[("files", ("tb2.csv", p2.tradebook(), "text/csv"))]).status_code == 200


def test_qa_http_partial_delete_keeps_sample_blocking_real_uploads_until_full_delete(client, who):
    who("qa-a")
    client.post(SAMPLE)
    for kind in ("tradebook", "ledger"):
        client.delete(UP + f"?confirm=true&kind={kind}")
    s = client.get(ST).json()
    assert s["sample"]["loaded"] and s["has_data"]
    assert s["sample"]["window"] is None, "tradebook run is gone, so no window is claimed"
    assert client.post(UP, files=[("files", ("tb.csv", p2.tradebook(), "text/csv"))]).status_code == 409
    r = client.post(SAMPLE).json()
    assert r["status"] == "already_loaded" and r["window"] is None
    client.delete(UP + "?confirm=true")
    assert client.post(SAMPLE).json()["status"] == "loaded"


def test_qa_http_failed_real_run_then_sample_load_then_remove(client, who, db_session):
    who("qa-a")
    assert _junk_upload(client).json()["files"][0]["status"] == "failed"
    assert client.get(ST).json()["sample"]["offer"] is True
    assert client.post(SAMPLE).json()["status"] == "loaded"
    s = client.get(ST).json()
    assert s["sample"]["loaded"] and "junk.csv" in {r["file_name"] for r in s["recent_runs"]}
    assert client.post(UP, files=[("files", ("tb.csv", p2.tradebook(), "text/csv"))]).status_code == 409
    client.delete(UP + "?confirm=true")
    assert client.get(ST).json()["sample"]["offer"] is True


def _boom_on(monkeypatch, kinds: set[str]):
    real = FnoImportService._persist

    def flaky(self, user_id, name, sha, size, parsed):
        if parsed.kind in kinds:
            raise RuntimeError("boom-secret")
        return real(self, user_id, name, sha, size, parsed)

    monkeypatch.setattr(FnoImportService, "_persist", flaky)


@pytest.mark.parametrize("kinds", [{"tradebook"}, {"ledger"}, {"pnl"}, {"tradebook", "ledger", "pnl"}])
def test_qa_http_mid_load_failure_in_any_file_purges_only_this_load(client, who, db_session, monkeypatch, kinds):
    who("qa-a")
    _junk_upload(client)
    _junk_upload(client)
    earlier = _run_names(db_session, "qa-a")
    assert earlier == ["junk.csv", "junk.csv"]
    _boom_on(monkeypatch, kinds)
    r = client.post(SAMPLE)
    assert r.status_code == 200
    body = r.json()
    assert (body["status"], body["reason"]) == ("refused", "sample_failed")
    assert "boom-secret" not in json.dumps(body) and body["files"] == []
    assert _rows_all(db_session, "qa-a") == {"trades": 0, "ledger": 0, "pnl": 0, "runs": 2}
    assert _run_names(db_session, "qa-a") == earlier
    monkeypatch.undo()
    monkeypatch.setattr(get_settings().data, "input_dir", str(h.REPO / "data" / "input"))
    assert client.post(SAMPLE).json()["status"] == "loaded", "state must be clean enough to retry"


def test_qa_http_exception_escaping_import_files_is_a_clean_sample_failed(client, who, db_session, monkeypatch):
    who("qa-a")
    real = FnoImportService.import_files

    def half_then_die(self, user_id, uploads, allow_reserved=False):
        real(self, user_id, uploads[:1], allow_reserved)        # tradebook committed, then crash
        raise RuntimeError("kaboom-secret")

    monkeypatch.setattr(FnoImportService, "import_files", half_then_die)
    r = client.post(SAMPLE)
    assert r.status_code == 200 and r.json()["reason"] == "sample_failed"
    assert "kaboom-secret" not in r.text
    assert _rows_all(db_session, "qa-a") == {"trades": 0, "ledger": 0, "pnl": 0, "runs": 0}


def test_qa_http_cleanup_failure_reports_incomplete_and_user_can_recover_with_delete(client, who, db_session,
                                                                                    monkeypatch):
    who("qa-a")
    _boom_on(monkeypatch, {"pnl"})

    def bad_purge(self, user_id):
        raise RuntimeError("purge-secret")

    monkeypatch.setattr(FnoTradeRepo, "purge", bad_purge)
    r = client.post(SAMPLE)
    body = r.json()
    assert r.status_code == 200 and (body["status"], body["reason"]) == ("refused", "sample_failed")
    assert "incomplete" in body["message"] and "purge-secret" not in r.text
    monkeypatch.undo()
    monkeypatch.setattr(get_settings().data, "input_dir", str(h.REPO / "data" / "input"))
    assert client.delete(UP + "?confirm=true").status_code == 200
    assert _rows_all(db_session, "qa-a") == {"trades": 0, "ledger": 0, "pnl": 0, "runs": 0}
    assert client.post(SAMPLE).json()["status"] == "loaded"
    assert _count(db_session, Trade, "qa-a") == 352


def test_qa_http_sample_disabled_blocks_load_but_never_hides_removal(client, who, monkeypatch):
    who("qa-a")
    client.post(SAMPLE)
    monkeypatch.setattr(get_settings().trade_analysis, "sample_enabled", False)
    r = client.post(SAMPLE).json()
    assert (r["status"], r["reason"]) == ("refused", "sample_disabled")
    s = client.get(ST).json()["sample"]
    assert s["loaded"] is True and s["enabled"] is False, "a loaded user must still see the banner to remove it"
    assert client.delete(UP + "?confirm=true").status_code == 200
    s = client.get(ST).json()["sample"]
    assert not s["offer"] and not s["can_load"]
    who("fresh")
    assert client.get(ST).json()["sample"]["offer"] is False


def _sample_copy(tmp_path, monkeypatch):
    d = tmp_path / "sample" / "fno"
    shutil.copytree(h.SAMPLE_DIR, d)
    monkeypatch.setattr(get_settings().data, "input_dir", str(tmp_path))
    return d


@pytest.mark.parametrize("breakage", ["renamed", "empty", "deleted", "dir_missing", "oversized"])
def test_qa_http_sample_files_missing_variants_refuse_and_write_nothing(client, who, db_session, monkeypatch,
                                                                         tmp_path, breakage):
    who("qa-a")
    d = _sample_copy(tmp_path, monkeypatch)
    if breakage == "renamed":
        (d / "SAMPLE_ledger.csv").rename(d / "SAMPLE_ledger_v2.csv")
    elif breakage == "empty":
        (d / "SAMPLE_pnl.csv").write_bytes(b"")
    elif breakage == "deleted":
        (d / "SAMPLE_tradebook.csv").unlink()
    elif breakage == "dir_missing":
        shutil.rmtree(d)
    else:
        monkeypatch.setattr(get_settings().trade_analysis, "import_max_file_bytes", 2000)
    s = client.get(ST).json()["sample"]
    assert s["offer"] and not s["can_load"] and s["unavailable_reason"] == "sample_files_missing"
    r = client.post(SAMPLE)
    assert r.status_code == 200
    assert (r.json()["status"], r.json()["reason"]) == ("refused", "sample_files_missing")
    assert _rows_all(db_session, "qa-a") == {"trades": 0, "ledger": 0, "pnl": 0, "runs": 0}


def test_qa_http_corrupt_sample_file_is_sample_failed_with_nothing_left(client, who, db_session, monkeypatch,
                                                                       tmp_path):
    who("qa-a")
    d = _sample_copy(tmp_path, monkeypatch)
    (d / "SAMPLE_ledger.csv").write_text("nonsense,columns\n1,2\n")
    assert client.get(ST).json()["sample"]["can_load"] is True    # readiness is existence + size only
    r = client.post(SAMPLE).json()
    assert (r["status"], r["reason"]) == ("refused", "sample_failed")
    assert _rows_all(db_session, "qa-a") == {"trades": 0, "ledger": 0, "pnl": 0, "runs": 0}


def test_qa_http_user_scoping_between_two_users(client, who, db_session):
    who("user-a")
    assert client.post(SAMPLE).json()["status"] == "loaded"
    who("user-b")
    sb = client.get(ST).json()
    assert not sb["has_data"] and not sb["sample"]["loaded"] and sb["sample"]["offer"]
    assert client.get("/api/v1/experience/fno/trade-analysis/imported-trades").json()["total"] == 0
    body = client.get(AN + "foundation").json()
    assert body["available"] is False and body["reason"] == "no_data"
    assert client.post(SAMPLE).json()["status"] == "loaded"       # B loads its OWN copy
    assert _count(db_session, Trade, "user-a") == _count(db_session, Trade, "user-b") == 352
    who("user-a")
    client.delete(UP + "?confirm=true")
    assert _rows_all(db_session, "user-a")["trades"] == 0 and _count(db_session, Trade, "user-b") == 352
    who("user-b")
    assert client.get(ST).json()["sample"]["loaded"] is True
    ids_b = {t["trade_id"] for t in client.get(
        "/api/v1/experience/fno/trade-analysis/imported-trades?page_size=200").json()["items"]}
    assert ids_b and all(i.startswith("SMP") for i in ids_b)


def test_qa_http_every_panel_has_empty_state_without_data_and_content_with_sample(client, who, db_session):
    who("empty")
    for p in PANELS:
        b = client.get(AN + p).json()
        assert b["available"] is False and b["reason"] == "no_data", p
        assert "load sample data" in (b["message"] or "").lower(), p
    who("fails-only")
    _junk_upload(client)
    assert client.get(AN + "suggestions").json()["reason"] == "no_data"
    who("sampler")
    h.seed_spot(db_session)
    assert client.post(SAMPLE).json()["status"] == "loaded"
    for p in PANELS:
        for qs in ("", "?underlying=NIFTY", "?underlying=BANKNIFTY", "?include_expiry_estimate=true",
                   "?include_expiry_estimate=false"):
            r = client.get(AN + p + qs)
            b = r.json()
            assert r.status_code == 200 and b["available"] is True and not b["reason"], (p, qs, b.get("reason"))


def test_qa_http_panels_survive_missing_spot_cache_without_500(client, who):
    """Prod risk 10.5: if the prod cache lacks the window the sample still loads and nothing 500s."""
    who("nospot")
    assert client.post(SAMPLE).json()["status"] == "loaded"
    for p in PANELS:
        r = client.get(AN + p)
        assert r.status_code == 200, p
    assert client.get(AN + "market-turn").json()["available"] in (True, False)
    assert client.get(AN + "margin-trap").json()["available"] is True        # ledger-only panel needs no spot


def test_qa_status_schema_accepts_legacy_payload_without_sample_block():
    from rita.schemas.fno_console_import import ImportStatusResponse

    legacy = ImportStatusResponse(**{k: v for k, v in _legacy_status().items()})
    assert legacy.sample is None


def _legacy_status() -> dict:
    s = FnoImportService  # noqa: F841 - keep import used
    from tests.unit.f42_p5_helpers import new_db
    from rita.services.fno_import_service import FnoImportReadService

    db = new_db()
    try:
        d = FnoImportReadService(db).status("legacy").model_dump(by_alias=True)
    finally:
        db.close()
    d.pop("sample")
    return d


# ── concurrency ────────────────────────────────────────────────────────────────

def _file_maker(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'c.db'}", connect_args={"check_same_thread": False, "timeout": 30})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)


def test_qa_eight_concurrent_loads_for_one_user_insert_exactly_once(tmp_path):
    maker = _file_maker(tmp_path)
    n = 8
    start = threading.Barrier(n)
    out: list[str] = []

    def go():
        db = maker()
        try:
            start.wait()
            out.append(FnoSampleService(db, FnoSampleFileRepo.from_settings()).load("racer").status)
        finally:
            db.close()

    ts = [threading.Thread(target=go) for _ in range(n)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(out) == ["already_loaded"] * (n - 1) + ["loaded"]
    db = maker()
    assert _rows_all(db, "racer") == {"trades": 352, "ledger": 63, "pnl": 79, "runs": 3}
    db.close()


def test_qa_concurrent_loads_for_different_users_never_leave_partial_or_duplicate_state(tmp_path):
    maker = _file_maker(tmp_path)
    users = ["cu1", "cu2", "cu3"]
    start = threading.Barrier(len(users) * 2)
    out: list[tuple[str, str, str | None]] = []

    def go(uid):
        db = maker()
        try:
            start.wait()
            r = FnoSampleService(db, FnoSampleFileRepo.from_settings()).load(uid)
            out.append((uid, r.status, r.reason))
        finally:
            db.close()

    ts = [threading.Thread(target=go, args=(u,)) for u in users for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    db = maker()
    for u in users:
        rows = _rows_all(db, u)
        assert rows in ({"trades": 352, "ledger": 63, "pnl": 79, "runs": 3},
                        {"trades": 0, "ledger": 0, "pnl": 0, "runs": 0}), (u, rows, out)
        assert sum(1 for x in out if x[0] == u and x[1] == "loaded") <= 1
    assert all(s != "refused" or r == "sample_failed" for _, s, r in out), out
    assert sum(1 for x in out if x[1] == "loaded") == len(users), f"SQLite contention broke a load: {out}"
    db.close()


def test_qa_lock_does_not_leak_on_failure(db_session, monkeypatch):
    """A failed load must release the per-user lock (a retry must not deadlock)."""
    real = FnoImportService.import_files
    monkeypatch.setattr(FnoImportService, "import_files",
                        lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    svc = FnoSampleService(db_session, FnoSampleFileRepo.from_settings())
    assert svc.load("lk").reason == "sample_failed"
    monkeypatch.setattr(FnoImportService, "import_files", real)
    done: list[str] = []
    t = threading.Thread(target=lambda: done.append(svc.load("lk").status))
    t.start()
    t.join(timeout=20)
    assert done == ["loaded"], "the per-user lock was not released after a failed load"


# ═══ E. JS contract ════════════════════════════════════════════════════════════

JS_DIR = h.REPO / "dashboard" / "js" / "fno"
HTML = h.REPO / "dashboard" / "fno.html"
_IDS = ["ta-sample-banner", "ta-sample-banner-text", "ta-sample-remove-btn", "ta-sample-own-btn",
        "ta-imp-sample-card", "ta-imp-sample-btn", "ta-imp-sample-note", "ta-empty-cta", "ta-empty-cta-btn"]


def _fn_body(src: str, name: str) -> str:
    m = re.search(rf"(?:async\s+)?function\s+{name}\s*\([^)]*\)\s*{{", src)
    assert m, name
    depth, i = 1, m.end()
    while depth:
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        i += 1
    return src[m.end():i]


@pytest.mark.parametrize("dom_id", _IDS)
def test_qa_js_dom_ids_exist_exactly_once(dom_id):
    html = HTML.read_text()
    assert len(re.findall(rf'\bid="{re.escape(dom_id)}"', html)) == 1


def test_qa_js_banner_precedes_tabs_and_inline_handlers_are_bound_on_window():
    html = HTML.read_text()
    assert html.index('id="ta-sample-banner"') < html.index('id="ta-tabs"')
    main = (JS_DIR / "main.js").read_text()
    for fn in ("taSampleLoad", "taSampleRemove"):
        assert re.search(rf"window\.{fn}\s*=\s*{fn}\s*;", main), fn
        assert re.search(rf"import\s*{{[^}}]*\b{fn}\b[^}}]*}}\s*from\s*'\./trade-import\.js'", main), fn
    handlers = set()
    for i in _IDS:
        m = re.search(rf'<[^>]*\bid="{i}"[^>]*>', html)
        handlers |= set(re.findall(r"\b(ta[A-Za-z]+)\(", " ".join(re.findall(r'onclick="([^"]*)"', m[0]))))
    for fn in handlers:
        assert re.search(rf"window\.{fn}\s*=", main), f"{fn} used by inline onclick but not on window"


def test_qa_js_server_strings_in_innerhtml_sinks_are_escaped():
    src = (JS_DIR / "trade-import.js").read_text()
    for fn in ("_renderSample", "taSampleLoad"):
        body = _fn_body(src, fn)
        for call in re.findall(r"setEl\(([^;]*)\);", body):
            stripped = re.sub(r"_(?:esc|dash)\([^()]*\)", "", call)
            assert not re.search(r"\$\{[^}]*\b(?:w|sm|s|out|refused|e)\.\w+", stripped), (fn, call)
            assert not re.search(r"\b(?:refused|out\.message)\b", stripped), (fn, call)
    assert "innerHTML" not in _fn_body(src, "taSampleRemove")
    assert "/api/v1/workflow/fno/console-import/sample" in src


def test_qa_js_no_data_copy_points_to_sample_and_cta_hidden_logic_present():
    ta = (JS_DIR / "trade-analytics.js").read_text()
    assert "load sample data" in ta
    assert "_show('ta-empty-cta', !(s && s.has_data))" in (JS_DIR / "trade-import.js").read_text()


_HARNESS = r"""
import { loadImportPanel, taSampleLoad, taSampleRemove } from './fno/trade-import.js';
const els = new Map();
const mk = id => ({ id, style: {}, innerHTML: '', textContent: '', disabled: false, value: '', checked: false });
globalThis.document = { getElementById: id => { if (!els.has(id)) els.set(id, mk(id)); return els.get(id); } };
globalThis.window = globalThis;
let confirmAnswer = true;
globalThis.confirm = () => confirmAnswer;
const calls = [];
let status = null, trades = { items: [], total: 0, page: 1, total_pages: 1 };
let post = null, postErr = null;
globalThis.__api = async (url, method) => {
  calls.push([method || 'GET', url]);
  if (url.includes('/sample') && method === 'POST') { if (postErr) throw postErr; return post; }
  if (url.includes('import-status')) return status;
  if (url.includes('imported-trades')) return trades;
  return {};
};
globalThis.__onRefresh = async () => { await loadImportPanel(); };
const el = id => document.getElementById(id);
const out = {};
const base = { has_data: false, scope: { underlyings: ['NIFTY'], expiry_months: [7], expiry_year: 2026, date_from: '2026-07-01' },
  limits: {}, trades: {}, pnl: {}, ledger: {}, last_imports: {}, recent_runs: [] };
const X = '<img src=x onerror=alert(1)>';

// 1 legacy payload without `sample`
status = { ...base };
await loadImportPanel();
out.legacy = { banner: el('ta-sample-banner').style.display, card: el('ta-imp-sample-card').style.display,
               cta: el('ta-empty-cta').style.display, bannerText: el('ta-sample-banner-text').innerHTML };

// 2 loaded with hostile window strings + hostile run names
status = { ...base, has_data: true, recent_runs: [{ id: 'r', kind: 'tradebook', file_name: X, status: 'ok', rows_parsed: 1,
  rows_inserted: 1, rows_updated: 0, rows_skipped: 0, rows_rejected: 0, created_at: X }],
  sample: { enabled: true, loaded: true, offer: false, can_load: false, unavailable_reason: null,
            window: { from: X, to: X }, file_prefix: 'SAMPLE_' } };
await loadImportPanel();
out.loaded = { banner: el('ta-sample-banner').style.display, text: el('ta-sample-banner-text').innerHTML,
               fileDisabled: el('ta-imp-file').disabled, uploadDisabled: el('ta-imp-upload-btn').disabled,
               chosen: el('ta-imp-chosen').innerHTML, runs: el('ta-imp-runs-body').innerHTML,
               card: el('ta-imp-sample-card').style.display, cta: el('ta-empty-cta').style.display };

// 3 loaded, window null
status = { ...status, sample: { ...status.sample, window: null } };
await loadImportPanel();
out.noWindow = el('ta-sample-banner-text').innerHTML;

// 4 offer but files missing
status = { ...base, sample: { enabled: true, loaded: false, offer: true, can_load: false,
           unavailable_reason: 'sample_files_missing', window: null, file_prefix: 'SAMPLE_' } };
await loadImportPanel();
out.unavailable = { card: el('ta-imp-sample-card').style.display, btn: el('ta-imp-sample-btn').disabled,
                    note: el('ta-imp-sample-note').textContent };

// 5 offer + can_load; double click -> a single POST; refusal text with hostile message is escaped
status = { ...base, sample: { enabled: true, loaded: false, offer: true, can_load: true, unavailable_reason: null,
           window: null, file_prefix: 'SAMPLE_' } };
await loadImportPanel();
out.offer = { card: el('ta-imp-sample-card').style.display, btn: el('ta-imp-sample-btn').disabled };
post = { status: 'refused', reason: 'has_own_data', message: X };
calls.length = 0;
await Promise.all([taSampleLoad(), taSampleLoad()]);
out.doubleClickPosts = calls.filter(c => c[0] === 'POST').length;
out.refusedNote = el('ta-imp-sample-note').innerHTML;
out.btnAfter = el('ta-imp-sample-btn').disabled;

// 6 thrown error is shown as text and the button is re-enabled
postErr = new Error(X);
await taSampleLoad();
out.errBanner = { text: el('ta-imp-banner').textContent, html: el('ta-imp-banner').innerHTML, btn: el('ta-imp-sample-btn').disabled };
postErr = null;

// 7 remove: declined confirm sends nothing, accepted confirm sends DELETE
calls.length = 0; confirmAnswer = false;
out.removeDeclined = { ret: await taSampleRemove(), calls: calls.length };
confirmAnswer = true;
const ret = await taSampleRemove();
out.removeAccepted = { ret, deletes: calls.filter(c => c[0] === 'DELETE').map(c => c[1]) };
console.log(JSON.stringify(out));
"""


@pytest.fixture()
def node_out(tmp_path):
    if shutil.which("node") is None:
        pytest.skip("node not installed")
    root = tmp_path / "web"
    (root / "fno").mkdir(parents=True)
    (root / "shared").mkdir()
    (root / "package.json").write_text('{"type":"module"}')
    shutil.copy(JS_DIR / "trade-import.js", root / "fno" / "trade-import.js")
    shutil.copy(h.REPO / "dashboard" / "js" / "shared" / "utils.js", root / "shared" / "utils.js")
    (root / "fno" / "api.js").write_text(
        "export const api = (u, m) => globalThis.__api(u, m);\nexport const apiUpload = async () => ({});\n")
    (root / "fno" / "trade-analysis.js").write_text(
        "export async function taRefresh() { await globalThis.__onRefresh(); }\n")
    (root / "harness.mjs").write_text(_HARNESS)
    r = subprocess.run(["node", "harness.mjs"], cwd=root, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_qa_js_node_legacy_payload_hides_sample_ui_without_throwing(node_out):
    lg = node_out["legacy"]
    assert lg["banner"] == "none" and lg["card"] == "none" and lg["bannerText"] == ""
    assert lg["cta"] == "", "no data -> empty-state CTA visible"


def test_qa_js_node_loaded_state_escapes_hostile_strings_and_gates_uploads(node_out):
    ld = node_out["loaded"]
    assert ld["banner"] == "" and ld["card"] == "none" and ld["cta"] == "none"
    assert ld["fileDisabled"] is True and ld["uploadDisabled"] is True
    assert "Remove the sample data" in ld["chosen"]
    for field in ("text", "runs"):
        assert "<img" not in ld[field] and "&lt;img" in ld[field], field


def test_qa_js_node_banner_without_window_has_no_undefined_or_null_text(node_out):
    t = node_out["noWindow"]
    assert "Sample data loaded" in t and "undefined" not in t and "null" not in t and "Window" not in t


def test_qa_js_node_unavailable_and_offer_states(node_out):
    u, o = node_out["unavailable"], node_out["offer"]
    assert u["card"] == "" and u["btn"] is True and "not available" in u["note"]
    assert o["card"] == "" and o["btn"] is False


def test_qa_js_node_double_click_posts_once_and_refusal_text_is_escaped(node_out):
    assert node_out["doubleClickPosts"] == 1
    assert "<img" not in node_out["refusedNote"] and "&lt;img" in node_out["refusedNote"]


def test_qa_js_node_error_path_uses_text_and_reenables_button(node_out):
    e = node_out["errBanner"]
    assert "<img" in e["text"] and "<img" not in e["html"], "banner must use textContent, never raw innerHTML"
    assert e["btn"] is False


def test_qa_js_node_remove_asks_confirmation_then_uses_existing_delete(node_out):
    assert node_out["removeDeclined"] == {"ret": False, "calls": 0}
    assert node_out["removeAccepted"]["ret"] is True
    assert node_out["removeAccepted"]["deletes"] == ["/api/v1/workflow/fno/console-import?confirm=true"]
