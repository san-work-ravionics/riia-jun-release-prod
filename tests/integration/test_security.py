"""Integration tests for CORS, JWT authentication, and rate limiting."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import rita.config as _rita_config

_rita_config._CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
_rita_config.get_settings.cache_clear()

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import rita.models  # noqa: F401, E402
from rita.database import Base, get_db  # noqa: E402


def _make_test_engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )


@pytest.fixture(scope="module")
def client():
    test_engine = _make_test_engine()
    Base.metadata.create_all(test_engine)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = TestSessionLocal()

    def override_get_db():
        yield session

    # Patch both the engine and SessionLocal so background threads also use in-memory DB.
    # SessionLocal is used in background workers (_run_training_job etc).
    import rita.database as _db_module
    import rita.main as _main_module

    with (
        patch.object(_db_module, "engine", test_engine),
        patch.object(_db_module, "SessionLocal", TestSessionLocal),
        patch.object(_main_module, "engine", test_engine),
    ):
        from rita.main import app
        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
        app.dependency_overrides.pop(get_db, None)

    session.close()
    Base.metadata.drop_all(test_engine)
    test_engine.dispose()


def _get_token(client: TestClient, username: str = "testuser") -> str:
    resp = client.post("/auth/token", json={"username": username, "password": "rita-dev"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


def test_cors_preflight(client: TestClient):
    resp = client.options(
        "/api/v1/positions/",
        headers={
            "Origin": "http://localhost:8000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code == 200
    assert "access-control-allow-origin" in resp.headers


def test_unauthenticated_workflow(client: TestClient):
    resp = client.post("/api/v1/workflow/train/", json={})
    # HTTPBearer raises 401 when no Authorization header is present (FastAPI >= 0.111)
    assert resp.status_code in (401, 403)


def test_login_wrong_password(client: TestClient):
    resp = client.post("/auth/token", json={"username": "user", "password": "wrong"})
    assert resp.status_code == 401


def test_login_returns_token(client: TestClient):
    resp = client.post("/auth/token", json={"username": "user", "password": "rita-dev"})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_authenticated_workflow(client: TestClient):
    token = _get_token(client)
    resp = client.post(
        "/api/v1/workflow/train/",
        json={
            "model_version": "v1.0",
            "algorithm": "DoubleDQN",
            "timesteps": 1000,
            "learning_rate": 0.0001,
            "buffer_size": 5000,
            "net_arch": "[64, 64]",
            "exploration_pct": 0.1,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    # Should not be 401 or 403 — any other code means auth passed
    assert resp.status_code not in (401, 403)
