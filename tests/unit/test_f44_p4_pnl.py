"""F44 P4 — ``portfolio.pnl`` (PortfolioPnlService) and the target path (rev 1 B2/B4, rev 2 N1,
rev 3): target_to_date formula + property, model-sleeve series, ytd kept across an accept,
segments chained, saved-after-s mixed chain, the untracked preview, saved P&L money figures.
"""
# ruff: noqa: F811 — pytest fixtures imported from a sibling module are redefined as test params
from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from rita.core.goal_targets import chain_returns, required_return, target_to_date
from rita.models.market_data import MarketDataCacheModel
from rita.models.user import UserModel
from rita.models.user_portfolio import UserPortfolioModel
from rita.models.user_portfolio_key import UserPortfolioKeyModel
from rita.services.portfolio_pnl_service import PnlError, PortfolioPnlService

from .f44_p3_helpers import fixed_run
from .f44_p4_helpers import journey_db  # noqa: F401 — fixture

YEAR = 2026
DATES = pd.bdate_range(f"{YEAR - 1}-12-01", f"{YEAR}-06-30")


# ── B2 target to date ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("r,s,as_of,days,D", [
    (0.08, date(2026, 1, 1), date(2026, 12, 31), 365, 365),
    (0.08, date(2024, 1, 1), date(2024, 12, 31), 366, 366),          # leap year
    (0.08, date(2026, 1, 1), date(2026, 1, 1), 1, 365),              # Jan 1
    (0.10, date(2026, 6, 15), date(2026, 9, 30), 108, 365),          # mid-year entry
])
def test_target_to_date_formula(r, s, as_of, days, D):
    assert target_to_date(r, s, as_of) == pytest.approx((1 + r) ** (days / D) - 1, rel=1e-12)


def test_target_to_date_before_start_is_zero():
    assert target_to_date(0.08, date(2026, 3, 1), date(2026, 2, 28)) == 0.0
    assert target_to_date(0.08, date(2026, 3, 1), date(2026, 1, 1)) == 0.0


@pytest.mark.parametrize("s,as_of", [(date(2026, 1, 1), date(2026, 4, 30)), (date(2026, 6, 15), date(2026, 9, 30)),
                                     (date(2024, 2, 29), date(2024, 11, 1))])
@pytest.mark.parametrize("r", [0.05, 0.0775, 0.12])
def test_on_the_path_means_required_equals_goal(r, s, as_of):
    t = target_to_date(r, s, as_of)
    rr = required_return(r, t, as_of, s)
    assert rr.required_return == pytest.approx(r, rel=1e-9)


def test_chain_returns():
    assert chain_returns([-0.08, 0.02]) == pytest.approx(0.92 * 1.02 - 1)
    assert chain_returns([]) == 0.0


# ── fixtures ───────────────────────────────────────────────────────────────────

def _rets(seed: int, n: int, drift: float = 0.0006) -> np.ndarray:
    return drift + np.random.default_rng(seed).normal(0, 0.008, n)


class FakeGoal:
    """``GoalSelectionService.instrument_runs`` stand-in over fixed sleeve returns."""

    def __init__(self, rets: dict[str, np.ndarray]):
        self.runs = {i: {t: fixed_run(i, r, DATES, tolerance=t) for t in ("low", "medium", "high")}
                     for i, r in rets.items()}

    def instrument_runs(self, inst):
        if inst not in self.runs:
            return SimpleNamespace(excluded=SimpleNamespace(reason="no_model"), runs={})
        return SimpleNamespace(excluded=None, runs=self.runs[inst])


def _seg(frm, to, hs, cause="track"):
    return {"from": frm.isoformat(), "to": to.isoformat() if to else None, "cause": cause,
            "holdings": [{"instrument_id": i, "allocation_pct": p, "tolerance": "medium"} for i, p in hs]}


def _growth(r: np.ndarray, start: date, end: date) -> float:
    s = pd.Series(r, index=DATES)
    s = s[(s.index > pd.Timestamp(start)) & (s.index <= pd.Timestamp(end))]
    return float((1 + s).prod() - 1)


