"""Repositories for the personal_fno_* Console-import tables (F42 Phase 2).

ADR-002: data access only.  NO commit anywhere (FnoImportService commits once per file).
PERSONAL DATA: every method takes ``user_id`` as a required argument and filters on it.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Iterable, Optional

from sqlalchemy import case, delete, func, select
from sqlalchemy.orm import Session

from rita.models.fno_import import (
    FnoImportRunModel as Run,
    FnoLedgerEntryModel as Ledger,
    FnoPnlChargeModel as Charge,
    FnoPnlLineModel as Line,
    FnoTradeModel as Trade,
)

_CHUNK = 500  # stay well under the SQLite bound-variable limit


def _chunks(items: list, n: int = _CHUNK) -> Iterable[list]:
    for i in range(0, len(items), n):
        yield items[i:i + n]


def _bulk(db: Session, model: type, user_id: str, run_id: str, rows: list[dict]) -> int:
    for chunk in _chunks(rows):
        db.bulk_insert_mappings(model, [
            {**r, "id": str(uuid.uuid4()), "user_id": user_id, "import_run_id": run_id}
            for r in chunk
        ])
    return len(rows)


class FnoImportRunRepo:
    def __init__(self, db: Session) -> None:
        self._db = db

    def add(self, run: Run) -> Run:
        self._db.add(run)
        self._db.flush()
        return run

    def recent(self, user_id: str, limit: int = 20) -> list[Run]:
        q = select(Run).where(Run.user_id == user_id)
        return list(self._db.scalars(q.order_by(Run.created_at.desc(), Run.id.desc()).limit(limit)))

    def last_by_kind(self, user_id: str, kind: str) -> Optional[Run]:
        q = select(Run).where(Run.user_id == user_id, Run.kind == kind, Run.status != "failed")
        return self._db.scalars(q.order_by(Run.created_at.desc(), Run.id.desc()).limit(1)).first()

    def purge(self, user_id: str, kind: Optional[str] = None) -> int:
        stmt = delete(Run).where(Run.user_id == user_id)
        if kind:
            stmt = stmt.where(Run.kind == kind)
        return self._db.execute(stmt).rowcount or 0


class FnoTradeRepo:
    def __init__(self, db: Session) -> None:
        self._db = db

    def existing_keys(self, user_id: str, keys: list[tuple[str, str, date]]) -> set[tuple]:
        found: set[tuple] = set()
        for chunk in _chunks(sorted({k[0] for k in keys}), 400):
            q = select(Trade.trade_id, Trade.order_id, Trade.trade_date).where(
                Trade.user_id == user_id, Trade.trade_id.in_(chunk))
            found.update((r[0], r[1], r[2]) for r in self._db.execute(q))
        return found & set(keys)

    def insert_new(self, user_id: str, run_id: str, rows: list[dict]) -> int:
        return _bulk(self._db, Trade, user_id, run_id, rows)

    def _scope(self, user_id: str, underlyings: list[str], months: list[str], date_from: Optional[date],
               date_to: Optional[date], include_fut: bool, underlying: Optional[str],
               side: Optional[str]) -> list[Any]:
        types = ["CE", "PE"] + (["FUT"] if include_fut else [])
        conds: list[Any] = [
            Trade.user_id == user_id,
            Trade.underlying.in_([underlying] if underlying else underlyings),
            Trade.instrument_type.in_(types),
            Trade.expiry_ym.in_(months),
        ]
        if date_from:
            conds.append(Trade.trade_date >= date_from)
        if date_to:
            conds.append(Trade.trade_date <= date_to)
        if side:
            conds.append(Trade.trade_type == side)
        return conds

    def page(self, user_id: str, underlyings: list[str], months: list[str],
             date_from: Optional[date], date_to: Optional[date], include_fut: bool,
             underlying: Optional[str], side: Optional[str], sort_desc: bool,
             page: int, page_size: int) -> tuple[int, list[Trade]]:
        conds = self._scope(user_id, underlyings, months, date_from, date_to, include_fut,
                            underlying, side)
        total = self._db.scalar(select(func.count()).select_from(Trade).where(*conds)) or 0
        order = (Trade.trade_date.desc(), Trade.order_execution_time.desc(), Trade.id.desc()) \
            if sort_desc else (Trade.trade_date.asc(), Trade.order_execution_time.asc(), Trade.id.asc())
        q = select(Trade).where(*conds).order_by(*order).offset((page - 1) * page_size).limit(page_size)
        return total, list(self._db.scalars(q))

    def coverage(self, user_id: str) -> dict[str, Any]:
        q = select(
            func.count(), func.min(Trade.trade_date), func.max(Trade.trade_date),
            func.sum(case((Trade.instrument_type == "FUT", 1), else_=0)),
            func.sum(case((Trade.instrument_type.in_(["CE", "PE"]), 1), else_=0)),
            func.sum(case((Trade.parse_status == "unparsed", 1), else_=0)),
        ).where(Trade.user_id == user_id)
        n, first, last, fut, opt, unp = self._db.execute(q).one()
        return {"count": n or 0, "first_date": first, "last_date": last,
                "fut_count": int(fut or 0), "option_count": int(opt or 0),
                "unparsed_count": int(unp or 0)}

    def count_in_scope(self, user_id: str, underlyings: list[str], months: list[str],
                       date_from: Optional[date]) -> int:
        conds = self._scope(user_id, underlyings, months, date_from, None, False, None, None)
        return self._db.scalar(select(func.count()).select_from(Trade).where(*conds)) or 0

    # ── F42 Phase 3 analytics reads (read-only; user_id required) ────────────
    def fills_for_analysis(self, user_id: str, underlyings: list[str], months: list[str],
                           date_to: date) -> list[Trade]:
        """CE/PE fills in scope up to date_to (NO date_from: FIFO needs the full history),
        ordered by the FIFO key (date, execution time, order id, trade id)."""
        q = select(Trade).where(
            Trade.user_id == user_id, Trade.underlying.in_(underlyings),
            Trade.instrument_type.in_(["CE", "PE"]), Trade.expiry_ym.in_(months),
            Trade.trade_date <= date_to,
        ).order_by(Trade.trade_date.asc(), Trade.order_execution_time.asc(),
                   Trade.order_id.asc(), Trade.trade_id.asc())
        return list(self._db.scalars(q))

    def turnover(self, user_id: str, date_from: date, date_to: date) -> float:
        """Sum of quantity x price over ALL the user's fills (any instrument) in the range."""
        q = select(func.sum(Trade.quantity * Trade.price)).where(
            Trade.user_id == user_id, Trade.trade_date >= date_from, Trade.trade_date <= date_to)
        return float(self._db.scalar(q) or 0.0)

    def unparsed_count(self, user_id: str, date_from: date) -> int:
        q = select(func.count()).select_from(Trade).where(
            Trade.user_id == user_id, Trade.parse_status == "unparsed",
            Trade.trade_date >= date_from)
        return int(self._db.scalar(q) or 0)

    def purge(self, user_id: str) -> int:
        return self._db.execute(delete(Trade).where(Trade.user_id == user_id)).rowcount or 0


