"""F40 migration 20261005_f40_hedge_plan_history — upgrade/downgrade/idempotency on temp SQLite."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_PRIOR = "20261003_add_last_step_to_user_hedge_plans"
_HEAD = "20261005_f40_hedge_plan_history"


def _alembic(db: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db}", "RITA_ENV": "development"}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=_ROOT, env=env,
        capture_output=True, text=True, timeout=300,
    )


def _cols(db: Path, table: str) -> list[str]:
    c = sqlite3.connect(db)
    try:
        return [r[1] for r in c.execute(f"PRAGMA table_info({table})")]
    finally:
        c.close()


def _tables(db: Path) -> set[str]:
    c = sqlite3.connect(db)
    try:
        return {r[0] for r in c.execute("select name from sqlite_master where type='table'")}
    finally:
        c.close()


@pytest.fixture(scope="module")
def prior_db(tmp_path_factory) -> Path:
    db = tmp_path_factory.mktemp("mig") / "prior.db"
    r = _alembic(db, "upgrade", _PRIOR)
    assert r.returncode == 0, r.stderr[-2000:]
    # The alembic chain has no baseline for `users` (the app creates it via lifespan
    # create_all); batch_alter_table on downgrade reflects the FK chain, so create it here.
    from sqlalchemy import create_engine
    from rita.models.user import UserModel
    eng = create_engine(f"sqlite:///{db}")
    UserModel.__table__.create(eng, checkfirst=True)
    eng.dispose()
    return db


def test_upgrade_preserves_rows_and_adds_objects(prior_db):
    c = sqlite3.connect(prior_db)
    c.execute("PRAGMA foreign_keys=OFF")
    c.execute("insert into user_portfolio_keys (key_id, user_id) values ('k','u')")
    c.execute(
        "insert into user_hedge_plans (key_id, hedged_ids, coverage, scenario_tab, duration, last_step) "
        "values ('k','[\"ASML\"]',50,'pp','1y','save')"
    )
    c.commit(); c.close()
    assert "selections" not in _cols(prior_db, "user_hedge_plans")
    r = _alembic(prior_db, "upgrade", "head")
    assert r.returncode == 0, r.stderr[-2000:]
    assert f"Running upgrade {_PRIOR} -> {_HEAD}" in (r.stdout + r.stderr)
    assert "selections" in _cols(prior_db, "user_hedge_plans")
    assert "user_hedge_plan_history" in _tables(prior_db)
    c = sqlite3.connect(prior_db)
    assert c.execute("select key_id, last_step, selections from user_hedge_plans").fetchall() == [("k", "save", None)]
    c.close()


def test_downgrade_then_upgrade_round_trip(prior_db):
    assert _alembic(prior_db, "upgrade", "head").returncode == 0
    r = _alembic(prior_db, "downgrade", _PRIOR)
    assert r.returncode == 0, r.stderr[-2000:]
    assert "user_hedge_plan_history" not in _tables(prior_db)
    assert "selections" not in _cols(prior_db, "user_hedge_plans")
    assert _alembic(prior_db, "upgrade", "head").returncode == 0


def test_idempotent_when_table_already_created_by_create_all(tmp_path):
    db = tmp_path / "ca.db"
    assert _alembic(db, "upgrade", _PRIOR).returncode == 0
    # simulate lifespan create_all having created the new table (but not the column)
    from sqlalchemy import create_engine
    from rita.models.user_hedge_plan_history import UserHedgePlanHistoryModel
    eng = create_engine(f"sqlite:///{db}")
    UserHedgePlanHistoryModel.__table__.create(eng)
    eng.dispose()
    r = _alembic(db, "upgrade", "head")
    assert r.returncode == 0, r.stderr[-2000:]
    assert "selections" in _cols(db, "user_hedge_plans")
