"""Synthetic builders for F42 P3 analytics tests (invented symbols, round numbers only)."""
from __future__ import annotations

import itertools
from datetime import date, datetime
from typing import Optional

from rita.config import TradeAnalysisSettings
from rita.services import fno_trade_analytics as an
from rita.services.fno_trade_fifo import Fill, SpotSeries, run_fifo

_ids = itertools.count(1)
D = date.fromisoformat


def dt(day: str, hhmm: str = "10:00") -> datetime:
    return datetime.fromisoformat(f"{day}T{hhmm}:00")


def fill(side: str, qty: int, price: float, day: str, hhmm: Optional[str] = "10:00",
         symbol: str = "NIFTY26OCT24000CE", underlying: str = "NIFTY", itype: str = "CE",
         strike: Optional[float] = 24000.0, expiry: Optional[str] = "2026-10-27",
         oid: Optional[str] = None, tid: Optional[str] = None) -> Fill:
    n = next(_ids)
    return Fill(
        symbol=symbol, underlying=underlying, itype=itype, strike=strike,
        expiry_eff=D(expiry) if expiry else None, expiry_ym=expiry[:7] if expiry else "2026-10",
        trade_date=D(day), exec_dt=dt(day, hhmm) if hhmm else None,
        sign=1 if side == "buy" else -1, qty=qty, price=price,
        trade_id=tid or f"T{n}", order_id=oid or f"O{n}")


def cfg(**kw) -> TradeAnalysisSettings:
    return TradeAnalysisSettings(**kw)


def spot(**series: list[tuple[str, float]]) -> dict[str, SpotSeries]:
    return {k: SpotSeries((D(d), c) for d, c in v) for k, v in series.items()}


def fifo(fills, date_from="2026-07-01", as_of="2026-10-05", sp=None):
    return run_fifo(fills, window_start=D(date_from), as_of=D(as_of), spot=sp or {})


def ctx(fills, date_from="2026-07-01", date_to="2026-10-05", include_est=True, sp=None, c=None):
    res = fifo(fills, date_from, date_to, sp)
    return an.make_ctx(res, c or cfg(), D(date_from), D(date_to), include_est, sp or {})


# ── DB seeding (service / API tests) ──────────────────────────────────────────

def seed(db, user_id: str, fills, spot_rows=None, ledger_rows=None, pnl_lines=None, charges=None):
    """Insert synthetic rows through the ORM; ``fills`` are Fill dataclasses."""
    from rita.models.fno_import import (
        FnoImportRunModel, FnoLedgerEntryModel, FnoPnlChargeModel, FnoPnlLineModel, FnoTradeModel,
    )
    from rita.models.market_data import MarketDataCacheModel

    run = FnoImportRunModel(user_id=user_id, kind="tradebook", file_name="synthetic.csv",
                            file_sha256="0" * 64, file_size=1, status="ok")
    db.add(run)
    db.flush()
    for f in fills:
        db.add(FnoTradeModel(
            user_id=user_id, import_run_id=run.id, symbol=f.symbol, trade_date=f.trade_date,
            trade_type="buy" if f.sign > 0 else "sell", quantity=f.qty, price=f.price,
            trade_id=f.trade_id, order_id=f.order_id, order_execution_time=f.exec_dt,
            expiry_date=f.expiry_eff, underlying=f.underlying, instrument_type=f.itype,
            strike=f.strike, opt_expiry=f.expiry_eff, expiry_ym=f.expiry_ym, parse_status="ok"))
    for u, d, c in spot_rows or []:
        db.add(MarketDataCacheModel(cache_id=f"{u}-{d}", date=D(d), underlying=u, open=c, high=c, low=c,
                                    close=c, recorded_at=datetime(2026, 10, 1)))
    for i, (d, deb, cred, nb) in enumerate(ledger_rows or []):
        db.add(FnoLedgerEntryModel(user_id=user_id, import_run_id=run.id, particulars="synthetic",
                                   posting_date=D(d), debit=deb, credit=cred, net_balance=nb,
                                   content_hash=f"h{i}", occurrence=0))
    for (sym, und, ym, pf, pt, realised, oq, ot) in pnl_lines or []:
        db.add(FnoPnlLineModel(user_id=user_id, import_run_id=run.id, symbol=sym, period_from=D(pf),
                               period_to=D(pt), realized_pnl=realised, open_quantity=oq,
                               open_quantity_type=ot, underlying=und, instrument_type="CE", expiry_ym=ym))
    for (pf, pt, section, item, amount) in charges or []:
        db.add(FnoPnlChargeModel(user_id=user_id, import_run_id=run.id, period_from=D(pf), period_to=D(pt),
                                 section=section, item=item, amount=amount))
    db.commit()
