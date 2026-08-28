# Skill: Add DB Model and Repository

**Guardrail refs:** org · engineer-role · rita-project  
**Last validated against spec:** 2026-05-26  
**Spec source:** `Spec_DB.md` + `Spec_Python_Code.md`

## When to use this skill
Use when adding a new SQLAlchemy ORM model, its matching repository class, and an Alembic migration. Covers the full chain: model → repository → Alembic migration → `alembic/env.py` registration → startup seeding (if needed).

---

## Rule 1: Safety Check FIRST

Before any destructive DB operation, check what's in the DB:
```bash
python - << 'EOF'
from rita.database import SessionLocal
from rita.repositories.training import TrainingRunsRepository
from rita.repositories.backtest import BacktestRunsRepository

db = SessionLocal()
print("training_runs :", len(TrainingRunsRepository(db).read_all()))
print("backtest_runs :", len(BacktestRunsRepository(db).read_all()))
db.close()
EOF
```
If `training_runs > 0`, back up the DB before any schema change:
```bash
cp rita_output/rita.db rita_output/rita.db.bak-$(date +%Y%m%d-%H%M)
```

---

## Rule 2: ORM Model Pattern

```python
# src/rita/models/my_entity.py
from sqlalchemy import Column, String, Float, Integer, DateTime
from sqlalchemy.sql import func
from rita.database import Base

class MyEntity(Base):
    __tablename__ = "my_entities"

    entity_id  = Column(String, primary_key=True)
    name       = Column(String, nullable=False)
    value      = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

**Rules:**
- Inherit from `rita.database.Base` — not SQLAlchemy's `Base` directly.
- Primary key is always a `String` UUID (not auto-increment int) for portability.
- Nullable fields: use `nullable=True` explicitly and return `null` (not `0`) from the API so the frontend can show `—`.
- Timestamps: use `server_default=func.now()` — do not set in Python code.

---

## Rule 3: Repository Class Pattern

```python
# src/rita/repositories/my_entity_repository.py
from sqlalchemy.orm import Session
from rita.repositories.base import SqlRepository
from rita.models.my_entity import MyEntity
from rita.schemas.my_entity import MyEntitySchema

class MyEntityRepository(SqlRepository[MyEntity, MyEntitySchema]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, MyEntity, MyEntitySchema)
```

Add custom queries as methods on the class:
```python
    def get_by_name(self, name: str) -> list[MyEntitySchema]:
        rows = self._db.query(MyEntity).filter(MyEntity.name == name).all()
        return [MyEntitySchema.model_validate(r) for r in rows]
```

**Rules:**
- Never instantiate without `db: Session` — `MyEntityRepository()` raises `TypeError`.
- `upsert()` is inherited and already calls `db.commit()` — do not commit again after calling it.
- For bulk inserts, bypass `upsert()`: `db.add_all(records); db.commit()` directly.
- Background thread? Open its own session:
  ```python
  from rita.database import SessionLocal
  def worker():
      db = SessionLocal()
      try:
          repo = MyEntityRepository(db)
          # ...
      finally:
          db.close()
  ```

---

## Rule 4: Pydantic Schema

```python
# src/rita/schemas/my_entity.py
from pydantic import BaseModel
from datetime import datetime

class MyEntitySchema(BaseModel):
    entity_id:  str
    name:       str
    value:      float | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}
```

- `model_config = {"from_attributes": True}` is required — enables SQLAlchemy ORM object → Pydantic conversion.
- Mirror nullability: if the ORM column is `nullable=True`, the schema field must be `T | None`.

---

## Rule 5: Alembic Migration

After creating the ORM model:

```bash
# Run from riia-jun-release/
alembic revision --autogenerate -m "add my_entities table"
alembic upgrade head
```

**Then update `alembic/env.py`** — add the import for the new model:
```python
# alembic/env.py — target_metadata section
from rita.models.my_entity import MyEntity   # ← add this line
```
Without this import, Alembic's autogenerate won't detect the new table.

Also update `main.py` import block so `Base.metadata.create_all()` includes the new table:
```python
from rita.models.my_entity import MyEntity   # noqa: F401
```

---

## Rule 6: Startup Seeding (only if the table needs initial data)

Add a seed block in `main.py`'s `lifespan()` function. Always check before inserting:

```python
# In lifespan() — after existing seed blocks
if db.query(MyEntity).count() == 0:
    db.add_all([
        MyEntity(entity_id="seed-1", name="Example"),
    ])
    db.commit()
    logger.info("Seeded my_entities")
```

Only add seeding if the table has static reference data. Pipeline run tables (`training_runs`, `backtest_runs`, etc.) are never seeded.

---

## Step-by-Step

1. **Safety check** — run the DB content check above; backup if `training_runs > 0`
2. **Create ORM model** in `src/rita/models/my_entity.py`
3. **Create Pydantic schema** in `src/rita/schemas/my_entity.py`
4. **Create repository** in `src/rita/repositories/my_entity_repository.py`
5. **Update `alembic/env.py`** — add model import
6. **Update `main.py`** — add model import (for `create_all`) and seeding block if needed
7. **Generate and apply migration** — `alembic revision --autogenerate` then `alembic upgrade head`
8. **Verify** — check the migration script in `alembic/versions/` looks correct before applying

---

## Files to Touch

| File | Action |
|---|---|
| `src/rita/models/my_entity.py` | Create — ORM model class |
| `src/rita/schemas/my_entity.py` | Create — Pydantic schema with `from_attributes = True` |
| `src/rita/repositories/my_entity_repository.py` | Create — repo class extending `SqlRepository` |
| `alembic/env.py` | Edit — add `from rita.models.my_entity import MyEntity` |
| `src/rita/main.py` | Edit — add model import + seeding block if needed |
| `alembic/versions/<timestamp>_add_my_entities.py` | Auto-generated by Alembic |
| `specs/Spec_DB.md` | Edit — add row to tables inventory (Section 3) |

---

## Definition of Done

- [ ] ORM model inherits `Base` from `rita.database`, not SQLAlchemy directly
- [ ] Repository constructor requires `db: Session` — no default constructor
- [ ] Pydantic schema has `model_config = {"from_attributes": True}`
- [ ] `alembic/env.py` updated with new model import
- [ ] `alembic revision --autogenerate` run and migration script reviewed
- [ ] `alembic upgrade head` applied successfully
- [ ] `specs/Spec_DB.md` table inventory updated
- [ ] DB backed up first if `training_runs > 0`
