"""
RITA Workflow — Chat Router

POST /api/v1/chat/warmup   Pre-warms the local SentenceTransformer classifier.
POST /api/v1/chat          Classify query + dispatch deterministic OHLCV handler.
GET  /api/v1/chat/monitor  Chat KPIs and recent query log.

Fully local — no Claude/Anthropic API call at runtime.
Model path is read from settings.chat.embed_model_path.
"""
from __future__ import annotations

import os
import time as _time
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from rita.config import get_settings
from rita.database import get_db
from rita.logging_config import log_event

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/chat", tags=["Chat"])

# ── Market signals cache — keyed by instrument id ─────────────────────────────
# { "NIFTY": {"df": ..., "mtime_key": (p, m)}, "NVIDIA": {...}, ... }
_market_signals_cache: dict[str, dict[str, Any]] = {}


def _get_df(instrument: str):
    """Load and cache the indicators DataFrame for the given instrument.

    Uses find_instrument_csv() for the primary file and appends the manual
    daily supplement (data/input/DAILY-DATA/{instrument}_manual.csv) when
    present (NIFTY and BANKNIFTY maintain one; others typically do not).
    Recomputes only when any source file's mtime changes.
    """
    import pandas as pd
    from rita.core.data_loader import load_ohlcv_csv
    from rita.core.data_understanding import find_instrument_csv
    from rita.core.technical_analyzer import calculate_indicators

    inst = instrument.upper()
    settings = get_settings()

    primary_path = str(find_instrument_csv(inst))
    manual_path  = Path(settings.data.input_dir) / "DAILY-DATA" / f"{inst.lower()}_manual.csv"

    mtime_primary = os.path.getmtime(primary_path)
    mtime_manual  = os.path.getmtime(str(manual_path)) if manual_path.exists() else 0.0
    mtime_key = (mtime_primary, mtime_manual)

    cached = _market_signals_cache.get(inst)
    if cached is not None and cached["mtime_key"] == mtime_key:
        return cached["df"]

    raw = load_ohlcv_csv(primary_path)
    if manual_path.exists():
        manual = load_ohlcv_csv(str(manual_path))
        raw = pd.concat([raw, manual])
        raw = raw[~raw.index.duplicated(keep="last")].sort_index()

    df = calculate_indicators(raw)
    _market_signals_cache[inst] = {"df": df, "mtime_key": mtime_key}
    log.info("chat.csv_reloaded", instrument=inst, primary=primary_path,
             rows=len(df), latest=str(df.index[-1].date()))
    return df


# ── Request schema ─────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    query: str
    instrument: str | None = None        # e.g. "NVIDIA"; falls back to server active instrument
    portfolio_inr: float = 1_000_000
    target_return_pct: float | None = None
    time_horizon_days: int | None = None


# ── Endpoints ──────────────────────────────────────────────────────────────────

def _build_alerts(summary: dict, scored: dict, instrument_name: str) -> list[dict]:
    """Return up to 2 proactive market alerts for extreme conditions."""
    alerts: list[dict] = []
    rsi     = summary["rsi_14"]
    atr_pct = summary["atr_percentile"]
    trend   = summary["trend"]
    total   = scored["total_score"]
    bb_pos  = summary["bb_position"]

    if rsi > 78:
        alerts.append({"severity": "danger", "message": f"{instrument_name} RSI is {rsi:.0f} — strongly overbought. Momentum reversal risk is elevated."})
    elif rsi < 22:
        alerts.append({"severity": "warn", "message": f"{instrument_name} RSI is {rsi:.0f} — deeply oversold. Potential bounce, but trend may persist."})

    if atr_pct > 0.90:
        alerts.append({"severity": "danger", "message": f"Volatility at {atr_pct*100:.0f}th percentile — unusually large daily swings. Stress-test your portfolio."})
    elif atr_pct < 0.08:
        alerts.append({"severity": "warn", "message": "Volatility is near historic lows. Low ATR periods often precede sharp moves — stay alert."})

    if not alerts and trend == "downtrend" and total <= -3:
        alerts.append({"severity": "danger", "message": f"{instrument_name} bearish consensus — score {total:+d}/6 with confirmed downtrend. RITA may recommend HOLD."})

    if not alerts and rsi > 65 and bb_pos == "near_upper_band":
        alerts.append({"severity": "warn", "message": f"{instrument_name} overbought with price at upper Bollinger Band — reversal signal. Ask RITA to explain its recommendation."})

    return alerts[:2]


