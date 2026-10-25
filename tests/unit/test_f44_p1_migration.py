"""F44 P1 migration 20261026_f44p1_mcp_calls_caller — single head, upgrade/downgrade/upgrade.

PATTERN-015: run on fresh temp SQLite databases with no `users` table.  `mcp_calls` is created by
the app's create_all (not Alembic), so two cases: table absent (migration is a no-op) and table
present with the pre-P1 columns (columns + index added, then removed, then added again).
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_PRIOR = "20261025_f43p2_rename_retire_columns_location_pk"
_HEAD = "20261026_f44p1_mcp_calls_caller"
_NEW = {"transport", "caller", "user_id"}


def _alembic(db: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db}", "RITA_ENV": "development"}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=_ROOT, env=env,
        capture_output=True, text=True, timeout=300,
    )


def _ok(r: subprocess.CompletedProcess) -> str:
    assert r.returncode == 0, (r.stdout + r.stderr)[-2000:]
    return r.stdout + r.stderr


def _q(db: Path, sql: str) -> list:
    c = sqlite3.connect(db)
    try:
        return c.execute(sql).fetchall()
    finally:
        c.close()


def _cols(db: Path) -> set[str]:
    return {r[1] for r in _q(db, "PRAGMA table_info(mcp_calls)")}


def _indexes(db: Path) -> set[str]:
    return {r[1] for r in _q(db, "PRAGMA index_list(mcp_calls)")}


def test_single_head(tmp_path):
    out = _ok(_alembic(tmp_path / "h.db", "heads"))
    heads = [ln for ln in out.splitlines() if "(head)" in ln]
    assert len(heads) == 1 and heads[0].startswith(_HEAD), out


def test_fresh_db_without_mcp_calls_round_trip(tmp_path):
    db = tmp_path / "fresh.db"
    _ok(_alembic(db, "upgrade", "head"))
    tables = {r[0] for r in _q(db, "select name from sqlite_master where type='table'")}
    assert "users" not in tables and "mcp_calls" not in tables
    _ok(_alembic(db, "downgrade", "-1"))
    _ok(_alembic(db, "upgrade", "head"))
    assert _q(db, "select version_num from alembic_version") == [(_HEAD,)]


@pytest.fixture
def prior_db_with_mcp_calls(tmp_path) -> Path:
    db = tmp_path / "prior.db"
    _ok(_alembic(db, "upgrade", _PRIOR))
    c = sqlite3.connect(db)
    c.execute("""
        CREATE TABLE mcp_calls (
            call_id VARCHAR NOT NULL PRIMARY KEY, timestamp DATETIME NOT NULL,
            tool_name VARCHAR NOT NULL, status VARCHAR NOT NULL, duration_ms FLOAT,
            args_summary VARCHAR, result_summary VARCHAR, recorded_at DATETIME NOT NULL)
    """)
    c.execute("insert into mcp_calls values ('c1','2026-10-01','ask_rita','ok',1.0,'a','r','2026-10-01')")
    c.commit()
    c.close()
    return db


def test_upgrade_downgrade_upgrade_with_existing_table(prior_db_with_mcp_calls):
    db = prior_db_with_mcp_calls
    assert not (_NEW & _cols(db))

    out = _ok(_alembic(db, "upgrade", "head"))
    assert f"Running upgrade {_PRIOR} -> {_HEAD}" in out
    assert _NEW <= _cols(db)
    assert "ix_mcp_calls_user_id" in _indexes(db)
    assert _q(db, "select call_id, transport, caller, user_id from mcp_calls") == [("c1", None, None, None)]

    _ok(_alembic(db, "downgrade", "-1"))
    assert not (_NEW & _cols(db))
    assert "ix_mcp_calls_user_id" not in _indexes(db)
    assert _q(db, "select call_id, tool_name from mcp_calls") == [("c1", "ask_rita")]

    _ok(_alembic(db, "upgrade", "head"))
    assert _NEW <= _cols(db)
    assert _q(db, "select count(*) from mcp_calls") == [(1,)]


def test_model_matches_migration():
    from rita.models.mcp_call import MCPCallModel

    cols = MCPCallModel.__table__.columns
    for name in _NEW:
        assert cols[name].nullable is True
    assert cols["user_id"].index is True
    assert not cols["user_id"].foreign_keys
