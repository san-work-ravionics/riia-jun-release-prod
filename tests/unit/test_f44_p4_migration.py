"""F44 P4 migration 20261027_f44p4_jarvis_tables — single head, upgrade → downgrade → upgrade
(PATTERN-015) on a fresh DB and on a P2-revision DB with rows; the partial unique index; the
model matches the migration.

Runs on temp SQLite databases (never the dev rita.db).
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
_PRIOR = "20261026_f44p2_user_portfolio_currency"
_HEAD = "20261027_f44p4_jarvis_tables"
_TABLES = {"user_journeys", "jarvis_sessions", "jarvis_messages"}
_P4_COLS = {"reselect_year", "back_to_plan_reason", "proposal", "version", "previous_journey_id",
            "plan_year_start", "segments", "tracking", "reselections"}


def _alembic(db: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db}", "RITA_ENV": "development"}
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=_ROOT, env=env,
                          capture_output=True, text=True, timeout=300)


def _ok(r: subprocess.CompletedProcess) -> str:
    assert r.returncode == 0, (r.stdout + r.stderr)[-2000:]
    return r.stdout + r.stderr


def _q(db: Path, sql: str, args: tuple = ()) -> list:
    c = sqlite3.connect(db)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def _tables(db: Path) -> set[str]:
    return {r[0] for r in _q(db, "select name from sqlite_master where type='table'")}


def _indexes(db: Path) -> dict[str, str]:
    return {r[0]: r[1] or "" for r in _q(db, "select name, sql from sqlite_master where type='index'")}


def test_single_head_is_p4(tmp_path):
    out = _ok(_alembic(tmp_path / "h.db", "heads"))
    heads = [ln for ln in out.splitlines() if "(head)" in ln]
    assert len(heads) == 1 and heads[0].startswith(_HEAD), out
    hist = _ok(_alembic(tmp_path / "h.db", "history"))
    assert f"{_PRIOR} -> {_HEAD}" in hist


def test_fresh_db_round_trip(tmp_path):
    db = tmp_path / "fresh.db"
    _ok(_alembic(db, "upgrade", "head"))
    assert _TABLES <= _tables(db) and "users" not in _tables(db)
    cols = {r[1]: r for r in _q(db, "PRAGMA table_info(user_journeys)")}
    assert _P4_COLS <= set(cols)
    assert cols["version"][3] == 1 and "1" in str(cols["version"][4])        # NOT NULL default 1
    assert {r[1] for r in _q(db, "PRAGMA table_info(jarvis_sessions)")} >= {"location", "status"}
    idx = _indexes(db)
    assert "ux_user_journeys_one_active" in idx and "WHERE" in idx["ux_user_journeys_one_active"].upper()
    assert {"ix_user_journeys_user_loc_active", "ix_jarvis_sessions_user_started",
            "ix_jarvis_messages_session_created"} <= set(idx)

    _ok(_alembic(db, "downgrade", "-1"))
    assert not (_TABLES & _tables(db))
    assert _q(db, "select version_num from alembic_version") == [(_PRIOR,)]
    _ok(_alembic(db, "upgrade", "head"))
    assert _TABLES <= _tables(db)
    assert _q(db, "select version_num from alembic_version") == [(_HEAD,)]


@pytest.fixture
def p2_db(tmp_path) -> Path:
    """DB at the P2 head with rows in the tables P4 must not touch."""
    db = tmp_path / "p2.db"
    _ok(_alembic(db, "upgrade", _PRIOR))
    c = sqlite3.connect(db)
    if "user_portfolios" in _tables(db):
        c.execute("PRAGMA foreign_keys=OFF")
        c.execute("insert into user_portfolios (portfolio_id, key_id, name, holdings, total_value_eur, "
                  "is_active, currency, location, total_value) values ('p1','k1','n',?,100.0,1,'EUR','europe',100.0)",
                  (json.dumps([{"instrument_id": "ASML", "allocation_pct": 100, "shares": 1}]),))
    if "mcp_calls" in _tables(db):
        c.execute("insert into mcp_calls (call_id, timestamp, tool_name, status, duration_ms, transport, caller) "
                  "values ('c1', '2026-10-01T00:00:00', 'ask_rita', 'ok', 1, 'sse', 'external')")
    c.commit()
    c.close()
    return db


def test_p2_db_with_rows_round_trip(p2_db):
    db = p2_db
    before_pf = _q(db, "select * from user_portfolios") if "user_portfolios" in _tables(db) else []
    before_calls = _q(db, "select * from mcp_calls") if "mcp_calls" in _tables(db) else []
    out = _ok(_alembic(db, "upgrade", "head"))
    assert f"Running upgrade {_PRIOR} -> {_HEAD}" in out
    assert _TABLES <= _tables(db)
    # an old SSE row keeps its transport string
    if before_calls:
        assert _q(db, "select transport from mcp_calls where call_id='c1'") == [("sse",)]
    _q(db, "insert into user_journeys (journey_id, user_id, location, currency, state, is_active, "
           "reselect_count, version, tracking, reselections, segments) "
           "values ('j1','u','europe','EUR','goal_loaded',1,0,1,'[]','[]','[]')")
    _ok(_alembic(db, "downgrade", "-1"))
    assert not (_TABLES & _tables(db))
    if before_pf:
        assert _q(db, "select * from user_portfolios") == before_pf
    if before_calls:
        assert _q(db, "select * from mcp_calls") == before_calls
    _ok(_alembic(db, "upgrade", "head"))
    assert _q(db, "select count(*) from user_journeys") == [(0,)]


def test_partial_unique_index_allows_one_active_row(tmp_path):
    db = tmp_path / "u.db"
    _ok(_alembic(db, "upgrade", "head"))
    c = sqlite3.connect(db)
    ins = ("insert into user_journeys (journey_id, user_id, location, currency, state, is_active, "
           "reselect_count, version, tracking, reselections, segments) "
           "values (?,'u','europe','EUR',?,?,0,1,'[]','[]','[]')")
    c.execute(ins, ("a", "closed", 0))
    c.execute(ins, ("b", "closed", 0))            # many closed rows are fine
    c.execute(ins, ("c", "goal_loaded", 1))
    with pytest.raises(sqlite3.IntegrityError):
        c.execute(ins, ("d", "goal_loaded", 1))   # a second active row is refused
    c.execute(ins.replace("'europe'", "'india'"), ("e", "goal_loaded", 1))   # other location ok
    c.close()


def test_model_matches_migration():
    from rita.models.jarvis import JarvisMessageModel, JarvisSessionModel, UserJourneyModel

    cols = UserJourneyModel.__table__.columns
    assert _P4_COLS <= set(cols.keys())
    assert cols["version"].nullable is False
    assert cols["plan_year_start"].nullable is True and cols["previous_journey_id"].nullable is True
    for name in ("goal_return", "horizon_years", "goal_value", "target_return", "plan_updated_at"):
        assert cols[name].nullable is True
    idx = {i.name: i for i in UserJourneyModel.__table__.indexes}
    assert idx["ux_user_journeys_one_active"].unique
    assert "location" in JarvisSessionModel.__table__.columns
    assert {"tool_calls", "slots", "template_id"} <= set(JarvisMessageModel.__table__.columns.keys())