def _build_dynamic_chips(summary: dict, scored: dict, instrument_name: str) -> list[dict]:
    """Return up to 10 suggested chat questions tailored to the current market state."""
    chips: list[dict] = []
    rsi       = summary["rsi_14"]
    trend     = summary["trend"]
    atr_pct   = summary["atr_percentile"]
    sentiment = scored["overall_sentiment"]
    bb_pos    = summary["bb_position"]

    # ── RSI signal ────────────────────────────────────────────────────────────
    if rsi > 70:
        chips.append({"label": f"Instrument overbought? (RSI {rsi:.0f})", "query": "Is the market overbought or oversold?"})
    elif rsi < 30:
        chips.append({"label": f"Instrument oversold? (RSI {rsi:.0f})", "query": "Is the market overbought or oversold?"})
    else:
        chips.append({"label": f"RSI at {rsi:.0f} — what does it mean?", "query": "What is the RSI reading today?"})

    # ── Volatility signal ─────────────────────────────────────────────────────
    if atr_pct > 0.85:
        chips.append({"label": "Volatility is very high — stress test my portfolio", "query": "How volatile is the market right now?"})
    elif atr_pct < 0.20:
        chips.append({"label": "Volatility is very low — good time to enter?", "query": "What is market volatility today?"})
    else:
        chips.append({"label": "Current volatility level?", "query": "What is market volatility today?"})

    # ── Trend signal ──────────────────────────────────────────────────────────
    if trend == "downtrend":
        chips.append({"label": "Instrument in downtrend — what if it falls 20%?", "query": "What if market crashes 20 percent?"})
        chips.append({"label": "Safe strategy in a downtrend?", "query": "Safe investment approach for this instrument"})
    elif trend == "uptrend":
        chips.append({"label": "Uptrend in play — can I go aggressive?", "query": "Aggressive investment strategy"})
        chips.append({"label": "What if the instrument rallies another 10%?", "query": "What if the market rises 10 percent?"})
    else:
        chips.append({"label": "Market is sideways — what happens to my portfolio?", "query": "Sideways market scenario"})

    # ── Sentiment / Bollinger ─────────────────────────────────────────────────
    if sentiment in ("BEARISH", "CAUTIOUSLY_BEARISH"):
        chips.append({"label": "Should I reduce my instrument allocation?", "query": "What allocation should I have in this instrument?"})
        chips.append({"label": "Protect capital — conservative strategy?", "query": "Conservative allocation for this instrument"})
    elif sentiment in ("BULLISH", "CAUTIOUSLY_BULLISH"):
        chips.append({"label": "Can I invest in this instrument now?", "query": "Can I invest in this market now?"})
        chips.append({"label": "What returns can I expect this year?", "query": "Annual return from this instrument"})
    else:
        chips.append({"label": "Can I invest in this instrument now?", "query": "Can I invest in this market now?"})

    if bb_pos == "near_upper_band":
        chips.append({"label": "Price at upper Bollinger Band — reversal risk?", "query": "Is the market overbought or oversold?"})
    elif bb_pos == "near_lower_band":
        chips.append({"label": "Price at lower Bollinger Band — buying opportunity?", "query": "Is this a good entry point?"})

    # ── Always-useful staples ─────────────────────────────────────────────────
    chips.append({"label": "Overall market sentiment today?", "query": "What is the current market sentiment?"})
    chips.append({"label": "3-year return outlook?", "query": "3 year return estimate"})
    chips.append({"label": "How has RITA performed historically?", "query": "How has RITA model performed historically?"})

    return chips[:10]


