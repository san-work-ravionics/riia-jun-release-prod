"""RITA Core — Per-Instrument Environment Configuration (Feature 32, Phase 3.6)

Replaces the shared module-level hyperparameters in ``trading_env_v2.py`` with
a YAML-backed, per-instrument config. Root cause (Phase 3.5.7 retrain gate,
0/4 instruments passed): a single set of hyperparameters (hedge cost, DSR eta,
episode length, ...) cannot capture the different market microstructures
across instruments (AEX mean-reverts, NIFTY trends, RELIANCE is high-vol INR,
ASML has an earnings-shock regime).

``InstrumentEnvConfig`` is the typed contract. ``DEFAULT_ENV_CONFIG`` mirrors
the pre-3.6 module-level constants in ``trading_env_v2.py`` exactly, so any
call site that omits ``env_config`` behaves identically to before this phase
(backward compatible — the existing 33 V2 tests must pass unchanged).
``load_instrument_env_config()`` reads the ``env:`` section of
``config/instruments/{instrument}.yaml`` and overlays it onto the default,
with an in-process cache (mirrors the pattern in
``ml_dispatch.py::load_instrument_defaults``).
"""
from __future__ import annotations

from pathlib import Path

import structlog
import yaml
from pydantic import BaseModel, Field, field_validator

log = structlog.get_logger(__name__)

# ── Feature columns (golden 8 structural + optional ema_ratio 9th feature) ────
# The 8 structural columns are always required by RIIATradingEnvV2's observation
# formula (non-negotiable). ``ema_ratio`` is the one optional feature toggled by
# this list — e.g. an instrument where ema_ratio isn't predictive can list only
# the 8 structural columns to drop it. Default includes ema_ratio so the
# pre-3.6 behaviour (auto-detect from the DataFrame) is preserved when no
# instrument config overrides feature_columns.
_BASE_FEATURE_COLUMNS: list[str] = [
    "daily_return", "rsi_14", "macd", "macd_signal",
    "bb_pct_b", "trend_score", "Close", "atr_14",
]
_ALL_FEATURE_COLUMNS: list[str] = _BASE_FEATURE_COLUMNS + ["ema_ratio"]

_INSTRUMENTS_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config" / "instruments"

_TOLERANCE_KEYS = ("low", "medium", "high")


class InstrumentEnvConfig(BaseModel):
    """Per-instrument hyperparameters for ``RIIATradingEnvV2``.

    Field defaults match the pre-3.6 module-level constants in
    ``trading_env_v2.py`` so ``InstrumentEnvConfig()`` (no args) is exactly
    ``DEFAULT_ENV_CONFIG``.
    """

    hedge_cost_per_day:   float = Field(default=0.0036, ge=0.0, le=0.05)
    hedge_daily_floor:    float = Field(default=-0.015, ge=-1.0, le=0.0)
    dsr_eta:              float = Field(default=0.004, gt=0.0, lt=1.0)
    rf_daily:             float = Field(default=0.07 / 252, ge=0.0, le=0.01)
    hard_mdd_limit:       float = Field(default=-0.10, ge=-1.0, lt=0.0)
    mdd_terminal_penalty: float = Field(default=-5.0, le=0.0)
    risk_tolerance_mdd:   dict[str, float] = Field(
        default_factory=lambda: {"low": -0.08, "medium": -0.15, "high": -0.25}
    )
    episode_length:       int = Field(default=252, gt=0)
    feature_columns:      list[str] = Field(default_factory=lambda: list(_ALL_FEATURE_COLUMNS))

    model_config = {"frozen": True}

    @field_validator("risk_tolerance_mdd")
    @classmethod
    def _tolerance_has_required_levels(cls, v: dict[str, float]) -> dict[str, float]:
        missing = [k for k in _TOLERANCE_KEYS if k not in v]
        if missing:
            raise ValueError(f"risk_tolerance_mdd missing required level(s): {missing}")
        for level, mdd in v.items():
            if mdd >= 0.0:
                raise ValueError(f"risk_tolerance_mdd[{level!r}] must be negative, got {mdd}")
        return v

    @field_validator("feature_columns")
    @classmethod
    def _feature_columns_non_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("feature_columns must not be empty")
        return v


# Default instance — matches current trading_env_v2.py module-level constants.
# Used whenever a call site passes ``env_config=None`` (backward compatible).
DEFAULT_ENV_CONFIG = InstrumentEnvConfig()

_ENV_CONFIG_CACHE: dict[str, InstrumentEnvConfig] = {}


def load_instrument_env_config(
    instrument: str, force_reload: bool = False
) -> InstrumentEnvConfig:
    """Load the ``env:`` section of ``config/instruments/{instrument}.yaml``.

    Overlays only the keys present in the YAML onto ``DEFAULT_ENV_CONFIG`` —
    an instrument config may specify a subset of fields. Cached per-instrument
    in-process; pass ``force_reload=True`` to bypass the cache (tests only).

    Missing file / missing ``env:`` section / any parse error → returns
    ``DEFAULT_ENV_CONFIG`` unchanged (edge case 1) and logs a warning rather
    than raising, so training/eval always has a usable config.
    """
    key = instrument.upper()
    if not force_reload and key in _ENV_CONFIG_CACHE:
        return _ENV_CONFIG_CACHE[key]

    config_file = _INSTRUMENTS_CONFIG_DIR / f"{key.lower()}.yaml"
    if not config_file.exists():
        log.warning("instrument_env_config.not_found", instrument=key)
        _ENV_CONFIG_CACHE[key] = DEFAULT_ENV_CONFIG
        return DEFAULT_ENV_CONFIG

    try:
        with config_file.open() as fh:
            raw = yaml.safe_load(fh) or {}
        env_section = raw.get("env") or {}
        if not env_section:
            log.warning("instrument_env_config.no_env_section", instrument=key)
            cfg = DEFAULT_ENV_CONFIG
        else:
            cfg = InstrumentEnvConfig(**{**DEFAULT_ENV_CONFIG.model_dump(), **env_section})
    except Exception as exc:  # noqa: BLE001 — any bad YAML/validation falls back to default
        log.error("instrument_env_config.load_failed", instrument=key, error=str(exc))
        cfg = DEFAULT_ENV_CONFIG

    _ENV_CONFIG_CACHE[key] = cfg
    log.debug("instrument_env_config.loaded", instrument=key,
              episode_length=cfg.episode_length, n_features=len(cfg.feature_columns))
    return cfg
