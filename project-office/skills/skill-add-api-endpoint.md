# Skill: Add API Endpoint

**Guardrail refs:** org · engineer-role · rita-project  
**Last validated against spec:** 2026-05-26  
**Spec source:** `Spec_Python_Code.md` + `Spec_DB.md`

## When to use this skill
Use when adding or modifying any FastAPI route in `src/rita/api/`. Covers creating the router, handler, service, repository, and Pydantic schemas, and verifying the JS frontend contract.

## Pre-conditions
- [ ] Confirm which tier the endpoint belongs to (see decision tree below)
- [ ] Grep `dashboard/js/` for the URL string to find the JS consumer (if a frontend exists for this endpoint)
- [ ] Check `src/rita/schemas/` — use existing Pydantic models; do not redefine them

---

## Rule 1: Tier Placement (ADR-001)

Use the first rule that matches:

| If the endpoint... | Tier | Directory |
|---|---|---|
| Reads or writes exactly ONE table, no logic | **System** | `src/rita/api/v1/system/<resource>.py` |
| Orchestrates a multi-step or ML workflow | **Workflow** | `src/rita/api/v1/workflow/<process>.py` |
| Composes a read-only UI payload from multiple sources | **Experience** | `src/rita/api/experience/<section>.py` |

**System rules:** Call ONE repository only. Zero business logic. Never call a service or combine tables.  
**Workflow rules:** Call services only — never call repositories directly from the router.  
**Experience rules:** Read-only. No side effects. No writes. Aggregate from system routers or services.

---

## Rule 2: Repository Pattern (ADR-002)

No direct DB/CSV access in routes or services. All data through `repositories/`.

```python
# src/rita/repositories/my_resource_repository.py
from rita.repositories.base import SqlRepository
from rita.models import MyModel
from rita.schemas.my_resource import MyResourceSchema

class MyResourceRepository(SqlRepository[MyModel, MyResourceSchema]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, MyModel, MyResourceSchema)
```

---

## Rule 3: FastAPI Dependency Injection

```python
# In the router file
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from rita.database import get_db
from rita.services.my_service import MyService

router = APIRouter()

def _get_service(db: Session = Depends(get_db)) -> MyService:
    return MyService(db)

@router.get("/resource")
def get_resource(svc: MyService = Depends(_get_service)):
    return svc.get_resource()
```

For System (CRUD) routers — inject the repo directly, skip the service:
```python
def _get_repo(db: Session = Depends(get_db)) -> MyResourceRepository:
    return MyResourceRepository(db)
```

---

## Rule 4: Service Constructor

```python
# src/rita/services/my_service.py
from sqlalchemy.orm import Session
from rita.repositories.my_resource_repository import MyResourceRepository

class MyService:
    def __init__(self, db: Session) -> None:
        self._repo = MyResourceRepository(db)
```

---

## Rule 5: Background Thread Sessions

If the handler spawns a background thread, the thread MUST open its own session:

```python
from rita.database import SessionLocal

def _background_worker(run_id: str) -> None:
    db = SessionLocal()
    try:
        repo = MyResourceRepository(db)
        # ... work ...
    finally:
        db.close()
```

Never pass a request-scoped `db` into a thread — sessions are not thread-safe.

---

## Rule 6: JS Frontend Contract Check

**This is mandatory for any endpoint that has a JS consumer.**

1. Grep `dashboard/js/` for the exact URL string:
   ```
   grep -r "/api/v1/my-endpoint" dashboard/js/
   ```
2. Open the JS file and list every field read from the response:
   - `r.fieldName`, `r['Field Name']`, `data.someKey`, etc.
3. Your handler's `return { ... }` dict **must include every field** in that list.
4. Missing fields become `undefined` in JS — no error is thrown, UI silently shows `—` or `NaN`.
5. Never echo a query param as a row field value.

**Common JS pitfalls to avoid:**

| Pitfall | Safe pattern |
|---|---|
| `parseFloat(null)` → `NaN` | Check raw value first: `v !== null ? parseFloat(v).toFixed(2) : '—'` |
| `catch (_) {}` swallows errors | Use `catch (e) { console.warn('...', e) }` |
| Query param echoed as row field | Derive phase/status from data; never echo the request param |
| `undefined` vs `null` | Only `null` is the intended sentinel; explicitly include every field |

---

## Step-by-Step

1. **Grep for the JS consumer** — find which JS module calls this endpoint and list the fields it reads
2. **Choose the tier** — use the decision tree above
3. **Check/create Pydantic schemas** in `src/rita/schemas/`
4. **Create/update the repository** in `src/rita/repositories/` (if new data access needed)
5. **Create/update the service** in `src/rita/services/` (for Workflow/Experience tiers)
6. **Create/update the router** in the correct tier directory
7. **Register the router** in `src/rita/main.py` (or the relevant router include file)
8. **Verify JS contract** — paste field list from JS next to your `return` dict and confirm all present
9. **Update spec** — if API contract changed, update `specs/Spec_Python_Code.md`

---

## Files to Touch

| File | Action |
|---|---|
| `src/rita/schemas/<resource>.py` | Create or extend — Pydantic request/response models |
| `src/rita/repositories/<resource>_repository.py` | Create — if new table access needed |
| `src/rita/services/<resource>_service.py` | Create — if Workflow or Experience tier |
| `src/rita/api/<tier>/<resource>.py` | Create or edit — router + handler |
| `src/rita/main.py` | Edit — `app.include_router(...)` |
| `Specs/Spec_Python_Code.md` | Edit — update API table if contract changed |

---

## Definition of Done

- [ ] Route lands in the correct tier directory
- [ ] No direct DB/CSV access in routes or services — all through repositories
- [ ] Every repo instantiation passes `db: Session`
- [ ] Handler's `return` dict includes every field the JS consumer reads
- [ ] `ruff check src/` passes with no errors
- [ ] Router is registered in `main.py`
- [ ] `Specs/Spec_Python_Code.md` updated if API contract changed
