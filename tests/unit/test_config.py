"""Unit tests for rita.config — Settings class.

All tests instantiate Settings() directly to avoid relying on the module-level
singleton.  The real config directory is never touched; every test creates its
own YAML files under tmp_path and patches _CONFIG_DIR.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.dump(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def make_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    Create a minimal config directory under tmp_path and patch
    rita.config._CONFIG_DIR to point there.

    Returns a helper callable:
        make_config_dir(base_extra=None, env_yaml=None, env_name="development")

    - base_extra: dict merged on top of the default base config
    - env_yaml: dict written as the env-specific YAML (defaults to minimal)
    - env_name: which env file to create (default "development")
    """

    def _factory(
        base_extra: dict | None = None,
        env_yaml: dict | None = None,
        env_name: str = "development",
    ) -> Path:
        import rita.config as cfg_module

        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir(parents=True, exist_ok=True)

        base: dict = {
            "app": {"name": "rita", "version": "1.0.0"},
            "server": {"host": "0.0.0.0", "port": 8000, "reload": False, "log_level": "info"},
            "data": {"input_dir": "rita_input", "output_dir": "rita_output"},
            "model": {"path": "rita_output/models"},
            "instruments": {
                "nifty": {"lot_size": 75},
                "banknifty": {"lot_size": 30},
            },
        }
        if base_extra:
            # shallow merge at the top level (sufficient for test setup)
            for k, v in base_extra.items():
                if isinstance(v, dict) and isinstance(base.get(k), dict):
                    base[k] = {**base[k], **v}
                else:
                    base[k] = v

        _write_yaml(cfg_dir / "base.yaml", base)

        env_data = env_yaml if env_yaml is not None else {}
        _write_yaml(cfg_dir / f"{env_name}.yaml", env_data)

        monkeypatch.setattr(cfg_module, "_CONFIG_DIR", cfg_dir)
        return cfg_dir

    return _factory


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDefaultsLoaded:
    def test_defaults_loaded(self, make_config_dir, monkeypatch):
        """base.yaml values appear in settings after construction."""
        make_config_dir()
        # Remove any leftover env vars that would interfere
        monkeypatch.delenv("RITA_ENV", raising=False)
        monkeypatch.delenv("RITA_JWT_SECRET", raising=False)

        from rita.config import Settings

        s = Settings()

        assert s.app.name == "rita"
        assert s.server.port == 8000
        assert s.instruments.nifty.lot_size == 75


class TestEnvOverrideMerges:
    def test_env_override_merges(self, make_config_dir, monkeypatch):
        """env-specific YAML overrides one value without losing sibling values."""
        make_config_dir(
            env_yaml={"server": {"log_level": "debug", "reload": True}},
        )
        monkeypatch.setenv("RITA_ENV", "development")
        monkeypatch.delenv("RITA_JWT_SECRET", raising=False)

        from rita.config import Settings

        s = Settings()

        # Overridden value
        assert s.server.log_level == "debug"
        assert s.server.reload is True
        # Sibling value from base.yaml must still be present
        assert s.server.port == 8000


class TestJwtSecretFromEnvVar:
    def test_jwt_secret_from_env_var(self, make_config_dir, monkeypatch):
        """RITA_JWT_SECRET env var is accessible via settings.security.jwt_secret."""
        make_config_dir()
        monkeypatch.delenv("RITA_ENV", raising=False)
        monkeypatch.setenv("RITA_JWT_SECRET", "supersecretvaluethatismorethan32chars!")

        from rita.config import Settings

        s = Settings()

        assert s.security.jwt_secret.get_secret_value() == "supersecretvaluethatismorethan32chars!"


class TestJwtSecretNotInYaml:
    def test_jwt_secret_not_in_yaml(self, make_config_dir, monkeypatch):
        """jwt_secret in YAML is stripped; settings falls back to default dev value."""
        make_config_dir(
            base_extra={
                "security": {"jwt_secret": "yaml-secret-should-not-appear"}
            }
        )
        monkeypatch.delenv("RITA_ENV", raising=False)
        monkeypatch.delenv("RITA_JWT_SECRET", raising=False)

        from rita.config import Settings

        s = Settings()

        # Must NOT be the YAML value
        assert s.security.jwt_secret.get_secret_value() != "yaml-secret-should-not-appear"
        # Should be the safe dev default
        assert s.security.jwt_secret.get_secret_value() == "dev-secret-change-in-prod"


class TestStagingRequiresSecret:
    def test_staging_requires_secret(self, make_config_dir, monkeypatch):
        """staging env with no RITA_JWT_SECRET raises ValueError."""
        make_config_dir(env_name="staging")
        monkeypatch.setenv("RITA_ENV", "staging")
        monkeypatch.delenv("RITA_JWT_SECRET", raising=False)

        from pydantic import ValidationError
        from rita.config import Settings

        with pytest.raises((ValidationError, ValueError)):
            Settings()

    def test_staging_requires_secret_min_length(self, make_config_dir, monkeypatch):
        """staging env with a short secret (< 32 chars) raises ValueError."""
        make_config_dir(env_name="staging")
        monkeypatch.setenv("RITA_ENV", "staging")
        monkeypatch.setenv("RITA_JWT_SECRET", "tooshort")

        from pydantic import ValidationError
        from rita.config import Settings

        with pytest.raises((ValidationError, ValueError)):
            Settings()


class TestUnknownEnvFallsBackGracefully:
    def test_unknown_env_falls_back_gracefully(self, make_config_dir, monkeypatch):
        """RITA_ENV=nonexistent loads base.yaml without crashing (no env file is fine)."""
        make_config_dir(env_name="development")  # no "nonexistent.yaml" created
        monkeypatch.setenv("RITA_ENV", "nonexistent")
        monkeypatch.delenv("RITA_JWT_SECRET", raising=False)

        from rita.config import Settings

        # Should not raise even though nonexistent.yaml does not exist
        s = Settings()

        assert s.app.name == "rita"


class TestDeepMergeDoesNotClobberSiblings:
    def test_deep_merge_does_not_clobber_siblings(self, make_config_dir, monkeypatch):
        """Overriding server.log_level does not remove server.port."""
        make_config_dir(
            env_yaml={"server": {"log_level": "warning"}},
        )
        monkeypatch.setenv("RITA_ENV", "development")
        monkeypatch.delenv("RITA_JWT_SECRET", raising=False)

        from rita.config import Settings

        s = Settings()

        assert s.server.log_level == "warning"
        assert s.server.port == 8000  # must not be lost
        assert s.server.host == "0.0.0.0"  # also preserved
