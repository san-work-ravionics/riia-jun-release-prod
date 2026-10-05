"""Pure parsers for Zerodha Console exports (F42 Phase 2).

No DB, no filesystem: everything works from bytes already in memory.  Row-level problems
become RowError entries (field name + code only, never cell contents); file-level problems
raise ParseFailure.  Column match is by normalised header name, never by position.
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Optional

from rita.services.fno_symbol_parser import parse_symbol

TRADEBOOK, PNL, LEDGER = "tradebook", "pnl", "ledger"
HEADER_SCAN_ROWS = 100
MAX_ERRORS = 50
_DATE_MIN = date(1990, 1, 1)
_EXCEL_EPOCH = datetime(1899, 12, 31) - timedelta(days=1)  # Excel serial day 0

_REQUIRED = {
    TRADEBOOK: {"trade_id", "order_id", "trade_type"},
    LEDGER: {"particulars", "posting_date", "voucher_type"},
    PNL: {"symbol", "realized_p_l"},
}
_PNL_SUMMARY_LABELS = {"charges", "other_credit_debit", "realized_p_l", "unrealized_p_l"}
_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_PERIOD = re.compile(r"from\s+(\S+)\s+to\s+(\S+)", re.IGNORECASE)
_DATE_FORMATS = (
    "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S.%f", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d-%m-%Y %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
)
Sheets = dict[str, list[list[Any]]]


class ParseFailure(Exception):
    """File-level failure carrying a structured error code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class RowError:
    row: Optional[int]
    field: Optional[str]
    code: str
    message: str


@dataclass
class ParsedFile:
    kind: str
    records: list[dict] = field(default_factory=list)
    charges: list[dict] = field(default_factory=list)  # pnl only
    period_from: Optional[date] = None
    period_to: Optional[date] = None
    errors: list[RowError] = field(default_factory=list)  # capped at MAX_ERRORS
    warnings: list[str] = field(default_factory=list)
    rows_parsed: int = 0
    rows_rejected: int = 0
    duplicates_in_file: int = 0


# ── low-level coercion ─────────────────────────────────────────────────────────

def norm_header(v: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(v if v is not None else "").strip().lower()).strip("_")


def clean_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = _CTRL.sub("", str(v)).strip()
    return s or None


def to_decimal(v: Any) -> Optional[Decimal]:
    """Blank / '-' -> None.  Raises ValueError for unparseable, nan and inf."""
    if v is None or isinstance(v, bool):
        if isinstance(v, bool):
            raise ValueError("bool")
        return None
    if isinstance(v, (int, float, Decimal)):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            raise ValueError("nan")
        d = Decimal(str(v))
    else:
        s = _CTRL.sub("", str(v)).strip()
        if s in ("", "-"):
            return None
        neg = s.startswith("(") and s.endswith(")")
        s = re.sub(r"[,\s₹$€%]|Rs\.?|INR", "", s.strip("()"))
        try:
            d = Decimal(s)
        except InvalidOperation as e:
            raise ValueError("number") from e
        if neg:
            d = -d
    if not d.is_finite():
        raise ValueError("nan")
    return d


def to_datetime(v: Any) -> datetime:
    """datetime / date / Excel serial / formatted string -> naive datetime; ValueError if not."""
    if isinstance(v, datetime):
        out = v.replace(tzinfo=None)
    elif isinstance(v, date):
        out = datetime(v.year, v.month, v.day)
    elif isinstance(v, (int, float)) and not isinstance(v, bool) and 1 <= v <= 80000:
        out = _EXCEL_EPOCH + timedelta(days=float(v))
    elif isinstance(v, str) and v.strip():
        s = v.strip()
        for fmt in _DATE_FORMATS:
            try:
                out = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
        else:
            raise ValueError("date")
    else:
        raise ValueError("date")
    return out


def to_date(v: Any) -> date:
    d = to_datetime(v).date()
    if d < _DATE_MIN or d > date.today() + timedelta(days=365 * 2):
        raise ValueError("date_out_of_range")
    return d


