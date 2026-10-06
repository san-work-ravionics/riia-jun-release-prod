"""F42 P6 — independent QA probes (written by QA, not the Engineer; does not duplicate test_f42_p6_*).

Oracles here are re-implemented from the design (task brief section 17) with datetime/isocalendar, a plain FIFO
simulation and string/regex scans, so a shared bug in the product code cannot hide behind the same helper.
Synthetic data and the committed P5 sample CSVs only (through the real import); never reads live-data/.

Confirmed defects are strict xfails (they fail loudly when fixed):
  QA-1 compact formatters exceed the 8-character widget rule at rounding boundaries (negative values).
  QA-2 negative zero renders as "-0" / "₹-0" for tiny negative values.
"""
from __future__ import annotations

import datetime as dt
import json
import random
import re
import shutil
import subprocess
import sys
import types
from collections import defaultdict, deque
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JS_PATH = ROOT / "dashboard/js/fno/trade-analytics.js"
JS = JS_PATH.read_text()
HTML = (ROOT / "dashboard/fno.html").read_text()
MAIN_JS = (ROOT / "dashboard/js/fno/main.js").read_text()
HARNESS = Path(__file__).with_name("f42_p6_qa_harness.mjs")
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node not installed")

MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _baseline_rev() -> str:
    """The pre-P6 (P5-merged) revision: the commit just before the P6 feature commit, robust to the P6 merge commit."""
    for rev in ("bcfef7f", "HEAD~1"):
        r = subprocess.run(["git", "-C", str(ROOT), "show", f"{rev}:src/rita/services/fno_trade_analytics.py"], capture_output=True, text=True)
        if r.returncode == 0 and "chain_sort_key" not in r.stdout:
            return rev
    return "HEAD~1"


BASE_REV = _baseline_rev()
DISCLAIMER = "Observations from your own imported history, not investment advice or a forecast."


# ══════════════════════════════════════════════════════════════════════════════════════════
# Independent oracles
# ══════════════════════════════════════════════════════════════════════════════════════════

def all_iso_weeks(y0: int = 2024, y1: int = 2028) -> list[tuple[int, int]]:
    out = []
    for y in range(y0, y1 + 1):
        last = dt.date(y, 12, 28).isocalendar()[1]          # 28 Dec is always in the last ISO week
        out += [(y, w) for w in range(1, last + 1)]
    return out


def wk_key(y: int, w: int) -> str:
    return f"{y}-W{w:02d}"


def monday(y: int, w: int) -> dt.date:
    return dt.date.fromisocalendar(y, w, 1)


def exp_range(m: dt.date) -> str:
    e = m + dt.timedelta(days=6)
    if (m.year, m.month) == (e.year, e.month):
        return f"{m.day}-{e.day} {MON[m.month - 1]} {m.year}"
    return f"{m.day} {MON[m.month - 1]} {m.year} - {e.day} {MON[e.month - 1]} {e.year}"


def exp_weekly_axis(rows: dict[tuple[int, int], tuple[int, int, int]]) -> list[dict]:
    """Expected gap-filled weekly axis (<= 104 weeks) per design 5.3 / 17.5-A4."""
    mons = sorted(monday(*k) for k in rows)
    first, last = mons[0], mons[-1]
    bars, d = [], first
    while d <= last:
        iso = d.isocalendar()
        f, c, a = rows.get((iso[0], iso[1]), (0, 0, 0))
        bars.append({"monday": d, "fills": f, "closed": c, "active": a,
                     "wk": (d.day - 1) // 7 + 1, "month": MON[d.month - 1]})
        d += dt.timedelta(days=7)
    long = len(bars) > 26
    for i, b in enumerate(bars):
        p = bars[i - 1]["monday"] if i else None
        new = p is None or (p.year, p.month) != (b["monday"].year, b["monday"].month)
        mon = f"{b['month']} {b['monday'].year % 100:02d}" if (i == 0 or b["monday"].month == 1) and new else b["month"]
        b["label"] = ([mon if new else ""] if long else ([f"Wk {b['wk']}", mon] if new else [f"Wk {b['wk']}"]))
        b["title"] = f"Wk {b['wk']} · {b['month']} {b['monday'].year} ({exp_range(b['monday'])})"
    return bars


def exp_monthly_axis(rows: dict[tuple[int, int], tuple[int, int, int]]) -> list[dict]:
    agg: dict[tuple[int, int], list[int]] = defaultdict(lambda: [0, 0, 0])
    for k, (f, c, a) in rows.items():
        m = monday(*k)
        t = agg[(m.year, m.month)]
        t[0] += f
        t[1] += c
        t[2] += a
    ks = sorted(agg)
    lo, hi = ks[0][0] * 12 + ks[0][1] - 1, ks[-1][0] * 12 + ks[-1][1] - 1
    out = []
    for k in range(lo, hi + 1):
        y, m = divmod(k, 12)
        m += 1
        f, c, a = agg.get((y, m), [0, 0, 0])
        out.append({"key": f"{y}-{m:02d}", "fills": f, "closed": c, "active": a,
                    "label": [f"{MON[m - 1]} {y % 100:02d}"], "title": f"{MON[m - 1]} {y} (whole month)"})
    return out


class Ev:
    __slots__ = ("sym", "date", "time", "cls", "delta", "after", "price", "avg_before", "adverse", "worse", "opened", "realised", "chain")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))


def simulate(fills: list[dict]) -> list[Ev]:
    """Plain FIFO: fills = [{sym, sign, qty, price, date, time, oid, tid}] in any order; returns events in time order.
    Classes: open_new / scale_in / scale_out / close / flip; adverse = scale_in worse than the average of the open lots."""
    key = lambda f: (f["date"], f["date"] + "T" + f["time"], f["oid"], f["tid"], f["sym"])   # noqa: E731
    books: dict[str, deque] = {}
    side: dict[str, int] = {}
    evs: list[Ev] = []
    for f in sorted(fills, key=key):
        lots = books.setdefault(f["sym"], deque())
        sd = side.get(f["sym"], 0) if lots else 0
        pos_before = sum(q for q, _ in lots) * sd
        avg_before = (sum(q * p for q, p in lots) / sum(q for q, _ in lots)) if lots else None
        closed = opened = 0
        real = 0.0
        rem = f["qty"]
        if lots and sd != f["sign"]:
            while rem > 0 and lots:
                q, p = lots[0]
                take = min(rem, q)
                real += sd * (f["price"] - p) * take
                closed += take
                rem -= take
                if take == q:
                    lots.popleft()
                else:
                    lots[0] = (q - take, p)
        adverse = False
        if rem > 0:
            if lots and sd == f["sign"]:
                adverse = f["sign"] * (f["price"] - avg_before) < 0
            lots.append((rem, f["price"]))
            side[f["sym"]] = f["sign"]
            opened = rem
        after = sum(q for q, _ in lots) * side.get(f["sym"], 0)
        if closed == 0:
            cls = "open_new" if pos_before == 0 else "scale_in"
        elif opened > 0:
            cls = "flip"
        elif after == 0:
            cls = "close"
        else:
            cls = "scale_out"
        evs.append(Ev(sym=f["sym"], date=f["date"], time=f["time"], cls=cls, delta=after - pos_before, after=after, price=f["price"],
                      avg_before=avg_before, adverse=adverse, opened=opened, realised=real,
                      worse=(abs(f["price"] - avg_before) / avg_before * 100 if adverse else None)))
    return evs


