# ADR-003: SQLite via SQLAlchemy ORM for v1 Data Layer

| Field | Value |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-04-02 |
| **Sprint** | 2.5 |

---

## Context

Sprint 2 completed the three-tier API over a CSV-backed repository layer. While the
repository pattern (ADR-002) successfully isolated all data access, CSV has real
operational constraints for a production trading system:

- No atomic multi-row transactions — partial writes on crash corrupt state
- No query capability — list-all + Python filter is O(n) for every request
- No referential integrity — orphaned rows accumulate silently
- Concurrent write safety requires manual file locking (implemented, but fragile under load)
- No audit trail at the storage layer — only at the application layer

The repository interface (`read_all`, `find_by_id`, `upsert`, `delete`) was deliberately
designed to be storage-agnostic. Migrating the backend from CSV to SQL requires touching
**only the repository layer** — zero changes to routers, services, or schemas.

---

## Decision

Replace the CSV backend with **SQLite** via **SQLAlchemy 2.x ORM** for v1.

- **SQLite** — zero-infra, file-based, ACID-compliant. No Docker service needed.
  Ships as part of Python's stdlib. Perfect for a single-node v1 deployment.
- **SQLAlchemy 2.x** — industry-standard ORM. Declarative models, session management,
  connection pooling. The same code runs against PostgreSQL by changing `database_url`.
- **Alembic** — schema migration tool. Tracks all DDL changes. Required for production
  upgrades without data loss.

### v1 → v2 upgrade path

Change one config value:

```
# v1 (SQLite)
database_url = "sqlite:///./rita_output/rita.db"

# v2 (PostgreSQL — Sprint 5 or later)
database_url = "postgresql+asyncpg://user:pass@host/rita"
```

No application code changes required — SQLAlchemy's dialect layer handles the rest.

---

## Architecture

### New files

```
riia-jun-release/
├── src/rita/
│   ├── database.py              ← engine, SessionLocal, Base, get_db() dependency
│   └── models/                  ← SQLAlchemy ORM models (one per table, 17+ total)
│       ├── __init__.py
│       ├── positions.py
│       ├── paper_positions.py   ← seeded ASML short calls (entry_date, expiry_date)
│       ├── user.py              ← user accounts
│       ├── model_registry.py    ← model version tracking
│       ├── orders.py
│       └── ... (17+ files)
├── alembic/
│   ├── env.py                   ← points to RITA Base metadata
│   ├── versions/
│   │   └── 0001_initial_schema.py  ← CREATE TABLE for all 15 tables
│   └── script.py.mako
└── alembic.ini
```

### Modified files

```
src/rita/config.py               ← add DatabaseSettings (database_url)
src/rita/repositories/base.py    ← rewrite: CsvRepository → SqlRepository[T, ModelT]
src/rita/repositories/*.py       ← 17+ files: update inheritance, add model_class attr
src/rita/main.py                 ← lifespan: Base.metadata.create_all + Alembic upgrade head
                                    + inline ALTER TABLE ADD COLUMN for new columns (idempotent)
pyproject.toml                   ← add sqlalchemy>=2.0, alembic>=1.13
```

**Inline column migrations:** `main.py` `lifespan()` runs idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements for new columns added after the initial Alembic migration. This handles dev environments where Alembic is not run explicitly. Alembic is the authoritative source; the inline migrations are a safety net only.

### Repository base interface (unchanged externally)

```python
class SqlRepository(Generic[SchemaT, ModelT]):
    model_class: type[ModelT]      # SQLAlchemy ORM model
    schema_class: type[SchemaT]    # Pydantic schema (unchanged)

    def read_all(self) -> list[SchemaT]: ...
    def find_by_id(self, id: str) -> SchemaT | None: ...
    def upsert(self, record: SchemaT) -> SchemaT: ...
    def delete(self, id: str) -> bool: ...
```

Callers (routers, services) are **unaffected** — same method signatures, same return types.

### Session injection

```python
# database.py
def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# repositories/base.py
class SqlRepository(Generic[SchemaT, ModelT]):
    def __init__(self, db: Session) -> None:   # ← db is required; no default
        self.db = db
```

Replaces the Sprint 0 `threading.Lock` per-instance approach — SQLAlchemy handles session isolation per request. All repositories require `db: Session`; no default constructor exists.

---

## Consequences

### Positive
- ACID transactions — no more partial-write corruption risk
- Single `database_url` change upgrades to PostgreSQL
- SQLAlchemy sessions handle concurrency — file locking code deleted
- Alembic gives a full DDL audit trail
- Tests use `sqlite:///:memory:` — zero setup, zero teardown, fast

### Negative
- Adds two new dependencies (sqlalchemy, alembic) — ~8MB
- ORM models are a second representation of the data (alongside Pydantic schemas)
  — mitigated by keeping models minimal (columns only, no business logic)
- SQLite does not support `ALTER COLUMN` — schema changes require workarounds.
  Acceptable for v1; PostgreSQL removes this constraint in v2.

### Neutral
- CSV files in `rita_input/` remain read-only source data for ML — **not replaced**
- `rita_output/` now stores `rita.db` instead of CSV output files
- Model `.zip` files (stable-baselines3) unaffected

---

## Alternatives Rejected

| Option | Reason rejected |
|---|---|
| Keep CSV | No transactions, file locking fragile under concurrent load |
| PostgreSQL for v1 | Requires Docker service, infra setup — too heavy for v1 single node |
| TinyDB / shelve | Non-standard, no migration tooling, no PostgreSQL upgrade path |
| Async SQLAlchemy | Adds complexity; sync is sufficient for current load profile; can migrate in Sprint 5 |
