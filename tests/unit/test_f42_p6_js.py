"""F42 P6 — node harness for dashboard/js/fno/trade-analytics.js (stubbed page modules, synthetic fixtures built in code:
invented symbols and round numbers, never read from disk or live-data/).  Skipped when node is not installed."""
from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "dashboard/js/fno/trade-analytics.js").read_text()
HARNESS = Path(__file__).with_name("f42_p6_harness.mjs")
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")

ENV = {"quality": {"fills_in_scope": 100, "timestamp_coverage_pct": 100.0, "spot_days_missing": 0, "spot_last_date": "2026-09-18",
                   "expiry_estimated_lots": 0, "expiry_unknown_lots": 0},
       "definition": "Synthetic definition.", "assumptions": ["Synthetic assumption."], "tags": {"measured": ["a"], "estimated": ["b"]},
       "filter": {"underlying": "ALL", "include_expiry_estimate": True, "date_from": "2026-07-01"}}


def _weeks():
    wk = [f"2026-W{w:02d}" for w in (27, 28, 29, 30, 32, 33, 34, 35, 36, 37)]      # W31 missing -> gap-filled by the axis
    return [{"week": w, "fills": 10 + i, "active_days": 3, "closed_trades": 4 + (i % 3)} for i, w in enumerate(wk)]


