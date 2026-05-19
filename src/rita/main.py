from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime, timezone

import structlog
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

import rita.models  # noqa: F401 -- registers all ORM models with Base.metadata
from rita.auth import get_current_user
from rita.config import get_settings
from rita.limiter import limiter
from rita.database import Base, engine, get_db
from rita.exception_handlers import (
    http_exception_handler,
    repository_validation_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from rita.logging_config import configure_logging
from rita.metrics import instrument_app
from rita.middleware import ApiCallLogMiddleware, TraceIDMiddleware
from rita.repositories.base import RepositoryValidationError
from rita.api.v1.auth import router as auth_router
from rita.api.v1.users import router as users_router
from rita.api.v1.system.positions import router as positions_router
from rita.api.v1.system.orders import router as orders_router
from rita.api.v1.system.snapshots import router as snapshots_router
from rita.api.v1.system.trades import router as trades_router
from rita.api.v1.system.alerts import router as alerts_router
from rita.api.v1.system.audit import router as audit_router
from rita.api.v1.system.market_data import router as market_data_router
from rita.api.v1.system.config_overrides import router as config_overrides_router
from rita.api.v1.system.instruments import router as instruments_router
from rita.api.v1.system.market_signals import router as market_signals_router
from rita.api.v1.system.training_runs import router as training_runs_router
from rita.api.v1.system.drift import router as drift_router
from rita.api.v1.system.data_prep import router as data_prep_router
from rita.api.v1.system.mcp_calls import router as mcp_calls_router
from rita.api.v1.system.client_errors import router as client_errors_router
from rita.api.v1.workflow.train import router as train_router
from rita.api.v1.workflow.backtest import router as backtest_router
from rita.api.v1.workflow.evaluate import router as evaluate_router
from rita.api.v1.workflow.pipeline import router as pipeline_router
from rita.api.v1.workflow.instrument_onboard import router as instrument_onboard_router
from rita.api.experience.dashboard import router as dashboard_router
from rita.api.experience.fno import router as fno_router
from rita.api.experience.ops import router as ops_router
from rita.api.experience.rita import router as rita_experience_router
from rita.api.experience.pipeline_wizard import router as pipeline_wizard_router
from rita.api.experience.ds import router as ds_router
from rita.api.experience.agent_panel import router as agent_panel_router
from rita.api.experience.invest_game import router as invest_game_router
from rita.api.v1.workflow.chat import router as chat_router
from rita.api.v1.workflow.commentary import router as commentary_router
from rita.api.v1.portfolio import router as portfolio_router

settings = get_settings()
log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.server.log_level)
    log.info("app.startup", name=settings.app.name, version=settings.app.version)
    Base.metadata.create_all(bind=engine)

    # ── Column migrations (idempotent: SQLite raises OperationalError if col exists) ──
    _NEW_COLUMNS = [
        ("backtest_runs",  "instrument",     "VARCHAR DEFAULT 'NIFTY'"),
        ("backtest_runs",  "total_trades",   "INTEGER"),
        ("training_runs",  "train_sharpe",   "REAL"),
        ("training_runs",  "train_mdd",      "REAL"),
        ("training_runs",  "train_return",   "REAL"),
        ("training_runs",  "train_trades",   "INTEGER"),
        ("training_runs",  "val_sharpe",     "REAL"),
        ("training_runs",  "val_mdd",        "REAL"),
        ("training_runs",  "val_return",     "REAL"),
        ("training_runs",  "val_cagr",       "REAL"),
        ("training_runs",  "val_trades",     "INTEGER"),
        ("training_runs",  "backtest_trades","INTEGER"),
        ("paper_positions", "entry_date",   "DATE"),
        ("paper_positions", "expiry_date",  "DATE"),
    ]
    try:
        from rita.database import SessionLocal as _SL
        _mdb = _SL()
        try:
            for _tbl, _col, _typedef in _NEW_COLUMNS:
                try:
                    _mdb.execute(text(f"ALTER TABLE {_tbl} ADD COLUMN {_col} {_typedef}"))
                    _mdb.commit()
                    log.info("db.migration.column_added", table=_tbl, column=_col)
                except Exception:
                    _mdb.rollback()  # column already exists — safe to ignore
        finally:
            _mdb.close()
    except Exception as _exc:
        log.warning("db.migration_failed", error=str(_exc))

    # ── Seed instruments table (one-time, skipped if rows already exist) ─────
    try:
        import datetime as _dt
        from rita.repositories.instrument import InstrumentRepository
        from rita.schemas.instrument import Instrument as _Instrument
        from rita.database import SessionLocal

        _SEED_INSTRUMENTS = [
            _Instrument(instrument_id="NIFTY",     name="Nifty 50",  exchange="NSE",    country_code="IN", lot_size=75,   is_available=False, created_at=_dt.datetime.now(_dt.timezone.utc)),
            _Instrument(instrument_id="BANKNIFTY", name="Bank Nifty", exchange="NSE",    country_code="IN", lot_size=30,   is_available=False, created_at=_dt.datetime.now(_dt.timezone.utc)),
            _Instrument(instrument_id="NVIDIA",    name="Nvidia",     exchange="NASDAQ", country_code="US", lot_size=None, is_available=False, created_at=_dt.datetime.now(_dt.timezone.utc)),
            _Instrument(instrument_id="ASML",      name="ASML",       exchange="AMS",    country_code="NL", lot_size=None, is_available=False, created_at=_dt.datetime.now(_dt.timezone.utc)),
        ]

        _db = SessionLocal()
        try:
            _repo = InstrumentRepository(_db)
            existing = _repo.read_all()
            existing_ids = {i.instrument_id for i in existing}

            # One-time rename: NVDA → NVIDIA (directory is named NVIDIA)
            if "NVDA" in existing_ids and "NVIDIA" not in existing_ids:
                from sqlalchemy import text as _text
                _db.execute(_text("UPDATE instruments SET instrument_id='NVIDIA' WHERE instrument_id='NVDA'"))
                _db.commit()
                log.info("instruments.renamed", old="NVDA", new="NVIDIA")
                existing_ids = {("NVIDIA" if i == "NVDA" else i) for i in existing_ids}

            if not existing_ids:
                for inst in _SEED_INSTRUMENTS:
                    _repo.upsert(inst)
                log.info("instruments.seeded", count=len(_SEED_INSTRUMENTS))
        finally:
            _db.close()
    except Exception as _exc:
        log.warning("instruments.seed_failed", error=str(_exc))

    # ── Seed market data (2025–2026) for all instruments if not yet present ───
    try:
        import uuid as _uuid
        import datetime as _dt
        import pandas as _pd  # noqa: PLC0415
        from rita.core.data_loader import load_instrument_data
        from rita.repositories.market_data import MarketDataCacheRepository
        from rita.models.market_data import MarketDataCacheModel as _MDModel  # noqa: PLC0415
        from rita.database import SessionLocal

        db = SessionLocal()
        try:
            repo = MarketDataCacheRepository(db)
            seeded = {r.underlying for r in repo.read_all()}

            for _inst in ["NIFTY", "BANKNIFTY", "ASML", "NVIDIA"]:
                if _inst in seeded:
                    continue
                try:
                    _df = load_instrument_data(_inst)
                    _df = _df[_df.index.year.isin([2025, 2026])]
                    _df = _df[~_df.index.duplicated(keep="last")].sort_index()
                    if _df.empty:
                        log.warning("market_data.no_rows", instrument=_inst)
                        continue
                    _now = _dt.datetime.now(_dt.timezone.utc)
                    _records = [
                        _MDModel(
                            cache_id=str(_uuid.uuid4()),
                            date=_ts.date(),
                            underlying=_inst,
                            open=float(_row["Open"]),
                            high=float(_row["High"]),
                            low=float(_row["Low"]),
                            close=float(_row["Close"]),
                            shares_traded=int(_row["Volume"]) if "Volume" in _row.index and not _pd.isna(_row["Volume"]) else None,
                            recorded_at=_now,
                        )
                        for _ts, _row in _df.iterrows()
                    ]
                    db.add_all(_records)
                    db.commit()
                    log.info("market_data.seeded", instrument=_inst, rows=len(_records))
                except Exception as _exc:
                    log.warning("market_data.seed_failed", instrument=_inst, error=str(_exc))
        finally:
            db.close()
    except Exception as _exc:
        log.warning("market_data.seed_failed", error=str(_exc))


    # ── Seed / sync paper positions (update-or-insert per instrument) ─────────
    try:
        import uuid as _uuid3
        import datetime as _dt3
        from rita.repositories.paper_positions import PaperPositionsRepository
        from rita.models.paper_positions import PaperPositionModel as _PPModel

        _PAPER = [
            dict(
                instrument="ASML26MAY1300CE",
                underlying="ASML", option_type="CE", strike=1300.0,
                expiry="MAY26",    expiry_date=_dt3.date(2026, 5, 15),
                quantity=-1,       avg_price=24.15, last_traded_price=24.00,
                pnl=15.00,         pct_change=-0.62,
                currency="EUR",    lot_size=100,
                sl_price=1260.0,   target_price=1150.0,
                entry_date=_dt3.date(2026, 4, 24),
            ),
            dict(
                instrument="ASML26JUN1300CE",
                underlying="ASML", option_type="CE", strike=1300.0,
                expiry="JUN26",    expiry_date=_dt3.date(2026, 6, 15),
                quantity=-1,       avg_price=115.00, last_traded_price=115.32,
                pnl=-32.00,        pct_change=0.28,
                currency="EUR",    lot_size=100,
                sl_price=1260.0,   target_price=1150.0,
                entry_date=_dt3.date(2026, 4, 24),
            ),
        ]

        _ppdb = SessionLocal()
        try:
            _pp_repo = PaperPositionsRepository(_ppdb)
            _existing = {r.instrument: r.position_id for r in _pp_repo.read_all()}
            _now3 = _dt3.datetime.now(_dt3.timezone.utc)

            for _p in _PAPER:
                if _p["instrument"] in _existing:
                    # Update mutable fields to keep paper data current
                    _ppdb.execute(text(
                        "UPDATE paper_positions SET "
                        "last_traded_price=:ltp, pnl=:pnl, pct_change=:chg, "
                        "entry_date=:ed, expiry_date=:xd "
                        "WHERE instrument=:inst"
                    ), {"ltp": _p["last_traded_price"], "pnl": _p["pnl"],
                        "chg": _p["pct_change"], "ed": _p["entry_date"],
                        "xd": _p["expiry_date"],  "inst": _p["instrument"]})
                    _ppdb.commit()
                    log.info("paper_positions.updated", instrument=_p["instrument"])
                else:
                    _ppdb.add(_PPModel(
                        position_id=str(_uuid3.uuid4()),
                        product="NRML", recorded_at=_now3, **_p,
                    ))
                    _ppdb.commit()
                    log.info("paper_positions.inserted", instrument=_p["instrument"])
        finally:
            _ppdb.close()
    except Exception as _exc:
        log.warning("paper_positions.seed_failed", error=str(_exc))

    yield
    log.info("app.shutdown")