def quantise4(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def normalise_money(v: Any) -> str:
    """Deterministic fixed-point string (4 dp) so int/float/str/Decimal hash identically."""
    d = to_decimal(v)
    q = quantise4(d if d is not None else Decimal(0))
    if q == 0:
        q = Decimal("0.0000")  # no negative zero
    return format(q, "f")


def _norm_text(v: Any) -> str:
    return " ".join((clean_str(v) or "").split()).casefold()


def ledger_content_hash(posting_date: date, voucher_type: Any, cost_center: Any,
                        particulars: Any, debit: Any, credit: Any) -> str:
    """sha256 over normalised fields; net_balance excluded (it is a running figure)."""
    parts = [posting_date.isoformat(), _norm_text(voucher_type), _norm_text(cost_center),
             _norm_text(particulars), normalise_money(debit), normalise_money(credit)]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


# ── reading ────────────────────────────────────────────────────────────────────

def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def read_table(raw: bytes, file_name: str, max_rows: int) -> Sheets:
    """csv/xlsx bytes -> {sheet_name: rows}.  CSV uses the single key 'csv'."""
    if not raw:
        raise ParseFailure("empty_file", "File is empty")
    if file_name.lower().endswith(".xlsx"):
        try:
            import openpyxl

            wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        except Exception as e:  # noqa: BLE001 — any corrupt-workbook error is "unreadable"
            raise ParseFailure("unreadable", "Workbook could not be read") from e
        sheets: Sheets = {}
        total = 0
        try:
            for ws in wb.worksheets:
                rows: list[list[Any]] = []
                for r in ws.iter_rows(values_only=True):
                    total += 1
                    if total > max_rows:
                        raise ParseFailure("unreadable", "Workbook exceeds the row limit")
                    rows.append(list(r))
                sheets[ws.title] = rows
        except ParseFailure:
            raise
        except Exception as e:  # noqa: BLE001
            raise ParseFailure("unreadable", "Workbook could not be read") from e
        finally:
            wb.close()
        return sheets
    text = _decode(raw)
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    delim = max([",", ";", "\t"], key=lambda d: (first.count(d), d == ","))
    rows = []
    try:
        for r in csv.reader(io.StringIO(text), delimiter=delim):
            if len(rows) >= max_rows:
                raise ParseFailure("unreadable", "File exceeds the row limit")
            rows.append(r)
    except csv.Error as e:
        raise ParseFailure("unreadable", "CSV could not be read") from e
    return {"csv": rows}


def _find_header(rows: list[list[Any]], required: set[str]) -> Optional[int]:
    for i, r in enumerate(rows[:HEADER_SCAN_ROWS]):
        if required <= {norm_header(c) for c in r if c is not None}:
            return i
    return None


def _locate(sheets: Sheets) -> dict[str, tuple[str, int]]:
    """kind -> (sheet_name, header_row_index) for every kind found."""
    found: dict[str, tuple[str, int]] = {}
    for kind, req in _REQUIRED.items():
        hits = [(n, h) for n, rows in sheets.items() if (h := _find_header(rows, req)) is not None]
        if not hits:
            continue
        if kind == PNL:
            fo = [x for x in hits if norm_header(x[0]) == "f_o"]
            hits = fo or hits
        found[kind] = hits[0]
    return found


def detect_kind(sheets: Sheets) -> Optional[str]:
    """Content-based kind; None if unrecognised; ParseFailure('ambiguous_kind') if several."""
    found = _locate(sheets)
    if len(found) > 1:
        raise ParseFailure("ambiguous_kind", "File matches more than one Console export kind")
    return next(iter(found), None)


def parse_file(raw: bytes, file_name: str, max_rows: int,
               aliases: Optional[dict[str, str]] = None) -> ParsedFile:
    sheets = read_table(raw, file_name, max_rows)
    found = _locate(sheets)
    if len(found) > 1:
        raise ParseFailure("ambiguous_kind", "File matches more than one Console export kind")
    if not found:
        raise ParseFailure("unrecognised_file_kind", "Not a recognised Console export")
    kind = next(iter(found))
    if kind == TRADEBOOK:
        n, h = found[kind]
        return parse_tradebook(sheets[n], h, aliases)
    if kind == LEDGER:
        n, h = found[kind]
        return parse_ledger(sheets[n], h)
    return parse_pnl(sheets, found[PNL], aliases)


# ── shared row helpers ─────────────────────────────────────────────────────────

class _Ctx:
    def __init__(self, pf: ParsedFile):
        self.pf = pf

    def reject(self, row: int, fld: str, code: str, msg: str) -> None:
        self.pf.rows_rejected += 1
        if len(self.pf.errors) < MAX_ERRORS:
            self.pf.errors.append(RowError(row, fld, code, msg))


def _colmap(header: list[Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for i, c in enumerate(header):
        n = norm_header(c)
        if n and n not in out:
            out[n] = i
    return out


def _get(row: list[Any], cm: dict[str, int], name: str) -> Any:
    i = cm.get(name)
    return row[i] if i is not None and i < len(row) else None


def _blank(row: list[Any]) -> bool:
    return all(c is None or (isinstance(c, str) and not c.strip()) for c in row)


def _require_cols(cm: dict[str, int], needed: list[str]) -> None:
    missing = [c for c in needed if c not in cm]
    if missing:
        raise ParseFailure("missing_columns", "Missing columns: " + ", ".join(missing))


def _derived(symbol: str, aliases: Optional[dict[str, str]]) -> dict:
    si = parse_symbol(symbol, aliases)
    return {"underlying": si.underlying, "instrument_type": si.instrument_type,
            "strike": si.strike, "opt_expiry": si.opt_expiry, "expiry_ym": si.expiry_ym,
            "parse_status": si.parse_status}


# ── tradebook ──────────────────────────────────────────────────────────────────

def parse_tradebook(rows: list[list[Any]], header_idx: int,
                    aliases: Optional[dict[str, str]] = None) -> ParsedFile:
    pf = ParsedFile(kind=TRADEBOOK)
    cx = _Ctx(pf)
    cm = _colmap(rows[header_idx])
    _require_cols(cm, ["symbol", "trade_date", "trade_type", "quantity", "price",
                       "trade_id", "order_id"])
    seen: dict[tuple, tuple] = {}
    neg_qty = bad_time = conflicts = unparsed = 0
    for off, row in enumerate(rows[header_idx + 1:]):
        if _blank(row):
            continue
        rn = header_idx + 2 + off
        pf.rows_parsed += 1
        symbol = clean_str(_get(row, cm, "symbol"))
        trade_id = clean_str(_get(row, cm, "trade_id"))
        order_id = clean_str(_get(row, cm, "order_id"))
        if not symbol:
            cx.reject(rn, "symbol", "missing_key", "symbol is required")
            continue
        if not trade_id or not order_id:
            cx.reject(rn, "trade_id" if not trade_id else "order_id", "missing_key",
                      "trade_id and order_id are required")
            continue
        try:
            tdate = to_date(_get(row, cm, "trade_date"))
        except ValueError as e:
            cx.reject(rn, "trade_date", "invalid_date", f"trade_date invalid ({e})")
            continue
        try:
            qty_d = to_decimal(_get(row, cm, "quantity"))
        except ValueError:
            cx.reject(rn, "quantity", "invalid_number", "quantity is not a number")
            continue
        qty = int(qty_d.to_integral_value(rounding=ROUND_HALF_UP)) if qty_d is not None else 0
        if qty == 0:
            cx.reject(rn, "quantity", "invalid_quantity", "quantity must be non-zero")
            continue
        try:
            price = to_decimal(_get(row, cm, "price"))
        except ValueError:
            price = None
        if price is None or price < 0:
            cx.reject(rn, "price", "invalid_number", "price must be a non-negative number")
            continue
        tt = (clean_str(_get(row, cm, "trade_type")) or "").lower()
        if tt not in ("buy", "sell"):
            if tt == "":
                tt = "sell" if qty < 0 else "buy"
            else:
                cx.reject(rn, "trade_type", "invalid_trade_type", "trade_type must be buy or sell")
                continue
        elif qty < 0:
            neg_qty += 1
        qty = abs(qty)
        try:
            etime = to_datetime(_get(row, cm, "order_execution_time")) \
                if clean_str(_get(row, cm, "order_execution_time")) else None
        except ValueError:
            etime = None
            bad_time += 1
        try:
            raw_exp = _get(row, cm, "expiry_date")
            exp = to_date(raw_exp) if clean_str(raw_exp) else None
        except ValueError:
            exp = None
            pf.warnings.append(f"row {rn}: expiry_date unparseable, using symbol")
        symbol = symbol.upper()
        d = _derived(symbol, aliases)
        if exp is not None:
            d["opt_expiry"] = exp
            d["expiry_ym"] = f"{exp.year:04d}-{exp.month:02d}"
        if d["parse_status"] == "unparsed":
            unparsed += 1
        rec = {
            "symbol": symbol, "isin": clean_str(_get(row, cm, "isin")), "trade_date": tdate,
            "exchange": clean_str(_get(row, cm, "exchange")),
            "segment": clean_str(_get(row, cm, "segment")),
            "series": clean_str(_get(row, cm, "series")), "trade_type": tt,
            "auction": clean_str(_get(row, cm, "auction")), "quantity": qty, "price": price,
            "trade_id": trade_id, "order_id": order_id, "order_execution_time": etime,
            "expiry_date": exp, **d,
        }
        key = (trade_id, order_id, tdate)
        if key in seen:
            pf.duplicates_in_file += 1
            prev = seen[key]
            if prev != (symbol, tt, qty, price, etime):
                conflicts += 1
            continue
        seen[key] = (symbol, tt, qty, price, etime)
        pf.records.append(rec)
    if neg_qty:
        pf.warnings.append(f"{neg_qty} row(s) had negative quantity; absolute value stored")
    if bad_time:
        pf.warnings.append(f"{bad_time} row(s) had unparseable order_execution_time (stored null)")
    if conflicts:
        pf.warnings.append(f"{conflicts} duplicate key(s) had differing content; first row kept")
    if unparsed:
        pf.warnings.append(f"{unparsed} row(s) had an unrecognised symbol pattern (kept as UNKNOWN)")
    if pf.rows_parsed == 0:
        pf.warnings.append("File has a header but no data rows")
    dates = [r["trade_date"] for r in pf.records]
    if dates:
        pf.period_from, pf.period_to = min(dates), max(dates)
    return pf


# ── ledger ─────────────────────────────────────────────────────────────────────

def parse_ledger(rows: list[list[Any]], header_idx: int) -> ParsedFile:
    pf = ParsedFile(kind=LEDGER)
    cx = _Ctx(pf)
    cm = _colmap(rows[header_idx])
    _require_cols(cm, ["particulars", "posting_date", "voucher_type"])
    occ: dict[tuple, int] = {}
    for off, row in enumerate(rows[header_idx + 1:]):
        if _blank(row):
            continue
        rn = header_idx + 2 + off
        pf.rows_parsed += 1
        particulars = clean_str(_get(row, cm, "particulars"))
        if not particulars:
            cx.reject(rn, "particulars", "missing_key", "particulars is required")
            continue
        try:
            pdate = to_date(_get(row, cm, "posting_date"))
        except ValueError as e:
            cx.reject(rn, "posting_date", "invalid_date", f"posting_date invalid ({e})")
            continue
        try:
            debit = to_decimal(_get(row, cm, "debit")) or Decimal(0)
            credit = to_decimal(_get(row, cm, "credit")) or Decimal(0)
            net = to_decimal(_get(row, cm, "net_balance"))
        except ValueError:
            cx.reject(rn, "amount", "invalid_number", "debit/credit/net_balance not numeric")
            continue
        vt, cc = clean_str(_get(row, cm, "voucher_type")), clean_str(_get(row, cm, "cost_center"))
        h = ledger_content_hash(pdate, vt, cc, particulars, debit, credit)
        k = (pdate, h)
        o = occ.get(k, 0)
        occ[k] = o + 1
        pf.records.append({
            "particulars": particulars, "posting_date": pdate, "cost_center": cc,
            "voucher_type": vt, "debit": debit, "credit": credit, "net_balance": net,
            "content_hash": h, "occurrence": o,
        })
    if pf.rows_parsed == 0:
        pf.warnings.append("File has a header but no data rows")
    dates = [r["posting_date"] for r in pf.records]
    if dates:
        pf.period_from, pf.period_to = min(dates), max(dates)
    return pf


# ── P&L ────────────────────────────────────────────────────────────────────────

def _num_or_none(v: Any) -> Optional[Decimal]:
    try:
        return to_decimal(v)
    except ValueError:
        return None


def _scan_pairs(row: list[Any]) -> list[tuple[str, Decimal]]:
    """(label, amount): a text label cell followed by the next non-empty numeric cell."""
    cells = [c for c in row if c is not None and not (isinstance(c, str) and not c.strip())]
    out: list[tuple[str, Decimal]] = []
    i = 0
    while i < len(cells) - 1:
        lab = cells[i]
        amt = _num_or_none(cells[i + 1])
        if isinstance(lab, str) and _num_or_none(lab) is None and amt is not None:
            out.append((clean_str(lab) or "", amt))
            i += 2
        else:
            i += 1
    return out


def _find_period(top: list[list[Any]]) -> Optional[tuple[date, date]]:
    for r in top:
        for c in r:
            if isinstance(c, str):
                m = _PERIOD.search(c)
                if m:
                    try:
                        a, b = to_date(m[1]), to_date(m[2])
                    except ValueError:
                        continue
                    return a, b
    return None


def _parse_other_dc(rows: list[list[Any]], pf: ParsedFile, period: tuple[date, date]) -> None:
    h = _find_header(rows, {"particulars", "amount"})
    if h is None:
        pf.warnings.append("'Other Debits and Credits' sheet has no recognisable header; ignored")
        return
    cm = _colmap(rows[h])
    date_col = next((c for c in ("posting_date", "date", "entry_date") if c in cm), None)
    agg: dict[tuple, Decimal] = {}
    skipped = 0
    for row in rows[h + 1:]:
        if _blank(row):
            continue
        item = clean_str(_get(row, cm, "particulars"))
        try:
            amt = to_decimal(_get(row, cm, "amount"))
            ed = to_date(_get(row, cm, date_col)) if date_col and clean_str(_get(row, cm, date_col)) else None
        except ValueError:
            amt, ed = None, None
            skipped += 1
            continue
        if not item or amt is None:
            skipped += 1
            continue
        k = (item, ed)
        agg[k] = agg.get(k, Decimal(0)) + amt
    for (item, ed), amt in agg.items():
        pf.charges.append({"section": "other_dc", "item": item, "entry_date": ed, "amount": amt,
                           "period_from": period[0], "period_to": period[1]})
    if skipped:
        pf.warnings.append(f"{skipped} 'Other Debits and Credits' row(s) skipped (invalid)")


def parse_pnl(sheets: Sheets, located: tuple[str, int],
              aliases: Optional[dict[str, str]] = None) -> ParsedFile:
    pf = ParsedFile(kind=PNL)
    cx = _Ctx(pf)
    sheet, h = located
    rows = sheets[sheet]
    top = rows[:h]
    period = _find_period(top)
    if period is None:
        raise ParseFailure("period_not_found", "P&L period ('from ... to ...') not found in header")
    pf.period_from, pf.period_to = period

    seen_items: set[tuple] = set()
    for r in top:
        for label, amt in _scan_pairs(r):
            n = norm_header(label)
            section = "summary" if n in _PNL_SUMMARY_LABELS else "charges"
            key = (section, label)
            if key in seen_items:
                continue
            seen_items.add(key)
            pf.charges.append({"section": section, "item": label, "entry_date": None,
                               "amount": amt, "period_from": period[0], "period_to": period[1]})

    cm = _colmap(rows[h])
    seen_sym: set[str] = set()
    unparsed = 0
    for off, row in enumerate(rows[h + 1:]):
        sym = clean_str(_get(row, cm, "symbol"))
        if not sym:
            break  # first blank symbol row ends the table
        rn = h + 2 + off
        pf.rows_parsed += 1
        try:
            num = {f: to_decimal(_get(row, cm, f)) for f in (
                "buy_value", "sell_value", "realized_p_l", "realized_p_l_pct",
                "previous_closing_price", "open_value", "unrealized_p_l", "unrealized_p_l_pct",
                "quantity", "open_quantity")}
        except ValueError:
            cx.reject(rn, "amount", "invalid_number", "a numeric column is not a number")
            continue
        sym = sym.upper()
        if sym in seen_sym:
            pf.duplicates_in_file += 1
            continue
        seen_sym.add(sym)
        d = _derived(sym, aliases)
        if d["parse_status"] == "unparsed":
            unparsed += 1

        def _i(x: Optional[Decimal]) -> Optional[int]:
            return None if x is None else int(x.to_integral_value(rounding=ROUND_HALF_UP))

        pf.records.append({
            "symbol": sym, "isin": clean_str(_get(row, cm, "isin")),
            "period_from": period[0], "period_to": period[1],
            "quantity": _i(num["quantity"]), "buy_value": num["buy_value"],
            "sell_value": num["sell_value"], "realized_pnl": num["realized_p_l"],
            "realized_pnl_pct": num["realized_p_l_pct"],
            "prev_close_price": num["previous_closing_price"],
            "open_quantity": _i(num["open_quantity"]),
            "open_quantity_type": clean_str(_get(row, cm, "open_quantity_type")),
            "open_value": num["open_value"], "unrealized_pnl": num["unrealized_p_l"],
            "unrealized_pnl_pct": num["unrealized_p_l_pct"], **d,
        })
    if unparsed:
        pf.warnings.append(f"{unparsed} row(s) had an unrecognised symbol pattern (kept as UNKNOWN)")

    if len(sheets) > 1 or sheet != "csv":
        other = next((n for n in sheets if norm_header(n).startswith("other_debits")), None)
        if other is not None and other != sheet:
            _parse_other_dc(sheets[other], pf, period)
        elif sheet != "csv":
            pf.warnings.append("'Other Debits and Credits' sheet not found")
        extra = [n for n in sheets if n not in (sheet, other)]
        if extra:
            pf.warnings.append("Ignored sheets: " + ", ".join(extra))
    return pf
