"""Unit tests for rita.core.instrument_config (Feature 32, Phase 3.6).

Covers: per-instrument YAML loading (two different instruments in the same
process — the literal acceptance criterion), default fallback for a missing
config file, DEFAULT_ENV_CONFIG parity with the pre-3.6 module constants in
trading_env_v2.py, and Pydantic validation of out-of-range hyperparameters.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from rita.core.instrument_config import (
    DEFAULT_ENV_CONFIG,
    InstrumentEnvConfig,
    load_instrument_env_config,
)


def test_default_env_config_matches_pre_phase36_constants():
    """DEFAULT_ENV_CONFIG must mirror the (kept) module-level constants in
    trading_env_v2.py exactly — this is the backward-compatibility contract."""
    from rita.core.trading_env_v2 import (
        RISK_TOLERANCE_MDD, HEDGE_DAILY_FLOOR, HEDGE_COST_PER_DAY,
        HARD_MDD_LIMIT, MDD_TERMINAL_PENALTY, ETA, RF_DAILY,
    )
    assert DEFAULT_ENV_CONFIG.hedge_cost_per_day == pytest.approx(HEDGE_COST_PER_DAY)
    assert DEFAULT_ENV_CONFIG.hedge_daily_floor == pytest.approx(HEDGE_DAILY_FLOOR)
    assert DEFAULT_ENV_CONFIG.dsr_eta == pytest.approx(ETA)
    assert DEFAULT_ENV_CONFIG.rf_daily == pytest.approx(RF_DAILY)
    assert DEFAULT_ENV_CONFIG.hard_mdd_limit == pytest.approx(HARD_MDD_LIMIT)
    assert DEFAULT_ENV_CONFIG.mdd_terminal_penalty == pytest.approx(MDD_TERMINAL_PENALTY)
    assert DEFAULT_ENV_CONFIG.risk_tolerance_mdd == RISK_TOLERANCE_MDD
    assert DEFAULT_ENV_CONFIG.episode_length == 252


def test_load_two_different_instrument_configs_in_same_process():
    """Acceptance criterion: RIIATradingEnvV2 reads config from file, not
    module-level constants — verified by loading two different instrument
    configs in the same process and confirming they differ."""
    nifty_cfg = load_instrument_env_config("NIFTY", force_reload=True)
    nvidia_cfg = load_instrument_env_config("NVIDIA", force_reload=True)

    assert isinstance(nifty_cfg, InstrumentEnvConfig)
    assert isinstance(nvidia_cfg, InstrumentEnvConfig)
    # Different rf_daily (INR vs USD) and different episode_length (252 vs 126).
    assert nifty_cfg.rf_daily != nvidia_cfg.rf_daily
    assert nifty_cfg.episode_length != nvidia_cfg.episode_length
    assert nifty_cfg.episode_length == 252
    assert nvidia_cfg.episode_length == 126


def test_load_asml_config_eur_rf_daily():
    cfg = load_instrument_env_config("ASML", force_reload=True)
    assert cfg.rf_daily == pytest.approx(0.035 / 252, rel=1e-6)
    assert cfg.episode_length == 189


def test_load_aex_and_reliance_configs_exist():
    """Both new Phase 3.6 instruments (AEX, RELIANCE) must load successfully."""
    aex_cfg = load_instrument_env_config("AEX", force_reload=True)
    reliance_cfg = load_instrument_env_config("RELIANCE", force_reload=True)
    assert aex_cfg.rf_daily == pytest.approx(0.035 / 252, rel=1e-6)   # EUR
    assert reliance_cfg.rf_daily == pytest.approx(0.07 / 252, rel=1e-6)  # INR
    assert reliance_cfg.episode_length == 126  # high-vol -> shorter window


def test_missing_instrument_config_falls_back_to_default(caplog):
    """Edge case 1: no YAML for this instrument -> DEFAULT_ENV_CONFIG, no error."""
    cfg = load_instrument_env_config("DOES_NOT_EXIST_XYZ", force_reload=True)
    assert cfg == DEFAULT_ENV_CONFIG


def test_config_is_cached_between_calls():
    a = load_instrument_env_config("NIFTY", force_reload=True)
    b = load_instrument_env_config("NIFTY")  # cache hit, no force_reload
    assert a is b


def test_instrument_lookup_is_case_insensitive():
    lower = load_instrument_env_config("nifty", force_reload=True)
    upper = load_instrument_env_config("NIFTY", force_reload=True)
    assert lower == upper


# ── Validation (edge case 7 — Pydantic validators) ────────────────────────────

@pytest.mark.parametrize("field,bad_value", [
    ("hedge_cost_per_day", 0.10),      # > 0.05
    ("hedge_cost_per_day", -0.01),     # < 0
    ("dsr_eta", 0.0),                  # not > 0
    ("dsr_eta", 1.0),                  # not < 1
    ("hard_mdd_limit", 0.0),           # not < 0
    ("hard_mdd_limit", -1.5),          # < -1
    ("rf_daily", 0.02),                # > 0.01
    ("rf_daily", -0.001),              # < 0
    ("episode_length", 0),             # not > 0
])
def test_out_of_range_field_raises_validation_error(field, bad_value):
    with pytest.raises(ValidationError):
        InstrumentEnvConfig(**{field: bad_value})


def test_risk_tolerance_mdd_missing_level_raises():
    with pytest.raises(ValidationError):
        InstrumentEnvConfig(risk_tolerance_mdd={"low": -0.08, "medium": -0.15})


def test_risk_tolerance_mdd_positive_value_raises():
    with pytest.raises(ValidationError):
        InstrumentEnvConfig(risk_tolerance_mdd={"low": 0.08, "medium": -0.15, "high": -0.25})


def test_empty_feature_columns_raises():
    with pytest.raises(ValidationError):
        InstrumentEnvConfig(feature_columns=[])


def test_config_is_immutable():
    cfg = InstrumentEnvConfig()
    with pytest.raises(ValidationError):
        cfg.episode_length = 999
