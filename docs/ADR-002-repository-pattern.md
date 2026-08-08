# ADR-002: Repository Pattern for Data Access

| Field | Value |
|---|---|
| **Status** | Accepted (updated Aug 2026) |
| **Date** | 2026-03-30 |
| **Last updated** | 2026-08-08 (full model/repo inventory — 28 models, 25 repos, 11 instruments) |
| **Sprint** | 0 → 2.5 → current |

---

## Context

The POC scattered `pd.read_csv()` and `df.to_csv()` calls throughout `rest_api.py` and the core modules with no centralised access layer, no file locking, and no schema validation on read or write. This caused:

- **Data corruption risk** — concurrent requests could write to the same CSV simultaneously.
- **No schema enforcement** — malformed rows silently propagated through the system.
- **Untestable I/O** — tests had to set up real CSV files or monkey-patch pandas in-place.
- **Tight coupling** — migrating to PostgreSQL in v2 would require touching every caller.

Sprint 0 introduced a `BaseRepository` with `threading.Lock` over CSV files. Sprint 2.5 replaced the entire CSV backend with SQLite via SQLAlchemy 2.x ORM (see ADR-003). The repository interface is unchanged externally — callers (routes, services) were unaffected by the migration.

---

## Decision

All data access is through a repository class. No route, service, or core module may query the database or read/write CSV output files directly.

### SqlRepository Base Interface

Every ORM-backed table has one class that inherits from `SqlRepository[SchemaT, ModelT]`. The two generic parameters are:
- `SchemaT` — the Pydantic schema returned to callers
- `ModelT` — the SQLAlchemy ORM model class

```python
# src/rita/repositories/base.py
from typing import Generic, TypeVar, Optional
from sqlalchemy.orm import Session

SchemaT = TypeVar("SchemaT")
ModelT  = TypeVar("ModelT")

class SqlRepository(Generic[SchemaT, ModelT]):
    model_class:  type[ModelT]
    schema_class: type[SchemaT]

    def __init__(self, db: Session) -> None:
        self.db = db

    def read_all(self) -> list[SchemaT]: ...
    def find_by_id(self, id: str) -> SchemaT | None: ...
    def upsert(self, record: SchemaT) -> SchemaT: ...    # calls db.commit() internally
    def delete(self, id: str) -> bool: ...
```

**Critical:** `upsert()` calls `db.commit()` internally. Never commit again after calling it.

### Concrete Repository Example

```python
# src/rita/repositories/positions.py
from rita.repositories.base import SqlRepository
from rita.models.positions import PositionModel
from rita.schemas.positions import Position

class PositionsRepository(SqlRepository[Position, PositionModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, PositionModel, Position)
```

### Session Injection

All repositories require a `db: Session`. No default constructor exists.

```python
# CORRECT — always inject db
from rita.database import SessionLocal, get_db

db = SessionLocal()
repo = PositionsRepository(db)

# WRONG — will raise TypeError at runtime
repo = PositionsRepository()
```

Session injection follows the FastAPI dependency injection pattern in all routers:

```python
from rita.database import get_db

def _get_repo(db: Session = Depends(get_db)) -> PositionsRepository:
    return PositionsRepository(db)
```

### Background Thread Sessions

Background threads must open their own session. Never pass a request-scoped `db` into a thread — sessions are not thread-safe.

```python
from rita.database import SessionLocal

def _background_worker(run_id: str) -> None:
    db = SessionLocal()
    try:
        repo = TrainingRunsRepository(db)
        # ... do work ...
    finally:
        db.close()
```

### v2 Migration Path

Only the repository layer changes to swap in PostgreSQL. Services, routes, and schemas are untouched. Change one config value:

```
# v1 (SQLite)
database_url = "sqlite:///./rita_output/rita.db"

# v2 (PostgreSQL — Sprint 5 or later)
database_url = "postgresql+asyncpg://user:pass@host/rita"
```

---

## ORM-Backed Tables — 28 Models, 25 Repositories