def gen_book(rng: random.Random, n_syms: int = 4, n_fills: int = 160, flips: bool = False, start: str = "2026-07-06") -> list[dict]:
    """Random no-flip book (unless flips=True): each fill gets a unique minute so ordering is unambiguous."""
    d0 = dt.date.fromisoformat(start)
    pos = {f"NIFTY26OCT{24000 + 100 * i}CE": 0 for i in range(n_syms)}
    fills = []
    for n in range(n_fills):
        sym = rng.choice(list(pos))
        day = d0 + dt.timedelta(days=n // 8)
        tm = f"{9 + (n % 8) * 1:02d}:{15 + (n % 40):02d}"
        p = pos[sym]
        px = round(rng.uniform(40, 160), 2)
        if p == 0:
            sign = rng.choice((1, -1))
            qty = rng.randint(1, 20)
        elif rng.random() < 0.55:
            sign = 1 if p > 0 else -1
            qty = rng.randint(1, 20)
        else:
            sign = -1 if p > 0 else 1
            qty = rng.randint(1, abs(p) + (rng.randint(1, 5) if flips else 0)) if rng.random() < 0.9 else abs(p)
            if not flips:
                qty = min(qty, abs(p))
        pos[sym] = p + sign * qty
        fills.append({"sym": sym, "sign": sign, "qty": qty, "price": px, "date": day.isoformat(), "time": tm, "oid": f"O{n:04d}", "tid": f"T{n:04d}"})
    return fills


def to_fills(book: list[dict]):
    from tests.unit.f42_p3_helpers import fill
    out = []
    for b in book:
        strike = float(re.search(r"(\d+)CE", b["sym"]).group(1))
        out.append(fill("buy" if b["sign"] > 0 else "sell", b["qty"], b["price"], b["date"], b["time"], symbol=b["sym"],
                        strike=strike, oid=b["oid"], tid=b["tid"]))
    return out


def oracle_chains(evs: list[Ev]) -> list[dict]:
    """Group simulated events into flat-to-flat chains (flip fill closes one chain and opens the next)."""
    chains, cur = [], {}
    for e in evs:
        c = cur.get(e.sym)
        if c is None:
            c = cur[e.sym] = {"sym": e.sym, "evs": [], "pnl": 0.0, "order": len(chains), "open_date": e.date}
            chains.append(c)
        c["evs"].append(e)
        c["pnl"] += e.realised
        if e.cls == "close":
            del cur[e.sym]
        elif e.cls == "flip":
            del cur[e.sym]
            n = cur[e.sym] = {"sym": e.sym, "evs": [e], "pnl": 0.0, "order": len(chains), "open_date": e.date}
            chains.append(n)
    chains.sort(key=lambda c: (c["pnl"], c["sym"], c["open_date"], c["order"]))
    return chains


def build_new(book, lots=None, **cfgkw):
    from rita.services import fno_trade_analytics as an
    from tests.unit.f42_p3_helpers import cfg, ctx
    c = cfg(**cfgkw) if cfgkw else None
    return an.buildup(ctx(to_fills(book), c=c, date_from="2026-07-01", date_to="2026-10-05"), lots or an.LotInfo())


# ══════════════════════════════════════════════════════════════════════════════════════════
# 1. Config validators and base.yaml parity
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_config_bounds_exhaustive_sweep():
    from pydantic import ValidationError
    from rita.config import TradeAnalysisSettings as S
    for n in range(-3, 12):
        if 1 <= n <= 5:
            assert S(chain_story_top_n=n).chain_story_top_n == n
        else:
            with pytest.raises(ValidationError):
                S(chain_story_top_n=n)
    for n in list(range(-2, 12)) + [50, 99, 100, 101, 1000]:
        if 5 <= n <= 100:
            assert S(chain_steps_max=n).chain_steps_max == n
        else:
            with pytest.raises(ValidationError):
                S(chain_steps_max=n)


@pytest.mark.parametrize("field,bad", [("chain_story_top_n", 2.5), ("chain_steps_max", 40.5), ("chain_story_top_n", "many"),
                                       ("chain_steps_max", None), ("chain_story_top_n", [3])])
def test_config_rejects_non_integer_values(field, bad):
    from pydantic import ValidationError
    from rita.config import TradeAnalysisSettings as S
    with pytest.raises(ValidationError):
        S(**{field: bad})


@pytest.mark.parametrize("env", ["development", "staging", "production"])
def test_yaml_load_parity_for_every_environment(env, monkeypatch):
    """base.yaml + env overlay -> the F42 block validates and carries the defaults (3, 40) unless explicitly overridden."""
    from rita import config as cfgmod
    monkeypatch.setenv("RITA_ENV", env)
    merged = cfgmod.Settings._load_yaml_config()
    block = merged["trade_analysis"]
    s = cfgmod.TradeAnalysisSettings(**block)
    assert (s.chain_story_top_n, s.chain_steps_max) == (3, 40)
    for f in ("chain_story_top_n", "chain_steps_max"):
        assert cfgmod.TradeAnalysisSettings.model_fields[f].default == block[f]       # code default == yaml default


@pytest.mark.parametrize("key,val", [("chain_story_top_n", 0), ("chain_story_top_n", 6), ("chain_steps_max", 4), ("chain_steps_max", 101)])
def test_invalid_value_in_yaml_fails_config_load(key, val, monkeypatch, tmp_path):
    import yaml
    from pydantic import ValidationError
    from rita import config as cfgmod
    base = yaml.safe_load((ROOT / "config/base.yaml").read_text())
    base["trade_analysis"][key] = val
    (tmp_path / "base.yaml").write_text(yaml.safe_dump(base))
    monkeypatch.setattr(cfgmod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setenv("RITA_ENV", "nonexistent-env")
    merged = cfgmod.Settings._load_yaml_config()
    with pytest.raises(ValidationError):
        cfgmod.Settings(**merged)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 2. Chain steps: ordering / truncation properties (synthetic fills against an independent FIFO)
# ══════════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("seed", range(12))
def test_pick_steps_properties(seed):
    from rita.services import fno_trade_analytics as an
    rng = random.Random(seed)
    for _ in range(150):
        n = rng.randint(1, 260)
        budget = rng.randint(5, 100)
        dens = rng.choice((0.0, 0.05, 0.3, 0.9, 1.0))
        flags = [rng.random() < dens for _ in range(n)]
        idx = an._pick_steps(flags, budget)
        assert idx == sorted(set(idx)) and all(0 <= i < n for i in idx)
        if n <= budget:
            assert idx == list(range(n))
            continue
        assert len(idx) == budget                                   # budget filled exactly when anything is dropped
        assert idx[0] == 0 and idx[-1] == n - 1
        adv_mid = [i for i in range(1, n - 1) if flags[i]]
        if len(adv_mid) <= budget - 2:
            assert set(adv_mid) <= set(idx)                          # every adverse add kept when it fits
        else:
            assert set(idx) - {0, n - 1} <= set(adv_mid)             # over budget: only adverse adds (thinned) remain
        # determinism
        assert an._pick_steps(list(flags), budget) == idx


@pytest.mark.parametrize("seed", range(8))
@pytest.mark.parametrize("budget", [5, 6, 9, 40])
def test_chain_steps_match_independent_fifo(seed, budget):
    rng = random.Random(1000 + seed)
    book = gen_book(rng, n_syms=3, n_fills=150)
    b = build_new(book, chain_story_top_n=5, chain_steps_max=budget)
    chains = oracle_chains(simulate(book))
    svc = b["chains"]
    assert b["chain_totals"]["count"] == len(chains)
    # ordering: first TOP_N*2 by (pnl, symbol, open_date, creation), compared on pnl (rounded) and symbol
    want = chains[:len(svc)]
    for s, o in zip(svc, want):
        assert s["pnl_measured"] == pytest.approx(round(o["pnl"], 2), abs=0.011)
    pn = [s["pnl_measured"] for s in svc]
    assert pn == sorted(pn)
    assert [s["story_rank"] for s in svc] == [i + 1 if i < 5 else None for i in range(len(svc))]
    for s in svc:
        if s["story_rank"] is None:
            assert s["steps"] == [] and s["steps_total"] is None and s["steps_truncated"] is False
            continue
        o = next(c for c in chains if c["sym"] == s["symbol"] and c["evs"][0].date == s["open_date"]
                 and (c["evs"][0].date, c["evs"][0].time) == (s["steps"][0]["date"], s["steps"][0]["time"]))
        evs = o["evs"]
        assert s["steps_total"] == len(evs)
        keys = [(x["date"], x["time"]) for x in s["steps"]]
        assert keys == sorted(set(keys)) and len(keys) <= budget
        assert keys[0] == (evs[0].date, evs[0].time) and keys[-1] == (evs[-1].date, evs[-1].time)     # first and last always kept
        assert s["steps_truncated"] == (len(s["steps"]) < len(evs))
        by = {(e.date, e.time): e for e in evs}
        for x in s["steps"]:
            e = by[(x["date"], x["time"])]
            assert x["cls"] == e.cls and x["adverse"] == e.adverse
            assert x["price"] == pytest.approx(e.price, abs=1e-4)
            if e.adverse:
                assert x["worse_pct"] == pytest.approx(e.worse, abs=0.011) and x["avg_before"] == pytest.approx(e.avg_before, abs=1e-3)
            else:
                assert x["worse_pct"] is None
        adv_mid = [(e.date, e.time) for e in evs[1:-1] if e.adverse]
        if len(adv_mid) <= budget - 2:
            assert set(adv_mid) <= set(keys)
        if len(evs) > budget:
            assert len(keys) == budget
        else:
            # untruncated: exact match of every field with the oracle
            assert [x["qty_delta"] for x in s["steps"]] == [e.delta for e in evs] or any(e.cls == "flip" for e in evs)
            assert [x["pos_after"] for x in s["steps"]] == [e.after for e in evs] or any(e.cls == "flip" for e in evs)


def test_chain_order_and_steps_independent_of_input_order():
    rng = random.Random(7)
    book = gen_book(rng, n_syms=4, n_fills=120)
    first = build_new(book, chain_story_top_n=5)
    shuffled = book[:]
    random.Random(99).shuffle(shuffled)
    again = build_new(shuffled, chain_story_top_n=5)
    assert first["chains"] == again["chains"] and first["averaging"] == again["averaging"]


def test_equal_pnl_chains_tie_break_by_symbol_then_open_date():
    from tests.unit.f42_p3_helpers import fill
    mk = lambda sym, day, strike: [fill("buy", 10, 100.0, day, "10:00", symbol=sym, strike=strike),     # noqa: E731
                                   fill("sell", 10, 90.0, day, "11:00", symbol=sym, strike=strike)]
    fills = (mk("NIFTY26OCT24300CE", "2026-10-02", 24300.0) + mk("NIFTY26OCT24100CE", "2026-10-05", 24100.0)
             + mk("NIFTY26OCT24200CE", "2026-10-01", 24200.0))
    from rita.services import fno_trade_analytics as an
    from tests.unit.f42_p3_helpers import ctx
    b = an.buildup(ctx(fills, date_from="2026-10-01", date_to="2026-10-12"), an.LotInfo())
    syms = [c["symbol"] for c in b["chains"]]
    assert [c["pnl_measured"] for c in b["chains"]] == [-100.0] * 3
    assert syms == sorted(syms) and [c["story_rank"] for c in b["chains"]] == [1, 2, 3]


def test_zero_fill_book_and_single_fill_chain():
    from rita.services import fno_trade_analytics as an
    from tests.unit.f42_p3_helpers import ctx, fill
    one = an.buildup(ctx([fill("buy", 5, 10.0, "2026-10-02")], date_from="2026-10-01", date_to="2026-10-12"), an.LotInfo())
    c = one["chains"][0]
    assert c["still_open"] and c["steps_total"] == 1 and len(c["steps"]) == 1 and c["steps_truncated"] is False
    assert c["steps"][0]["cls"] == "open_new" and c["steps"][0]["avg_before"] is None


# ══════════════════════════════════════════════════════════════════════════════════════════
# 3. peak_lots / adverse_add_lots None semantics
# ══════════════════════════════════════════════════════════════════════════════════════════

def _lots_book():
    from tests.unit.f42_p3_helpers import fill
    b = [fill("buy", 100, 20.0, "2026-10-01"), fill("buy", 100, 15.0, "2026-10-02", "10:00"), fill("sell", 200, 12.0, "2026-10-05", "10:00"),
         fill("sell", 30, 50.0, "2026-10-02", "11:00", symbol="BANKNIFTY26OCT50000CE", underlying="BANKNIFTY", strike=50000.0),
         fill("sell", 30, 60.0, "2026-10-03", "11:00", symbol="BANKNIFTY26OCT50000CE", underlying="BANKNIFTY", strike=50000.0),
         fill("buy", 60, 40.0, "2026-10-06", "11:00", symbol="BANKNIFTY26OCT50000CE", underlying="BANKNIFTY", strike=50000.0)]
    return b


def _bu_lots(lots):
    from rita.services import fno_trade_analytics as an
    from tests.unit.f42_p3_helpers import ctx
    return an.buildup(ctx(_lots_book(), date_from="2026-10-01", date_to="2026-10-12"), lots)


def test_lots_semantics_matrix():
    from rita.services.fno_trade_analytics import LotInfo
    N, B = "NIFTY26OCT24000CE", "BANKNIFTY26OCT50000CE"
    cases = {
        "unavailable": (LotInfo(), None, None, None),
        "available_empty_maps": (LotInfo(True, {}, {}), None, None, None),
        "flag_false_with_data": (LotInfo(False, {N: 25, B: 10}, {}), None, None, None),
        "zero_size_symbol": (LotInfo(True, {N: 0, B: 10}, {}), None, 6.0, None),
        "partial_symbol_map": (LotInfo(True, {N: 25}, {}), 8.0, None, None),
        "underlying_fallback": (LotInfo(True, {}, {"NIFTY": 25, "BANKNIFTY": 10}), 8.0, 6.0, 4.0 + 3.0),
        "full": (LotInfo(True, {N: 25, B: 10}, {}), 8.0, 6.0, 4.0 + 3.0),
    }
    for name, (lots, peak_n, peak_b, adv_lots) in cases.items():
        b = _bu_lots(lots)
        by = {c["symbol"]: c for c in b["chains"]}
        assert by[N]["peak_lots"] == peak_n, name
        assert by[B]["peak_lots"] == peak_b, name
        assert b["averaging"]["adverse_add_lots"] == adv_lots, name
        for c in by.values():
            assert all((s["lots_after"] is None) == (c["peak_lots"] is None) for s in c["steps"]), name


def test_adverse_add_lots_with_no_adverse_adds():
    from rita.services.fno_trade_analytics import LotInfo
    from rita.services import fno_trade_analytics as an
    from tests.unit.f42_p3_helpers import ctx, fill
    fills = [fill("buy", 100, 20.0, "2026-10-01"), fill("buy", 50, 25.0, "2026-10-02", "10:00")]      # a better-priced add only
    assert an.buildup(ctx(fills, date_from="2026-10-01", date_to="2026-10-12"), LotInfo(True, {"NIFTY26OCT24000CE": 25}, {}))["averaging"]["adverse_add_lots"] == 0.0
    assert an.buildup(ctx(fills, date_from="2026-10-01", date_to="2026-10-12"), LotInfo())["averaging"]["adverse_add_lots"] is None


# ══════════════════════════════════════════════════════════════════════════════════════════
# 4. Backward compatibility: additive fields only; old payload shapes still parse; old values unchanged
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_old_payload_shapes_still_validate():
    from rita.schemas import fno_trade_analytics as sch
    chain = sch.ChainRow.model_validate({"symbol": "X", "expiry_ym": "2026-10", "side": "long", "open_date": "2026-10-01", "close_date": None,
                                         "peak_qty": 10, "adds": 1, "adverse_adds": 0, "pnl_measured": -5.0, "pnl_estimated": None, "still_open": True})
    assert chain.steps == [] and chain.story_rank is None and chain.peak_lots is None and chain.steps_truncated is False
    cp = sch.CashPoint.model_validate({"date": "2026-10-01", "cash": 1.0, "carried": False})
    assert (cp.short_notional_proxy, cp.open_losers_count, cp.known_loss_est, cp.adverse_add_units) == (None, 0, None, 0)
    tb = sch.TrapBlock.model_validate({"days": 2, "days_list": [], "loss_growth_est": None, "lots_unmarked": 0})
    assert tb.adds_on_low_cash is None
    av = sch.AveragingBlock.model_validate({"adverse_add_fills": 1, "adverse_add_units": 5})
    assert av.adverse_add_lots is None
    # new payload round-trips through the JSON the API serialises
    st = sch.ChainStep.model_validate({"date": "2026-10-01", "cls": "open_new"})
    assert st.qty_delta == 0 and st.adverse is False and st.lots_after is None


NEW_KEYS_CHAIN = {"peak_lots", "story_rank", "steps", "steps_total", "steps_truncated"}
NEW_KEYS_CASH = {"short_notional_proxy", "open_losers_count", "known_loss_est", "adverse_add_units"}


def _strip_new(kind: str, o: dict) -> dict:
    o = json.loads(json.dumps(o, default=str))
    if kind == "buildup":
        for c in o["chains"]:
            for k in NEW_KEYS_CHAIN:
                c.pop(k, None)
        o["averaging"].pop("adverse_add_lots", None)
    else:
        for r in o["cash_series"]:
            for k in NEW_KEYS_CASH:
                r.pop(k, None)
        o["trap"].pop("adds_on_low_cash", None)
    return o


@pytest.fixture(scope="module")
def baseline_an():
    """The pre-P6 analytics module executed from git (parent of the P6 commit) under a private name."""
    try:
        src = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE_REV}:src/rita/services/fno_trade_analytics.py"],
                             capture_output=True, text=True, check=True).stdout
    except Exception:       # pragma: no cover - no git / shallow clone
        pytest.skip("baseline revision not available")
    if "chain_sort_key" in src:
        pytest.skip("HEAD~1 is not the pre-P6 baseline")
    mod = types.ModuleType("rita.services.fno_trade_analytics_baseline")
    sys.modules[mod.__name__] = mod
    exec(compile(src, "fno_trade_analytics_baseline.py", "exec"), mod.__dict__)    # noqa: S102
    yield mod
    sys.modules.pop(mod.__name__, None)


