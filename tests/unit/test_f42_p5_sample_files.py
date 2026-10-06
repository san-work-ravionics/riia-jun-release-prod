"""F42 P5 - the committed SYNTHETIC sample files: content hygiene, generator drift guard, CSV round
trip through the real parsers, reconciliation and the numeric headline bands (design section 6.8),
all evaluated through the REAL import service and analytics services.  Synthetic data only."""
from __future__ import annotations

import ast
import csv
import subprocess
import sys
import warnings
from collections import defaultdict
from datetime import date

import pytest

from rita.config import get_settings
from rita.services.console_parsers import LEDGER, PNL, TRADEBOOK, parse_file
from rita.services.fno_symbol_parser import parse_symbol
from tests.unit import f42_p5_helpers as h

CFG = get_settings().trade_analysis
LOTS = {"NIFTY": get_settings().instruments.nifty.lot_size,
        "BANKNIFTY": get_settings().instruments.banknifty.lot_size}
SCRIPT = h.REPO / "scripts" / "generate_fno_sample.py"
TB_HEADER = ["symbol", "isin", "trade_date", "exchange", "segment", "series", "trade_type", "auction",
             "quantity", "price", "trade_id", "order_id", "order_execution_time", "expiry_date"]
USER = "u-sample-bands"


def _rows(kind: str) -> list[dict]:
    with (h.SAMPLE_DIR / h.NAMES[kind]).open(newline="") as f:
        return list(csv.DictReader(f))


# ── 1. committed files: hygiene ────────────────────────────────────────────────

def test_three_files_exist_and_are_small():
    sizes = [(h.SAMPLE_DIR / n).stat().st_size for n in h.NAMES.values()]
    assert all(s > 0 for s in sizes)
    assert sum(sizes) < 200 * 1024                  # guards against committing a large "sample"
    assert sorted(p.name for p in h.SAMPLE_DIR.iterdir()) == sorted(h.NAMES.values())


def test_tradebook_content_rules():
    with (h.SAMPLE_DIR / h.NAMES["tradebook"]).open(newline="") as f:
        assert next(csv.reader(f)) == TB_HEADER
    rows = _rows("tradebook")
    assert 300 <= len(rows) <= 500
    lo, hi = h.WINDOW
    for r in rows:
        assert r["trade_id"].startswith("SMP") and len(r["trade_id"]) == 11
        assert r["order_id"].startswith("SMP") and len(r["order_id"]) == 15
        assert r["exchange"] == "NFO" and r["segment"] == "FO" and r["auction"] == "false"
        assert r["trade_type"] in ("buy", "sell")
        info = parse_symbol(r["symbol"])
        assert info.underlying in LOTS and info.parse_status == "ok" and info.instrument_type in ("CE", "PE")
        assert int(r["quantity"]) % LOTS[info.underlying] == 0 and int(r["quantity"]) > 0
        assert float(r["price"]) >= 0.05
        assert lo <= date.fromisoformat(r["trade_date"]) <= hi
        exp = date.fromisoformat(r["expiry_date"])
        assert exp.month in CFG.expiry_months and exp.year == CFG.expiry_year
        assert r["order_execution_time"].startswith(r["trade_date"])
        hhmm = r["order_execution_time"][11:16]
        assert "09:15" <= hhmm <= "15:30"
    assert len({r["trade_id"] for r in rows}) == len(rows)


def test_ledger_and_pnl_content_rules():
    led = _rows("ledger")
    assert led and all(r["particulars"].startswith("SAMPLE ") for r in led)
    lo, hi = h.WINDOW
    assert all(lo <= date.fromisoformat(r["posting_date"]) <= hi for r in led)
    text = (h.SAMPLE_DIR / h.NAMES["pnl"]).read_text()
    assert "SAMPLE-DEMO" in text and "not a real account" in text
    assert f"from {lo.isoformat()} to {hi.isoformat()}" in text


def test_total_size_budget_and_no_personal_markers():
    for n in h.NAMES.values():
        blob = (h.SAMPLE_DIR / n).read_text().lower()
        assert "live-data" not in blob and "zerodha console" not in blob


# ── generator: pinned inputs, stdlib only, drift guard ─────────────────────────

def test_generator_is_stdlib_only_and_has_no_live_data_reference():
    src = SCRIPT.read_text()
    assert "live-data" not in src and "print(" not in src
    tree = ast.parse(src)
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[0])
    assert mods <= set(sys.stdlib_module_names) | {"__future__"}, mods


