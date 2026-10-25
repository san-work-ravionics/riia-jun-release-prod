"""F44 P2 migration 20261026_f44p2_user_portfolio_currency — single head, backfill,
upgrade → downgrade → upgrade (PATTERN-015).

Runs on fresh temp SQLite databases (never the dev rita.db).  A migration-only database has no
``users`` table; ``user_portfolios`` is created by the 20260530 revision, so the prior-head DB gets
legacy rows inserted by hand before upgrading.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_PRIOR = "20261026_f44p1_mcp_calls_caller"
_HEAD = "20261026_f44p2_user_portfolio_currency"
_NEW = {"currency", "location", "total_value"}


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


def _cols(db: Path) -> dict[str, tuple]:
    # name -> (type, notnull, default)
    return {r[1]: (r[2], r[3], r[4]) for r in _q(db, "PRAGMA table_info(user_portfolios)")}


def test_single_head(tmp_path):
    out = _ok(_alembic(tmp_path / "h.db", "heads"))
    heads = [ln for ln in out.splitlines() if "(head)" in ln]
    assert len(heads) == 1 and heads[0].startswith(_HEAD), out


def test_fresh_db_round_trip_without_users_table(tmp_path):
    """PATTERN-015: upgrade → downgrade → upgrade on a fresh DB that has no ``users`` table."""
    db = tmp_path / "fresh.db"
    _ok(_alembic(db, "upgrade", "head"))
    tables = {r[0] for r in _q(db, "select name from sqlite_master where type='table'")}
    assert "users" not in tables
    if "user_portfolios" in tables:
        assert _NEW <= set(_cols(db))
    _ok(_alembic(db, "downgrade", "-1"))
    if "user_portfolios" in tables:
        assert not (_NEW & set(_cols(db)))
    _ok(_alembic(db, "upgrade", "head"))
    assert _q(db, "select version_num from alembic_version") == [(_HEAD,)]


@pytest.fixture
def prior_db(tmp_path) -> Path:
    """DB at the P1 head with three legacy portfolios (one without total_value_eur)."""
    db = tmp_path / "prior.db"
    _ok(_alembic(db, "upgrade", _PRIOR))
    c = sqlite3.connect(db)
    tables = {r[0] for r in c.execute("select name from sqlite_master where type='table'")}
    if "user_portfolios" not in tables:  # pragma: no cover — created by 20260530 on a fresh DB
        c.close()
        pytest.skip("user_portfolios not created by the migration chain")
    holdings = json.dumps([{"instrument_id": "NIFTY", "allocation_pct": 100.0, "shares": 1, "cash_eur": 3.5}])
    c.execute("PRAGMA foreign_keys=OFF")
    for pid, tv in (("p1", 50000.0), ("p2", 1234.5), ("p3", None)):
        c.execute(
            "insert into user_portfolios (portfolio_id, key_id, name, holdings, total_value_eur, is_active) "
            "values (?, 'k1', 'n', ?, ?, 1)", (pid, holdings, tv))
    c.commit()
    c.close()
    return db


def test_upgrade_backfills_then_downgrade_upgrade(prior_db):
    db = prior_db
    assert not (_NEW & set(_cols(db)))
    before = _q(db, "select portfolio_id, holdings, total_value_eur from user_portfolios order by portfolio_id")

    out = _ok(_alembic(db, "upgrade", "head"))
    assert f"Running upgrade {_PRIOR} -> {_HEAD}" in out
    cols = _cols(db)
    assert _NEW <= set(cols)
    assert cols["currency"][1] == 1 and "EUR" in str(cols["currency"][2])   # NOT NULL default 'EUR'
    assert cols["location"][1] == 0 and cols["total_value"][1] == 0
    rows = _q(db, "select portfolio_id, currency, location, total_value, total_value_eur, holdings "
                  "from user_portfolios order by portfolio_id")
    assert len(rows) == len(before) == 3
    assert all(r[1] == "EUR" and r[2] is None for r in rows)
    assert all(r[3] == r[4] for r in rows)                       # total_value = total_value_eur
    assert [r[5] for r in rows] == [b[1] for b in before]        # holdings JSON untouched

    _ok(_alembic(db, "downgrade", "-1"))
    assert not (_NEW & set(_cols(db)))
    assert _q(db, "select portfolio_id, holdings, total_value_eur from user_portfolios order by portfolio_id") == before

    _ok(_alembic(db, "upgrade", "head"))
    assert _q(db, "select count(*) from user_portfolios where currency='EUR' and "
                  "(total_value = total_value_eur or (total_value is null and total_value_eur is null))") == [(3,)]


def test_model_matches_migration():
    from rita.models.user_portfolio import UserPortfolioModel

    cols = UserPortfolioModel.__table__.columns
    assert cols["currency"].nullable is False
    assert cols["currency"].server_default.arg == "EUR"
    assert cols["location"].nullable is True
    assert cols["total_value"].nullable is True
    assert cols["total_value_eur"].nullable is True   # deprecated, kept one release
