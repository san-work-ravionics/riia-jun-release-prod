"""F42 P2 — static contract (JS vs HTML/schema/main.js), hardcoding greps, migration."""
from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from rita.schemas import fno_console_import as S

_ROOT = Path(__file__).resolve().parents[2]
_JS = (_ROOT / "dashboard/js/fno/trade-import.js").read_text()
_HTML = (_ROOT / "dashboard/fno.html").read_text()
_MAIN = (_ROOT / "dashboard/js/fno/main.js").read_text()
_TABLES = ["personal_fno_import_runs", "personal_fno_trades", "personal_fno_pnl_lines",
           "personal_fno_pnl_charges", "personal_fno_ledger_entries"]


def test_every_ta_imp_id_in_js_exists_in_html():
    ids = set(re.findall(r"['\"`](ta-imp-[a-z-]+)['\"`]", _JS))
    ids |= {f"ta-imp-cov-{k}" for k in ["first", "last", "trades", "inscope", "ledger", "pnl"]}
    assert len(ids) > 15
    for i in ids:
        assert f'id="{i}"' in _HTML, i
    section = _HTML[_HTML.index('id="page-trade-analysis"'):]
    assert 'id="ta-imp-file"' in section and "sec-trade-analysis" not in _HTML


def test_window_bindings_exported_and_imported():
    names = re.findall(r"window\.(taImp\w+)\s*=", _MAIN)
    assert len(names) == 6
    for n in names:
        assert re.search(rf"export (async )?function {n}\b", _JS), n
        assert n in re.search(r"import \{([^}]*)\} from './trade-import.js'", _MAIN)[1]
        assert re.search(rf"\b{n}\(", _HTML), n  # inline handler present


def test_api_upload_exported_through_fno_api():
    assert "export async function apiUpload" in (_ROOT / "dashboard/js/shared/api.js").read_text()
    assert "apiUpload" in (_ROOT / "dashboard/js/fno/api.js").read_text()
    shared = (_ROOT / "dashboard/js/shared/api.js").read_text()
    up = shared[shared.index("export async function apiUpload"):]
    assert "auth_token" in up and "Content-Type" not in up


def _fields(model) -> set[str]:
    return set(model.model_fields)


def test_js_field_reads_exist_in_schemas():
    checks = {
        "has_data": S.ImportStatusResponse, "limits": S.ImportStatusResponse,
        "scope": S.ImportStatusResponse, "recent_runs": S.ImportStatusResponse,
        "last_imports": S.ImportStatusResponse, "in_scope_count": S.TradesCoverage,
        "unparsed_count": S.TradesCoverage, "fut_count": S.TradesCoverage,
        "line_count": S.PnlCoverage, "periods": S.PnlCoverage,
        "max_file_bytes": S.ImportLimits, "max_files": S.ImportLimits,
        "allowed_extensions": S.ImportLimits, "expiry_year": S.ImportScope,
        "rows_inserted": S.ImportRunSummary, "rows_updated": S.ImportRunSummary,
        "rows_skipped": S.ImportRunSummary, "rows_rejected": S.ImportRunSummary,
        "skipped_duplicates": S.FileResult, "inserted": S.FileResult, "warnings": S.FileResult,
        "errors": S.FileResult, "total_pages": S.ImportedTradesResponse,
        "items": S.ImportedTradesResponse, "order_execution_time": S.ImportedTradeRow,
        "trade_type": S.ImportedTradeRow, "expiry_date": S.ImportedTradeRow,
    }
    for name, model in checks.items():
        assert name in _JS, name
        assert name in _fields(model), (name, model)
    for name in ("period_from", "period_to", "created_at", "file_name", "status", "kind"):
        assert name in _fields(S.ImportRunSummary)


def test_no_lot_sizes_or_print_in_new_modules():
    files = ["models/fno_import.py", "repositories/fno_import.py", "services/console_parsers.py",
             "services/fno_symbol_parser.py", "services/fno_import_service.py",
             "api/v1/workflow/fno_console_import.py", "api/experience/fno_trade_import.py",
             "schemas/fno_console_import.py"]
    for f in files:
        src = (_ROOT / "src/rita" / f).read_text()
        assert not re.search(r"\blot_size\b|\b(75|30)\b", src), f
        assert not re.search(r"^\s*print\(", src, re.M), f
        assert "localhost" not in src, f


def test_personal_prefix_on_every_table():
    from rita.models import fno_import as m

    names = [getattr(m, c).__tablename__ for c in dir(m)
             if c.startswith("Fno") and c.endswith("Model")]
    assert sorted(names) == sorted(_TABLES)


# ── migration ──────────────────────────────────────────────────────────────────

_PRIOR = "20261005_f40_hedge_plan_history"
_REV = "20261006_f42_console_import"


def _alembic(db: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db}", "RITA_ENV": "development",
           "PYTHONPATH": str(_ROOT / "src")}
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=_ROOT, env=env,
                          capture_output=True, text=True, timeout=300)


def _tables(db: Path) -> set[str]:
    c = sqlite3.connect(db)
    try:
        return {r[0] for r in c.execute("select name from sqlite_master where type='table'")}
    finally:
        c.close()


def test_migration_upgrade_downgrade_idempotent(tmp_path):
    db = tmp_path / "m.db"
    assert _alembic(db, "upgrade", _PRIOR).returncode == 0
    assert not set(_TABLES) & _tables(db)
    r = _alembic(db, "upgrade", "head")
    assert r.returncode == 0, r.stderr[-1500:]
    assert f"Running upgrade {_PRIOR} -> {_REV}" in r.stdout + r.stderr
    assert set(_TABLES) <= _tables(db)
    c = sqlite3.connect(db)
    sql = " ".join(r[0] or "" for r in c.execute(
        "select sql from sqlite_master where name like '%personal_fno%'"))
    c.close()
    for uq in ("uq_personal_fno_trades_natural", "uq_personal_fno_pnl_lines",
               "uq_personal_fno_pnl_charges", "uq_personal_fno_ledger"):
        assert uq in sql, uq
    # downgrade then re-upgrade; also idempotent when tables pre-exist (create_all case)
    assert _alembic(db, "downgrade", _PRIOR).returncode == 0
    assert not set(_TABLES) & _tables(db)
    assert _alembic(db, "upgrade", "head").returncode == 0
    assert _alembic(db, "stamp", _PRIOR).returncode == 0
    assert _alembic(db, "upgrade", "head").returncode == 0
    assert set(_TABLES) <= _tables(db)
