#!/usr/bin/env python3
"""Dev-time generator for the F42 P5 "Load sample data" files.

SYNTHETIC DATA, NOT DERIVED FROM ANY ACCOUNT.  Every id, quantity, price, time and amount is
invented by a seeded simulator.  The only market input is the small committed fixture
``scripts/fixtures/fno_sample_closes.csv`` (public NIFTY / BANKNIFTY closes).  Nothing else is
read from disk or from any user data.

The simulator books a scripted set of trades (a "story": a day-trader whose swing book leans
against the market, one averaging-down chain per side, a cash squeeze, overtrading bursts on
big-move days), matches them FIFO exactly like the app's analytics, and writes three
Zerodha-Console-style CSV files:

    SAMPLE_tradebook.csv   SAMPLE_pnl.csv   SAMPLE_ledger.csv

Run it by hand; the app never imports or executes it.  Lot sizes are passed in (the caller
takes them from ``settings.instruments.*.lot_size``); there are no defaults here:

    python scripts/generate_fno_sample.py --nifty-lot 75 --banknifty-lot 30 \\
        --out data/input/sample/fno

Only stdlib.  One ``random.Random(seed)``; only ``random()``, ``randrange()``, ``sample()`` are
used, in a fixed order.  Money is integer paise, formatted without float repr.
"""
from __future__ import annotations

import argparse
import csv
import io
import math
import random
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_CLOSES = HERE / "fixtures" / "fno_sample_closes.csv"
WINDOW_FROM = date(2026, 7, 1)
WINDOW_TO = date(2026, 9, 18)
SEED = 20260701
TICK = 5                                   # paise (INR 0.05)
MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
STEP = {"NIFTY": 50, "BANKNIFTY": 100}
VOL = {"NIFTY": 0.11, "BANKNIFTY": 0.10}   # annualised, only used for the premium look
SETTLE_PREFIX = "SAMPLE "

# headline targets (the committed files are checked against these bands by the test-suite)
WIN_SUM = 108000.0
LOSS_SUM = 143440.0
LOT_BIAS = 2.1                             # >1: smaller premium moves, larger quantities
BURST_DAYS = (6, 8, 13, 16, 24, 45, 54)    # 1-based window trading-day numbers


# ── tiny helpers ──────────────────────────────────────────────────────────────

def money(p: int) -> str:
    sign = "-" if p < 0 else ""
    p = abs(p)
    return f"{sign}{p // 100}.{p % 100:02d}"


def tick_round(p: float) -> int:
    """Round a paise value to the nearest tick (never below one tick)."""
    return max(TICK, int(math.floor(round(p, 4) / TICK + 0.5)) * TICK)


def mins(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:5])