def test_generator_requires_lot_sizes_no_defaults(tmp_path):
    r = subprocess.run([sys.executable, str(SCRIPT), "--out", str(tmp_path)], capture_output=True, text=True)
    assert r.returncode != 0 and "--nifty-lot" in r.stderr


def test_generator_drift_guard_byte_identical(tmp_path):
    """Regenerating from the pinned closes fixture + settings lot sizes reproduces the committed files."""
    r = subprocess.run([sys.executable, str(SCRIPT), "--nifty-lot", str(LOTS["NIFTY"]),
                        "--banknifty-lot", str(LOTS["BANKNIFTY"]), "--out", str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    for name in h.NAMES.values():
        assert (tmp_path / name).read_bytes() == (h.SAMPLE_DIR / name).read_bytes(), \
            f"{name} drifted: regenerate (lot sizes in settings changed?) and re-run the band tests"


def test_closes_fixture_matches_dev_csvs_informational():
    """Warn-only: the fixture is a frozen public-close snapshot; it need not follow later refreshes."""
    dev = {}
    for und, rel in (("NIFTY", "data/input/NIFTY/nifty_daily.csv"),
                     ("BANKNIFTY", "data/input/BANKNIFTY/banknifty_daily.csv")):
        p = h.REPO / rel
        if not p.exists():
            pytest.skip("dev CSVs absent")
        with p.open(newline="") as f:
            dev[und] = {r["Date"]: float(r["Close"]) for r in csv.DictReader(f)}
    diff = [d for d, n, b in h.closes() if abs(dev["NIFTY"].get(d, -1) - n) > 0.01
            or abs(dev["BANKNIFTY"].get(d, -1) - b) > 0.01]
    if diff:
        warnings.warn(f"closes fixture differs from the dev CSVs on {len(diff)} day(s)")


def test_fixture_covers_the_trading_window():
    days = [d for d, _n, _b in h.closes()]
    assert days[0] <= "2026-06-30" and days[-1] == "2026-09-18"
    rows = _rows("tradebook")
    assert min(r["trade_date"] for r in rows) >= "2026-07-01"
    assert max(r["trade_date"] for r in rows) <= days[-1]
    assert len([d for d in days if "2026-07-01" <= d <= "2026-09-18"]) == 57


# ── 2. CSV round trip through the REAL parsers ─────────────────────────────────

def test_parse_file_each_kind_zero_rejected():
    rows = {k: (h.SAMPLE_DIR / n).read_bytes() for k, n in h.NAMES.items()}
    tb = parse_file(rows["tradebook"], h.NAMES["tradebook"], CFG.import_max_rows)
    lg = parse_file(rows["ledger"], h.NAMES["ledger"], CFG.import_max_rows)
    pn = parse_file(rows["pnl"], h.NAMES["pnl"], CFG.import_max_rows)
    assert (tb.kind, lg.kind, pn.kind) == (TRADEBOOK, LEDGER, PNL)
    assert tb.rows_rejected == lg.rows_rejected == pn.rows_rejected == 0
    assert tb.rows_parsed == len(_rows("tradebook")) == len(tb.records)
    assert lg.rows_parsed == len(_rows("ledger"))
    assert not tb.errors and not lg.errors and not pn.errors


def test_pnl_csv_header_off_row_one_period_summary_and_symbols():
    pn = parse_file((h.SAMPLE_DIR / h.NAMES["pnl"]).read_bytes(), h.NAMES["pnl"], CFG.import_max_rows)
    assert (pn.period_from, pn.period_to) == h.WINDOW
    items = {c["item"]: c for c in pn.charges}
    assert {"Charges", "Other Credit & Debit", "Realized P&L", "Unrealized P&L"} <= set(items)
    assert all(items[k]["section"] == "summary" for k in
               ("Charges", "Other Credit & Debit", "Realized P&L", "Unrealized P&L"))
    assert {"Brokerage", "STT/CTT", "GST"} <= {c["item"] for c in pn.charges if c["section"] == "charges"}
    tb_symbols = {r["symbol"] for r in _rows("tradebook")}
    assert {r["symbol"] for r in pn.records} == tb_symbols
    assert sum(1 for r in pn.records if r["open_quantity"]) == 2        # the two window-end positions


# ── 3-4. loaded-sample fixture: reconciliation and headline bands ──────────────

@pytest.fixture(scope="module")
def loaded():
    db = h.new_db()
    h.seed_spot(db)
    res = h.load_files(db, USER)
    assert res.totals.files_failed == 0
    out = {"db": db, "res": res, "meas": h.panels(db, USER, False), "dflt": h.panels(db, USER, True),
           "ctx": h.ctx_for(db, USER, False)}
    out["m"] = {k: v.model_dump() for k, v in out["meas"].items()}
    out["d"] = {k: v.model_dump() for k, v in out["dflt"].items()}
    yield out
    db.close()


def test_three_runs_ok_named_sample(loaded):
    assert [f.status for f in loaded["res"].files] == ["ok", "ok", "ok"]
    assert [f.file_name for f in loaded["res"].files] == [h.NAMES["tradebook"], h.NAMES["ledger"], h.NAMES["pnl"]]
    assert all(f.rejected == 0 for f in loaded["res"].files)


def test_every_panel_is_available_in_both_estimate_modes(loaded):
    for mode in ("m", "d"):
        for name, p in loaded[mode].items():
            assert p["available"] is True and not p["reason"], (mode, name)
    assert loaded["m"]["margin-trap"]["ledger"]["available"] is True


def test_reconciliation_by_construction(loaded):
    rec = loaded["m"]["foundation"]["reconciliation"]
    rows = rec["rows"]
    gap = [r for r in rows if not r["within_tolerance"]]
    assert rec["totals"]["n_symbols_gap"] == len(gap) == 3
    assert all(r["causes"] == ["expiry_unclosed"] for r in gap)
    assert all(abs(r["gap_with_estimate"]) <= 1.0 for r in rows)            # estimate closes every gap
    assert all(abs(r["gap_measured"]) <= 1.0 for r in rows if r not in gap)
    assert rec["totals"]["sheet_lines_overlap_dropped"] == 0
    t = rec["totals"]
    assert abs(t["sheet_realised"] - (t["fifo_measured"] + t["fifo_expiry_estimate"])) <= 1.0


def test_headline_winloss_charges_and_net(loaded):
    w = loaded["m"]["overtrading"]["winloss"]
    ch = loaded["m"]["overtrading"]["charges"]
    trades = loaded["ctx"].trades
    assert 78 <= w["n"] <= 82 and 34 <= w["wins"] <= 38 and 42.0 <= w["win_rate"] <= 48.0
    assert 2850 <= w["avg_win"] <= 3150 and 3100 <= w["avg_loss"] <= 3420
    assert -40000 <= w["pnl"] <= -31000
    assert abs(w["pnl"] - sum(t.pnl for t in trades)) <= 1.0               # reported total == sum of trades
    assert 9000 <= ch["total_sheet"] <= 10000 and abs(ch["total_sheet"] - ch["est_window"]) <= 1.0
    assert -50000 <= w["pnl"] - ch["est_window"] <= -40000
    assert 4 <= w["max_loss_streak"] <= 7


def test_expiry_estimate_three_held_symbols(loaded):
    f = loaded["m"]["foundation"]
    assert -1000 <= f["fifo_totals"]["estimated_pnl"] <= 4000
    est = [r for r in f["reconciliation"]["rows"] if abs(r["fifo_expiry_estimate"]) > 0]
    assert len(est) == 3
    assert sorted(r["fifo_expiry_estimate"] > 0 for r in est) == [False, True, True]   # 2 worthless, 1 ITM short
    assert f["fifo_totals"]["measured_pnl"] == loaded["m"]["overtrading"]["winloss"]["pnl"]


def test_sub_five_minute_trades(loaded):
    edge = CFG.holding_bucket_edges_minutes[0]
    quick = [t for t in loaded["ctx"].trades
             if t.same_day and t.holding_minutes is not None and t.holding_minutes < edge]
    assert 12 <= len(quick) <= 16
    assert -9000 <= sum(t.pnl for t in quick) <= -5000
    buckets = {b["label"]: b["count"] for b in loaded["m"]["overtrading"]["holding"]["buckets"]}
    assert buckets[f"<{edge}m"] == len(quick)


def test_bursts_reentries_and_busiest_days(loaded):
    b = loaded["m"]["overtrading"]["bursts"]
    assert 6 <= b["count"] <= 9
    assert b["reentries_after_loss"]["count"] >= 3
    per_day: dict = defaultdict(int)
    for e in loaded["ctx"].events:
        per_day[e.fill.trade_date] += 1
    assert max(per_day.values()) >= 14 and sum(1 for v in per_day.values() if v >= 14) >= 2


def test_buildup_chains_and_peak_lots(loaded):
    bu = loaded["m"]["buildup"]
    assert 2 <= bu["chain_totals"]["with_adverse_add"] <= 3
    adding = [c for c in bu["chains"] if c["adverse_adds"]]
    assert len(adding) == 2 and {c["side"] for c in adding} == {"long", "short"}
    biggest = max(adding, key=lambda c: c["peak_qty"])
    assert 8 <= biggest["peak_qty"] / LOTS["NIFTY"] <= 10


def _facts():
    """Market facts recomputed from the pinned closes fixture and the live threshold."""
    rows = h.closes()
    out = {"big": 0, "turn": 0}
    for idx in (1, 2):
        prev_r = None
        for i in range(1, len(rows)):
            r = round((rows[i][idx] / rows[i - 1][idx] - 1.0) * 100.0, 9)
            d = rows[i][0]
            if h.WINDOW[0].isoformat() <= d <= h.WINDOW[1].isoformat():
                big = abs(r) >= CFG.turn_threshold_pct
                sg = lambda x: 0 if x is None or abs(x) < 1e-9 else (1 if x > 0 else -1)  # noqa: E731
                out["big"] += big
                out["turn"] += bool(big and sg(prev_r) != 0 and sg(r) != sg(prev_r))
            prev_r = r
    return out


def test_market_turn(loaded):
    k = loaded["m"]["market-turn"]["kpis"]
    f = _facts()
    assert (f["big"], f["turn"]) == (14, 6)                                 # at turn_threshold_pct = 1.0
    assert k["n_big_move_days"] == f["big"] and k["n_turn_days"] == f["turn"]
    assert k["n_adverse_exposed"] >= 4 and k["adverse_exposed_pct"] >= 66.0
    assert k["realised_pnl_turn_adverse"] <= -12000


def test_loss_concentration_pinned_to_gross_losses(loaded):
    day: dict = defaultdict(float)
    for t in loaded["ctx"].trades:
        day[t.close_date] += t.pnl
    worst5 = sum(sorted(v for v in day.values() if v < 0)[:5])
    gross_loss = -sum(t.pnl for t in loaded["ctx"].trades if t.pnl < 0)
    share = -worst5 / gross_loss * 100.0
    assert 50.0 <= share <= 65.0
    wd = loaded["m"]["market-turn"]["worst_days"]
    assert abs(sum(x["realised_pnl_day"] for x in wd) - worst5) <= 1.0


def test_spot_vs_pnl_panel(loaded):
    sp = loaded["m"]["spot-vs-pnl"]
    blocks = {b["underlying"]: b for b in sp["underlyings"]}
    assert set(blocks) == {"NIFTY", "BANKNIFTY"}
    closing_days = set()
    for u, b in blocks.items():
        assert b["available"] is True
        rel = b["relationship"]
        d = {x["key"]: x for x in rel["by_direction"]}
        assert d["up"]["n_closing_days"] >= 5 and d["down"]["n_closing_days"] >= 5
        assert rel["all_days"]["n"] >= 20 and rel["all_days"]["pearson"] is not None
        closing_days |= {dt for dt, c in zip(b["series"]["dates"], b["series"]["closing_day"]) if c}
    assert len(closing_days) >= 30
    al = {u: b["alignment"] for u, b in blocks.items()}
    scored = {u: a["with_n"] + a["against_n"] for u, a in al.items()}
    assert all(n >= 10 for n in scored.values()) and sum(scored.values()) >= 24
    against = sum(a["against_n"] for a in al.values()) / sum(scored.values()) * 100.0
    assert 60.0 <= against <= 72.0
    assert al["NIFTY"]["verdict"] == "against_market"
    assert blocks["NIFTY"]["unrealised_snapshot"]["available"] is True


def test_suggestions_all_rules_evaluable(loaded):
    s = loaded["m"]["suggestions"]
    assert s["available"] is True
    assert all(r["status"] != "insufficient_data" for r in s["rules"])
    positive = [r for r in s["rules"] if r["what_if"] and r["what_if"]["delta"] > 0]
    assert len(positive) >= 2
    assert s["combined"]["what_if"]["delta"] > 0


def test_margin_trap_cash_path(loaded):
    mt = loaded["m"]["margin-trap"]
    assert mt["ledger"]["balance_sign"] == 1 and mt["ledger"]["available"]
    c = mt["cash"]
    assert 8 <= c["days_below_threshold"] <= 14
    assert 8000 <= c["min"] <= 20000 and c["days_negative"] == 0
    st = mt["debit_streaks"]
    assert st and max(s["days"] for s in st) >= 5 and any(s["days"] >= 3 for s in st)
    assert mt["trap"]["days"] >= 3
    led = _rows("ledger")
    credits = sum(float(r["credit"] or 0) for r in led)
    debits = sum(float(r["debit"] or 0) for r in led)
    assert abs(float(led[-1]["net_balance"]) - (credits - debits)) <= 0.01      # opening + credits - debits
    assert abs(c["end"] - float(led[-1]["net_balance"])) <= 0.01