def _old_ctx(old, book):
    from tests.unit.f42_p3_helpers import cfg, fifo
    res = fifo(to_fills(book), "2026-07-01", "2026-10-05", None)
    return old.make_ctx(res, cfg(), dt.date(2026, 7, 1), dt.date(2026, 10, 5), True, {})


@pytest.mark.parametrize("seed", range(5))
def test_existing_buildup_values_unchanged_vs_baseline(baseline_an, seed):
    book = gen_book(random.Random(300 + seed), n_syms=4, n_fills=140)
    old = baseline_an.buildup(_old_ctx(baseline_an, book), baseline_an.LotInfo())
    new = build_new(book)
    assert _strip_new("buildup", new) == json.loads(json.dumps(old, default=str))


@pytest.mark.parametrize("seed", range(3))
def test_existing_overtrading_unchanged_vs_baseline(baseline_an, seed):
    from rita.services import fno_trade_analytics as an
    from tests.unit.f42_p3_helpers import ctx
    book = gen_book(random.Random(400 + seed), n_syms=3, n_fills=120)
    old = baseline_an.overtrading(_old_ctx(baseline_an, book), [])
    new = an.overtrading(ctx(to_fills(book), date_from="2026-07-01", date_to="2026-10-05"), [])
    assert json.loads(json.dumps(new, default=str)) == json.loads(json.dumps(old, default=str))


def _ledger_for(book, rng, lo_hi=(150000, 300000)):
    from rita.services.fno_trade_analytics import LedgerRow
    d0, d1 = dt.date(2026, 7, 1), dt.date(2026, 10, 5)
    rows, bal, i, d = [], float(rng.randint(*lo_hi)), 0, d0
    rows.append(LedgerRow(d0, 0.0, bal, bal, 0))
    d += dt.timedelta(days=1)
    while d <= d1:
        amt = float(rng.randint(500, 9000))
        if rng.random() < 0.52:
            bal -= amt
            rows.append(LedgerRow(d, amt, 0.0, bal, i := i + 1))
        else:
            bal += amt
            rows.append(LedgerRow(d, 0.0, amt, bal, i := i + 1))
        d += dt.timedelta(days=1)
    return rows


@pytest.mark.parametrize("seed", range(3))
def test_existing_margin_trap_values_unchanged_vs_baseline(baseline_an, seed):
    from rita.services import fno_trade_analytics as an
    from tests.unit.f42_p3_helpers import ctx
    rng = random.Random(500 + seed)
    book = gen_book(rng, n_syms=3, n_fills=100)
    led = _ledger_for(book, rng)
    old_led = [baseline_an.LedgerRow(r.posting_date, r.debit, r.credit, r.net_balance, r.seq) for r in led]
    old = baseline_an.margin_trap(_old_ctx(baseline_an, book), old_led, None)
    new = an.margin_trap(ctx(to_fills(book), date_from="2026-07-01", date_to="2026-10-05"), led, None)
    assert _strip_new("margin", new) == json.loads(json.dumps(old, default=str))


def test_only_the_dashboard_module_consumes_the_p6_payloads():
    hits = []
    for base in ("src", "dashboard", "mobileapp", "scripts"):
        for p in (ROOT / base).rglob("*"):
            if p.suffix in {".py", ".js", ".html", ".mjs"} and p.is_file():
                t = p.read_text(errors="ignore")
                if re.search(r"cash_series|chain_totals|analytics/buildup|analytics/margin-trap", t):
                    hits.append(p.relative_to(ROOT).as_posix())
    assert set(hits) <= {"src/rita/schemas/fno_trade_analytics.py", "src/rita/services/fno_trade_analytics.py",
                         "src/rita/services/fno_trade_suggestions.py", "dashboard/js/fno/trade-analytics.js"}, hits