def _ok():
    ot = {**ENV, "available": True,
          "activity": {"fills_total": 352, "orders_total": 300, "active_days": 40, "market_days": 58,
                       "fills_per_day": {"mean": 8.8, "median": 8.0, "p90": 15.0, "max": 30}},
          "weekly": _weeks(),
          "by_expiry": [{"key": "2026-08", "fills": 100, "closed_trades": 20, "win_rate": 45.0, "pnl": -2000.0},
                        {"key": "2026-07", "fills": 80, "closed_trades": 18, "win_rate": 55.0, "pnl": 5000.0},
                        {"key": "2026-09", "fills": 60, "closed_trades": 10, "win_rate": 40.0, "pnl": -9000.0}],
          "by_underlying": [{"key": "NIFTY", "fills": 200, "closed_trades": 40, "win_rate": 50.0, "pnl": 1000.0},
                            {"key": "BANKNIFTY", "fills": 150, "closed_trades": 30, "win_rate": 42.0, "pnl": -12000.0}],
          "holding": {"available": True, "median_minutes": 22.5,
                      "buckets": [{"label": "<5m", "count": 10}, {"label": "5-30m", "count": 25}, {"label": "30m-2h", "count": 12}, {"label": ">2h", "count": 3}]},
          "churn": {"churn_qty_pct": 42.5, "churn_count_pct": 40.0, "churn_pnl": -1200.0, "same_day_trades": 88},
          "bursts": {"available": True, "count": 7, "reentries_after_loss": {"count": 4, "pnl": -3000.0},
                     "top": [{"date": f"2026-08-{d:02d}", "start": "10:05", "fills": 9, "symbols_count": 3, "pnl": p}
                             for d, p in ((3, -4000.0), (4, -500.0), (5, 200.0), (6, 0.0), (7, 1500.0), (10, -9000.0))]},
          "charges": {"available": True, "est_window": 12000.0, "pct_of_gross": 35.5, "per_closed_trade": 120.0, "breakeven_trades_needed": 40,
                      "estimated": True, "net_gross_negative": False},
          "winloss": {"n": 70, "wins": 33, "losses": 35, "scratch": 2, "win_rate": 47.1, "avg_win": 900.0, "avg_loss": -700.0, "payoff": 1.4,
                      "expectancy": 320.0, "breakeven_win_rate": 43.8, "largest_win": 9000.0, "largest_loss": -8000.0, "max_loss_streak": 5,
                      "by_side": [{"key": "long", "n": 30, "win_rate": 50.0, "pnl": 3000.0}, {"key": "short", "n": 40, "win_rate": 45.0, "pnl": -6000.0}],
                      "measured_only": {"n": 65, "win_rate": 46.0, "expectancy": 100.0, "pnl": 6500.0}}}

    def step(d, cls, delta, pos, price, avg, adv=False, worse=None, lots=None):
        return {"date": d, "time": "10:00", "cls": cls, "qty_delta": delta, "pos_after": pos, "lots_after": lots, "price": price,
                "avg_before": avg, "adverse": adv, "worse_pct": worse}

    def chain(sym, pnl, rank, steps=None):
        c = {"symbol": sym, "expiry_ym": "2026-08", "side": "long", "open_date": "2026-08-03", "close_date": "2026-08-10", "peak_qty": 250,
             "adds": 2, "adverse_adds": 1, "pnl_measured": pnl, "pnl_estimated": None, "still_open": False, "peak_lots": 10.0,
             "story_rank": rank, "steps": steps or [], "steps_total": len(steps) if steps else None, "steps_truncated": False}
        return c

    sa = [step("2026-08-03", "open_new", 100, 100, 20.0, None, lots=4.0), step("2026-08-04", "scale_in", 100, 200, 15.0, 20.0, True, 25.0, 8.0),
          step("2026-08-05", "scale_in", 50, 250, 18.0, 17.5, False, None, 10.0), step("2026-08-10", "close", -250, 0, 10.0, 17.5, lots=0.0)]
    bu = {**ENV, "available": True, "timeline": [], "events": {"open_new": 50, "scale_in": 30, "scale_out": 10, "close": 40, "flip": 1},
          "averaging": {"adverse_add_fills": 12, "adverse_add_units": 900, "share_of_entries_pct": 15.0, "adverse_add_closed_pnl": -20000.0,
                        "adverse_add_open_units": 50, "adverse_add_lots": 36.0, "spot_adverse_adds": 5},
          "chains": [chain("NIFTYAAA", -20000.0, 1, sa), chain("NIFTYBBB", -9000.0, 2, sa[:2] + sa[3:]), chain("BANKNIFTYCCC", -3000.0, 3, sa),
                     chain("NIFTYDDD", -1000.0, None)],
          "chain_totals": {"count": 83, "with_adverse_add": 12, "max_adds": 9},
          "chains_info": {"definition": "chains", "assumptions": []}, "timeline_info": {"definition": "t", "assumptions": []},
          "lots": {"lots_available": True, "lots_basis": "kite_master", "coverage_pct": 100.0}}
    days = [f"2026-08-{d:02d}" for d in range(3, 13)]
    cash = [90000, 70000, 30000, 20000, 15000, 60000, 80000, 85000, 90000, 95000]
    series = [{"date": d, "cash": float(c), "carried": False, "short_notional_proxy": 1000000.0 + i * 1000, "open_losers_count": 1 if c < 50000 else 0,
               "known_loss_est": -500.0 if c < 50000 else 0.0, "adverse_add_units": 100 if i == 2 else 0} for i, (d, c) in enumerate(zip(days, cash))]
    mt = {**ENV, "available": True,
          "ledger": {"available": True, "balance_sign": 1, "balance_sign_match_pct": 100.0, "first": days[0], "last": days[-1],
                     "ordering_ambiguous_days": 0, "ledger_gap_days": 2},
          "cash": {"start": 90000.0, "end": 95000.0, "min": 15000.0, "min_date": days[4], "days_below_threshold": 3, "days_negative": 0, "threshold": 50000.0, "info": {"definition": "c", "assumptions": []}},
          "cash_series": series,
          "debit_streaks": [{"start": days[1], "end": days[4], "days": 4, "net_outflow": 75000.0, "cash_at_end": 15000.0}],
          "exposure": {"peak_short_notional_proxy": 1009000.0, "avg_proxy_to_cash_ratio": 25.0, "estimated": True},
          "trap": {"days": 3, "lots_unmarked": 0, "info": {"definition": "t", "assumptions": []},
                   "days_list": [{"date": days[2], "cash": 30000.0, "open_losers_count": 1, "short_notional_proxy": 1002000.0, "proxy_to_cash_ratio": 33.4, "known_loss_est": -4000.0, "long_premium_at_risk": 0.0},
                                 {"date": days[3], "cash": 20000.0, "open_losers_count": 1, "short_notional_proxy": 1003000.0, "proxy_to_cash_ratio": 50.0, "known_loss_est": -7000.0, "long_premium_at_risk": 0.0}],
                   "loss_growth_est": {"symbols_n": 1, "first_trap_date": days[2], "loss_at_first_trap_est": -4000.0, "final_closed_pnl": -20000.0, "growth": -16000.0},
                   "adds_on_low_cash": {"fills": 3, "units": 250, "adverse_fills": 2, "adverse_units": 150}},
          "stops": {"definition": "stops", "assumptions": [], "long_closed_excluded": 4, "short_closed": 30,
                    "rows": [{"multiple": m, "n_exceeded": n, "realised_loss_exceeding": -ls, "saved_if_stopped": s, "share_of_total_loss_pct": 20.0 - m,
                              "open_beyond_n": 1, "open_beyond_excess_est": -300.0} for m, n, ls, s in ((1.0, 8, 9000.0, 6000.0), (1.5, 5, 5000.0, 3500.0), (2.0, 3, 2000.0, 1500.0))]}}

    def rule(rid, status, **kw):
        base = {"id": rid, "title": f"Server {rid}", "status": status, "parameter": {"name": "p", "value": 3, "unit": "fills", "lots": None},
                "threshold_basis": "75th percentile of your history", "what_if": None, "evidence": [{"label": "ev label", "value": 5, "source": "src"}],
                "caveats": ["caveat one"], "variants": []}
        base.update(kw)
        return base

    wi = {"baseline_pnl": -10000.0, "whatif_pnl": -6000.0, "delta": 4000.0, "trades_removed": 6, "units_removed": 600.0, "closed_trades_affected": 5,
          "open_units_vetoed": 0.0, "method": "m"}
    rules = [rule("max_trades_per_day", "applicable", what_if=wi), rule("no_averaging_down", "applicable", what_if=wi),
             rule("stop_discipline", "applicable", what_if=wi, variants=[{"multiple": 1.0, "saved_if_stopped": 1.0, "n_exceeded": 1}]),
             rule("expiry_proximity_entries", "not_triggered"), rule("bias_hedge_illustrative", "illustrative", parameter={"name": "offset", "value": 5000.0, "unit": "INR (estimate)", "lots": None}),
             rule("bias_limit", "insufficient_data", parameter=None, threshold_basis="too few closed trades")]
    sg = {**ENV, "available": True, "disclaimer": "Observations from your own imported history, not investment advice or a forecast.",
          "sample": {"closed_trades": 40, "min_required": 50}, "baseline_pnl": -10000.0, "rules": rules,
          "combined": {"rules_included": ["max_trades_per_day"], "what_if": wi, "stop_addon": 1500.0, "combined_with_stop": 5500.0, "definition": "c", "assumptions": []},
          "observations": [{"id": "o1", "text": "A plain observation.", "evidence": []}]}
    return {"foundation": {"available": False, "reason": "no_data", "quality": {}}, "overtrading": ot, "buildup": bu,
            "marketturn": {"available": False, "reason": "spot_unavailable", "quality": {}}, "margintrap": mt, "suggestions": sg}


