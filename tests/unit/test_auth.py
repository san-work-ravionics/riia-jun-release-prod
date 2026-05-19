"""Unit tests for JWT auth utilities."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt

import rita.config as _rita_config
from pathlib import Path

_rita_config._CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
_rita_config.get_settings.cache_clear()

from rita.auth import create_access_token, get_current_user  # noqa: E402
from rita.config import get_settings  # noqa: E402


def test_create_and_decode_token():
    token = create_access_token(subject="testuser")
    settings = get_settings()
    payload = jwt.decode(
        token,
        settings.security.jwt_secret.get_secret_value(),
        algorithms=[settings.security.jwt_algorithm],
    )
    assert payload["sub"] == "testuser"
    assert "exp" in payload


def test_expired_token():
    settings = get_settings()
    expire = datetime.now(timezone.utc) - timedelta(minutes=1)
    payload = {"sub": "expireduser", "exp": expire}
    token = jwt.encode(
        payload,
        settings.security.jwt_secret.get_secret_value(),
        algorithm=settings.security.jwt_algorithm,
    )
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(credentials=credentials)
    assert exc_info.value.status_code == 401


def test_invalid_token():
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials="this.is.garbage"
    )
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(credentials=credentials)
    assert exc_info.value.status_code == 401