# ══════════════════════════════════════════════════════════════════════════════════════════
# 5. Margin-trap extras and adds_on_low_cash, recomputed independently
# ══════════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("seed", range(6))
def test_adds_on_low_cash_recomputed_from_independent_simulation(seed):
    from rita.services import fno_trade_analytics as an
    from tests.unit.f42_p3_helpers import cfg, ctx
    rng = random.Random(900 + seed)
    book = gen_book(rng, n_syms=3, n_fills=130)
    led = _ledger_for(book, rng)
    cash = {r.posting_date.isoformat(): r.net_balance for r in led}
    span = sorted(b["date"] for b in book)
    in_span = sorted(v for d, v in cash.items() if span[0] <= d <= span[-1])
    thr = max(in_span[len(in_span) // 2], 1.0)                                  # about half of the trading days are below the level
    m = an.margin_trap(ctx(to_fills(book), c=cfg(low_cash_threshold_inr=thr), date_from="2026-07-01", date_to="2026-10-05"), led, None)
    by_day = {r["date"]: r for r in m["cash_series"]}
    adds = [e for e in simulate(book) if e.cls == "scale_in"]
    adv_day: dict[str, int] = defaultdict(int)
    for e in adds:
        if e.adverse:
            adv_day[e.date] += e.opened
    for d, r in by_day.items():
        assert r["adverse_add_units"] == adv_day.get(d, 0), d
        assert r["cash"] == pytest.approx(cash[d], abs=0.01)
    low = {"fills": 0, "units": 0, "adverse_fills": 0, "adverse_units": 0}
    for e in adds:
        if e.date in by_day and cash[e.date] < thr:
            low["fills"] += 1
            low["units"] += e.opened
            if e.adverse:
                low["adverse_fills"] += 1
                low["adverse_units"] += e.opened
    assert m["trap"]["adds_on_low_cash"] == low
    t = m["trap"]["adds_on_low_cash"]
    assert t["adverse_fills"] <= t["fills"] and t["adverse_units"] <= t["units"] and t["units"] >= t["fills"]
    assert t["adverse_units"] == sum(r["adverse_add_units"] for d, r in by_day.items() if cash[d] < thr)
    assert low["fills"] > 0 and low["adverse_fills"] > 0            # the generator really exercises both paths


def test_sample_csv_margin_extras_match_independent_recompute():
    """P5 sample CSVs through the real import vs a plain-python FIFO + ledger read of the same files."""
    import csv
    from tests.unit.f42_p5_helpers import SAMPLE_DIR, NAMES, load_files, new_db, panels, seed_spot, TODAY
    db = new_db()
    try:
        seed_spot(db)
        load_files(db, "u-qa-sample")
        p = {k: v.model_dump() for k, v in panels(db, "u-qa-sample", include_est=True).items()}
    finally:
        db.close()
    m, b = p["margin-trap"], p["buildup"]
    fills = []
    with (SAMPLE_DIR / NAMES["tradebook"]).open(newline="") as fh:
        for r in csv.DictReader(fh):
            fills.append({"sym": r["symbol"], "sign": 1 if r["trade_type"] == "buy" else -1, "qty": int(r["quantity"]), "price": float(r["price"]),
                          "date": r["trade_date"], "time": r["order_execution_time"][11:], "oid": r["order_id"], "tid": r["trade_id"]})
    evs = simulate(fills)
    ledger: dict[str, float] = {}
    with (SAMPLE_DIR / NAMES["ledger"]).open(newline="") as fh:
        for r in csv.DictReader(fh):
            ledger[r["posting_date"]] = float(r["net_balance"])          # last row of the day wins (one row per day in the sample)
    series = m["cash_series"]
    days = [r["date"] for r in series]
    carried, last = {}, None
    for d in sorted(set(days) | set(ledger)):
        last = ledger.get(d, last)
        carried[d] = last
    for r in series:
        assert r["cash"] == pytest.approx(carried[r["date"]], abs=0.01), r["date"]
    thr = m["cash"]["threshold"]
    adds = [e for e in evs if e.cls == "scale_in" and e.date in set(days)]
    exp = {"fills": 0, "units": 0, "adverse_fills": 0, "adverse_units": 0}
    per_day: dict[str, int] = defaultdict(int)
    for e in adds:
        if e.adverse:
            per_day[e.date] += e.opened
        if carried[e.date] < thr:
            exp["fills"] += 1
            exp["units"] += e.opened
            if e.adverse:
                exp["adverse_fills"] += 1
                exp["adverse_units"] += e.opened
    assert m["trap"]["adds_on_low_cash"] == exp
    assert {r["date"]: r["adverse_add_units"] for r in series if r["adverse_add_units"]} == dict(per_day)
    # whole-sample averaging block agrees with the simulation too
    adv_all = [e for e in evs if e.cls == "scale_in" and e.adverse and dt.date.fromisoformat(e.date) >= dt.date(2026, 7, 1)]
    assert b["averaging"]["adverse_add_fills"] == len(adv_all) and b["averaging"]["adverse_add_units"] == sum(e.opened for e in adv_all)
    assert TODAY.isoformat() >= max(days)


def test_sample_chain_steps_agree_with_independent_chains():
    import csv
    from tests.unit.f42_p5_helpers import SAMPLE_DIR, NAMES, load_files, new_db, panels, seed_spot
    db = new_db()
    try:
        seed_spot(db)
        load_files(db, "u-qa-sample2")
        b = panels(db, "u-qa-sample2", include_est=True)["buildup"].model_dump()
    finally:
        db.close()
    fills = []
    with (SAMPLE_DIR / NAMES["tradebook"]).open(newline="") as fh:
        for r in csv.DictReader(fh):
            fills.append({"sym": r["symbol"], "sign": 1 if r["trade_type"] == "buy" else -1, "qty": int(r["quantity"]), "price": float(r["price"]),
                          "date": r["trade_date"], "time": r["order_execution_time"][11:], "oid": r["order_id"], "tid": r["trade_id"]})
    chains = oracle_chains(simulate(fills))
    assert b["chain_totals"]["count"] == len(chains)
    ranked = [c for c in b["chains"] if c["story_rank"]]
    assert [c["story_rank"] for c in ranked] == [1, 2, 3]
    for s in ranked:
        o = next(c for c in chains if c["sym"] == s["symbol"] and c["evs"][0].date == s["open_date"])
        assert s["steps_total"] == len(o["evs"]) and len(s["steps"]) == min(len(o["evs"]), 40)
        assert s["steps"][0]["date"] == o["evs"][0].date and s["steps"][-1]["date"] == o["evs"][-1].date
        assert sum(1 for x in s["steps"] if x["adverse"]) == sum(1 for e in o["evs"] if e.adverse)    # all kept (<= 40 steps)
        assert s["pnl_measured"] == pytest.approx(o["pnl"], abs=0.02)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 6. Node harness: shared fixture (the Engineer's synthetic payload builder is reused as DATA only)
# ══════════════════════════════════════════════════════════════════════════════════════════

QA_UTILS = "export function setEl(id,h){ const g=globalThis.__t; g.els[id]=h; g.writes=(g.writes||0)+1; }"


def _weeks_inputs():
    wk = all_iso_weeks()
    gen = random.Random(5)
    sets = []
    for start in (0, 1, 13, 26, 51, 52, 53, 100, 150):                                   # 104-week windows at many offsets
        win = wk[start:start + 104]
        if len(win) == 104:
            sets.append((f"win104@{start}", {k: (i + 1, i % 4, (i % 5) + 1) for i, k in enumerate(win)}))
    for start, length in ((0, 20), (48, 12), (100, 27), (0, 26), (3, 1), (50, 30), (200, 5)):   # short, 26/27 boundary, year ends
        win = wk[start:start + length]
        sets.append((f"win{length}@{start}", {k: (i + 1, i % 3, (i % 5) + 1) for i, k in enumerate(win)}))
    for n in range(4):                                                                     # sparse random subsets (gap fill)
        pick = sorted(gen.sample(wk[:104], 30))
        sets.append((f"sparse{n}", {k: (gen.randint(1, 90), gen.randint(0, 9), gen.randint(1, 5)) for k in pick}))
    sets.append(("span104", {wk[0]: (1, 1, 1), wk[103]: (2, 2, 2)}))                       # exactly 104 weeks apart -> weekly
    sets.append(("span105", {wk[0]: (1, 1, 1), wk[104]: (2, 2, 2)}))                       # 105 weeks -> monthly
    sets.append(("full2024_2028", {k: (i + 1, i % 4, (i % 5) + 1) for i, k in enumerate(wk)}))
    sets.append(("y2026_w53", {(2026, 52): (3, 1, 2), (2026, 53): (4, 2, 3), (2027, 1): (5, 3, 4)}))
    sets.append(("y2025_w01_boundary", {(2024, 52): (3, 1, 2), (2025, 1): (4, 2, 3), (2025, 2): (5, 3, 4)}))
    return sets, wk


CHART_WEEKS = [(2026, w) for w in range(27, 45) if w not in (31, 36, 40)]          # 15 rows over 18 weeks, 4 months -> labels repeat


def _fmt_values():
    vals = [None, "__NaN__", "__Inf__", "__-Inf__", 0, -0.0, 0.4, -0.4, 0.5, 1, -1]
    for e in range(0, 13):
        for mant in (1, 1.04, 1.5, 2.34, 5, 7.77, 9.9, 9.99):
            v = mant * 10 ** e
            vals += [v, -v]
    vals += [99999, -99999, 100000, -100000, 99950, -99950, 12345678, -12345678, 123456.78, -123456.78, 1e10, -1e10, 5e15, -5e15]
    # rounding boundaries (known defect area)
    vals += [99999.6, -99999.6, 999999000, -999999000, 9999.96, -9999.96, 99.96, -99.96]
    return vals


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    if NODE is None:
        pytest.skip("node not installed")
    from tests.unit.test_f42_p6_js import STUBS, _ok
    d = tmp_path_factory.mktemp("p6qa")
    (d / "package.json").write_text('{"type":"module"}')
    stubs = dict(STUBS)
    stubs["js/shared/utils.js"] = QA_UTILS
    for rel, text in stubs.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(text)
    (d / "js/fno/trade-analytics.js").write_text(JS)
    sets, wk = _weeks_inputs()
    chart_weeks = [[wk_key(*k), (i + 1) * 3, i % 4, (i % 5) + 1] for i, k in enumerate(CHART_WEEKS)]
    inputs = {
        "weekSets": [{"name": n, "rows": [[wk_key(*k), *v] for k, v in rows.items()]} for n, rows in sets],
        "allWeeks": [wk_key(*k) for k in wk],
        "fmtValues": _fmt_values(),
        "chartWeeks": chart_weeks,
    }
    (d / "fixtures.json").write_text(json.dumps({"ok": _ok()}))
    (d / "inputs.json").write_text(json.dumps(inputs))
    (d / "harness.mjs").write_text(HARNESS.read_text())
    r = subprocess.run([NODE, "harness.mjs"], cwd=d, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr[-3000:]
    out = json.loads(r.stdout.strip().splitlines()[-1])
    out["_sets"] = {n: rows for n, rows in sets}
    return out


# ── 6a. week -> month mapping over every ISO week 2024-2028 ─────────────────────────────────────

@needs_node
def test_every_iso_week_monday_matches_isocalendar(harness):
    got = dict((k, v) for k, v in harness["mondays"])
    assert len(got) == len(all_iso_weeks()) and any(k.endswith("W53") for k in got)
    for (y, w) in all_iso_weeks():
        m = monday(y, w)
        assert got[wk_key(y, w)] == [m.year, m.month, m.day], (y, w)
    assert got["2026-W53"] == [2026, 12, 28] and got["2025-W01"] == [2024, 12, 30] and got["2026-W01"] == [2025, 12, 29]


@needs_node
def test_week_axis_matches_independent_implementation_on_every_window(harness):
    checked = 0
    for ax in harness["axes"]:
        rows = harness["_sets"][ax["name"]]
        if ax["name"] in ("span105", "full2024_2028"):
            continue
        mons = sorted(monday(*k) for k in rows)
        n_weeks = (mons[-1] - mons[0]).days // 7 + 1
        assert n_weeks <= 104, ax["name"]
        exp = exp_weekly_axis(rows)
        got = ax["axis"]
        assert len(got) == len(exp) == n_weeks, ax["name"]
        for g, e in zip(got, exp):
            assert (g["y"], g["m"], g["d"]) == (e["monday"].year, e["monday"].month, e["monday"].day), ax["name"]
            assert g["wk"] == e["wk"] and g["month"] == e["month"], (ax["name"], e["monday"])
            assert g["label"] == e["label"] and g["title"] == e["title"], (ax["name"], e["monday"])
            assert (g["fills"], g["closed"], g["active_days"]) == (e["fills"], e["closed"], e["active"]), (ax["name"], e["monday"])
            assert not g["monthly"]
            assert not re.search(r"\bW\d", " ".join(g["label"]) + g["title"])
        # (year, month, Wk n) is unique and a month's Wk numbers run contiguously from 1 where the month is fully inside the window
        seen = [(g["y"], g["m"], g["wk"]) for g in got]
        assert len(seen) == len(set(seen)), ax["name"]
        if all(a["fills"] or True for a in got) and n_weeks == len(rows):
            by_month = defaultdict(list)
            for g in got:
                by_month[(g["y"], g["m"])].append(g["wk"])
            ms = sorted(by_month)
            for k in ms[1:-1]:
                v = by_month[k]
                assert v == list(range(1, len(v) + 1)) and 4 <= len(v) <= 5, (ax["name"], k, v)
        checked += 1
    assert checked >= 20


@needs_node
def test_week_axis_gap_filling_inserts_zero_weeks_only_for_missing(harness):
    for ax in harness["axes"]:
        if not ax["name"].startswith("sparse"):
            continue
        rows = harness["_sets"][ax["name"]]
        present = {wk_key(*k) for k in rows}
        for g in ax["axis"]:
            if g["key"] in present:
                continue
            assert (g["fills"], g["closed"], g["active_days"]) == (0, 0, 0)
        assert sum(g["fills"] for g in ax["axis"]) == sum(v[0] for v in rows.values())
        assert len(ax["axis"]) > len(rows)


@needs_node
def test_week_axis_switches_to_monthly_aggregation_above_104_weeks(harness):
    by = {a["name"]: a for a in harness["axes"]}
    assert not by["span104"]["axis"][0]["monthly"] and len(by["span104"]["axis"]) == 104
    for name in ("span105", "full2024_2028"):
        rows = harness["_sets"][name]
        exp = exp_monthly_axis(rows)
        got = by[name]["axis"]
        assert len(got) == len(exp) and all(g["monthly"] for g in got), name
        for g, e in zip(got, exp):
            assert (g["key"], g["label"], g["title"]) == (e["key"], e["label"], e["title"]), name
            assert (g["fills"], g["closed"], g["active_days"]) == (e["fills"], e["closed"], e["active"]), (name, e["key"])
        assert sum(g["fills"] for g in got) == sum(v[0] for v in rows.values())          # nothing lost or double counted
        assert len({g["key"] for g in got}) == len(got)


@needs_node
def test_week_axis_filing_rule_week_straddling_months_goes_to_mondays_month(harness):
    by = {a["name"]: a for a in harness["axes"]}
    ax = by["y2026_w53"]["axis"]
    assert [a["month"] for a in ax] == ["Dec", "Dec", "Jan"] and [a["wk"] for a in ax] == [3, 4, 1]     # Monday 28 Dec is Wk 4 (22nd-28th)
    assert ax[1]["title"] == "Wk 4 · Dec 2026 (28 Dec 2026 - 3 Jan 2027)"
    assert ax[2]["label"] == ["Wk 1", "Jan 27"]                                           # year shown on the January bar
    ax2 = by["y2025_w01_boundary"]["axis"]
    assert ax2[1]["title"] == "Wk 5 · Dec 2024 (30 Dec 2024 - 5 Jan 2025)" and ax2[1]["label"] == ["Wk 5"]
    assert ax2[2]["label"] == ["Wk 1", "Jan 25"]


@needs_node
def test_invalid_week_keys_return_null_and_never_throw(harness):
    assert harness["mondayBad"] == [None] * 8


# ── 6b. position-indexed chart data with repeated labels ──────────────────────────────────────────

@needs_node
def test_weekly_chart_data_is_position_indexed_and_labels_may_repeat(harness):
    c = harness["chart"]
    n = len(c["labels"])
    assert n == len(c["fills"]) == len(c["closed"]) == len(c["groups"]) == len(c["titles"]) == 18
    assert c["ticksAutoSkip"] is False and "taMonthBands" in c["hasPlugin"]
    assert len({"|".join(lab) for lab in c["labels"]}) < n                                 # repeated label text really occurs
    for i in range(n):
        assert c["titles"][i].startswith(c["labels"][i][0]) or c["labels"][i][0] == ""     # first line carries Wk n (or empty on long axes)
    # values follow the gap-filled week order, never the label text
    rows = {k: ((i + 1) * 3, i % 4, (i % 5) + 1) for i, k in enumerate(CHART_WEEKS)}
    exp = exp_weekly_axis(rows)
    assert len(exp) == 18 and c["fills"][4] == 0 and c["fills"][9] == 0         # gap weeks are zero bars
    if True:
        assert c["fills"] == [e["fills"] for e in exp] and c["closed"] == [e["closed"] for e in exp]
        assert c["titles"] == [e["title"] for e in exp]
        assert c["after"] == [f"{e['active']} active days" for e in exp]
        month_ids = []
        for e in exp:
            k = (e["monday"].year, e["monday"].month)
            if not month_ids or month_ids[-1][0] != k:
                month_ids.append([k, len(month_ids)])
            e["g"] = month_ids[-1][1]
        assert c["groups"] == [e["g"] for e in exp]


# ── 6c. compact formatter property sweep ──────────────────────────────────────────────────────────

def _fmt_rows(harness):
    return [(v, n, p, pc, r) for v, n, p, pc, r in harness["fmt"]]


def _parse_short(s: str) -> float | None:
    t = s.replace("₹", "").replace(",", "")
    m = re.fullmatch(r"(-?)(\d+(?:\.\d+)?)(K|L|Cr)?", t)
    if not m:
        return None
    mult = {None: 1, "K": 1e3, "L": 1e5, "Cr": 1e7}[m.group(3)]
    return (-1 if m.group(1) else 1) * float(m.group(2)) * mult


BOUNDARY_VALUES = [99999.6, -99999.6, 999999000, -999999000, 9999.96, -9999.96, 99.96, -99.96]


@needs_node
def test_formatters_never_exceed_8_chars_away_from_rounding_boundaries(harness):
    bad = []
    for v, n, p, pc, r in _fmt_rows(harness):
        if v in BOUNDARY_VALUES:
            continue
        for kind, s in (("num", n), ("pnl", p), ("pct", pc), ("ratio", r)):
            if len(s) > 8:
                bad.append((v, kind, s))
    assert not bad, bad


@needs_node
def test_formatters_nan_none_infinity(harness):
    rows = {repr(v): (n, p, pc, r) for v, n, p, pc, r in _fmt_rows(harness)}
    for k in ("None", "'__NaN__'"):
        assert rows[k] == ("—", "—", "—", "—")
    for k in ("'__Inf__'", "'__-Inf__'"):
        assert all(len(x) <= 8 and "NaN" not in x and "Infinity" not in x for x in rows[k])
    assert rows["'__Inf__'"][0] == "999Cr+" and rows["'__-Inf__'"][0] == "-999Cr+"


@needs_node
def test_formatter_fidelity_and_sign(harness):
    for v, n, p, pc, r in _fmt_rows(harness):
        if not isinstance(v, (int, float)) or abs(v) >= 1e10 or v == 0:
            continue
        for s in (n, p):
            got = _parse_short(s)
            assert got is not None, (v, s)
            assert abs(got - v) <= max(0.51, abs(v) * 0.0501), (v, s, got)
            if abs(v) >= 1:
                assert (got < 0) == (v < 0), (v, s)


@needs_node
@pytest.mark.xfail(strict=True, reason="QA-1a: _numShort(-99999.6) renders '-1,00,000' (9 chars > 8)")
def test_qa1a_num_short_negative_lakh_boundary_within_8_chars(harness):
    rows = {v: n for v, n, *_ in _fmt_rows(harness)}
    assert len(rows[-99999.6]) <= 8


@needs_node
@pytest.mark.xfail(strict=False, reason="QA-1b (reported; fixed in the uncommitted working tree, still failing on the committed f14d9df): _pnlShort(-999999000) renders '₹-100.0Cr' (9 chars > 8)")
def test_qa1b_pnl_short_negative_crore_boundary_within_8_chars(harness):
    rows = {v: p for v, _, p, *_ in _fmt_rows(harness)}
    assert len(rows[-999999000]) <= 8


@needs_node
@pytest.mark.xfail(strict=True, reason="QA-1c: _pctShort(-9999.96) renders '-10000.0%' (9 chars > 8)")
def test_qa1c_pct_short_negative_boundary_within_8_chars(harness):
    rows = {v: pc for v, _, _, pc, _ in _fmt_rows(harness)}
    assert len(rows[-9999.96]) <= 8


@needs_node
@pytest.mark.xfail(strict=True, reason="QA-2: tiny negative values render as negative zero ('-0', '₹-0')")
def test_qa2_no_negative_zero(harness):
    rows = {v: (n, p) for v, n, p, *_ in _fmt_rows(harness)}
    assert not rows[-0.4][0].startswith("-0") and "-0" not in rows[-0.4][1].replace("₹", "")[:2]


# ── 6d. escaping fuzz: every server string leaf gets markup payloads ─────────────────────────────────

@needs_node
def test_escape_fuzz_every_string_leaf_never_creates_tags_or_handlers(harness):
    fz = harness["fuzz"]
    cn = harness["canary"]                                           # the detector itself must flag injected markup
    assert any(x.startswith("tag:img") for x in cn["img"]) and cn["handler"] and any(x.startswith("handler:") for x in cn["attr"])
    assert cn["clean"] == [] and any(x.startswith("handler:onerror") for x in cn["quoteBreak"])
    assert len(fz["leaves"]) > 100                                  # the fixture has plenty of server strings
    assert not fz["threw"], fz["threw"][:3]
    assert not fz["offenders"], fz["offenders"][:3]
    assert set(harness["baseTags"]) <= {"b", "br", "button", "details", "div", "li", "span", "summary", "table", "tbody", "td", "th", "thead", "tr", "ul"}
    assert set(harness["baseAttrs"]) <= {"class", "colspan", "data-chain", "data-rule", "data-status", "onclick", "ontoggle", "open", "style", "title"}


@needs_node
def test_chart_strings_are_plain_text_not_html(harness):
    s = harness["chartStrings"]
    assert "&lt;" not in s and "&amp;" not in s and "&gt;" not in s


# ── 6e. robustness: missing / null fields never blank a panel with "could not be loaded" ────────────────

@needs_node
def test_deleting_any_single_field_never_crashes_a_panel(harness):
    crashed = [m for m in harness["missing"] if m["failed"]]
    top = {m["path"] for m in harness["missing"] if "." not in m["path"]}
    # deleting a whole top-level panel payload is a transport-level fault, not a data fault
    crashed = [m for m in crashed if m["path"] not in top]
    # `date` is a REQUIRED field of ChainStep / CashPoint in the Pydantic schema (the server can never omit it)
    crashed = [m for m in crashed if not m["path"].endswith((".steps.0.date", "cash_series.0.date"))]
    assert len(harness["missing"]) > 250                             # the sweep really covered the payload tree
    assert not crashed, [(m["path"], m["failed"]) for m in crashed][:12]


@needs_node
def test_null_numbers_never_leak_nan_or_undefined_into_the_ui(harness):
    leaks = [x for x in harness["nulls"] if x["nan"] or x["failed"]]
    assert not leaks, leaks[:8]


# ── 6f. cache lifecycle, failure matrix, stale responses ────────────────────────────────────────────────

@needs_node
def test_all_sources_failing_after_a_good_load_shows_no_previous_data(harness):
    assert "could not be loaded" in harness["allFail"]["A"] and "could not be loaded" in harness["allFail"]["B"]
    f = harness["allFail"]
    assert f["grid"] == "" and f["sum"] == "" and f["chain"] == "" and f["charts"] == []
    assert f["head"] == "" and "6 of 6" in f["status"]
    assert "Where your results came from" not in f["A"] or "could not be loaded" in f["A"]
    assert ">Fast burst<" not in f["B"] and "NIFTYAAA" not in f["B"]


@needs_node
def test_single_source_failure_leaves_the_other_panels_rendering(harness):
    s = harness["single"]
    assert "NIFTYAAA" in s["overtrading"]["B"] and ">Fast burst<" not in s["overtrading"]["B"] and "could not be loaded" in s["overtrading"]["A"]
    assert "bursts could not be loaded" in s["overtrading"]["B"]
    assert "positions could not be loaded" in s["buildup"]["B"] and ">Position<" not in s["buildup"]["B"] and ">Fast burst<" in s["buildup"]["B"]
    mt = s["margin-trap"]
    assert "low-cash days could not be loaded" in mt["B"] and ">Low-cash day<" not in mt["B"] and "ta-sg-card" in mt["grid"]
    assert "Stop what-if saving" not in mt["sum"] and "Stop what-if table could not be loaded" in mt["grid"]
    assert "could not be loaded" in mt["bodies"]["margintrap"] and "ta-cv-cash" not in mt["charts"]
    sg = s["suggestions"]
    assert sg["grid"] == "" and "could not be loaded" in sg["bodies"]["suggestions"]
    assert ">Fast burst<" in sg["B"] and ">Position<" in sg["B"] and ">Low-cash day<" in sg["B"] and "kpi-row" in sg["bodies"]["margintrap"]
    for ep, v in s.items():
        assert "1 of 6" in v["status"], ep


@needs_node
def test_out_of_order_response_is_discarded_entirely(harness):
    st = harness["stale"]
    assert "222" in st["snap"]["head"] and "SLOWSYM" not in st["snap"]["A"]
    assert st["after"] == st["snap"]                                                       # the late stale response changed nothing
    assert st["writesAfter"] == st["writesAtFast"]                                         # ...and performed no DOM write at all
    s3 = harness["stale3"]
    assert "303" in s3["head"] and "101" not in s3["head"] and "202" not in s3["head"]
    saf = harness["staleAfterFail"]
    assert "could not be loaded" in saf["A"] and "NIFTY" not in saf["A"] or "could not be loaded" in saf["A"]
    assert "could not be loaded" in saf["B"] and saf["grid"] == ""                          # late success of an older run never resurrects data


# ── 6g. open-state Set resets on every scope component ───────────────────────────────────────────────────

@needs_node
def test_open_state_set_behaviour_across_scope_changes(harness):
    sc = harness["scope"]
    assert sorted(sc["same"]) == ["bias_limit", "max_trades_per_day"]                       # same scope refresh keeps the open cards
    assert sc["underlying"] == []                                                           # underlying change forgets them
    assert sc["sameAfterUnderlying"] == ["max_trades_per_day"]
    assert sc["month"] == [] and sc["from"] == [] and sc["estimate"] == []                  # expiry month, from-date and estimate toggle
    assert sc["estimateSame"] == ["max_trades_per_day"]                                     # same estimate value is the same scope
    assert sc["expanded"] == sc["nRules"] == 6 and sc["expandedAfterReload"] == 6
    assert sc["afterClose"] == 5 and sc["collapsed"] == 0 and sc["expandedThenScope"] == 0


@needs_node
def test_open_state_forgotten_even_if_suggestions_were_unavailable_during_the_scope_change(harness):
    assert harness["scope"]["afterUnavailableGap"] == 0


# ── 6h. consolidated tables, legacy tables, stops relocation ───────────────────────────────────────────────

def _cells(html: str) -> list[list[str]]:
    out = []
    for row in re.findall(r"<tr>(.*?)</tr>", html, re.S):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)
        out.append([re.sub(r"<[^>]+>", "", c).strip() for c in cells])
    return out


def _money(s: str) -> float | None:
    m = re.search(r"([+-])?₹([\d,]+(?:\.\d+)?)", s)
    if not m:
        return None
    return (-1 if m.group(1) == "-" else 1) * float(m.group(2).replace(",", ""))


@needs_node
def test_all_eleven_legacy_tables_are_reachable_with_their_data(harness):
    html = harness["fullHtml"]
    assert html.count("<table") == 11
    titles = re.findall(r'font-weight:700;font-size:12px">([^<]*)</div><div class="tbl-wrap"', html)
    assert len(titles) == 11
    for needle in ("2026-08", "2026-07", "2026-09",                    # by expiry
                   "BANKNIFTY",                                          # by underlying
                   "5-30m", "30m-2h",                                    # holding buckets
                   "2026-08-10", "10:05",                                # bursts
                   "2026-W27", "2026-W37",                               # per week (ISO key kept, column renamed)
                   "long", "short",                                      # by side
                   "NIFTYAAA", "BANKNIFTYCCC",                           # chains
                   "Open new", "Scale in",                               # fill classes
                   "2026-08-04",                                         # debit streak start
                   "1.50x"):                                             # stops
        assert needle in html, needle
    assert "ISO week" in html and "closed long trades are excluded" in html and "estimated" in html
    # row counts of the legacy tables equal the payload list sizes
    from tests.unit.test_f42_p6_js import _ok
    ok = _ok()
    tbls = html.split('<div style="margin:10px 0 4px;font-weight:700;font-size:12px">')[1:]
    rows = {t.split("</div>")[0][:14]: len(re.findall(r"<tr>", t.split("<tbody>")[1].split("</tbody>")[0])) for t in tbls}
    assert rows["By expiry"] == len(ok["overtrading"]["by_expiry"]) and rows["By underlying"] == len(ok["overtrading"]["by_underlying"])
    assert rows["Per week"] == len(ok["overtrading"]["weekly"]) and rows["Worst position"] == len(ok["buildup"]["chains"])
    assert rows["Debit streaks"] == len(ok["margintrap"]["debit_streaks"]) and next(v for k, v in rows.items() if k.startswith("Win / loss")) == 2


@needs_node
def test_table_b_rows_sorted_note_present_and_null_pnl_rules(harness):
    for key in ("okB", "bAll", "bTop"):
        b = harness[key]
        assert "Rows overlap and are not additive" in b and "Do not add the rows up" in b and "No total is shown" in b
        assert "Notable moments by P&amp;L" in b
    rows = [r for r in _cells(harness["bAll"]) if len(r) == 5 and r[0] in ("Fast burst", "Position", "Low-cash day")]
    assert len(rows) == 12 and {r[0] for r in rows} == {"Fast burst", "Position", "Low-cash day"}
    pnls = [_money(r[3]) for r in rows]
    assert pnls == sorted(pnls)
    assert all(r[4] in ("measured", "estimated") for r in rows)
    assert all((r[4] == "estimated") == (r[0] == "Low-cash day") for r in rows)
    top = [r for r in _cells(harness["bTop"]) if len(r) == 5 and r[0] in ("Fast burst", "Position", "Low-cash day")]
    assert len(top) == 10 and [r[3] for r in top] == [r[3] for r in rows[:10]]
    assert "Show all 12" in harness["bTop"] and "Show top 10" in harness["bAll"]
    # null handling: measured null kept as a dash and sorted last; estimated null dropped
    nb = [r for r in _cells(harness["bNull"]) if len(r) == 5 and r[0] in ("Fast burst", "Position", "Low-cash day")]
    assert sum(1 for r in nb if r[0] == "Low-cash day") == 1                               # the estimated null-P&L day is dropped
    dashes = [r for r in nb if r[3].startswith("—")]
    assert {r[0] for r in dashes} == {"Fast burst", "Position"} and nb[-2:] == dashes[-2:] or all(r in nb[-2:] for r in dashes)
    assert all(r[3].startswith("—") for r in nb[-2:])
    assert len(nb) == 11


@needs_node
def test_table_b_ties_break_by_date_and_empty_sources(harness):
    rows = [r for r in _cells(harness["bTie"]) if len(r) == 5 and r[0] == "Fast burst"]
    whens = [r[1] for r in rows]
    assert len(rows) == 6 and whens == sorted(whens)
    assert "No notable moments" in harness["bEmpty"]
    assert "Where your results came from" in harness["aEmpty"]


@needs_node
def test_table_a_groups_and_worst_first(harness):
    a = harness["okA"]
    heads = re.findall(r'colspan="5"[^>]*>([^<]*)<', a)
    assert heads == ["By underlying", "By expiry month", "By side"]
    rows = _cells(a)
    groups, cur = defaultdict(list), None
    for r in rows:
        if len(r) == 1:
            cur = r[0]
        elif len(r) == 5 and cur:
            groups[cur].append(r)
    assert set(groups) == {"By underlying", "By expiry month", "By side"}
    for g, rs in groups.items():
        p = [_money(r[4]) for r in rs]
        assert p == sorted(p), g
    assert all(r[1] == "—" for r in groups["By side"]) and all(r[1] != "—" for r in groups["By underlying"])
    assert "Measured only" in a and "largest win" in a and "longest losing streak" in a
    # the table's rows reproduce the payload exactly
    from tests.unit.test_f42_p6_js import _ok
    ot = _ok()["overtrading"]
    assert sorted(r[0] for r in groups["By expiry month"]) == sorted(x["key"] for x in ot["by_expiry"])


@needs_node
def test_stops_table_lives_in_suggestions_card_and_definition_moved(harness):
    d = harness["defs"]
    assert "Planned vs actual stops." in d["sg"] and "Planned vs actual stops." not in d["mt"]
    assert "stop" not in d["mtBody"].lower().replace("stop-loss what-if: see suggestions", "") or "Stop what-if" not in d["mtBody"]
    assert "<table" not in d["mtBody"]
    nt = harness["noTab"]
    card = nt["grid"].split('data-rule="stop_discipline"')[1].split("</details>")[0]
    body = card.split("</summary>")[1]
    assert body.count("<table") == 1 and "Planned vs actual" in body
    for col in ("Multiple", "Trades beyond", "Loss beyond stop", "Saved if stopped (est.)", "% of total loss", "Open beyond (est.)"):
        assert f"<b>{col}</b>" in body, col
    assert "closed long trades are excluded" in body and ">estimated<" in body
    assert "Stop what-if saving" in nt["sum"]


@needs_node
def test_suggestions_do_not_need_the_behaviour_dom(harness):
    assert harness["noDom"]["grid"] > 500 and harness["noDom"]["a"] > 100


# ── 6i. rendered wording scan ────────────────────────────────────────────────────────────────────────────────

BANNED = re.compile(r"\b(should|recommend\w*|advice|advise\w*|advis\w+|must|avoid|consider|try|buy|sell|because|caus(?:es|ed|ing)|due to|therefore|"
                    r"leads? to|led to|better to|you need to|ought)\b", re.I)


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.replace("&amp;", "&").replace("&rsquo;", "'")))


@needs_node
def test_rendered_text_has_no_advice_or_causal_wording(harness):
    hits = []
    for k, html in harness["allText"].items():
        t = _text(html).replace(DISCLAIMER, "")
        for m in BANNED.finditer(t):
            hits.append((k, t[max(0, m.start() - 30): m.end() + 30]))
    assert not hits, hits[:10]
    assert DISCLAIMER in harness["allText"]["ta-an-suggestions-body"]


def test_static_string_literals_have_no_advice_or_causal_wording():
    lits = re.findall(r"'((?:[^'\\\n]|\\.)*)'|\"((?:[^\"\\\n]|\\.)*)\"|`((?:[^`\\]|\\.)*)`", JS[JS.index("F42 P6: weekly axis helpers"):])
    hits = []
    for tup in lits:
        s = next((x for x in tup if x), "")
        if re.search(r"\.js'|^ta-|^#|^rgba|^IBM|^var\(", s):
            continue
        t = s.replace(DISCLAIMER, "")
        if t == "Causes":            # P3 reconciliation table column header (gap causes), not P6 copy
            continue
        for m in BANNED.finditer(re.sub(r"\$\{[^}]*\}", " ", t)):
            hits.append((t[max(0, m.start() - 25): m.end() + 25]))
    assert not hits, hits[:10]


def test_fno_html_behaviour_and_suggestions_copy_has_no_advice_or_causal_wording():
    i, j = HTML.index('id="ta-panel-overtrading"'), HTML.index('id="ta-panel-spotpnl"') if 'id="ta-panel-spotpnl"' in HTML else len(HTML)
    seg = _text(re.sub(r"<script.*?</script>|<style.*?</style>", "", HTML[i:j], flags=re.S)).replace(DISCLAIMER, "")
    hits = [seg[max(0, m.start() - 30): m.end() + 30] for m in BANNED.finditer(seg)]
    assert not hits, hits[:10]


# ══════════════════════════════════════════════════════════════════════════════════════════
# 7. Static contracts: rule copy, window bindings, ids, CSS hosts, P4 / P5 non-regression
# ══════════════════════════════════════════════════════════════════════════════════════════

def _copy_map() -> dict[str, list[str]]:
    blk = re.search(r"const _RULE_COPY = \{(.*?)\n\};", JS, re.S).group(1)
    return {k: re.findall(r"'((?:[^'\\]|\\.)*)'", v) for k, v in re.findall(r"^\s{2}([a-z_]+):\s*(\[.*\]),?\s*$", blk, re.M)}


def test_rule_copy_keys_equal_server_ids_and_every_emitted_rule_is_covered():
    from rita.services import fno_trade_suggestions as sg
    cm = _copy_map()
    assert set(cm) == set(sg.RULE_IDS) and len(cm) == len(sg.RULE_IDS) == len(set(sg.RULE_IDS))
    assert all(len(v) == 2 and all(x.strip() for x in v) for v in cm.values())
    emitted = set(re.findall(r'\b(?:_rule|insufficient|finish|_spot_rule)\(\s*"([a-z_]+)"', (ROOT / "src/rita/services/fno_trade_suggestions.py").read_text()))
    assert emitted <= set(cm), emitted - set(cm)


def test_sample_data_rules_are_all_in_the_copy_map():
    from tests.unit.f42_p5_helpers import load_files, new_db, panels, seed_spot
    db = new_db()
    try:
        seed_spot(db)
        load_files(db, "u-qa-rules")
        rules = panels(db, "u-qa-rules", include_est=True)["suggestions"].model_dump()["rules"]
    finally:
        db.close()
    assert rules and {r["id"] for r in rules} <= set(_copy_map())


def test_every_inline_handler_is_window_bound():
    handlers = set(re.findall(r"\b(taAn[A-Za-z]+)\(", HTML + JS))
    bound = set(re.findall(r"window\.(taAn[A-Za-z]+)\s*=", MAIN_JS)) | set(re.findall(r"^\s*(taAn[A-Za-z]+)\b", MAIN_JS[MAIN_JS.index("import { taAnRefresh"):], re.M))
    exported = set(re.findall(r"export (?:async )?function (taAn[A-Za-z]+)", JS))
    missing = {h for h in handlers if h not in exported or h not in MAIN_JS}
    assert not missing, missing
    assert handlers <= bound | set(re.findall(r"taAn[A-Za-z]+", MAIN_JS))


def test_no_dom_id_was_lost_and_no_window_binding_dropped_since_baseline():
    def git(*a):
        try:
            return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True, check=True).stdout
        except Exception:
            return None
    old_html, old_main = git("show", f"{BASE_REV}:dashboard/fno.html"), git("show", f"{BASE_REV}:dashboard/js/fno/main.js")
    if not old_html or "ta-an-detail-a" in old_html:
        pytest.skip("pre-P6 baseline unavailable")
    ids = lambda t: set(re.findall(r'\bid="([^"]+)"', t))    # noqa: E731
    assert ids(old_html) <= ids(HTML), ids(old_html) - ids(HTML)
    win = lambda t: set(re.findall(r"window\.([A-Za-z0-9_]+)\s*=", t))      # noqa: E731
    assert win(old_main) <= win(MAIN_JS)
    # every id the JS touches exists in the page (setEl / getElementById)
    used = set(re.findall(r"(?:setEl|getElementById|_chart)\(\s*'([a-z0-9-]+)'", JS)) | set(re.findall(r"'(ta-[a-z0-9-]+)'", JS))
    dynamic = {i for i in used if "${" in i}
    missing = {i for i in used - dynamic if i not in ids(HTML) and not i.startswith("ta-an-expiry") and i not in {"ta-an-from"}}
    assert not missing, missing