API = ("export async function api(u){ const g=globalThis.__t; (g.calls ||= []).push(u);"
       " const ep=u.split('?')[0].split('/').pop(); const run=g.run;"
       " if (g.delay && g.delay[run]) await new Promise(r=>setTimeout(r,g.delay[run]));"
       " if (g.fail.has(ep)) throw new Error('boom');"
       " const pl=(g.payloadsByRun&&g.payloadsByRun[run])||g.payloads;"
       " const key={'margin-trap':'margintrap','market-turn':'marketturn'}[ep]||ep; return pl[key]; }")
STUBS = {
    "js/shared/utils.js": "export function setEl(id,h){ globalThis.__t.els[id]=h; }",
    "js/shared/charts.js": "export function mkChart(id,c){ const g=globalThis.__t; g.charts[id]=c; g.chartCalls.push(id); }"
                           " export function destroyChart(id){ delete globalThis.__t.charts[id]; }",
    "js/fno/trade-analysis.js": (
        "export const _esc=v=>String(v==null?'':v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');"
        "export const _num=(v,d=0)=>v==null?'—':Number(v).toLocaleString('en-IN',{minimumFractionDigits:d,maximumFractionDigits:d});"
        "export const _pnl=v=>v==null?'—':(v<0?'-':'+')+'₹'+Math.abs(v).toLocaleString('en-IN');"
        "export const taGetFilters=()=>globalThis.__t.filters;"),
    "js/fno/api.js": API,
}


