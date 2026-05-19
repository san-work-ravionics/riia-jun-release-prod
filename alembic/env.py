import os
import sys
import types
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool
from alembic import context

# ---------------------------------------------------------------------------
# Make rita importable and patch _CONFIG_DIR to the correct location.
#
# Background: rita.config computes _CONFIG_DIR as:
#   Path(__file__).parent.parent.parent / "config"
# When alembic loads env.py from riia-jun-release/alembic/, Python imports
# rita.config via the unresolved path "alembic/../src/rita/config.py".
# The 3-level .parent ascent may land in the wrong directory depending on CWD.
# We pre-register a patched rita.config module (with the correct absolute
# _CONFIG_DIR) before any other rita import triggers the module-level code.
# ---------------------------------------------------------------------------

# alembic/env.py  →  alembic/  →  riia-jun-release/
_ALEMBIC_DIR = Path(__file__).resolve().parent
_RELEASE_DIR = _ALEMBIC_DIR.parent          # riia-jun-release/
_SRC = _RELEASE_DIR / "src"
_CONFIG_DIR = _RELEASE_DIR / "config"

sys.path.insert(0, str(_SRC))


def _load_rita_config_with_correct_path() -> None:
    """Pre-load rita.config with _CONFIG_DIR patched to riia-jun-release/config/."""
    if "rita.config" in sys.modules:
        cfg = sys.modules["rita.config"]
        cfg._CONFIG_DIR = _CONFIG_DIR
        cfg.get_settings.cache_clear()
        import rita.config as _cfg
        _cfg.settings = _cfg.Settings()
        return

    config_source_path = _SRC / "rita" / "config.py"
    source = config_source_path.read_text(encoding="utf-8")

    correct_dir = str(_CONFIG_DIR).replace("\\", "/")
    original_line = (
        '_CONFIG_DIR: Path = Path(__file__).parent.parent.parent / "config"'
    )
    replacement_line = f'_CONFIG_DIR: Path = Path(r"{correct_dir}")'
    patched_source = source.replace(original_line, replacement_line, 1)

    # Ensure rita package exists in sys.modules
    if "rita" not in sys.modules:
        rita_pkg = types.ModuleType("rita")
        rita_pkg.__path__ = [str(_SRC / "rita")]
        rita_pkg.__package__ = "rita"
        rita_pkg.__spec__ = None
        sys.modules["rita"] = rita_pkg

    mod = types.ModuleType("rita.config")
    mod.__file__ = str(config_source_path)
    mod.__package__ = "rita"
    mod.__loader__ = None

    sys.modules["rita.config"] = mod  # register early to avoid circular imports

    code = compile(patched_source, str(config_source_path), "exec")
    exec(code, mod.__dict__)


_load_rita_config_with_correct_path()

from rita.database import Base  # noqa: E402
import rita.models  # noqa: E402, F401 — registers all ORM models with Base.metadata
from rita.config import get_settings  # noqa: E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override sqlalchemy.url from app settings.
# Resolve relative SQLite paths (sqlite:///./...) to absolute so alembic
# can create the db file regardless of the caller's working directory.
_settings = get_settings()
_db_url = _settings.database.database_url
if _db_url.startswith("sqlite:///./"):
    _rel = _db_url[len("sqlite:///./"):]
    _abs = (_RELEASE_DIR / _rel).resolve()
    _abs.parent.mkdir(parents=True, exist_ok=True)
    _db_url = f"sqlite:///{_abs}"
config.set_main_option("sqlalchemy.url", _db_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