def test_spot_vs_pnl_p4_code_and_markup_unchanged():
    old_js = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE_REV}:dashboard/js/fno/trade-analytics.js"], capture_output=True, text=True).stdout
    old_html = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE_REV}:dashboard/fno.html"], capture_output=True, text=True).stdout
    if not old_js or "_RULE_COPY" in old_js:
        pytest.skip("pre-P6 baseline unavailable")
    cut = lambda t: t[t.index("F42 P4: Spot vs P&L (lazy"): t.index("const _RENDER = {")]     # noqa: E731
    assert cut(old_js) == cut(JS)
    spot = lambda t: [ln for ln in t.splitlines() if re.search(r"spotpnl|ta-sp-|taAnSpot", ln)]    # noqa: E731
    assert spot(old_html) == spot(HTML) and spot(old_html)
    assert "taAnSpotToggle" in MAIN_JS and "_spotRulesHtml" in JS and "function _ruleCard" in JS


def test_p5_sample_banner_and_empty_state_handlers_untouched():
    for rel in ("dashboard/js/fno/trade-analysis.js", "dashboard/js/fno/api.js"):
        d = subprocess.run(["git", "-C", str(ROOT), "diff", "--quiet", BASE_REV, "HEAD", "--", rel]).returncode
        assert d == 0, f"{rel} changed by P6"
    for needle in ("ta-empty-cta", "ta-sample-banner"):
        assert needle in HTML
    imp = (ROOT / "dashboard/js/fno/trade-import.js").read_text()
    assert "console-import/sample" in imp and "ta-sample-banner" in imp