@router.post("/warmup", status_code=202)
def chat_warmup(instrument: str | None = None, db: Session = Depends(get_db)) -> dict:
    """Pre-warm the intent classifier and compute market-driven chips for the given instrument.

    Called by the dashboard when the user opens the Market Analysis section.
    Idempotent — safe to call multiple times (chips are always recomputed).
    """
    from rita.core.classifier import _build_seed_index
    from rita.core.technical_analyzer import get_market_summary, get_sentiment_score
    from rita.api.v1.workflow.pipeline import _get_active_instrument_id

    _build_seed_index()

    inst = (instrument or _get_active_instrument_id(db)).upper()
    chips = None
    alerts: list = []
    try:
        df = _get_df(inst)
        summary = get_market_summary(df)
        scored  = get_sentiment_score(summary)
        chips   = _build_dynamic_chips(summary, scored, inst)
        alerts  = _build_alerts(summary, scored, inst)
        log.info("chat.warmed_up", instrument=inst, sentiment=scored["overall_sentiment"],
                 chips=len(chips), alerts=len(alerts))
    except Exception as exc:
        log.warning("chat.warmup_chips_failed", instrument=inst, error=str(exc))

    return {"status": "ready", "instrument": inst, "chips": chips, "alerts": alerts}


@router.post("")
def chat(req: ChatRequest, db: Session = Depends(get_db)) -> dict:
    """Classify a free-text investment query and return a deterministic OHLCV-driven response.

    Uses all-MiniLM-L6-v2 (local, offline) cosine similarity to route to one of
    20 fixed investment scenarios, then runs the matching core handler against
    live data for the selected instrument.
    """
    from rita.core.classifier import classify, dispatch
    from rita.core.chat_monitor import log_query as _log_query
    from rita.api.v1.workflow.pipeline import _get_active_instrument_id
    from pathlib import Path as _Path

    settings = get_settings()
    t0 = _time.perf_counter()

    inst = (req.instrument or _get_active_instrument_id(db)).upper()
    instrument_output_dir = str(_Path(settings.data.output_dir) / inst)

    try:
        df = _get_df(inst)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load market data: {exc}") from exc

    log_event(log, "info", "chat.request", msg_len=len(req.query))

    try:
        t_classify = _time.perf_counter()
        result = classify(req.query)
        response_text = dispatch(
            result, df,
            portfolio_inr=req.portfolio_inr,
            output_dir=instrument_output_dir,
            target_return_pct=req.target_return_pct,
            time_horizon_days=req.time_horizon_days,
        )
        classify_ms = (_time.perf_counter() - t_classify) * 1000
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Classification error: {exc}") from exc

    log_event(
        log, "info", "chat.response",
        intent=result.intent.name,
        confidence=round(result.confidence, 3),
        duration_ms=round(classify_ms, 1),
    )

    latency_ms = (_time.perf_counter() - t0) * 1000
    status = "low_confidence" if result.low_confidence else "success"

    try:
        _log_query(
            query_text=req.query,
            intent_name=result.intent.name,
            handler=result.intent.handler,
            confidence=result.confidence,
            low_confidence=result.low_confidence,
            latency_ms=latency_ms,
            response_preview=response_text[:200],
            status=status,
        )
    except Exception as _log_exc:
        log.warning("chat.monitor_write_failed", error=str(_log_exc))

    log.info(
        "chat.query",
        instrument=inst,
        intent=result.intent.name,
        confidence=round(result.confidence, 3),
        low_confidence=result.low_confidence,
        latency_ms=round(latency_ms, 1),
    )

    return {
        "instrument":     inst,
        "intent":         result.intent.name,
        "handler":        result.intent.handler,
        "confidence":     round(result.confidence, 4),
        "low_confidence": result.low_confidence,
        "response":       response_text,
        "latency_ms":     round(latency_ms, 1),
    }


@router.get("/monitor")
def chat_monitor_summary(db: Session = Depends(get_db)) -> dict:
    """KPIs and recent queries from the chat monitor CSV.

    Also merges commentary_logs KPIs: commentary_count, commentary_avg_latency_ms,
    commentary_error_count.
    """
    from rita.core.chat_monitor import get_summary, get_recent_queries, get_intent_distribution
    from rita.repositories.commentary_log import CommentaryLogRepository

    summary = get_summary()
    try:
        commentary_kpis = CommentaryLogRepository(db).get_summary()
        summary.update(commentary_kpis)
    except Exception as exc:
        log.warning("chat_monitor.commentary_kpis_failed", error=str(exc))

    return {
        "summary": summary,
        "recent":  get_recent_queries(20),
        "intents": get_intent_distribution(),
    }