app = FastAPI(title=settings.app.name, version=settings.app.version, lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# -- Middleware (registration order: last-added executes outermost/first) ------
app.add_middleware(ApiCallLogMiddleware)
app.add_middleware(TraceIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.security.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -- Exception handlers (most-specific first) ---------------------------------
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(RepositoryValidationError, repository_validation_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

# -- Auth router (no auth required on /auth/token itself) ---------------------
app.include_router(auth_router)

# -- Users router (admin only) ------------------------------------------------
app.include_router(users_router)

# -- System tier -- pure CRUD routers (one per table) -------------------------
app.include_router(positions_router)
app.include_router(orders_router)
app.include_router(snapshots_router)
app.include_router(trades_router)
app.include_router(alerts_router)
app.include_router(audit_router)
app.include_router(market_data_router)
app.include_router(config_overrides_router)
app.include_router(instruments_router)
app.include_router(market_signals_router)
app.include_router(training_runs_router)
app.include_router(drift_router)
app.include_router(data_prep_router)
app.include_router(mcp_calls_router)
app.include_router(client_errors_router)

# -- Workflow tier -- JWT-protected business process routers ------------------
app.include_router(train_router, dependencies=[Depends(get_current_user)])
app.include_router(backtest_router, dependencies=[Depends(get_current_user)])
app.include_router(evaluate_router, dependencies=[Depends(get_current_user)])
app.include_router(pipeline_router)
app.include_router(instrument_onboard_router)

# -- Experience Layer -- UI-shaped aggregation routers (read-only) -------------
app.include_router(dashboard_router)
app.include_router(fno_router)
app.include_router(ops_router)
app.include_router(rita_experience_router)
app.include_router(pipeline_wizard_router)
app.include_router(ds_router)
app.include_router(agent_panel_router)
app.include_router(invest_game_router)

# -- Chat -- local intent classifier + OHLCV dispatch (no external API) -------
app.include_router(chat_router)

# -- Commentary -- deterministic narrative generation (no auth) ----------------
app.include_router(commentary_router)

# -- Portfolio -- cross-instrument overview + backtest (read-only, no auth) ----
app.include_router(portfolio_router)

# -- Prometheus metrics (must come after all routers are registered) -----------
instrument_app(app)

# -- Static files: dashboard UI (must be last — catch-all) --------------------
_dashboard_dir = Path(__file__).parent.parent.parent / "dashboard"
if _dashboard_dir.exists():
    app.mount("/dashboard", StaticFiles(directory=_dashboard_dir, html=True), name="dashboard")

_agent_ops_dir = Path(__file__).parent.parent.parent.parent / "data" / "agent-ops"
if _agent_ops_dir.exists():
    app.mount("/agent-ops-data", StaticFiles(directory=_agent_ops_dir), name="agent-ops-data")

_ops_dir = Path(__file__).parent.parent.parent / "ops"
if _ops_dir.exists():
    app.mount("/ops", StaticFiles(directory=_ops_dir), name="ops")

_mobile_dir = Path(__file__).parent.parent.parent / "mobileapp"
if _mobile_dir.exists():
    app.mount("/mobileapp", StaticFiles(directory=_mobile_dir, html=True), name="mobileapp")


@app.get("/onboarding", include_in_schema=False)
def onboarding():
    _path = Path(__file__).parent.parent.parent / "mobileapp" / "investor-flow" / "v2" / "invest-dashboard.html"
    return FileResponse(_path)


@app.get("/health", tags=["observability"])
def health(db: Session = Depends(get_db)) -> dict:
    """Liveness probe — enriched with model and data-freshness info for the dashboard.

    Returns HTTP 200 as long as the process is running.  The DB check for
    freshness/model data is best-effort: failures are swallowed so the probe
    never returns 5xx due to a storage issue.
    """
    from rita.repositories.market_data import MarketDataCacheRepository
    from rita.repositories.training import TrainingRunsRepository

    model_exists: bool = False
    model_age_days: Optional[int] = None
    csv_loaded: bool = False
    last_pipeline_run: Optional[str] = None
    data_freshness: dict[str, Any] = {}
    sharpe_trend_last5: list[float] = []
    output_dir: str = settings.data.output_dir

    try:
        # Model file check — search recursively (models live in instrument subfolders)
        model_dir = Path(settings.model.path)
        zips = sorted(model_dir.rglob("*.zip")) if model_dir.exists() else []
        if zips:
            model_exists = True
            latest_model = max(zips, key=lambda p: p.stat().st_mtime)
            age_secs = (datetime.now(timezone.utc).timestamp() - latest_model.stat().st_mtime)
            model_age_days = int(age_secs / 86400)

        # CSV / input data check — count rows and find latest date from files
        input_dir = Path(settings.data.input_dir)
        csv_files = list(input_dir.rglob("*.csv")) if input_dir.exists() else []
        csv_loaded = len(csv_files) > 0
        total_csv_rows = 0
        csv_latest_dt: date | None = None
        for _csv in csv_files:
            try:
                with open(_csv, encoding="utf-8", errors="ignore") as _f:
                    _lines = [_l.rstrip() for _l in _f if _l.strip()]
                if len(_lines) < 2:
                    continue
                total_csv_rows += len(_lines) - 1  # subtract header
                _last_val = _lines[-1].split(",")[0].strip()
                _parsed: date | None = None
                for _fmt in ("%d-%b-%Y", "%Y-%m-%d"):
                    try:
                        _parsed = datetime.strptime(_last_val[:len(_fmt) + 4], _fmt).date()
                        break
                    except ValueError:
                        pass
                if _parsed and (csv_latest_dt is None or _parsed > csv_latest_dt):
                    csv_latest_dt = _parsed
            except Exception:  # noqa: BLE001
                pass

        # Data freshness — prefer CSV files (canonical source); DB is a supplementary check
        mkt_repo = MarketDataCacheRepository(db)
        records = mkt_repo.read_all()
        if records:
            db_latest = max(r.date for r in records)
            db_days_old = (date.today() - db_latest).days
            db_status = "ok" if db_days_old < 7 else ("warn" if db_days_old < 30 else "alert")
            data_freshness = {
                "latest_date": str(db_latest),
                "days_since_latest": db_days_old,
                "status": db_status,
            }
        # Override with CSV-derived date when CSV is fresher than DB
        if csv_latest_dt:
            csv_days_old = (date.today() - csv_latest_dt).days
            if not data_freshness or csv_days_old < data_freshness.get("days_since_latest", 9999):
                csv_status = "ok" if csv_days_old < 7 else ("warn" if csv_days_old < 30 else "alert")
                data_freshness = {
                    "latest_date": str(csv_latest_dt),
                    "days_since_latest": csv_days_old,
                    "status": csv_status,
                }
        data_freshness["total_rows"] = total_csv_rows

        # Last pipeline run + sharpe trend
        train_repo = TrainingRunsRepository(db)
        runs = sorted(train_repo.read_all(), key=lambda r: r.recorded_at)
        if runs:
            last_run = runs[-1]
            last_pipeline_run = last_run.ended_at.isoformat() if last_run.ended_at else last_run.recorded_at.isoformat()
        sharpe_trend_last5 = [
            r.backtest_sharpe for r in runs[-5:] if r.backtest_sharpe is not None
        ]
    except Exception:  # noqa: BLE001
        pass

    return {
        "status": "ok",
        "version": settings.app.version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model_exists": model_exists,
        "model_age_days": model_age_days,
        "csv_loaded": csv_loaded,
        "last_pipeline_run": last_pipeline_run,
        "data_freshness": data_freshness,
        "sharpe_trend_last5": sharpe_trend_last5,
        "output_dir": output_dir,
    }


@app.get("/progress", tags=["observability"])
def progress(db: Session = Depends(get_db)) -> dict:
    """Return pipeline step statuses for the progress bar in the RITA dashboard.

    Steps match the 8-segment bar in rita.html:
    Goal → Market → Strategy → Train → Period → Backtest → Results → Update.
    Statuses are derived from training and backtest run records in the DB.
    """
    from rita.repositories.training import TrainingRunsRepository
    from rita.repositories.backtest import BacktestRunsRepository

    steps = [
        {"name": "Goal",     "status": "completed"},    # always considered set
        {"name": "Market",   "status": "completed"},    # static market analysis
        {"name": "Strategy", "status": "completed"},    # config-driven strategy
        {"name": "Train",    "status": "pending"},
        {"name": "Period",   "status": "pending"},      # backtest period selection
        {"name": "Backtest", "status": "pending"},
        {"name": "Results",  "status": "pending"},
        {"name": "Update",   "status": "pending"},
    ]

    try:
        train_repo = TrainingRunsRepository(db)
        bt_repo = BacktestRunsRepository(db)

        train_runs = sorted(train_repo.read_all(), key=lambda r: r.recorded_at)
        bt_runs = sorted(bt_repo.read_all(), key=lambda r: r.recorded_at)

        if train_runs:
            latest_train = train_runs[-1]
            if latest_train.status == "complete":
                steps[3]["status"] = "completed"
            elif latest_train.status in ("running", "pending"):
                steps[3]["status"] = "in_progress"
            elif latest_train.status == "failed":
                steps[3]["status"] = "failed"

        if bt_runs:
            latest_bt = bt_runs[-1]
            bt_status = "pending"
            if latest_bt.status == "complete":
                bt_status = "completed"
            elif latest_bt.status in ("running", "pending"):
                bt_status = "in_progress"
            elif latest_bt.status == "failed":
                bt_status = "failed"

            # Period is "completed" once a backtest has been submitted (period was chosen)
            steps[4]["status"] = "completed" if bt_status in ("completed", "in_progress", "failed") else "pending"
            steps[5]["status"] = bt_status          # Backtest
            steps[6]["status"] = bt_status          # Results — available once backtest runs
            steps[7]["status"] = bt_status          # Update — recommendation available after backtest
    except Exception:  # noqa: BLE001
        pass

    return {"steps": steps}


@app.post("/reset", tags=["observability"])
def reset() -> dict:
    """Session reset — stateless API, nothing to clear.

    Returns a simple acknowledgement consumed by the dashboard Reset button.
    """
    return {"status": "ok", "message": "Session reset"}


@app.get("/readyz", tags=["observability"])
def readyz() -> JSONResponse:
    """Readiness probe.

    Checks DB connectivity via SELECT 1.  Returns HTTP 200 when the database
    is reachable, HTTP 503 otherwise.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        log.warning("readyz_check_failed", error=str(exc))
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "detail": str(exc)},
        )
    return JSONResponse(status_code=200, content={"status": "ready"})
