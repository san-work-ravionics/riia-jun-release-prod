"""F44 P2 — a legacy EUR portfolio renders identically before and after P2 (DoD).

The snapshot file ``fixtures/f44_p2_legacy_analytics_snapshot.json`` was written with the
**pre-P2 code** (master ``2e8db25``) by running this module with ``F44P2_WRITE_SNAPSHOT=1``.
After P2 every key in that snapshot must still have the same value; P2 may only add keys
(``portfolio_meta.total_value`` / ``currency``).

The data lives in an in-memory SQLite DB (never the dev ``rita_output/rita.db``); the app is
called without its lifespan.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from rita.auth import get_current_user, get_optional_user
from rita.database import Base, get_db
from rita.main import app
from rita.models.market_data import MarketDataCacheModel
from rita.models.user import UserModel
from rita.models.user_portfolio import UserPortfolioModel
from rita.models.user_portfolio_key import UserPortfolioKeyModel

SNAPSHOT = Path(__file__).parent / "fixtures" / "f44_p2_legacy_analytics_snapshot.json"
USER_ID = "legacy-user"


def _closes(seed: float, n: int = 90) -> list[float]:
    # Deterministic zig-zag series (no RNG).
    out, v = [], seed
    for i in range(n):
        v = v * (1.0 + (0.011 if i % 3 else -0.017))
        out.append(round(v, 4))
    return out


def seed_legacy_portfolio(db) -> None:
    """A pre-P2 row: no currency / location / total_value; holdings carry ``cash_eur``."""
    now = datetime(2026, 10, 1, 12, 0, 0)
    db.add(UserPortfolioKeyModel(key_id="k-legacy", user_id=USER_ID, created_at=now))
    db.add(UserPortfolioModel(
        portfolio_id="p-legacy", key_id="k-legacy", name="Legacy EUR",
        holdings=[
            {"instrument_id": "NIFTY", "allocation_pct": 60.0, "shares": 1, "cash_eur": 12.5},
            {"instrument_id": "ASML", "allocation_pct": 40.0, "shares": 20, "cash_eur": 7.25},
        ],
        total_value_eur=50000.0, created_at=now, updated_at=now, is_active=True,
    ))
    start = date(2026, 6, 1)
    for und, seed in (("NIFTY", 24000.0), ("ASML", 650.0)):
        for i, c in enumerate(_closes(seed)):
            db.add(MarketDataCacheModel(
                cache_id=str(uuid.uuid4()), date=start + timedelta(days=i), underlying=und,
                open=c, high=c * 1.01, low=c * 0.99, close=c, recorded_at=now,
            ))
    db.commit()


@pytest.fixture
def legacy_client():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    seed_legacy_portfolio(session)

    def _db():
        yield session

    user = UserModel(id=USER_ID)
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_optional_user] = lambda: user
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield TestClient(app)  # no lifespan: never touches the dev DB
    finally:
        for dep in (get_db, get_optional_user, get_current_user):
            app.dependency_overrides.pop(dep, None)
        session.close()
        engine.dispose()


def _analytics(client) -> dict:
    r = client.get("/api/v1/experience/fno/portfolio-analytics?mode=real")
    assert r.status_code == 200, r.text
    return r.json()


def _assert_superset(expected, got, path="$"):
    if isinstance(expected, dict):
        assert isinstance(got, dict), path
        for k, v in expected.items():
            assert k in got, f"{path}.{k} missing"
            _assert_superset(v, got[k], f"{path}.{k}")
    elif isinstance(expected, list):
        assert isinstance(got, list) and len(got) == len(expected), path
        for i, (e, g) in enumerate(zip(expected, got)):
            _assert_superset(e, g, f"{path}[{i}]")
    elif isinstance(expected, float):
        assert got == pytest.approx(expected, rel=1e-9, abs=1e-9), f"{path}: {got} != {expected}"
    else:
        assert got == expected, f"{path}: {got!r} != {expected!r}"


def test_legacy_eur_analytics_unchanged(legacy_client):
    got = _analytics(legacy_client)
    if os.environ.get("F44P2_WRITE_SNAPSHOT") == "1":
        SNAPSHOT.parent.mkdir(exist_ok=True)
        SNAPSHOT.write_text(json.dumps(got, indent=1, sort_keys=True))
    expected = json.loads(SNAPSHOT.read_text())
    _assert_superset(expected, got)


def test_snapshot_is_a_real_legacy_payload():
    snap = json.loads(SNAPSHOT.read_text())
    assert snap["mode"] == "real"
    assert snap["portfolio_meta"]["total_value_eur"] == 50000.0
    assert [(p["und"], p["position_eur"]) for p in snap["positions"]] == [("NIFTY", 30000.0), ("ASML", 20000.0)]


def test_user_portfolio_read_of_legacy_row(legacy_client):
    """GET user-portfolio on a pre-P2 row: EUR, no location, total_value = total_value_eur,
    holdings ``cash`` from ``cash_eur``."""
    r = legacy_client.get("/api/v1/experience/user-portfolio")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_value_eur"] == 50000.0
    if "currency" in body:  # P2 fields (absent when the snapshot was written)
        assert body["currency"] == "EUR"
        assert body["location"] is None
        assert body["total_value"] == 50000.0
        assert [h["cash"] for h in body["holdings"]] == [12.5, 7.25]
    assert [h["cash_eur"] for h in body["holdings"]] == [12.5, 7.25]