@pytest.fixture
def pnl_db(journey_db):
    db = journey_db
    db.add(UserModel(id="alice"))
    db.add(UserPortfolioKeyModel(key_id="k1", user_id="alice"))
    db.commit()
    return db


def _closes(db, inst: str, path: np.ndarray):
    for d, c in zip(DATES, path):
        db.add(MarketDataCacheModel(cache_id=f"{inst}-{d.date()}", date=d.date(), underlying=inst, open=c, high=c,
                                    low=c, close=float(c), recorded_at=datetime(2026, 7, 1)))
    db.commit()


def _portfolio(db, pid: str, created: date, holdings: list[dict], active: bool = True):
    db.add(UserPortfolioModel(portfolio_id=pid, key_id="k1", name=pid, holdings=holdings, currency="EUR",
                              location="europe", total_value=10000.0, created_at=datetime.combine(created, datetime.min.time()),
                              is_active=active))
    db.commit()


# ── model sleeves ──────────────────────────────────────────────────────────────

def test_pnl_model_sleeves_series(pnl_db):
    r1, r2 = _rets(1, len(DATES)), _rets(2, len(DATES))
    svc = PortfolioPnlService(pnl_db, goal=FakeGoal({"E1": r1, "E2": r2}))
    s = date(YEAR, 2, 2)
    out = svc.pnl("alice", "europe", goal_return=0.08, source="model_sleeves", year_start=s,
                  segments=[_seg(s, None, [("E1", 60), ("E2", 40)])])
    assert out.source == "model_sleeves" and out.money is None and out.coverage == 1.0
    assert out.year_start == s and out.as_of == DATES[-1].date()
    assert out.series[0].date == s and out.series[0].ret == 0.0
    exp = 0.6 * (1 + _growth(r1, s, out.as_of)) + 0.4 * (1 + _growth(r2, s, out.as_of)) - 1   # buy-and-drift
    assert out.ytd_return == pytest.approx(exp, rel=1e-9) and out.series[-1].ret == pytest.approx(exp, rel=1e-9)
    assert out.target_to_date == pytest.approx(target_to_date(0.08, s, out.as_of))
    assert len(out.target_path) == len(out.series)
    assert {h.instrument_id: h.status for h in out.holdings} == {"E1": "ok", "E2": "ok"}


def test_uncovered_instrument_lowers_coverage(pnl_db):
    svc = PortfolioPnlService(pnl_db, goal=FakeGoal({"E1": _rets(1, len(DATES))}))
    s = date(YEAR, 2, 2)
    out = svc.pnl("alice", "europe", source="model_sleeves", year_start=s,
                  segments=[_seg(s, None, [("E1", 75), ("ATO", 25)])])
    assert out.coverage == 0.75 and {h.instrument_id: h.status for h in out.holdings}["ATO"] == "excluded"


def test_ytd_keeps_loss_across_accept(pnl_db):
    """−8 % in segment 1, accept, +2 % in segment 2 → ytd = 0.92·1.02 − 1 with s unchanged."""
    s, acc = date(YEAR, 2, 2), date(YEAR, 4, 1)
    n = len(DATES)
    i_s = int(np.searchsorted(DATES, pd.Timestamp(s), side="right"))
    i_a = int(np.searchsorted(DATES, pd.Timestamp(acc), side="right"))
    r1 = np.zeros(n)
    r1[i_s:i_a] = (0.92) ** (1 / (i_a - i_s)) - 1             # E1 loses 8 % over segment 1
    r1[i_a:] = 0.05                                            # … and would have rallied after
    r2 = np.zeros(n)
    r2[i_a:] = 1.02 ** (1 / (n - i_a)) - 1                    # E2 gains 2 % over segment 2
    svc = PortfolioPnlService(pnl_db, goal=FakeGoal({"E1": r1, "E2": r2}))
    segs = [_seg(s, acc, [("E1", 100)]), _seg(acc, None, [("E2", 100)], "accept")]
    out = svc.pnl("alice", "europe", goal_return=0.08, source="model_sleeves", year_start=s, segments=segs)
    assert out.year_start == s
    assert out.ytd_return == pytest.approx(0.92 * 1.02 - 1, rel=1e-9)
    rr = required_return(0.08, out.ytd_return, out.as_of, s)     # the guard sees the same s and ytd
    assert rr.required_return > 0.08


