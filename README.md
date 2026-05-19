# RITA Production Release (riia-jun-release)

This is the production application code for RITA (Risk Informed Trading Approach).
Built by Claude Cowork engineer agents, sprint by sprint.

## Structure

```
riia-jun-release/
├── src/rita/
│   ├── api/
│   │   ├── v1/system/      # Pure CRUD routers (positions, orders, snapshots)
│   │   ├── v1/workflow/    # Business process routers (train, backtest, evaluate)
│   │   └── experience/     # Experience Layer routers (dashboard, fno, ops)
│   ├── services/           # Business logic (WorkflowService, ManoeuvreService, etc.)
│   ├── repositories/       # CSV access layer (one class per table, file locking)
│   ├── schemas/            # Pydantic models for all data contracts
│   ├── core/               # Pure calculation/ML logic (ported from POC)
│   ├── interfaces/         # Streamlit app, MCP server
│   └── config.py           # Pydantic Settings (validated at startup)
├── config/
│   ├── base.yaml
│   ├── development.yaml
│   ├── staging.yaml
│   └── production.yaml
├── tests/
│   ├── unit/               # Unit tests (target: 200+ tests)
│   ├── integration/        # Integration tests (target: 30 tests)
│   └── e2e/                # End-to-end Playwright tests (target: 5 tests)
├── dashboard/
│   ├── js/rita/            # ES modules decomposed from rita.html
│   ├── js/fno/             # ES modules decomposed from fno.html
│   ├── js/ops/             # ES modules decomposed from ops.html
│   └── css/responsive.css  # Responsive breakpoints: 480/768/1100px
├── k8s/                    # Kubernetes manifests
└── docs/                   # Architecture Decision Records (ADRs)
```

## Source (POC)
`../poc/rita-cowork-demo` (local — not in this repo)

## Status
Built sprint-by-sprint — see `../PLAN_STATUS.md` and Confluence Sprint Boards for current progress.

Option 1 — Local Python (recommended for development)

  From riia-jun-release/:

  # 1. Create and activate a virtual environment
  cd riia-jun-release
  python -m venv .venv
  source .venv/bin/activate          # Windows: .venv\Scripts\activate
                                     # (or run activate-env.ps1 in PowerShell)

  # 2. Install dependencies
  pip install -e ".[dev]"

  # 3. Set required env vars
  cp .env.example .env               # then edit .env if needed
  export RITA_JWT_SECRET="change-me-to-something-32-chars-long"
  export RITA_ENV=development

  # 4. Run DB migrations
  alembic upgrade head

  # 5. Start the server
  uvicorn rita.main:app --host 0.0.0.0 --port 8000 --reload

  API available at: http://localhost:8000
  Interactive docs: http://localhost:8000/docs

  ---
  Option 2 — Docker

  cd riia-jun-release

  # Build (runs lint + tests with 80% coverage gate inside builder stage)
  docker build -t rita:local .

  # Run
  docker run -p 8000:8000 \
    -e RITA_JWT_SECRET="change-me-to-something-32-chars-long" \
    -e RITA_ENV=development \
    -v /path/to/rita_input:/app/rita_input:ro \
    -v /path/to/rita_output:/app/rita_output \
    rita:local

  ---
  Option 3 — Local Docker Desktop (Recommended for Windows/Mac)

  This is the easiest way to run the isolated application. Make sure Docker Desktop is running.

  cd riia-jun-release

  # Create local volume directories if they don't exist
  mkdir -p rita_input rita_output

  # Start the application using Docker Compose (builds and runs simultaneously)
  docker-compose up --build -d

  # View the logs to ensure the API started properly
  docker-compose logs -f

  API available at: http://localhost:8000
  Interactive docs: http://localhost:8000/docs
  
  # Shut down container when you are done
  docker-compose down

  ---
  Running tests

  cd riia-jun-release

  # Unit + integration tests
  pytest tests/ -q --cov=rita

  # E2E (Playwright — needs server running on :8765)
  pytest tests/e2e/ -q
  
  
  docker commands
   1. Free up Docker disk space first:
    docker system prune -f
  
    2. Retry the build — it may just work now with freed space.
  
    3. If it fails again, disable BuildKit (falls back to legacy builder which is more tolerant):
    DOCKER_BUILDKIT=0 docker build -t rita .
  
  4. If on Docker Desktop — check Settings → Resources → increase Disk image size (needs at least ~10 GB free) and Memory to 4+ GB.