class FnoPnlRepo:
    def __init__(self, db: Session) -> None:
        self._db = db

    def line_symbols(self, user_id: str, pf: date, pt: date) -> set[str]:
        q = select(Line.symbol).where(Line.user_id == user_id, Line.period_from == pf,
                                      Line.period_to == pt)
        return set(self._db.scalars(q))

    def charge_keys(self, user_id: str, pf: date, pt: date) -> set[tuple]:
        q = select(Charge.section, Charge.item, Charge.entry_date).where(
            Charge.user_id == user_id, Charge.period_from == pf, Charge.period_to == pt)
        return {(r[0], r[1], r[2]) for r in self._db.execute(q)}

    def delete_period(self, user_id: str, pf: date, pt: date) -> None:
        for m in (Line, Charge):
            self._db.execute(delete(m).where(m.user_id == user_id, m.period_from == pf,
                                             m.period_to == pt))

    def insert_lines(self, user_id: str, run_id: str, rows: list[dict]) -> int:
        return _bulk(self._db, Line, user_id, run_id, rows)

    def insert_charges(self, user_id: str, run_id: str, rows: list[dict]) -> int:
        return _bulk(self._db, Charge, user_id, run_id, rows)

    def coverage(self, user_id: str) -> dict[str, Any]:
        n = self._db.scalar(select(func.count()).select_from(Line).where(Line.user_id == user_id)) or 0
        q = select(Line.period_from, Line.period_to).where(Line.user_id == user_id).distinct() \
            .order_by(Line.period_from, Line.period_to)
        return {"line_count": n, "periods": [(r[0], r[1]) for r in self._db.execute(q)]}

    def lines_for_scope(self, user_id: str, underlyings: list[str], months: list[str]) -> list[Line]:
        q = select(Line).where(
            Line.user_id == user_id, Line.underlying.in_(underlyings),
            Line.instrument_type.in_(["CE", "PE"]), Line.expiry_ym.in_(months),
        ).order_by(Line.period_from.asc(), Line.period_to.asc(), Line.symbol.asc())
        return list(self._db.scalars(q))

    def charge_summary(self, user_id: str) -> list[Charge]:
        """Summary + charges rows (all periods) for the charges estimate."""
        q = select(Charge).where(
            Charge.user_id == user_id, Charge.section.in_(["summary", "charges"]),
        ).order_by(Charge.period_from.asc(), Charge.period_to.asc(), Charge.item.asc())
        return list(self._db.scalars(q))

    def purge(self, user_id: str) -> tuple[int, int]:
        a = self._db.execute(delete(Line).where(Line.user_id == user_id)).rowcount or 0
        b = self._db.execute(delete(Charge).where(Charge.user_id == user_id)).rowcount or 0
        return a, b