def test_sleeve_series_chained_by_segment(pnl_db):
    r1, r2 = _rets(3, len(DATES)), _rets(4, len(DATES))
    s, acc = date(YEAR, 1, 2), date(YEAR, 3, 16)
    svc = PortfolioPnlService(pnl_db, goal=FakeGoal({"E1": r1, "E2": r2}))
    out = svc.pnl("alice", "europe", source="model_sleeves", year_start=s,
                  segments=[_seg(s, acc, [("E1", 100)]), _seg(acc, None, [("E2", 100)], "accept")])
    g1, g2 = _growth(r1, s, acc), _growth(r2, acc, out.as_of)
    at_acc = next(p.ret for p in out.series if p.date == acc)
    assert at_acc == pytest.approx(g1, rel=1e-9)                # segment 1 path up to the switch
    assert out.ytd_return == pytest.approx((1 + g1) * (1 + g2) - 1, rel=1e-9)
    assert [p.date for p in out.series] == sorted({p.date for p in out.series})   # one point per day


def test_untracked_preview_from_jan1(pnl_db):
    r1 = _rets(5, len(DATES))
    svc = PortfolioPnlService(pnl_db, goal=FakeGoal({"E1": r1}))
    out = svc.pnl("alice", "europe", goal_return=0.08, source="model_sleeves", preview=True,
                  segments=[_seg(date(YEAR, 5, 1), None, [("E1", 100)], "preview")])
    assert out.source == "model_sleeves_preview" and out.year_start == date(YEAR, 1, 1)
    assert out.ytd_return == pytest.approx(_growth(r1, date(YEAR, 1, 1), out.as_of), rel=1e-9)


def test_no_portfolio_no_segments_is_not_found(pnl_db):
    with pytest.raises(PnlError) as e:
        PortfolioPnlService(pnl_db, goal=FakeGoal({})).pnl("alice", "europe")
    assert e.value.code == "not_found"


# ── saved portfolio ────────────────────────────────────────────────────────────

def _path(seed: int, start: float = 100.0) -> np.ndarray:
    return start * np.cumprod(1 + _rets(seed, len(DATES), 0.0004))


def test_saved_portfolio_money_and_ytd(pnl_db):
    p1, p2 = _path(7), _path(8, 50.0)
    _closes(pnl_db, "E1", p1)
    _closes(pnl_db, "E2", p2)
    created = date(YEAR, 2, 10)
    _portfolio(pnl_db, "pf1", created, [{"instrument_id": "E1", "allocation_pct": 60, "shares": 10, "cash": 5.0},
                                        {"instrument_id": "E2", "allocation_pct": 40, "shares": 20}])
    out = PortfolioPnlService(pnl_db, goal=FakeGoal({})).pnl("alice", "europe", goal_return=0.08)
    s = pd.Series(10 * p1 + 20 * p2, index=DATES)
    base = s[s.index <= pd.Timestamp(created)].iloc[-1]
    assert out.source == "saved" and out.year_start == created and out.entry_date == created
    assert out.ytd_return == pytest.approx((s.iloc[-1] + 5.0) / (base + 5.0) - 1, rel=1e-9)
    m = out.money
    assert m.portfolio_id == "pf1" and m.cash == 5.0 and m.value_now == pytest.approx(s.iloc[-1] + 5.0)
    assert m.pnl == pytest.approx(m.value_now - m.value_entry) and len(m.holdings) == 2
    assert m.holdings[0].pnl == pytest.approx(10 * (p1[-1] - p1[DATES <= pd.Timestamp(created)][-1]))
    assert out.coverage == 1.0 and {h.status for h in out.holdings} == {"ok"}