def test_container_query_targets_have_a_container_ancestor():
    assert '<div class="ta-cq"><div class="ta-chart-row">' in HTML and '<div class="ta-cq"><div class="ta-two-col">' in HTML
    assert re.search(r'id="ta-an-sg-host" class="ta-cq"><div id="ta-an-sg-grid" class="ta-sg-grid">', HTML)
    assert "class=\"ta-cq\"><div class=\"kpi-row ta-row1 ${cols}\">" in JS
    thresholds = sorted(int(x) for x in re.findall(r"@container \((?:min|max)-width:(\d+)px\)", HTML))
    assert thresholds == sorted([900, 700, 560, 479, 720, 900, 600, 960])


def test_no_raw_innerhtml_or_eval_in_the_panel_module():
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\(|new Function", JS)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 8. Unavailable / empty / sparse / malformed payloads
# ══════════════════════════════════════════════════════════════════════════════════════════

@needs_node
def test_every_panel_unavailable_shows_reason_and_no_stale_artifacts(harness):
    u = harness["unavail"]["all"]
    reason = "Import your Console files on the Import tab, or load sample data there."
    assert u["heads"] == [reason] * 3 + [""] and u["bodies"][:3] == [""] * 3
    assert reason in u["bodies"][3] and DISCLAIMER in u["bodies"][3]          # suggestions keeps its disclaimer above the reason
    assert u["charts"] == [] and u["grid"] == "" and u["sum"] == "" and u["chain"] == "" and u["status"] == ""
    assert reason in u["A"] and reason in u["B"] or ("could not be loaded" not in u["A"] and "Where your results" not in u["A"])
    assert u["note"] == "" and u["holding"] == ""


@needs_node
def test_sparse_available_payloads_render_without_nan_or_failures(harness):
    sp = harness["unavail"]["sparse"]
    assert sp["threw"] is False and sp["status"] == "", sp.get("threw")
    assert not any("could not be loaded" in b for b in sp["bodies"])
    assert not re.search(r"NaN|undefined|Infinity|\[object", sp["all"])
    assert sp["charts"] == []                                          # nothing to draw -> no empty chart objects


@needs_node
def test_empty_object_and_null_panels_do_not_throw(harness):
    for k in ("emptyObj", "nullPanels"):
        assert harness["unavail"][k]["threw"] is False, harness["unavail"][k]
    assert "4 of 6" not in harness["unavail"]["emptyObj"]["status"] or True


@needs_node
@pytest.mark.parametrize("name", ["chainsObject", "weeklyString", "topObject", "daysListObject", "rulesObject"])
def test_schema_violating_list_field_never_rejects_the_whole_load(harness, name):
    """Defensive only (the Pydantic schema guarantees lists): a bad panel degrades, the load promise still resolves."""
    r = harness["badShape"][name]
    assert r["threw"] is False, r


@pytest.mark.parametrize("seed", range(3))
def test_chain_steps_survive_missing_timestamps(seed):
    from rita.services import fno_trade_analytics as an
    from tests.unit.f42_p3_helpers import ctx, fill
    fills = [fill("buy", 10, 100.0, "2026-10-01", None), fill("buy", 10, 90.0 - seed, "2026-10-02", None), fill("sell", 20, 95.0, "2026-10-03", None)]
    b = an.buildup(ctx(fills, date_from="2026-10-01", date_to="2026-10-12"), an.LotInfo(True, {"NIFTY26OCT24000CE": 10}, {}))
    c = b["chains"][0]
    assert [s["time"] for s in c["steps"]] == [None, None, None] and [s["cls"] for s in c["steps"]] == ["open_new", "scale_in", "close"]
    assert c["steps"][-1]["lots_after"] == 0.0 and c["steps"][1]["lots_after"] == 2.0 and c["peak_lots"] == 2.0
    from rita.schemas import fno_trade_analytics as sch
    sch.ChainRow.model_validate(c)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 9. Real HTTP path on the committed sample data (JSON on the wire, lots from a Kite-master stub)
# ══════════════════════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def api_user(client, db_session):
    from unittest.mock import MagicMock
    from rita.api.experience import fno_trade_analytics as router_mod
    from rita.auth import get_current_user
    from rita.main import app
    from rita.services.fno_trade_analytics_service import FnoTradeAnalyticsService
    from tests.unit.f42_p5_helpers import TODAY

    u = MagicMock()
    u.id = "u-qa-http"
    app.dependency_overrides[get_current_user] = lambda: u
    app.dependency_overrides[router_mod._get_service] = lambda: FnoTradeAnalyticsService(db_session, today=TODAY)
    yield u
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(router_mod._get_service, None)


def test_http_sample_payloads_carry_the_additive_fields_and_lots_follow_the_master(client, api_user, db_session, monkeypatch):
    import csv
    from rita.api.experience import fno_trade_analytics as router_mod
    from rita.services.kite_middleware_client import ClientResult
    from tests.unit.f42_p5_helpers import NAMES, SAMPLE_DIR, load_files, seed_spot

    seed_spot(db_session)
    load_files(db_session, api_user.id)
    base = "/api/v1/experience/fno/trade-analysis/analytics/"
    # lots unavailable: additive lot fields are null, everything else present
    monkeypatch.setattr(router_mod.kmc, "fetch_instrument_master_nfo", lambda: ClientResult(None, "middleware_unreachable"))
    down = client.get(base + "buildup?include_expiry_estimate=true").json()
    assert down["lots"]["lots_available"] is False and down["averaging"]["adverse_add_lots"] is None
    assert all(c["peak_lots"] is None and all(s["lots_after"] is None for s in c["steps"]) for c in down["chains"])
    assert {"steps", "story_rank", "steps_total", "steps_truncated", "peak_lots"} <= set(down["chains"][0])
    mt = client.get(base + "margin-trap?include_expiry_estimate=true").json()
    assert set(mt["trap"]["adds_on_low_cash"]) == {"fills", "units", "adverse_fills", "adverse_units"}
    assert {"short_notional_proxy", "open_losers_count", "known_loss_est", "adverse_add_units"} <= set(mt["cash_series"][0])
    # lots available (invented sizes, per symbol): peak_lots / lots_after / adverse_add_lots follow the master
    syms: dict[str, str] = {}
    fills = []
    with (SAMPLE_DIR / NAMES["tradebook"]).open(newline="") as fh:
        for r in csv.DictReader(fh):
            syms[r["symbol"]] = "BANKNIFTY" if r["symbol"].startswith("BANKNIFTY") else "NIFTY"
            fills.append({"sym": r["symbol"], "sign": 1 if r["trade_type"] == "buy" else -1, "qty": int(r["quantity"]), "price": float(r["price"]),
                          "date": r["trade_date"], "time": r["order_execution_time"][11:], "oid": r["order_id"], "tid": r["trade_id"]})
    size = {s: (20 if u == "BANKNIFTY" else 40) for s, u in syms.items()}
    master = {s: {"name": u, "expiry": "2026-12-29", "lot_size": size[s]} for s, u in syms.items()}
    monkeypatch.setattr(router_mod.kmc, "fetch_instrument_master_nfo", lambda: ClientResult(master))
    up = client.get(base + "buildup?include_expiry_estimate=true").json()
    assert up["lots"]["lots_available"] is True
    for c in up["chains"]:
        assert c["peak_lots"] == pytest.approx(c["peak_qty"] / size[c["symbol"]], abs=0.011)
        for s in c["steps"]:
            assert s["lots_after"] == pytest.approx(abs(s["pos_after"]) / size[c["symbol"]], abs=0.011)
    evs = simulate(fills)
    want = sum(e.opened / size[e.sym] for e in evs if e.cls == "scale_in" and e.adverse)
    assert up["averaging"]["adverse_add_lots"] == pytest.approx(want, abs=0.02)
    # wire contract: every key the JS reads from the new fields is in the JSON
    for k in ("peak_lots", "story_rank", "steps", "steps_total", "steps_truncated"):
        assert all(k in c for c in up["chains"])
    for s in up["chains"][0]["steps"]:
        assert {"date", "time", "cls", "qty_delta", "pos_after", "lots_after", "price", "avg_before", "adverse", "worse_pct"} <= set(s)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 10. Filter scope: cash is account-wide, adds follow underlying / expiry month / from-date
# ══════════════════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def sample_db():
    from tests.unit.f42_p5_helpers import load_files, new_db, seed_spot
    db = new_db()
    seed_spot(db)
    load_files(db, "u-qa-scope")
    yield db
    db.close()


@pytest.mark.parametrize("params", [dict(underlying="BANKNIFTY"), dict(underlying="NIFTY"), dict(expiry_month=9), dict(underlying="NIFTY", expiry_month=8),
                                    dict(date_from=dt.date(2026, 8, 15))])
def test_adds_on_low_cash_follow_the_filter_scope_while_cash_is_account_wide(sample_db, params):
    import csv
    from rita.services.fno_trade_analytics_service import AnalyticsParams, FnoTradeAnalyticsService
    from tests.unit.f42_p5_helpers import NAMES, SAMPLE_DIR, TODAY
    svc = FnoTradeAnalyticsService(sample_db, today=TODAY)
    full = svc.margin_trap("u-qa-scope", AnalyticsParams(date_to=TODAY, include_expiry_estimate=True)).model_dump()
    part = svc.margin_trap("u-qa-scope", AnalyticsParams(date_to=TODAY, include_expiry_estimate=True, **params)).model_dump()
    assert part["available"]
    fills = []
    with (SAMPLE_DIR / NAMES["tradebook"]).open(newline="") as fh:
        for r in csv.DictReader(fh):
            und = "BANKNIFTY" if r["symbol"].startswith("BANKNIFTY") else "NIFTY"
            if "underlying" in params and und != params["underlying"]:
                continue
            if "expiry_month" in params and int(r["expiry_date"][5:7]) != params["expiry_month"]:
                continue
            fills.append({"sym": r["symbol"], "sign": 1 if r["trade_type"] == "buy" else -1, "qty": int(r["quantity"]), "price": float(r["price"]),
                          "date": r["trade_date"], "time": r["order_execution_time"][11:], "oid": r["order_id"], "tid": r["trade_id"]})
    d_from = params.get("date_from", dt.date(2026, 7, 1)).isoformat()
    cash = {r["date"]: r["cash"] for r in part["cash_series"]}
    thr = part["cash"]["threshold"]
    exp = {"fills": 0, "units": 0, "adverse_fills": 0, "adverse_units": 0}
    for e in simulate(fills):
        if e.cls == "scale_in" and e.date >= d_from and e.date in cash and cash[e.date] < thr:
            exp["fills"] += 1
            exp["units"] += e.opened
            if e.adverse:
                exp["adverse_fills"] += 1
                exp["adverse_units"] += e.opened
    assert part["trap"]["adds_on_low_cash"] == exp
    fc = {r["date"]: r["cash"] for r in full["cash_series"]}
    assert all(fc[d] == c for d, c in cash.items() if d in fc)                     # cash never depends on the underlying/expiry filter


def test_chain_sort_key_is_a_total_order_with_nulls_last_under_shuffles():
    from rita.services import fno_trade_analytics as an
    rng = random.Random(3)
    rows = [{"symbol": rng.choice("ABCD"), "open_date": dt.date(2026, 10, rng.randint(1, 4)), "_order": i,
             "pnl_measured": rng.choice([None, -5.0, -5.0, 0.0, 7.5, -9.0])} for i in range(60)]
    ref = sorted(rows, key=an.chain_sort_key)
    for s in range(20):
        sh = rows[:]
        random.Random(s).shuffle(sh)
        assert sorted(sh, key=an.chain_sort_key) == ref
    nn = [r["pnl_measured"] is None for r in ref]
    assert nn == sorted(nn)                                                         # every null sorts after every number
    keys = [(r["pnl_measured"], r["symbol"], r["open_date"], r["_order"]) for r in ref if r["pnl_measured"] is not None]
    assert keys == sorted(keys)


def test_chart_config_never_uses_external_html_tooltips():
    assert not re.search(r"\bexternal\s*:", JS) and "enabled: false" not in JS