def hhmm_of(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


# ── market input ──────────────────────────────────────────────────────────────

class Market:
    def __init__(self, closes_path: Path) -> None:
        self.rows: list[tuple[date, float, float, str, str]] = []
        with closes_path.open(newline="") as f:
            for r in csv.DictReader(f):
                self.rows.append((date.fromisoformat(r["date"]), float(r["nifty_close"]),
                                  float(r["banknifty_close"]), r["nifty_close"], r["banknifty_close"]))
        self.days = [r[0] for r in self.rows if WINDOW_FROM <= r[0] <= WINDOW_TO]
        self.close = {("NIFTY", r[0]): r[1] for r in self.rows}
        self.close.update({("BANKNIFTY", r[0]): r[2] for r in self.rows})

    def d(self, i: int) -> date:
        return self.days[i - 1]

    def spot(self, und: str, i: int) -> float:
        return self.close[(und, self.d(i))]


def tuesdays(start: date, end: date) -> list[date]:
    d = start
    while d.weekday() != 1:
        d += timedelta(days=1)
    out = []
    while d <= end:
        out.append(d)
        d += timedelta(days=7)
    return out


def is_monthly(d: date) -> bool:
    return (d + timedelta(days=7)).month != d.month


EXPIRIES = tuesdays(date(2026, 7, 7), date(2026, 12, 29))
MONTHLY = [d for d in EXPIRIES if is_monthly(d)]


def make_symbol(und: str, cp: str, strike: int, exp: date) -> str:
    yy = exp.year % 100
    if und == "BANKNIFTY" or is_monthly(exp):
        return f"{und}{yy:02d}{MON[exp.month - 1]}{strike}{cp}"
    mcode = str(exp.month) if exp.month < 10 else {10: "O", 11: "N", 12: "D"}[exp.month]
    return f"{und}{yy:02d}{mcode}{exp.day:02d}{strike}{cp}"


def model_px(und: str, cp: str, strike: int, spot: float, dte: int) -> int:
    """Synthetic premium in paise: intrinsic + a decaying time value.  Look only, not a pricer."""
    t = max(dte, 0.5) / 365.0
    sig = spot * VOL[und] * math.sqrt(t)
    dist = (strike - spot) if cp == "CE" else (spot - strike)      # > 0 = out of the money
    tv = 0.4 * sig * math.exp(-0.5 * (dist / sig) ** 2)
    intrinsic = max(-dist, 0.0)
    return tick_round((intrinsic + tv) * 100.0)


# ── scenario model ────────────────────────────────────────────────────────────

@dataclass
class Order:
    day: int
    hhmm: str
    side: int                  # +1 buy / -1 sell
    lots: int
    nfills: int
    px: int = 0                # paise; 0 on a closing order = solved from ``pnl``
    pnl: float | None = None   # INR target for a closing order
    ser: int = 0               # creation serial (tie-break)


@dataclass
class Life:
    und: str
    cp: str
    strike: int
    expiry: date
    orders: list[Order] = field(default_factory=list)
    tag: str = ""
    held_to_expiry: bool = False

    @property
    def symbol(self) -> str:
        return make_symbol(self.und, self.cp, self.strike, self.expiry)


@dataclass
class Fill:
    life: Life
    order: Order
    day: int
    sec: int                   # seconds from midnight
    side: int
    qty: int
    px: int


class Sim:
    def __init__(self, mk: Market, lots: dict[str, int], rng: random.Random) -> None:
        self.mk, self.lot, self.rng = mk, lots, rng
        self.lives: list[Life] = []
        self.busy: dict[int, list[int]] = {}
        self._ser = 0
        self.scales: tuple[float, float] | None = None

    # -- construction helpers -------------------------------------------------
    def order(self, life: Life, day: int, hhmm: str, side: int, lots: int, nfills: int,
              px: int = 0, pnl: float | None = None) -> Order:
        self._ser += 1
        o = Order(day, hhmm, side, lots, nfills, px, pnl, self._ser)
        life.orders.append(o)
        self.busy.setdefault(day, []).append(mins(hhmm))
        return o

    def strike_for(self, und: str, cp: str, day: int, off: int) -> int:
        step = STEP[und]
        atm = int(round(self.mk.spot(und, day) / step)) * step
        return atm + off * step if cp == "CE" else atm - off * step

    def pick_expiry(self, und: str, last_day: int, gap: int = 2) -> date:
        pool = MONTHLY if und == "BANKNIFTY" else EXPIRIES
        lim = self.mk.d(last_day) + timedelta(days=gap)
        return next(e for e in pool if e >= lim)

    def entry_px(self, life: Life, day: int, jitter: float = 0.0) -> int:
        spot = self.mk.spot(life.und, day)
        dte = (life.expiry - self.mk.d(day)).days
        return tick_round(model_px(life.und, life.cp, life.strike, spot, dte) * (1.0 + jitter))

    def size(self, und: str, e_px: int, pnl: float, pref: float, lmin: int, lmax: int) -> int:
        """Whole lots whose move (|pnl| / units) is closest to ``pref`` x the entry premium."""
        best, best_err = lmin, 1e18
        for lots in range(lmin, lmax + 1):
            ratio = abs(pnl) / (lots * self.lot[und]) / (e_px / 100.0)
            err = abs(ratio - pref / LOT_BIAS)
            if err < best_err:
                best, best_err = lots, err
        return best

    def round_trip(self, und: str, cp: str, side: int, off: int, opens: list[tuple[int, str, int]],
                   close: tuple[int, str, int], pnl: float, pref: float, lmin: int = 1,
                   lmax: int = 10, tag: str = "", expiry: date | None = None,
                   lots: int | None = None) -> Life:
        d0 = opens[0][0]
        life = Life(und, cp, self.strike_for(und, cp, d0, off),
                    expiry or self.pick_expiry(und, close[0], 2 if und == "NIFTY" else 3), tag=tag)
        e1 = self.entry_px(life, d0, (self.rng.random() - 0.5) * 0.08)
        total = lots or self.size(und, e1, pnl, pref, max(lmin, len(opens)), lmax)
        first = total if len(opens) == 1 else max(1, min(total - 1, int(math.ceil(total * 0.6))))
        parts = [first] if len(opens) == 1 else [first, total - first]
        for k, ((day, t, nf), lo) in enumerate(zip(opens, parts)):
            px = e1 if k == 0 else tick_round(e1 * (1.0 + 0.03 * side))   # later adds: better than the average (never adverse)
            self.order(life, day, t, side, lo, nf, px=px)
        self.order(life, close[0], close[1], -side, total, close[2], pnl=pnl)
        self.lives.append(life)
        return life

    def chain(self, und: str, cp: str, side: int, strike: int, expiry: date,
              steps: list[tuple[int, str, int, int, int]], px0: int, drift: float,
              closes: list[tuple[int, str, int, int, float]], tag: str) -> Life:
        """Averaging chain: every add at a worse price than the running average (adverse add)."""
        life = Life(und, cp, strike, expiry, tag=tag)
        px = px0
        for k, (day, t, lo, nf, _unused) in enumerate(steps):
            self.order(life, day, t, side, lo, nf, px=tick_round(px))
            px = px * (1.0 + drift)
        for day, t, lo, nf, pnl in closes:
            self.order(life, day, t, -side, lo, nf, pnl=pnl)
        self.lives.append(life)
        return life

    def hold_to_expiry(self, und: str, cp: str, side: int, strike: int, day: int, t: str, lots: int,
                       nf: int, expiry: date, tag: str) -> Life:
        life = Life(und, cp, strike, expiry, tag=tag, held_to_expiry=True)
        self.order(life, day, t, side, lots, nf, px=self.entry_px(life, day))
        self.lives.append(life)
        return life

    def free_slot(self, day: int, near: int | None = None, lo: int = 560, hi: int = 900,
                  gap: int = 35) -> int | None:
        """A minute-of-day at least ``gap`` away from every order already booked that day."""
        used = self.busy.get(day, [])
        for _ in range(300):
            m = lo + int(self.rng.random() * (hi - lo))
            m = (m // 5) * 5
            if all(abs(m - u) >= gap for u in used):
                return m
        return None


# ── the story ─────────────────────────────────────────────────────────────────

# fixed trades: (key, und, cp, side, off, day_open, t_open, day_close, t_close, pnl, kind)
# core NIFTY swing book: direction chosen against the coming moves (B = bullish, R = bearish).
CORE = [
    # name  cp  side off  open(day,t)        close(day,t)      pnl     pref  expiry-hint
    ("N1", "CE", -1, 6, (1, "14:10"), (4, "11:20"), -2400.0),
    ("N2", "CE", -1, 6, (4, "13:45"), (8, "11:05"), 3100.0),
    ("N3", "PE", -1, 5, (8, "13:15"), (10, "10:40"), -2800.0),
    ("N5", "PE", -1, 5, (29, "14:00"), (32, "11:10"), -3100.0),
    ("N6", "CE", -1, 6, (32, "13:50"), (36, "10:50"), 3300.0),
    ("N7", "CE", -1, 6, (36, "14:15"), (40, "10:30"), -2900.0),
    ("N8", "PE", -1, 5, (40, "13:45"), (42, "11:00"), -2700.0),
    ("N9", "CE", -1, 6, (42, "14:20"), (43, "10:45"), -1900.0),
    ("N10", "PE", -1, 5, (43, "13:25"), (46, "10:35"), -3400.0),
    ("N11", "CE", -1, 6, (46, "13:40"), (50, "10:50"), 3500.0),
    ("N12", "PE", -1, 5, (50, "13:30"), (53, "11:10"), -3600.0),
    ("N13", "PE", -1, 5, (53, "13:20"), (54, "10:15"), -5200.0),
]
# scalps: (day, und, cp, side, t_open, pnl, nfills)
SCALPS = [
    (6, "NIFTY", "CE", 1, "09:20", -820.0, 3), (6, "BANKNIFTY", "CE", 1, "09:27", -990.0, 3),
    (6, "NIFTY", "PE", 1, "09:41", 1250.0, 3),
    (8, "NIFTY", "PE", 1, "09:24", -760.0, 2), (8, "NIFTY", "CE", -1, "09:48", -910.0, 2),
    (13, "NIFTY", "CE", 1, "10:05", -680.0, 2), (13, "BANKNIFTY", "PE", 1, "10:40", -1020.0, 2),
    (16, "NIFTY", "PE", -1, "09:22", -870.0, 2), (16, "NIFTY", "CE", 1, "09:50", -740.0, 2),
    (24, "NIFTY", "PE", 1, "09:20", -1030.0, 3), (24, "BANKNIFTY", "CE", 1, "09:45", -880.0, 3),
    (24, "NIFTY", "CE", 1, "10:15", 1070.0, 3),
    (45, "NIFTY", "PE", 1, "09:30", -790.0, 2), (54, "BANKNIFTY", "PE", 1, "09:25", -810.0, 2),
]
BNF_FILL_DAYS = {19: "up", 31: "up", 38: "up", 41: "up", 47: "up", 55: "up",
                 20: "dn", 30: "dn", 35: "dn", 42: "dn", 49: "dn", 51: "dn"}
NO_FILL_DAYS = set(BURST_DAYS) | {10, 27, 28}
N_FILLERS_LOSS = 12


def build_story(mk: Market, lots: dict[str, int], rng: random.Random) -> Sim:
    sim = Sim(mk, lots, rng)

    # ---- swing book (shorts, direction against the move; two flipped winners) ----
    for name, cp, side, off, (d0, t0), (d1, t1), pnl in CORE:
        sim.round_trip("NIFTY", cp, side, off, [(d0, t0, 2)], (d1, t1, 2), pnl,
                       pref=0.18 if pnl < 0 else 0.14, lmin=2, lmax=9, tag=name)

    # ---- S1: SHORT averaging-down chain on NIFTY CE (peak 9 lots), stopped on the 07-17 spike
    s1_strike = sim.strike_for("NIFTY", "CE", 10, 5)
    s1_exp = EXPIRIES[2]                                   # 2026-07-21 weekly
    e1 = model_px("NIFTY", "CE", s1_strike, mk.spot("NIFTY", 10), (s1_exp - mk.d(10)).days)
    sim.chain("NIFTY", "CE", -1, s1_strike, s1_exp,
              [(10, "14:05", 3, 2, 0), (11, "11:20", 3, 2, 0), (12, "11:40", 3, 2, 0)],
              e1, 0.07, [(13, "10:20", 9, 3, -15400.0)], "S1")

    # ---- S2: LONG PE averaging-down chain (10 lots) - drives the cash trough ----
    s2_strike = sim.strike_for("NIFTY", "PE", 12, 10)
    s2_exp = date(2026, 8, 11)                             # weekly expiry AFTER the last exit (08-10)
    e2 = model_px("NIFTY", "PE", s2_strike, mk.spot("NIFTY", 12), (s2_exp - mk.d(12)).days)
    s2_lots = [2, 2, 2, 1, 1, 1, 1]
    s2_when = [(12, "09:55"), (14, "10:15"), (16, "10:20"), (17, "11:15"), (18, "10:40"), (19, "11:30"),
               (20, "10:30")]
    sim.chain("NIFTY", "PE", 1, s2_strike, s2_exp,
              [(d, t, lo, 2, 0) for (d, t), lo in zip(s2_when, s2_lots)],
              e2, -0.045,
              [(27, "11:20", 3, 2, -6200.0), (28, "13:40", 3, 2, -6800.0), (29, "11:30", 4, 2, -7600.0)],
              "S2")

    # ---- hedges: BANKNIFTY long puts (also cash drag) ----
    for tag, off, t_in, d_out, t_out, pnl in (("H1", 14, "12:00", (27, "13:10"), None, -3700.0),
                                              ("H2", 19, "13:10", (28, "10:50"), None, -2900.0)):
        hl = 4 if tag == "H1" else 5
        sim.round_trip("BANKNIFTY", "PE", 1, off, [(14, t_in, 2)], (d_out[0], d_out[1], 2), pnl,
                       pref=0.08, lots=hl, tag=tag, expiry=MONTHLY[1])

    # ---- turn-day BANKNIFTY positions (book against the spike) ----
    for tag, cp, side, d0, t0, d1, t1, pnl, off in (
            ("B1", "PE", -1, 9, "13:40", 10, "11:30", -16200.0, 6),
            ("B2", "CE", -1, 12, "14:00", 13, "11:05", -6300.0, 5),
            ("B4", "PE", -1, 44, "15:00", 45, "09:55", -13100.0, 6),
            ("B5", "PE", -1, 53, "14:30", 54, "09:50", -14400.0, 6)):
        sim.round_trip("BANKNIFTY", cp, side, off, [(d0, t0, 2)], (d1, t1, 2), pnl,
                       pref=0.30, lmin=3, lmax=10, tag=tag)

    # ---- scalps (sub-5-minute) on the burst days ----
    for k, (day, und, cp, side, t0, pnl, nf) in enumerate(SCALPS, 1):
        t1 = hhmm_of(mins(t0) + 3)
        sim.round_trip(und, cp, side, 3 if und == "NIFTY" else 4, [(day, t0, nf)], (day, t1, nf), pnl,
                       pref=0.10, lmin=nf, lmax=nf + 2, tag=f"SC{k}", expiry=None)

    # ---- one more burst-day trade: a stopped-out short on the 08-03 spike ----
    sim.round_trip("NIFTY", "CE", -1, 4, [(24, "10:40", 2)], (24, "11:10", 2), -1350.0,
                   pref=0.40, lmin=2, lmax=4, tag="BX1")

    # ---- held to expiry (settled at spot intrinsic): two worthless shorts, one ITM short ----
    sim.hold_to_expiry("NIFTY", "PE", -1, sim.strike_for("NIFTY", "PE", 31, 14), 31, "10:30",
                       2, 2, date(2026, 8, 18), "E1")
    sim.hold_to_expiry("BANKNIFTY", "PE", -1, sim.strike_for("BANKNIFTY", "PE", 37, 17), 37, "10:45",
                       6, 2, date(2026, 8, 25), "E2")
    sim.hold_to_expiry("NIFTY", "PE", -1, sim.strike_for("NIFTY", "PE", 47, 1), 47, "10:20",
                       1, 1, date(2026, 9, 8), "E3")

    # ---- two positions still open at the window end ----
    o1 = Life("NIFTY", "PE", 22500, date(2026, 10, 27), tag="O1")
    sim.order(o1, 54, "13:30", 1, 2, 2, px=sim.entry_px(o1, 54))
    sim.lives.append(o1)
    o2 = Life("BANKNIFTY", "PE", 54000, date(2026, 10, 27), tag="O2")
    sim.order(o2, 55, "11:10", -1, 3, 2, px=sim.entry_px(o2, 55))
    sim.lives.append(o2)

    add_fillers(sim)
    return sim


def add_fillers(sim: Sim) -> None:
    """43 intraday short-premium trades (31 winners, 12 losers) on quiet days."""
    rng = sim.rng
    bnf_days = sorted(BNF_FILL_DAYS)
    elig = [d for d in range(1, 58) if d not in NO_FILL_DAYS and d not in BNF_FILL_DAYS]
    n_days = sorted(rng.sample(elig, 31))
    plan = [("BANKNIFTY", d) for d in bnf_days] + [("NIFTY", d) for d in n_days]
    plan.sort(key=lambda x: (x[1], x[0]))
    slots: list[tuple[str, int, int, int, int | None]] = []
    for und, day in plan:
        for _ in range(60):
            m0 = sim.free_slot(day, lo=560, hi=700)
            if m0 is None:
                continue
            dur = 45 + int(rng.random() * 200)
            m1 = ((m0 + dur) // 5) * 5
            if m1 > 915 or any(abs(m1 - u) < 35 for u in sim.busy.get(day, [])) or abs(m1 - m0) < 35:
                continue
            m2 = None
            if rng.random() < 0.8:
                cand = m0 + 35 + int(rng.random() * 40)
                cand = (cand // 5) * 5
                if cand + 35 <= m1 and all(abs(cand - u) >= 35 for u in sim.busy.get(day, []) + [m0, m1]):
                    m2 = cand
            sim.busy.setdefault(day, []).extend([m0, m1] + ([m2] if m2 else []))
            slots.append((und, day, m0, m1, m2))
            break
    assert len(slots) == 43, len(slots)

    # outcome flags: pick the 13 losers so the longest losing streak (all closes) is exactly 5
    fixed: list[tuple[int, int, bool]] = []      # (day, minute, is_loss) of every non-filler close
    for life in sim.lives:
        for o in life.orders:
            if o.pnl is not None:
                fixed.append((o.day, mins(o.hhmm), o.pnl < 0))
    order_idx = sorted(range(len(slots)), key=lambda k: (slots[k][1], slots[k][3]))
    for _ in range(400):
        losers = set(rng.sample(range(len(slots)), N_FILLERS_LOSS))
        seq = sorted(fixed + [(slots[k][1], slots[k][3], k in losers) for k in order_idx])
        run = best = 0
        for _d, _m, loss in seq:
            run = run + 1 if loss else 0
            best = max(best, run)
        if best == 5:
            break
    else:
        raise SystemExit("could not find a filler outcome pattern with max losing streak 5")

    raw = []
    for k, (und, day, m0, m1, m2) in enumerate(slots):
        loss = k in losers
        mag = (400.0 + rng.random() * 1300.0) if loss else (1500.0 + rng.random() * 3400.0)
        raw.append((loss, mag))
    fixed_w = sum(o.pnl for lf in sim.lives for o in lf.orders if o.pnl is not None and o.pnl > 0)
    fixed_l = -sum(o.pnl for lf in sim.lives for o in lf.orders if o.pnl is not None and o.pnl < 0)
    sw = (WIN_SUM - fixed_w) / sum(m for is_loss, m in raw if not is_loss)
    sl = (LOSS_SUM - fixed_l) / sum(m for is_loss, m in raw if is_loss)
    sim.scales = (sw, sl)
    for k, (und, day, m0, m1, m2) in enumerate(slots):
        loss, mag = raw[k]
        pnl = -mag * sl if loss else mag * sw
        side = -1 if rng.random() < 0.75 else 1
        cp = "CE" if rng.random() < 0.5 else "PE"
        off = int(rng.random() * 4) if side < 0 else int(rng.random() * 2)
        if und == "BANKNIFTY":
            off = 1 + int(rng.random() * 4) if side < 0 else int(rng.random() * 3)
        if side < 0:
            pref = 0.17 if loss else 0.09
        else:
            pref = 0.14 if loss else 0.16
        opens = [(day, hhmm_of(m0), 2 if rng.random() < 0.9 else 1)]
        if m2:
            opens.append((day, hhmm_of(m2), 1 + int(rng.random() * 2)))
        sim.round_trip(und, cp, side, off, opens, (day, hhmm_of(m1), 2), pnl, pref,
                       lmin=2 if len(opens) > 1 else 1, lmax=16, tag=f"F{k + 1}")


# ── booking: FIFO, prices, fills ──────────────────────────────────────────────

@dataclass
class Booked:
    fills: list[Fill]
    realised: dict[str, int]            # symbol -> measured realised paise
    buy_val: dict[str, int]
    sell_val: dict[str, int]
    buy_qty: dict[str, int]
    open_pos: dict[str, tuple[int, int]]    # symbol -> (signed qty, total cost paise)
    closed: list[tuple[int, int, str, int, int, int]]   # (day, sec, symbol, side, units, pnl paise)
    est: dict[str, int]                 # expiry-settled pnl paise
    settle_cash: dict[int, int]         # day index (expiry) -> cash debit paise (ITM shorts)
    meta: dict[str, Life]


def book(sim: Sim) -> Booked:
    mk, lot = sim.mk, sim.lot
    allo = sorted((o.day, mins(o.hhmm), o.ser, life, o) for life in sim.lives for o in life.orders)
    books: dict[str, list[list[int]]] = {}       # symbol -> list of [qty, px] (open lots, signed side in side_of)
    side_of: dict[str, int] = {}
    fills: list[Fill] = []
    realised: dict[str, int] = {}
    buy_val: dict[str, int] = {}
    sell_val: dict[str, int] = {}
    buy_qty: dict[str, int] = {}
    closed: list[tuple[int, int, str, int, int, int]] = []
    meta: dict[str, Life] = {}
    for day, m, _ser, life, o in allo:
        sym = life.symbol
        meta[sym] = life
        units = o.lots * lot[life.und]
        lots_q = books.setdefault(sym, [])
        pos_side = side_of.get(sym, 0) if lots_q else 0
        n = min(o.nfills, o.lots)
        base, rem = divmod(o.lots, n)
        q_per = [(base + (1 if i < rem else 0)) * lot[life.und] for i in range(n)]
        closing = bool(lots_q) and pos_side != o.side
        if closing:
            assert units <= sum(q for q, _ in lots_q), (sym, day, o.hhmm)
            matched_units = 0
            matched_cost = 0
            need = units
            for q, p in lots_q:
                take = min(q, need)
                matched_units += take
                matched_cost += take * p
                need -= take
                if need == 0:
                    break
            target = int(round((o.pnl or 0.0) * 100.0))
            exit_px = (target * 1.0 / pos_side + matched_cost) / units
            px_close = tick_round(exit_px)
            px_each = [px_close] * n
        else:
            assert o.px > 0
            px_each = [o.px + (TICK if i > 0 else 0) * o.side for i in range(n)]
        pnl_order = 0
        for i in range(n):
            f = Fill(life, o, day, m * 60 + i, o.side, q_per[i], px_each[i])
            fills.append(f)
            if o.side > 0:
                buy_val[sym] = buy_val.get(sym, 0) + f.qty * f.px
                buy_qty[sym] = buy_qty.get(sym, 0) + f.qty
            else:
                sell_val[sym] = sell_val.get(sym, 0) + f.qty * f.px
            if closing:
                need = f.qty
                while need > 0:
                    lq = lots_q[0]
                    take = min(lq[0], need)
                    pnl_order += take * (f.px - lq[1]) * pos_side
                    lq[0] -= take
                    need -= take
                    if lq[0] == 0:
                        lots_q.pop(0)
            else:
                lots_q.append([f.qty, f.px])
                side_of[sym] = o.side
        if closing:
            realised[sym] = realised.get(sym, 0) + pnl_order
            closed.append((day, m * 60, sym, pos_side, units, pnl_order))
    open_pos: dict[str, tuple[int, int]] = {}
    est: dict[str, int] = {}
    settle_cash: dict[int, int] = {}
    day_of = {mk.d(i): i for i in range(1, len(mk.days) + 1)}
    for sym, lots_q in books.items():
        if not lots_q:
            continue
        life = meta[sym]
        qty = sum(q for q, _ in lots_q)
        avg = sum(q * p for q, p in lots_q) / qty
        sd = side_of[sym]
        if life.held_to_expiry:
            close = mk.close[(life.und, life.expiry)]
            intr = max(close - life.strike, 0.0) if life.cp == "CE" else max(life.strike - close, 0.0)
            pnl = int(round(sd * qty * (intr * 100.0 - avg)))
            est[sym] = pnl
            if sd < 0 and intr > 0:
                settle_cash[day_of[life.expiry]] = settle_cash.get(day_of[life.expiry], 0) + \
                    int(round(qty * intr * 100.0))
        else:
            open_pos[sym] = (sd * qty, sum(q * p for q, p in lots_q))
    return Booked(fills, realised, buy_val, sell_val, buy_qty, open_pos, closed, est, settle_cash, meta)


# ── charges, ledger, files ────────────────────────────────────────────────────

def charges_for(fills: list[Fill]) -> dict[int, dict[str, int]]:
    """Per window day: brokerage, exchange, stt, sebi, stamp, gst in paise (Zerodha-style options)."""
    by_day: dict[int, dict[str, int]] = {}
    orders_seen: dict[int, dict[int, int]] = {}
    for f in fills:
        v = f.qty * f.px
        d = by_day.setdefault(f.day, dict.fromkeys(("turn", "buy", "sell", "orders"), 0))
        d["turn"] += v
        d["buy" if f.side > 0 else "sell"] += v
        od = orders_seen.setdefault(f.day, {})
        od[f.order.ser] = od.get(f.order.ser, 0) + v
    out: dict[int, dict[str, int]] = {}
    for day, d in by_day.items():
        brk = sum(min(2000, int(round(v * 0.0003))) for v in orders_seen[day].values())
        exch = int(round(d["turn"] * 0.0003503))
        stt = int(round(d["sell"] * 0.001))
        sebi = int(round(d["turn"] * 0.000001))
        stamp = int(round(d["buy"] * 0.00003))
        gst = int(round((brk + exch + sebi) * 0.18))
        out[day] = {"Brokerage": brk, "Exchange Transaction Charges": exch, "STT/CTT": stt,
                    "SEBI Turnover Fees": sebi, "Stamp Duty": stamp, "GST": gst}
    return out


def ledger_rows(sim: Sim, bk: Booked, ch: dict[int, dict[str, int]]) -> tuple[list[list[str]], dict]:
    mk = sim.mk
    flows: dict[int, list[tuple[str, str, int]]] = {}      # day -> [(particulars, voucher, signed paise)]

    def add(day: int, part: str, voucher: str, amt: int) -> None:
        flows.setdefault(day, []).append((SETTLE_PREFIX + part, voucher, amt))

    add(1, "Opening fund transfer (synthetic)", "Bank Receipts", 20000000)
    add(8, "Fund top-up 1 (synthetic)", "Bank Receipts", 10000000)
    add(30, "Fund top-up 2 (synthetic)", "Bank Receipts", 10000000)
    day_buy: dict[int, int] = {}
    day_sell: dict[int, int] = {}
    for f in bk.fills:
        (day_buy if f.side > 0 else day_sell)[f.day] = (day_buy if f.side > 0 else day_sell).get(f.day, 0) + f.qty * f.px
    for day in sorted(set(day_buy) | set(day_sell)):
        net = day_sell.get(day, 0) - day_buy.get(day, 0) - sum(ch[day].values())
        add(day, "Net obligation for the day F&O", "Book Voucher", net)
    for day, cash in bk.settle_cash.items():
        add(day, "Final settlement of expired contract", "Book Voucher", -cash)
    dp_days = (11, 33, 53)
    for dd in dp_days:
        add(dd, "Account maintenance DP charges", "Journal Entry", -11800)
    rows: list[list[str]] = []
    bal = 0
    cash_path: dict[int, int] = {}
    for day in sorted(flows):
        for part, voucher, amt in flows[day]:
            bal += amt
            deb, cred = (-amt, 0) if amt < 0 else (0, amt)
            rows.append([part, mk.d(day).isoformat(), "SAMPLE F&O", voucher,
                         money(deb) if deb else "", money(cred) if cred else "", money(bal)])
        cash_path[day] = bal
    return rows, {"cash": cash_path, "dp_total": len(dp_days) * 11800, "final": bal}


def tradebook_rows(sim: Sim, bk: Booked) -> list[list[str]]:
    mk = sim.mk
    fills = sorted(bk.fills, key=lambda f: (f.day, f.sec, f.order.ser))
    # ids in time order; order id = SMP + yymmdd + 6-digit serial (12 digits)
    order_ids: dict[int, str] = {}
    seq_by_day: dict[int, int] = {}
    for f in fills:
        if f.order.ser not in order_ids:
            seq_by_day[f.day] = seq_by_day.get(f.day, 0) + 1
            d = mk.d(f.day)
            order_ids[f.order.ser] = f"SMP{d.year % 100:02d}{d.month:02d}{d.day:02d}{seq_by_day[f.day] * 7 + 100000:06d}"
    rng = random.Random(SEED + 7)
    tid = 41000000
    rows = []
    for f in fills:
        tid += 1 + rng.randrange(0, 37)
        d = mk.d(f.day)
        hh, rest = divmod(f.sec, 3600)
        mm, ss = divmod(rest, 60)
        rows.append([f.life.symbol, "", d.isoformat(), "NFO", "FO", "OPT",
                     "buy" if f.side > 0 else "sell", "false", str(f.qty), money(f.px),
                     f"SMP{tid:08d}", order_ids[f.order.ser], f"{d.isoformat()}T{hh:02d}:{mm:02d}:{ss:02d}",
                     f.life.expiry.isoformat()])
    return rows


def pnl_csv(sim: Sim, bk: Booked, ch: dict[int, dict[str, int]], other_dc: int) -> bytes:
    mk = sim.mk
    items: dict[str, int] = {}
    for d in ch.values():
        for k, v in d.items():
            items[k] = items.get(k, 0) + v
    total_ch = sum(items.values())
    syms = sorted(bk.meta)
    realised_total = 0
    unreal_total = 0
    sym_rows = []
    un_p_of: dict[str, int] = {}
    for sym in syms:
        life = bk.meta[sym]
        rl = bk.realised.get(sym, 0) + bk.est.get(sym, 0)
        realised_total += rl
        buy_v, sell_v = bk.buy_val.get(sym, 0), bk.sell_val.get(sym, 0)
        oq, ot, ov, un, prev = "", "", "", "", ""
        if sym in bk.open_pos:
            q, cost = bk.open_pos[sym]
            spot = mk.spot(life.und, 57)
            px = model_px(life.und, life.cp, life.strike, spot, (life.expiry - WINDOW_TO).days)
            un_p = (1 if q > 0 else -1) * (abs(q) * px - cost)
            unreal_total += un_p
            un_p_of[sym] = un_p
            oq, ot, ov = str(abs(q)), ("Long" if q > 0 else "Short"), money(cost)
            un, prev = money(un_p), money(px)
        else:
            oq, ot, ov, un, prev = "0", "", "0.00", "0.00", ""
        pct = money(int(round(rl * 10000.0 / buy_v))) if buy_v else "0.00"
        un_pct = "0.00"
        if sym in bk.open_pos:
            un_pct = money(int(round(un_p_of[sym] * 10000.0 / bk.open_pos[sym][1])))
        sym_rows.append([sym, "", str(bk.buy_qty.get(sym, 0)), money(buy_v), money(sell_v), money(rl), pct,
                         prev, oq, ot, ov, un, un_pct])
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["Client ID", "SAMPLE-DEMO"])
    w.writerow(["Synthetic P&L statement - not a real account", ""])
    w.writerow([f"P&L Statement for F&O from {WINDOW_FROM.isoformat()} to {WINDOW_TO.isoformat()}"])
    w.writerow([])
    w.writerow(["", "Charges", money(total_ch)])
    w.writerow(["", "Other Credit & Debit", money(-other_dc)])
    w.writerow(["", "Realized P&L", money(realised_total)])
    w.writerow(["", "Unrealized P&L", money(unreal_total)])
    w.writerow([])
    for k in ("Brokerage", "Exchange Transaction Charges", "Clearing Charges", "GST", "STT/CTT",
              "SEBI Turnover Fees", "Stamp Duty"):
        w.writerow(["", k, money(items.get(k, 0))])
    w.writerow([])
    w.writerow(["Symbol", "ISIN", "Quantity", "Buy Value", "Sell Value", "Realized P&L",
                "Realized P&L Pct.", "Previous Closing Price", "Open Quantity", "Open Quantity Type",
                "Open Value", "Unrealized P&L", "Unrealized P&L Pct."])
    w.writerows(sym_rows)
    return out.getvalue().encode("utf-8")


def to_csv(header: list[str], rows: list[list[str]]) -> bytes:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return out.getvalue().encode("utf-8")


TB_HEADER = ["symbol", "isin", "trade_date", "exchange", "segment", "series", "trade_type", "auction",
             "quantity", "price", "trade_id", "order_id", "order_execution_time", "expiry_date"]
LG_HEADER = ["particulars", "posting_date", "cost_center", "voucher_type", "debit", "credit", "net_balance"]


def generate(closes: Path, nifty_lot: int, banknifty_lot: int,
             seed: int = SEED) -> tuple[dict[str, bytes], dict]:
    mk = Market(closes)
    rng = random.Random(seed)
    sim = build_story(mk, {"NIFTY": nifty_lot, "BANKNIFTY": banknifty_lot}, rng)
    bk = book(sim)
    ch = charges_for(bk.fills)
    lrows, lstat = ledger_rows(sim, bk, ch)
    files = {
        "SAMPLE_tradebook.csv": to_csv(TB_HEADER, tradebook_rows(sim, bk)),
        "SAMPLE_ledger.csv": to_csv(LG_HEADER, lrows),
        "SAMPLE_pnl.csv": pnl_csv(sim, bk, ch, lstat["dp_total"]),
    }
    wins = [p for *_a, p in bk.closed if p > 0]
    losses = [-p for *_a, p in bk.closed if p < 0]
    seq = sorted(bk.closed, key=lambda c: (c[0], c[1]))
    run = best = 0
    for c in seq:
        run = run + 1 if c[5] < 0 else 0
        best = max(best, run)
    info = {
        "fills": len(bk.fills), "closed": len(bk.closed), "wins": len(wins), "losses": len(losses),
        "win_sum": sum(wins) / 100.0, "loss_sum": sum(losses) / 100.0,
        "measured": sum(p for *_a, p in bk.closed) / 100.0, "est": sum(bk.est.values()) / 100.0,
        "charges": sum(sum(d.values()) for d in ch.values()) / 100.0, "max_streak": best,
        "cash_min": min(lstat["cash"].values()) / 100.0, "cash_final": lstat["final"] / 100.0,
        "cash": {mk.d(k).isoformat(): v / 100.0 for k, v in sorted(lstat["cash"].items())},
        "scales": sim.scales,
    }
    return files, info


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate the F42 P5 synthetic Console sample files.")
    ap.add_argument("--nifty-lot", type=int, required=True, help="NIFTY lot size (settings.instruments.nifty.lot_size)")
    ap.add_argument("--banknifty-lot", type=int, required=True,
                    help="BANKNIFTY lot size (settings.instruments.banknifty.lot_size)")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--closes", type=Path, default=DEFAULT_CLOSES)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--report", action="store_true", help="print a short self-check summary")
    a = ap.parse_args(argv)
    files, info = generate(a.closes, a.nifty_lot, a.banknifty_lot, a.seed)
    a.out.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (a.out / name).write_bytes(data)
    if a.report:
        for k, v in info.items():
            if k != "cash":
                sys.stdout.write(f"{k}: {v}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