| Repository Class | ORM Model | Primary Key | Notes |
|---|---|---|---|
| `PositionsRepository` | `PositionModel` | `position_id` | Live broker positions |
| `PaperPositionsRepository` | `PaperPositionModel` | `position_id` | Seeded ASML paper options; `entry_date`, `expiry_date` columns |
| `OrdersRepository` | `OrderModel` | `order_id` | |
| `SnapshotsRepository` | `SnapshotModel` | `snapshot_id` | |
| `TradesRepository` | `TradeModel` | `trade_id` | |
| `PortfolioRepository` | `PortfolioModel` | `portfolio_id` | |
| `ManoeuvresRepository` | `ManoeuvreModel` | `manoeuvre_id` | |
| `BacktestRunsRepository` | `BacktestRunModel` | `run_id` | |
| `BacktestResultsRepository` | `BacktestResultModel` | `result_id` | |
| `TrainingRunsRepository` | `TrainingRunModel` | `run_id` | val_sharpe/mdd/return/trades nullable for historical runs |
| `TrainingMetricsRepository` | `TrainingMetricModel` | — | Per-step training metrics |
| `RiskTimelineRepository` | `RiskTimelineModel` | — | Day-by-day allocation/drawdown/regime |
| `ModelRegistryRepository` | `ModelRegistryModel` | `model_id` | |
| `AlertsRepository` | `AlertModel` | `alert_id` | Chat query log (replaces old `chat_monitor.csv`) |
| `AuditLogRepository` | `AuditLogModel` | `log_id` | API call audit trail |
| `MarketDataCacheRepository` | `MarketDataCacheModel` | `cache_id` | Market data across 11 instruments |
| `ConfigOverridesRepository` | `ConfigOverrideModel` | `override_id` | Includes `active_instrument_id` key |
| `InstrumentRepository` | `InstrumentModel` | `instrument_id` | 11 instruments (see instrument configs) |
| — | `UserModel` | `user_id` | `username, email, hashed_password, is_active, is_admin` |
| `AgentPerformanceRepository` | `AgentPerformance` | — | Agent performance tracking (Feature 32) |
| `AgentBuildRepository` | `AgentBuildRunModel`, `AgentBuildAgentModel` | — | Agent build run tracking |
| `ApiCallLogRepository` | `ApiCallLogModel` | — | API call logging |
| `CommentaryLogRepository` | `CommentaryLogModel` | — | Commentary generation log |
| `LoginEventRepository` | `LoginEventModel` | — | User login event tracking |
| `MCPCallRepository` | `MCPCallModel` | — | MCP call logging |
| `UserHedgePlanRepository` | `UserHedgePlanModel` | — | User hedge plan storage |
| `UserPortfolioRepository` | `UserPortfolioModel` | — | User portfolio holdings |
| `UserPortfolioKeyRepository` | `UserPortfolioKeyModel` | — | User portfolio API keys |

### Supported instruments (11)

Instrument configs live in `config/instruments/`. Each YAML defines training hyperparams, data paths, and lot sizes.

| Instrument | Config file | Region |
|---|---|---|
| NIFTY | `nifty.yaml` | India |
| BANKNIFTY | `banknifty.yaml` | India |
| RELIANCE | `reliance.yaml` | India |
| SBIN | `sbin.yaml` | India |
| ASML | `asml.yaml` | Europe |
| AEX | `aex.yaml` | Europe |
| ASRNL | `asrnl.yaml` | Europe |
| ATO | `ato.yaml` | Europe |
| NVIDIA | `nvidia.yaml` | US |
| DJI | `dji.yaml` | US |
| IXIC | `ixic.yaml` | US |

`rita_input/` is **read-only** source data for ML (CSV files). It is not accessed via repositories.
`rita_output/rita.db` is the SQLite database file — all ORM tables live here.

---

## What Was Dropped in Sprint 2.5

The following Sprint 0 mechanisms were **removed** when the CSV backend was replaced:

| Removed | Replacement |
|---|---|
| `BaseRepository(ABC)` with `write_all()` | `SqlRepository[T, M]` with SQLAlchemy ORM |
| `threading.Lock` per repository instance | SQLAlchemy session isolation per request |
| CSV files in `rita_output/*.csv` | `rita_output/rita.db` (SQLite) |
| `pd.read_csv()` / `df.to_csv()` in repos | `db.query(Model)...` / `db.add()` / `db.commit()` |

---

## Consequences

**Positive:**
- ACID transactions — no more partial-write corruption risk.
- All data access is testable — repositories can be mocked or replaced with `sqlite:///:memory:` in tests.
- SQLAlchemy sessions handle concurrency — file locking code deleted.
- Single `database_url` change upgrades to PostgreSQL.
- Schema validation at the Pydantic boundary; ORM models are minimal (columns only, no business logic).

**Negative:**
- ORM models are a second representation of the data alongside Pydantic schemas — mitigated by keeping models minimal.
- 25 repository classes is more boilerplate than direct DB calls — offset by testability and the clean migration path.

---

## Alternatives Considered

| Option | Reason Rejected |
|---|---|
| Keep CSV with `BaseRepository` | No transactions, file locking fragile under concurrent load |
| Direct SQLAlchemy in routes | Untestable, violates ADR-001 separation of concerns |
| SQLModel (combined ORM+Pydantic) | Adds a layer over SQLAlchemy that constrains our v2 migration flexibility |
| Pandas-native access | No locking, no schema enforcement, untestable |
