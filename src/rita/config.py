"""
RITA production configuration.

Loads base.yaml then deep-merges the environment-specific YAML on top.
Secrets are sourced exclusively from environment variables — never from YAML.

Environment selection:
    RITA_ENV=development  (default)
    RITA_ENV=staging
    RITA_ENV=production

Required env vars in staging/production:
    RITA_JWT_SECRET   — min 32-char secret for JWT signing
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# Config directory resolution
# ---------------------------------------------------------------------------
# __file__ = riia-jun-release/src/rita/config.py
# .parent = rita/  .parent = src/  .parent = riia-jun-release/
_CONFIG_DIR: Path = Path(__file__).parent.parent.parent / "config"


# ---------------------------------------------------------------------------
# Deep-merge helper
# ---------------------------------------------------------------------------

def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into *base*, returning a new dict."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


# ---------------------------------------------------------------------------
# Nested settings models
# ---------------------------------------------------------------------------

class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="forbid")

    name: str = "rita"
    version: str = "1.0.0"


class ServerSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="forbid")

    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = False
    log_level: str = "info"


class DataSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="forbid")

    raw_dir: str = "data/raw"        # Source CSVs as downloaded — read-only
    input_dir: str = "data/input"    # Processed/merged CSVs ready for model
    output_dir: str = "data/output"  # Backtest results, risk timeline, trade events


class ModelSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="forbid")

    path: str = "models"  # Trained model ZIPs; instrument subfolder added at runtime


class InstrumentConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="forbid")

    lot_size: int


class InstrumentsSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="forbid")

    nifty: InstrumentConfig = InstrumentConfig(lot_size=75)
    banknifty: InstrumentConfig = InstrumentConfig(lot_size=30)


class ChatSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="forbid")

    # Local path to the sentence-transformers/all-MiniLM-L6-v2 snapshot.
    # Override via RITA_CHAT__EMBED_MODEL_PATH env var or base.yaml.
    # When set to a local directory SentenceTransformer() loads offline — no
    # HuggingFace network call is ever made.
    embed_model_path: str = (
        r"C:\Users\Sandeep\.cache\huggingface\hub"
        r"\models--sentence-transformers--all-MiniLM-L6-v2"
        r"\snapshots\c9745ed1d9f207416be6d2e6f8de32d1f16199bf"
    )
    # Directory for chat_monitor.csv. Override in production to a writable
    # volume — data/output is mounted read-only on EC2.
    monitor_dir: str = "data/output"


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="forbid")

    database_url: str = "sqlite:///./rita_output/rita.db"


class SecuritySettings(BaseSettings):
    """
    Security settings.

    jwt_secret is sourced exclusively from the RITA_JWT_SECRET environment
    variable and is never loaded from YAML.  In staging/production, the
    absence of this variable raises a ValueError at startup.
    """

    model_config = SettingsConfigDict(extra="forbid", env_prefix="RITA_")

    jwt_secret: SecretStr = Field(
        default=SecretStr("dev-secret-change-in-prod"),
        validation_alias="RITA_JWT_SECRET",
    )
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 60
    cors_origins: list[str] = ["http://localhost:8000"]

    google_client_id: str = Field(
        default="",
        validation_alias="RITA_GOOGLE_CLIENT_ID"
    )
    google_client_secret: SecretStr = Field(
        default=SecretStr(""),
        validation_alias="RITA_GOOGLE_CLIENT_SECRET",
    )
    base_url: str = Field(
        default="",
        validation_alias="RITA_BASE_URL",
    )


# ---------------------------------------------------------------------------
# Root Settings
# ---------------------------------------------------------------------------

class Settings(BaseSettings):
    """
    Root application settings.

    Constructed by loading base.yaml and deep-merging the environment-specific
    YAML on top.  Secrets are injected from environment variables only.
    """

    model_config = SettingsConfigDict(extra="forbid")

    app: AppSettings = AppSettings()
    server: ServerSettings = ServerSettings()
    data: DataSettings = DataSettings()
    model: ModelSettings = ModelSettings()
    chat: ChatSettings = ChatSettings()
    instruments: InstrumentsSettings = InstrumentsSettings()
    security: SecuritySettings = SecuritySettings()
    database: DatabaseSettings = DatabaseSettings()

    # The active environment name (informational — used during construction).
    env: str = "development"

    @classmethod
    def _load_yaml_config(cls) -> dict[str, Any]:
        """Load and merge base + environment-specific YAML config."""
        rita_env = os.environ.get("RITA_ENV", "development").lower()

        base_path = _CONFIG_DIR / "base.yaml"
        env_path = _CONFIG_DIR / f"{rita_env}.yaml"

        with base_path.open() as fh:
            merged: dict[str, Any] = yaml.safe_load(fh) or {}

        if env_path.exists():
            with env_path.open() as fh:
                env_cfg: dict[str, Any] = yaml.safe_load(fh) or {}
            merged = _deep_merge(merged, env_cfg)

        # Strip jwt_secret from YAML if it accidentally appears — secrets come
        # from env vars only.
        merged.get("security", {}).pop("jwt_secret", None)

        # ── Data / model path env-var overrides ───────────────────────────────
        # RITA_DATA_INPUT_DIR, RITA_DATA_OUTPUT_DIR, RITA_MODEL_PATH take
        # precedence over both base.yaml and the environment YAML.  Set them
        # in start.py (or your shell) to point at the real data directories
        # without touching any YAML file.
        if (v := os.environ.get("RITA_DATA_RAW_DIR")):
            merged.setdefault("data", {})["raw_dir"] = v
        if (v := os.environ.get("RITA_DATA_INPUT_DIR")):
            merged.setdefault("data", {})["input_dir"] = v
        if (v := os.environ.get("RITA_DATA_OUTPUT_DIR")):
            merged.setdefault("data", {})["output_dir"] = v
        if (v := os.environ.get("RITA_MODEL_PATH")):
            merged.setdefault("model", {})["path"] = v

        merged["env"] = rita_env
        return merged

    @model_validator(mode="before")
    @classmethod
    def _build_from_yaml(cls, values: Any) -> Any:
        """Pre-populate field values from YAML before env-var overrides apply."""
        if not isinstance(values, dict):
            return values

        yaml_cfg = cls._load_yaml_config()

        # Merge YAML into any explicitly passed values (passed values win).
        merged = _deep_merge(yaml_cfg, values)
        return merged

    @model_validator(mode="after")
    def _validate_secrets(self) -> "Settings":
        """Enforce that RITA_JWT_SECRET is set in non-development environments."""
        if self.env in ("staging", "production"):
            secret_val = self.security.jwt_secret.get_secret_value()
            if not secret_val or secret_val == "dev-secret-change-in-prod":
                raise ValueError(
                    f"RITA_JWT_SECRET environment variable must be set to a strong "
                    f"secret in the '{self.env}' environment."
                )
            if len(secret_val) < 32:
                raise ValueError(
                    "RITA_JWT_SECRET must be at least 32 characters long."
                )
        return self


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

settings: Settings = Settings()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached Settings singleton (use with FastAPI Depends)."""
    return settings