class FnoLedgerRepo:
    def __init__(self, db: Session) -> None:
        self._db = db

    def existing_counts(self, user_id: str, dfrom: date, dto: date) -> dict[tuple, int]:
        q = select(Ledger.posting_date, Ledger.content_hash, func.count()).where(
            Ledger.user_id == user_id, Ledger.posting_date >= dfrom, Ledger.posting_date <= dto,
        ).group_by(Ledger.posting_date, Ledger.content_hash)
        return {(r[0], r[1]): r[2] for r in self._db.execute(q)}

    def insert_new(self, user_id: str, run_id: str, rows: list[dict]) -> int:
        return _bulk(self._db, Ledger, user_id, run_id, rows)

    def coverage(self, user_id: str) -> dict[str, Any]:
        q = select(func.count(), func.min(Ledger.posting_date), func.max(Ledger.posting_date)) \
            .where(Ledger.user_id == user_id)
        n, first, last = self._db.execute(q).one()
        return {"count": n or 0, "first_date": first, "last_date": last}

    def series(self, user_id: str, date_from: date, date_to: date) -> list[Ledger]:
        """Ledger rows in range, in import order within a posting date."""
        q = select(Ledger).where(
            Ledger.user_id == user_id, Ledger.posting_date >= date_from,
            Ledger.posting_date <= date_to,
        ).order_by(Ledger.posting_date.asc(), Ledger.created_at.asc(), Ledger.occurrence.asc(),
                   Ledger.id.asc())
        return list(self._db.scalars(q))

    def last_before(self, user_id: str, d: date) -> Optional[Ledger]:
        """Latest ledger row strictly before ``d`` that carries a balance, or None."""
        q = select(Ledger).where(
            Ledger.user_id == user_id, Ledger.posting_date < d, Ledger.net_balance.isnot(None),
        ).order_by(Ledger.posting_date.desc(), Ledger.created_at.desc(), Ledger.id.desc()).limit(1)
        return self._db.scalars(q).first()

    def purge(self, user_id: str) -> int:
        return self._db.execute(delete(Ledger).where(Ledger.user_id == user_id)).rowcount or 0