@pytest.fixture(scope="module")
def out(tmp_path_factory) -> dict:
    d = tmp_path_factory.mktemp("p6js")
    (d / "package.json").write_text('{"type":"module"}')
    for rel, text in STUBS.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(text)
    (d / "js/fno/trade-analytics.js").write_text(JS)
    (d / "fixtures.json").write_text(json.dumps({"ok": _ok()}))
    (d / "harness.mjs").write_text(HARNESS.read_text())
    r = subprocess.run([NODE, "harness.mjs"], cwd=d, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


# ── helpers ────────────────────────────────────────────────────────────────────────────────

def test_iso_week_mondays_match_python(out):
    for key, m in out["mondays"]:
        y, w = key.split("-W")
        want = dt.date.fromisocalendar(int(y), int(w), 1)
        assert (m["y"], m["m"], m["d"]) == (want.year, want.month, want.day), key
    assert out["mondayBad"] is None
    assert dict((k, (m["y"], m["m"], m["d"])) for k, m in out["mondays"])["2026-W53"] == (2026, 12, 28)


def test_week_axis_labels_wk_numbers_and_gap_fill(out):
    ax = out["axis1"]
    assert [a["key"] for a in ax][0] == "2026-W32" and len(ax) == 3                    # W33 filled in
    assert ax[0]["label"] == ["Wk 1", "Aug 26"] and ax[1]["label"] == ["Wk 2"] and ax[2]["label"] == ["Wk 3"]
    assert ax[1]["fills"] == 0 and ax[1]["closed"] == 0                                # zero bar for the quiet week
    assert ax[0]["title"] == "Wk 1 · Aug 2026 (3-9 Aug 2026)"
    assert not any(re.search(r"W\d\d", " ".join(a["label"]) + a["title"]) for a in ax)  # no W32-style label anywhere


def test_week_axis_cross_month_and_year(out):
    cross = out["axisCross"]
    assert cross[0]["wk"] == 5 and cross[0]["month"] == "Jun" and cross[0]["label"] == ["Wk 5", "Jun 26"]
    assert cross[0]["title"] == "Wk 5 · Jun 2026 (29 Jun 2026 - 5 Jul 2026)"            # month of the Monday, range crosses months
    assert cross[1]["label"] == ["Wk 1", "Jul"] and cross[1]["wk"] == 1
    yr = out["axisYear"]
    assert [a["month"] for a in yr] == ["Dec", "Dec", "Jan"] and yr[1]["wk"] == 4
    assert yr[2]["label"] == ["Wk 1", "Jan 27"]                                         # year appended on January
    assert yr[1]["title"] == "Wk 4 · Dec 2026 (28 Dec 2026 - 3 Jan 2027)"
    assert out["axisEmpty"] == []


def test_week_axis_long_series_modes(out):
    ax = out["axis30"]                                     # > 26 weeks: month name on the first bar of a month only
    assert ax[0] == ["Dec 25"] and ["Jan 26"] in ax and ["Feb"] in ax and [""] in ax
    assert all(len(lbl) == 1 for lbl in ax) and not any("Wk" in lbl[0] for lbl in ax)
    m = out["axisMonthly"]                                 # > 104 weeks: one bar per month, sums preserved
    assert m["monthly"] and m["first"] == ["Jan 24"] and m["n"] == 26
    assert m["sumFills"] == m["inFills"] and m["firstTitle"] == "Jan 2024 (whole month)"


def test_compact_formatters_never_exceed_eight_chars(out):
    f = out["fmt"]
    for k in ("num", "pnl"):
        assert all(len(v) <= 8 for v in f[k]), (k, f[k])
    assert all(len(v) <= 8 for v in f["pct"] + f["ratio"])
    assert f["samples"] == ["12,345", "2.5L", "₹-12.3K", "₹-1.2L", "₹-1.2Cr", "₹950"]
    assert "—" in f["num"] and f["pct"][-1] == "—"


def test_cash_index_keeps_trap_and_add_days(out):
    assert out["cashIdx"]["small"] == 10
    big = out["cashIdx"]["big"]
    assert big["keeps501"] and big["keeps777"] and big["keepsLast"] and big["sorted"] and big["n"] < 700


# ── overtrading ───────────────────────────────────────────────────────────────────────────────

def test_overtrading_one_row_of_exactly_eight_widgets(out):
    o = out["ot"]
    assert o["rows"] == 1 and o["kpis"] == 8 and o["cq"] == 1 and o["titles"] == 9 and o["est"] == 1      # 8 widget hovers + the est. tag
    assert o["labels"] == ["Executions", "Active days", "Fills per active day", "Same-day in-and-out", "Charges vs gross P&amp;L",
                           "Trades to cover charges", "Win rate", "Avg win vs avg loss"]
    assert all(len(v) <= 8 for v in o["values"]), o["values"]
    assert o["values"][7] == "1.4x"


def test_overtrading_headline_and_notes(out):
    h = out["ot"]["headline"]
    assert "You placed 352 executions on 40 of 58 market days (typically 8 on an active day)." in h
    assert "42.50% of the quantity in your closed trades was opened and closed on the same day" in h
    assert "estimated charges equal 35.50% of your gross P&L" in h
    assert "7 fast bursts; 4 re-entries shortly after a loss" in out["ot"]["note"]
    assert "no market days" not in out["otVariants"] and "40 active days" in out["otVariants"]
    assert "paid while gross P&L was not positive" in out["otVariants"]


def test_weekly_chart_config(out):
    w = out["weekly"]
    assert w["type"] == "bar" and w["labelsIsArray"] and w["n"] == 11            # 10 weeks + the filled W31
    assert w["dataLens"] == [w["n"], w["n"]]                                      # position-indexed
    assert w["plugin"] == ["taMonthBands"] and len(w["groups"]) == w["n"]
    assert w["groups"][0] == 0 and w["groups"] == sorted(w["groups"])
    assert w["tip"].startswith("Wk 5 · Jun 2026") and w["after"] == ["3 active days"]
    s = out["sharedLabel"]                                                        # labels repeat across months ...
    assert s["a"] == s["b"] == ["Wk 2"] and s["n"] == 7                           # ... which is why data is position-indexed
    assert out["bands"] == 1                                                      # groups [0,0,1,1,1,2]: only the odd month is shaded


def test_holding_histogram(out):
    assert out["holding"] == {"has": True, "n": 4}
    assert out["holdingEmpty"] == {"chart": False, "msg": "No same-day trades"}


def test_unavailable_overtrading_puts_reason_in_headline(out):
    u = out["otUnavail"]
    assert "Import your Console files" in u["head"] and u["body"] == "" and u["charts"] is False


# ── build-up ──────────────────────────────────────────────────────────────────────────────────

def test_buildup_headline_picker_and_ladder(out):
    b = out["bu"]
    assert b["kpis"] == 4 and b["row"] == 1
    assert "12 of your 83 position chains were added to at a worse price." in b["head"]
    assert "Worst chain: NIFTYAAA (long) — you added 2 times, 1 at a worse price, the position peaked at 250 units (10.0 lots) and closed at -₹20,000." in b["head"]
    assert "30 of your 80 entries were adds to an existing position." in b["head"]
    assert b["picker"] == ["0", "1", "2"]                                           # chains with story_rank, not the 4th
    assert "NIFTYAAA" in b["pickerText"] and "NIFTYDDD" not in b["pickerText"]
    lad = out["ladder"]
    assert lad["stepped"] == "after" and lad["n"] == 4 and lad["sizes"] == [100, 200, 250, 0]     # always UNITS
    assert lad["colors"] == ["#8C877A", "#9B1C1C", "#1A6B3C", "#8C877A"]            # grey open, red adverse add, green add, grey close
    assert lad["closeSet"] and lad["closeLabel"].startswith("Closed:") and lad["label0"] == "Position size (units)"
    assert any("25.0% worse" in t for t in lad["tip"])
    assert any("200 units (8.0 lots)" in t for t in lad["tip"])                       # lots only in the hover text
    assert "Lots from the Kite master" not in out["bu"]["bodyHtml"] and "Lots unavailable" not in out["bu"]["bodyHtml"]
    assert out["ladder"]["yTitle"] == "units"


def test_chain_pick_rerenders_only_the_chart(out):
    p = out["pick"]
    assert p["calls"] == ["ta-cv-buildup"] and p["bodySame"] and p["n"] == 3
    assert [c for c in p["active"] if "active" in c[0]] == [["ta-chip active", "1"]]
    assert out["pickClamp"] == 4                                                     # index clamped to the last story chain


def test_buildup_truncation_note_and_fallbacks(out):
    assert "Showing 4 of 77 fills" in out["truncNote"]
    s = out["schematic"]
    assert s["labels"] == ["2026-08-03", "peak size", "2026-08-10"] and s["sizes"] == [0, 250, 0]
    assert "needs a newer server" in s["note"] and s["picker"] == 3
    assert out["noAdverse"]["head"].startswith("None of your 83 position chains were added to at a worse price.")
    assert out["noAdverse"]["picker"] == 3                                           # same top chains by P&L
    nc = out["noChains"]
    assert nc["head"] == "No position chains in this scope." and nc["chart"] is False and "No position chains to draw" in nc["note"]
    assert out["buUnavail"]["chart"] is False and out["buUnavail"]["picker"] == ""


# ── margin trap ───────────────────────────────────────────────────────────────────────────────

def test_margin_headline_caveat_widgets_no_table(out):
    m = out["mt"]
    assert m["rows"] == 1 and m["kpis"] == 5 and m["noTable"] and m["addsWidget"]
    h = m["head"]
    assert h.startswith("In the selected scope, on 3 days your account cash was below ₹50,000 while you held positions that were at a loss (estimate).")
    assert "On the first such day 1 positions showed about -₹4,000 of loss (estimate); the same positions closed at -₹20,000 in total." in h
    assert "you made 3 fills that added to a position, 2 of them at a worse price." in h and "(with or without open losers)" in h and "whole account" not in h
    assert "whole account" in out["mtFilter"]
    assert "Cash stayed above ₹50,000" in out["mtNoTrap"]
    assert "the same positions closed" not in out["mtNoGrowth"] and "on 3 days" in out["mtNoGrowth"]
    nl = out["mtNoLedger"]
    assert "Import your Console ledger" in nl["head"] and nl["chart"] is False and "kpi-row" not in nl["body"]


def test_margin_chart_series_and_bands(out):
    m = out["mt"]
    assert m["ds"] == ["Cash in your account (ledger)", "Low-cash level", "Short option exposure (estimate)", "Added at a worse price"]
    assert m["scales"] == ["x", "y", "y1"] and m["plugin"] == ["taDayBands"] and m["labels"] == 10
    assert m["bands"]["low"] == [2, 3, 4] and m["bands"]["streaks"] == [[1, 4]]
    assert m["addPts"][2] == 30000.0 and sum(v is not None for v in m["addPts"]) == 1
    assert m["tipAdd"][0] == "added 100 units at a worse price" and "1 open losers" in m["tipAdd"][1]
    assert m["labelsText"][0] == "03 Aug"


def test_margin_degrades_without_additive_fields(out):
    o = out["mtOld"]
    assert o["ds"] == ["Cash in your account (ledger)", "Low-cash level"] and o["scales"] == ["x", "y"]
    assert o["widget"] is False and o["kpis"] == 4
    assert "You added" not in o["head"]
    big = out["mtBig"]
    assert big["n"] < 900 and big["hasAdd"]


# ── details tables ────────────────────────────────────────────────────────────────────────────

def test_table_a_groups_and_worst_first(out):
    a = out["A"]
    assert a["groups"] == ["By underlying", "By expiry month", "By side"] and a["cols"] == 5 and a["foot"] and a["colNotes"]
    cells = a["firstCells"]
    assert cells[:3] == ["By underlying", "BANKNIFTY", "NIFTY"]                       # worst P&L first inside the group
    assert cells.index("2026-09") < cells.index("2026-08") < cells.index("2026-07")
    assert cells.index("short") < cells.index("long")


def _pnl_of(txt: str) -> float:
    return float(txt.replace("₹", "").replace(",", "").replace("+", ""))


def test_table_b_merges_sorts_and_states_overlap(out):
    b = out["B"]
    assert b["title"] and b["overlap"] and b["noTotal"] and b["n"] == 10 and b["more"] == "Show all 12"
    assert set(b["rows"]) == {"Fast burst", "Position", "Low-cash day"}
    vals = [_pnl_of(t) for t in out["Bsort"]]
    assert vals == sorted(vals)                                                       # ascending: most negative first
    assert vals[0] == -20000.0
    assert out["B2"]["n"] == 12 and out["B2"]["btn"]


def test_table_b_drop_rule(out):
    d = out["drop"]
    assert d["lowCash"] == 1                         # estimated row with null P&L dropped
    assert d["bursts"] == 6                          # measured burst with null P&L is kept (shown as a dash)


def test_failure_matrix_and_cache_reset(out):
    f = out["failMt"]
    assert "low-cash days could not be loaded" in f["B"] and ">Low-cash day<" not in f["B"]
    assert "Stop what-if saving" not in f["summary"] and "Stop what-if table could not be loaded" in f["grid"]
    assert "could not be loaded" in f["margin"] and f["chart"] is False
    s = out["failSg"]
    assert s["grid"] == "" and "could not be loaded" in s["body"] and s["A"] and s["B"] and s["ot"]    # Behaviour fully renders
    assert "could not be loaded" in out["failOt"]["A"] and "bursts could not be loaded" in out["failOt"]["B"]
    assert "could not be loaded" in out["failAll"]["A"] and out["failAll"]["B"] == '<div class="kpi-sub">— could not be loaded</div>'
    assert out["stale"] == {"before": True, "after": False}                            # no rows left over from the previous run


def test_stale_response_does_not_overwrite_newer_render(out):
    assert "222" in out["stale2"]["head"] and "111" not in out["stale2"]["head"]


def test_full_tables_lazy_and_single_stops_builder(out):
    assert out["fullClosed"] == ""
    f = out["full"]
    assert f["tables"] == 11 and f["titles"] == 11 and f["isoWeek"]
    assert f["stopHeads"] == 6 and f["note"] and f["badge"]
    assert len(re.findall(r"function _stopsTable\(", JS)) == 1                           # one builder, two call sites
    assert len(re.findall(r"_stopsTable\(", JS)) == 3


# ── suggestions ───────────────────────────────────────────────────────────────────────────────

def test_suggestions_grid_one_card_per_rule(out):
    s = out["sg"]
    assert s["n"] == 6 and s["ids"] == ["max_trades_per_day", "no_averaging_down", "stop_discipline", "expiry_proximity_entries",
                                        "bias_hedge_illustrative", "bias_limit"]
    assert s["app"] and s["notTrig"] and s["ill"] and s["insuf"]
    assert s["titles"][:3] == ["Daily entry cap", "Averaging down", "Stop at a multiple of premium"]
    assert "Observations (1)" in s["obs"] and s["disc"]
    assert "3 applicable · 1 not triggered" in s["counts"]
    assert "Planned vs actual stops." in s["def"]                                         # Definition moved here
    assert "applied to your history" in s["head"]


def test_collapsed_summary_has_no_detail_and_stop_table_is_in_the_expanded_body(out):
    assert not any(c["sumHasEvidence"] for c in out["sgBody"]) and all(c["bodyHasEvidence"] for c in out["sgBody"])
    sc = out["stopCard"]
    assert sc == {"heads": 6, "note": True, "badge": True, "inBody": True, "colNotes": True}
    assert out["stopsWidget"] is True
    assert out["sgNoStops"] == {"widget": False, "variants": True}                         # margin-trap missing -> rule variants fallback
    assert out["sgUnavail"]["grid"] == "" and "Observations from your own imported history" in out["sgUnavail"]["body"]


def test_open_state_survives_refresh_and_resets_on_scope_change(out):
    assert out["open1"] == 1 and out["open2"] == ["bias_limit"]
    assert out["openAfterScope"] == 0
    assert out["expanded"] == 6 and out["collapsed"] == 0


def test_unknown_rule_id_falls_back_to_server_text(out):
    assert out["unknown"] == {"title": True, "basis": True}


def test_every_new_string_is_escaped_img_onerror(out):
    x = out["xss"]
    assert not x["rawImg"] and not x["rawAttr"] and not x["onerrorTag"]
    assert x["escapedImg"] and x["chartLabelsPlain"]


def test_only_the_six_gets_are_called(out):
    assert all("spot-vs-pnl" not in u for u in out["urls"])
    assert len({u.split("?")[0] for u in out["urls"]}) == 6


def test_no_taswitchtab_dependency():
    assert "taSwitchTab" not in JS.split("export async function loadAnalyticsPanels")[1][:3000]


def test_review_followups(out):
    r = out["review"]
    assert r["expiryHead"].count("closed only by the expiry estimate") == 1 and r["expiryMarker"].startswith("Closed by expiry estimate")
    assert r["gridDuringLoad"] > 100 and r["gridAfterNullCollapse"] == r["gridDuringLoad"]        # Expand/Collapse no-op while loading
    assert r["rendererThrowDetails"] == "ok" and r["statusSet"]                                # joined views guarded; status still written
    assert r["stopCopy"] == "1.00x, 1.50x, 2.00x"
    assert r["pnlShort"] == ["₹-99.9Cr", "₹-100Cr", "₹100Cr"] and all(len(v) <= 8 for v in r["pnlShort"])
    assert "&amp;amp;" not in r["titles"]
