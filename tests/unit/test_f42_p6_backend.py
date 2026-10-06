"""F42 P6 — additive backend fields (chain story, margin-trap per-day extras), config validators, ordering parity,
copy-coverage against the server rule ids, and the committed P5 sample data through the REAL import.
Synthetic data only (invented symbols, round numbers); never touches live-data/."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from rita.config import TradeAnalysisSettings
from rita.schemas import fno_trade_analytics as sch
from rita.services import fno_trade_analytics as an
from rita.services import fno_trade_suggestions as sg
from tests.unit.f42_p3_helpers import D, cfg, ctx, fill, spot

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "dashboard/js/fno/trade-analytics.js").read_text()
W = dict(date_from="2026-10-01", date_to="2026-10-12")
SYM2 = dict(symbol="BANKNIFTY26OCT50000CE", underlying="BANKNIFTY", strike=50000.0)


# ── config validators ──────────────────────────────────────────────────────────────────

def test_config_defaults_and_bounds():
    c = TradeAnalysisSettings()
    assert (c.chain_story_top_n, c.chain_steps_max) == (3, 40)
    for bad in ({"chain_story_top_n": 0}, {"chain_story_top_n": 6}, {"chain_steps_max": 4}, {"chain_steps_max": 101}):
        with pytest.raises(ValidationError):
            TradeAnalysisSettings(**bad)
    ok = TradeAnalysisSettings(chain_story_top_n=5, chain_steps_max=100)
    assert (ok.chain_story_top_n, ok.chain_steps_max) == (5, 100)
    assert TradeAnalysisSettings(chain_story_top_n=1, chain_steps_max=5).chain_steps_max == 5


def test_base_yaml_carries_the_keys_and_loads():
    import yaml

    y = yaml.safe_load((ROOT / "config/base.yaml").read_text())
    blk = next(v for v in y.values() if isinstance(v, dict) and "burst_window_minutes" in v)
    assert blk["chain_story_top_n"] == 3 and blk["chain_steps_max"] == 40
    TradeAnalysisSettings(**blk)      # the whole block validates (extra=forbid would fail on an unknown key)


# ── chain story ──────────────────────────────────────────────────────────────────────────

def _book_two_chains():
    # chain A (NIFTY): 3 adds (2 adverse), closes at a loss; chain B (BANKNIFTY): small win
    a = [fill("buy", 100, 20.0, "2026-10-01"), fill("buy", 100, 15.0, "2026-10-02", "10:00"),
         fill("buy", 50, 18.0, "2026-10-03", "10:00"), fill("sell", 250, 10.0, "2026-10-06", "10:00")]
    b = [fill("buy", 20, 100.0, "2026-10-02", "11:00", **SYM2), fill("sell", 20, 110.0, "2026-10-03", "11:00", **SYM2)]
    return a + b


def _bu(fills, lots=None, **cfgkw):
    return an.buildup(ctx(fills, c=cfg(**cfgkw) if cfgkw else None, **W), lots or an.LotInfo())


def test_chains_additive_fields_and_ordering():
    b = _bu(_book_two_chains())
    ch = b["chains"]
    assert [c["symbol"] for c in ch] == ["NIFTY26OCT24000CE", "BANKNIFTY26OCT50000CE"]      # pnl ascending
    assert all(isinstance(c["pnl_measured"], float) for c in ch)                               # verified: never None
    assert [c["story_rank"] for c in ch] == [1, 2]
    a = ch[0]
    assert a["steps_total"] == 4 and a["steps_truncated"] is False and len(a["steps"]) == 4
    s = a["steps"]
    assert [x["cls"] for x in s] == ["open_new", "scale_in", "scale_in", "close"]
    assert [x["pos_after"] for x in s] == [100, 200, 250, 0]
    assert [x["qty_delta"] for x in s] == [100, 100, 50, -250]
    assert [x["adverse"] for x in s] == [False, True, False, False]       # 15.0 < avg 20.0 is adverse; 18.0 > avg 17.5 is not
    assert s[1]["avg_before"] == 20.0 and s[1]["worse_pct"] == 25.0
    assert s[0]["date"] == "2026-10-01" and s[0]["time"] == "10:00"
    assert a["peak_lots"] is None and all(x["lots_after"] is None for x in s)                   # no LotInfo
    assert b["averaging"]["adverse_add_lots"] is None


def test_lots_per_symbol_and_none_when_any_symbol_unknown():
    full = an.LotInfo(True, {"NIFTY26OCT24000CE": 25, "BANKNIFTY26OCT50000CE": 10}, {})
    b = _bu(_book_two_chains(), full)
    a = b["chains"][0]
    assert a["peak_lots"] == 10.0 and [x["lots_after"] for x in a["steps"]] == [4.0, 8.0, 10.0, 0.0]
    assert b["averaging"]["adverse_add_lots"] == 4.0               # one adverse add of 100 units / 25
    partial = an.LotInfo(True, {"NIFTY26OCT24000CE": 25}, {})
    b2 = _bu(_book_two_chains(), partial)
    assert b2["chains"][0]["peak_lots"] == 10.0 and b2["chains"][1]["peak_lots"] is None
    assert b2["averaging"]["adverse_add_lots"] == 4.0              # the adverse adds all sit in the known symbol
    none_known = an.LotInfo(True, {"BANKNIFTY26OCT50000CE": 10}, {})
    assert _bu(_book_two_chains(), none_known)["averaging"]["adverse_add_lots"] is None   # no partial sum


def test_steps_only_for_top_n_chains_and_cap_keeps_first_last_adverse():
    fills = []
    for i in range(5):    # five tiny single-symbol chains, distinct symbols, distinct losses
        sym = f"NIFTY26OCT{24000 + i * 100}CE"
        fills += [fill("buy", 10, 100.0, "2026-10-01", symbol=sym, strike=24000.0 + i * 100),
                  fill("sell", 10, 100.0 - (i + 1), "2026-10-02", symbol=sym, strike=24000.0 + i * 100)]
    b = _bu(fills, chain_story_top_n=2)
    assert [c["story_rank"] for c in b["chains"]] == [1, 2, None, None, None]
    assert all(c["steps"] == [] and c["steps_total"] is None for c in b["chains"][2:])
    assert all(len(c["steps"]) == 2 for c in b["chains"][:2])

    big = [fill("buy", 10, 100.0, "2026-10-01", "09:15")]
    px = 100.0
    for k in range(60):          # 60 adds; every 7th one is adverse (price drops), others improve slightly
        px = px - 1.0 if k % 7 == 0 else px + 0.01
        big.append(fill("buy", 1, px, "2026-10-02", f"{9 + k // 60:02d}:{k % 60:02d}"))
    big.append(fill("sell", 70, 90.0, "2026-10-03", "10:00"))
    b2 = _bu(big, chain_steps_max=10)
    c = b2["chains"][0]
    assert c["steps_total"] == 62 and c["steps_truncated"] is True and len(c["steps"]) == 10
    assert c["steps"][0]["cls"] == "open_new" and c["steps"][-1]["cls"] == "close"
    advs = [x for x in c["steps"] if x["adverse"]]
    assert advs and all(x["worse_pct"] is not None for x in advs)
    keys = [(x["date"], x["time"]) for x in c["steps"]]
    assert keys == sorted(keys)                                    # chronological


def test_pick_steps_budget_and_adverse_priority():
    flags = [False] * 30
    for i in (3, 9, 15, 21):
        flags[i] = True
    idx = an._pick_steps(flags, 8)
    assert idx[0] == 0 and idx[-1] == 29 and len(idx) == 8 and {3, 9, 15, 21} <= set(idx)
    many = [True] * 30
    idx2 = an._pick_steps(many, 6)
    assert idx2[0] == 0 and idx2[-1] == 29 and len(idx2) == 6 and idx2 == sorted(idx2)
    assert an._pick_steps([False] * 5, 40) == [0, 1, 2, 3, 4]


def test_chain_sort_key_nulls_last_and_tiebreaks():
    base = {"symbol": "B", "open_date": D("2026-10-02"), "_order": 1, "pnl_measured": -5.0}
    rows = [
        {**base, "symbol": "Z", "pnl_measured": None, "_order": 0},
        {**base, "symbol": "B"},
        {**base, "symbol": "A", "open_date": D("2026-10-03")},
        {**base, "symbol": "A", "open_date": D("2026-10-01"), "_order": 9},
        {**base, "pnl_measured": -9.0, "symbol": "Q"},
    ]
    got = [(r["symbol"], r["open_date"].isoformat(), r["pnl_measured"]) for r in sorted(rows, key=an.chain_sort_key)]
    assert got == [("Q", "2026-10-02", -9.0), ("A", "2026-10-01", -5.0), ("A", "2026-10-03", -5.0),
                   ("B", "2026-10-02", -5.0), ("Z", "2026-10-02", None)]
    tie = [{**base, "_order": 3}, {**base, "_order": 1}]
    assert [r["_order"] for r in sorted(tie, key=an.chain_sort_key)] == [1, 3]


def test_flip_steps_split_into_old_chain_close_and_new_chain_open():
    b = _bu([fill("buy", 100, 10.0, "2026-10-01"), fill("sell", 150, 12.0, "2026-10-02", "10:00"),
             fill("buy", 50, 11.0, "2026-10-03", "10:00")])
    old = next(c for c in b["chains"] if c["side"] == "long")
    new = next(c for c in b["chains"] if c["side"] == "short")
    assert [x["pos_after"] for x in old["steps"]] == [100, 0] and old["steps"][-1]["qty_delta"] == -100
    assert old["steps"][-1]["cls"] == "flip"
    assert new["steps"][0]["cls"] == "flip" and new["steps"][0]["qty_delta"] == -50 and new["steps"][0]["pos_after"] == -50
    assert new["steps"][0]["avg_before"] is None


# ── margin trap per-day extras ──────────────────────────────────────────────────────────

LED = [("2026-10-01", 0, 100000, 100000), ("2026-10-02", 60000, 0, 40000),
       ("2026-10-03", 10000, 0, 30000), ("2026-10-06", 5000, 0, 25000)]


def _margin():
    book = [fill("sell", 100, 10.0, "2026-10-02", "10:00"), fill("sell", 10, 14.0, "2026-10-03", "10:00"),
            fill("buy", 110, 18.0, "2026-10-07", "10:00")]
    sp = spot(NIFTY=[(d, 24000.0) for d in ("2026-10-01", "2026-10-02", "2026-10-03", "2026-10-06", "2026-10-07")])
    leds = [an.LedgerRow(D(d), deb, cred, nb, i) for i, (d, deb, cred, nb) in enumerate(LED)]
    return an.margin_trap(ctx(book, sp=sp, **W), leds, None)


def test_cash_series_extras_and_adds_on_low_cash_hand_computed():
    m = _margin()
    by = {r["date"]: r for r in m["cash_series"]}
    r3 = by["2026-10-03"]
    # 10-03: second SELL 10 @ 14 vs avg 10 => an adverse add for a short, cash 30000 < 50000, 1 open loser
    assert r3["adverse_add_units"] == 10 and r3["open_losers_count"] == 1
    assert r3["short_notional_proxy"] == 110 * 24000.0 and r3["known_loss_est"] < 0
    assert by["2026-10-02"]["adverse_add_units"] == 0 and by["2026-10-02"]["open_losers_count"] == 0
    assert all({"short_notional_proxy", "open_losers_count", "known_loss_est", "adverse_add_units"} <= set(r)
               for r in m["cash_series"])
    assert m["trap"]["adds_on_low_cash"] == {"fills": 1, "units": 10, "adverse_fills": 1, "adverse_units": 10}
    # schema accepts and types the new fields
    parsed = sch.MarginTrapResponse.model_validate({"available": True, **m})
    assert parsed.trap.adds_on_low_cash.adverse_units == 10 and parsed.cash_series[2].adverse_add_units == 10


def test_adds_on_low_cash_counts_only_days_below_threshold():
    book = [fill("sell", 100, 10.0, "2026-10-02", "10:00"), fill("sell", 10, 14.0, "2026-10-03", "10:00")]
    leds = [an.LedgerRow(D(d), deb, cred, nb, i) for i, (d, deb, cred, nb) in enumerate(LED)]
    hi = an.margin_trap(ctx(book, c=cfg(low_cash_threshold_inr=20000.0), **W), leds, None)    # nothing below 20000
    assert hi["trap"]["adds_on_low_cash"] == {"fills": 0, "units": 0, "adverse_fills": 0, "adverse_units": 0}
    assert {r["date"]: r["adverse_add_units"] for r in hi["cash_series"]}["2026-10-03"] == 10   # per-day field still set


def test_no_ledger_leaves_adds_on_low_cash_absent_and_schema_none():
    m = an.margin_trap(ctx([fill("sell", 10, 10.0, "2026-10-02")], **W), [], None)
    assert m["ledger"]["available"] is False and "adds_on_low_cash" not in m["trap"]
    assert sch.MarginTrapResponse.model_validate({"available": True, **m}).trap.adds_on_low_cash is None
    old = sch.CashPoint.model_validate({"date": "2026-10-01", "cash": 5.0})
    assert old.short_notional_proxy is None and old.adverse_add_units == 0 and old.open_losers_count == 0


def test_schema_defaults_keep_old_clients_valid():
    row = sch.ChainRow.model_validate({"symbol": "X", "side": "long"})
    assert row.steps == [] and row.story_rank is None and row.steps_truncated is False and row.peak_lots is None
    assert sch.AveragingBlock().adverse_add_lots is None


# ── copy coverage vs server rule ids ───────────────────────────────────────────────────────

def _js_copy_ids() -> set[str]:
    blk = re.search(r"const _RULE_COPY = \{(.*?)\n\};", JS, re.S).group(1)
    return set(re.findall(r"^\s{2}([a-z_]+):\s*\[", blk, re.M))


def test_rule_copy_keys_equal_server_rule_ids():
    assert _js_copy_ids() == set(sg.RULE_IDS)


def test_every_literal_rule_id_in_the_server_module_is_declared():
    src = (ROOT / "src/rita/services/fno_trade_suggestions.py").read_text()
    used = set(re.findall(r'(?:_rule|insufficient|finish)\(\s*"([a-z_]+)"', src))
    assert used <= set(sg.RULE_IDS), used - set(sg.RULE_IDS)
    assert set(sg.SPOT_RULE_IDS) <= set(sg.RULE_IDS)


# ── the committed P5 sample data through the REAL import ───────────────────────────────────

@pytest.fixture(scope="module")
def sample_panels():
    from tests.unit.f42_p5_helpers import load_files, new_db, panels, seed_spot

    db = new_db()
    try:
        seed_spot(db)
        load_files(db, "u-p6")
        yield {k: v.model_dump() for k, v in panels(db, "u-p6", include_est=True).items()}
    finally:
        db.close()


def test_sample_buildup_has_story_chains_with_steps(sample_panels):
    b = sample_panels["buildup"]
    assert b["available"] and b["chains"]
    ranked = [c for c in b["chains"] if c["story_rank"] is not None]
    assert [c["story_rank"] for c in ranked] == list(range(1, len(ranked) + 1)) and 1 <= len(ranked) <= 3
    for c in ranked:
        assert c["steps"] and c["steps_total"] >= len(c["steps"]) and c["steps"][0]["date"]
        assert isinstance(c["pnl_measured"], float)
    assert all(c["steps"] == [] for c in b["chains"] if c["story_rank"] is None)
    pnls = [c["pnl_measured"] for c in b["chains"]]
    assert pnls == sorted(pnls)
    assert b["averaging"]["adverse_add_fills"] >= 0 and "adverse_add_lots" in b["averaging"]


def test_sample_margin_trap_series_and_trap_block(sample_panels):
    m = sample_panels["margin-trap"]
    assert m["ledger"]["available"] and m["cash_series"]
    assert any(r["short_notional_proxy"] for r in m["cash_series"])
    t = m["trap"]
    assert t["adds_on_low_cash"] is not None and set(t["adds_on_low_cash"]) == {"fills", "units", "adverse_fills", "adverse_units"}
    low_days = {r["date"] for r in m["cash_series"] if r["cash"] is not None and r["cash"] < m["cash"]["threshold"]}
    assert t["days"] <= len(low_days)
    assert m["stops"]["rows"]
    assert sum(r["adverse_add_units"] for r in m["cash_series"]) <= sample_panels["buildup"]["averaging"]["adverse_add_units"]


def test_sample_overtrading_feeds_the_axis_and_tables(sample_panels):
    o = sample_panels["overtrading"]
    assert o["available"] and o["weekly"] and all(re.fullmatch(r"\d{4}-W\d{2}", w["week"]) for w in o["weekly"])
    assert o["by_underlying"] and o["by_expiry"] and o["winloss"]["by_side"]
    assert o["holding"]["buckets"] is not None


def test_sample_rule_ids_are_all_in_the_copy_map(sample_panels):
    rules = sample_panels["suggestions"]["rules"]
    assert rules and {r["id"] for r in rules} <= _js_copy_ids()