def test_saved_after_s_mixed_chain(pnl_db):
    """[s, created_at) from the segment's sleeves, [created_at, as_of] from the saved path."""
    r1 = _rets(9, len(DATES))
    p1 = _path(10)
    _closes(pnl_db, "E1", p1)
    s, created = date(YEAR, 1, 5), date(YEAR, 3, 2)
    _portfolio(pnl_db, "pf1", created, [{"instrument_id": "E1", "allocation_pct": 100, "shares": 3}])
    svc = PortfolioPnlService(pnl_db, goal=FakeGoal({"E1": r1}))
    out = svc.pnl("alice", "europe", goal_return=0.08, year_start=s, segments=[_seg(s, None, [("E1", 100)])])
    assert out.source == "mixed" and out.year_start == s
    sleeve = _growth(r1, s, created)
    closes = pd.Series(p1, index=DATES)
    saved = closes.iloc[-1] / closes[closes.index <= pd.Timestamp(created)].iloc[-1] - 1
    assert out.ytd_return == pytest.approx((1 + sleeve) * (1 + saved) - 1, rel=1e-9)
    srcs = [p.source for p in out.series]
    assert srcs[0] == "model_sleeves" and srcs[-1] == "saved" and srcs == sorted(srcs)   # sleeves then saved
    assert out.money is not None and out.entry_date == created


def test_resave_chains_rows(pnl_db):
    p1, p2 = _path(11), _path(12)
    _closes(pnl_db, "E1", p1)
    _closes(pnl_db, "E2", p2)
    a, b = date(YEAR, 1, 20), date(YEAR, 4, 6)
    _portfolio(pnl_db, "old", a, [{"instrument_id": "E1", "allocation_pct": 100, "shares": 5}], active=False)
    _portfolio(pnl_db, "new", b, [{"instrument_id": "E2", "allocation_pct": 100, "shares": 7}])
    out = PortfolioPnlService(pnl_db, goal=FakeGoal({})).pnl("alice", "europe")
    c1, c2 = pd.Series(p1, index=DATES), pd.Series(p2, index=DATES)

    def ret(c, x, y):
        return c[c.index <= pd.Timestamp(y)].iloc[-1] / c[c.index <= pd.Timestamp(x)].iloc[-1] - 1

    exp = (1 + ret(c1, a, b)) * (1 + ret(c2, b, DATES[-1])) - 1
    assert out.ytd_return == pytest.approx(exp, rel=1e-9) and out.money.portfolio_id == "new"


def test_resave_to_all_cash_keeps_the_year_path_to_as_of(pnl_db):
    """P4b fix: a re-save whose holdings all have 0 shares is all cash — its value is flat at the
    cash, so the chained year path runs to as_of (it used to stop at the previous row's last bar
    and show a stale June return as "this year")."""
    p1 = _path(13)
    _closes(pnl_db, "E1", p1)
    a, b = date(YEAR, 1, 20), date(YEAR, 4, 6)
    _portfolio(pnl_db, "old", a, [{"instrument_id": "E1", "allocation_pct": 100, "shares": 5}], active=False)
    _portfolio(pnl_db, "cash", b, [{"instrument_id": "E1", "allocation_pct": 100, "shares": 0, "cash": 750.0}])
    out = PortfolioPnlService(pnl_db, goal=FakeGoal({})).pnl("alice", "europe")
    c1 = pd.Series(p1, index=DATES)
    held = c1[c1.index <= pd.Timestamp(b)].iloc[-1] / c1[c1.index <= pd.Timestamp(a)].iloc[-1] - 1
    assert out.as_of == DATES[-1].date()
    assert out.ytd_return == pytest.approx(held, rel=1e-9)                 # flat after the all-cash re-save
    assert out.money.portfolio_id == "cash" and out.money.value_now == pytest.approx(750.0)
    assert out.money.pnl == pytest.approx(0.0)


def test_row_without_share_counts_still_has_no_value_path(pnl_db):
    """Pre-P2 rows with no ``shares`` key stay unpriced (unknown, not cash)."""
    _closes(pnl_db, "E1", _path(14))
    _portfolio(pnl_db, "old", date(YEAR, 1, 20), [{"instrument_id": "E1", "allocation_pct": 100, "cash": 10.0}])
    out = PortfolioPnlService(pnl_db, goal=FakeGoal({})).pnl("alice", "europe")
    assert out.ytd_return is None and out.money.value_now is None
