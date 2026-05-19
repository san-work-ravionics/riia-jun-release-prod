"""
RITA Workflow — Commentary Router

POST /api/v1/commentary  Auto-generate narrative commentary for RITA dashboard pages.

Fully local — deterministic rule-based reasoning.  _build_narrative() is the
single LLM swap point for a future upgrade.

No auth required — matches the chat_router pattern.
"""
from __future__ import annotations

import time as _time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from rita.database import get_db
from rita.repositories.commentary_log import CommentaryLogRepository
from rita.schemas.commentary import (
    CommentaryLogCreate,
    CommentaryRequest,
    CommentaryResponse,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/commentary", tags=["Commentary"])

# ── Instruments ───────────────────────────────────────────────────────────────
_OVERVIEW_INSTRUMENTS: list[str] = ["NVIDIA", "ASML", "NIFTY", "BANKNIFTY"]

_GEO_BUCKETS: dict[str, list[str]] = {
    "US": ["NVIDIA"],
    "EU": ["ASML"],
    "India": ["NIFTY", "BANKNIFTY"],
}

# ── Consecutive error tracking ────────────────────────────────────────────────
_consecutive_errors: int = 0
_ERROR_WARN_THRESHOLD: int = 3


# ── Narrative builder — LLM swap point ───────────────────────────────────────

def _build_narrative(data: dict) -> str:
    """Deterministic rule-based narrative builder.  Replace with LLM call here."""
    page = data.get("page")
    if page == "overview":
        return _narrative_overview(data)
    if page == "strategy":
        return _narrative_strategy(data)
    return "No narrative available."


def _narrative_overview(data: dict) -> str:
    """Build plain-English overview narrative from per-instrument classification."""
    classifications: dict[str, dict] = data.get("classifications", {})
    rankings: list[str] = data.get("rankings", [])

    if not classifications:
        return "Insufficient market data to generate commentary at this time."

    # Geographic summary
    geo_sentences: list[str] = []
    for region, instruments in _GEO_BUCKETS.items():
        region_data = [
            (inst, classifications[inst])
            for inst in instruments
            if inst in classifications
        ]
        if not region_data:
            continue
        region_labels = [
            f"{inst} ({info.get('weekly', 'NEUTRAL')} weekly / {info.get('monthly', 'NEUTRAL')} monthly)"
            for inst, info in region_data
        ]
        geo_sentences.append(f"{region}: {', '.join(region_labels)}")

    geo_text = "; ".join(geo_sentences) if geo_sentences else "data unavailable"

    # Top and bottom ranked
    top = rankings[0] if rankings else None
    bottom = rankings[-1] if len(rankings) > 1 else None

    strength_text = ""
    if top:
        top_info = classifications.get(top, {})
        strength_text += (
            f"{top} leads the portfolio ({top_info.get('weekly', 'NEUTRAL')} momentum)"
        )
    if bottom and bottom != top:
        bottom_info = classifications.get(bottom, {})
        strength_text += (
            f", while {bottom} is the laggard ({bottom_info.get('weekly', 'NEUTRAL')} signal)"
        )

    return (
        f"Cross-instrument overview: {geo_text}. "
        + (strength_text + ". " if strength_text else "")
        + "Signals are computed from SMA-20, RSI-14, EMA-20 slope, and volume average across weekly and monthly timeframes."
    )


def _narrative_strategy(data: dict) -> str:
    """Build plain-English strategy rationale from allocation recommendation."""
    recommendation: str = data.get("recommendation", "HOLD")
    allocation_pct: int = data.get("allocation_pct", 0)
    rationale: str = data.get("rationale", "")
    primary_constraint: str = data.get("primary_constraint", "")
    instrument: str = data.get("instrument", "the selected instrument")

    action_phrases = {
        "HOLD": "recommends holding cash",
        "HALF": "recommends a 50% allocation",
        "FULL": "recommends full 100% allocation",
    }
    action_phrase = action_phrases.get(recommendation, f"recommends {allocation_pct}% allocation")

    parts: list[str] = [
        f"For {instrument}, RITA's strategy engine {action_phrase}.",
    ]
    if rationale:
        parts.append(rationale)
    if primary_constraint:
        parts.append(f"Primary constraint: {primary_constraint}.")

    return " ".join(parts)


# ── Per-instrument signal computation ─────────────────────────────────────────

def _classify_instrument(inst: str) -> dict[str, str]:
    """Classify one instrument across weekly and monthly timeframes.

    Returns {"weekly": label, "monthly": label} where label is one of:
    STRONG / NEUTRAL / CONSOLIDATING / WEAK / RECOVERING.

    Raises on CSV missing/corrupt — caller must handle.
    """
    import numpy as np
    from rita.api.v1.workflow.chat import _get_df

    df = _get_df(inst)
    if df is None or len(df) < 30:
        log.info("commentary.thin_data", instrument=inst, rows=len(df) if df is not None else 0)
        return {"weekly": "NEUTRAL", "monthly": "NEUTRAL"}

    result: dict[str, str] = {}
    for tf, rule in [("weekly", "W"), ("monthly", "ME")]:
        try:
            # Resample OHLCV — keep last close, mean volume
            resampled = df.resample(rule).agg(
                {
                    "Close": "last",
                    "Volume": "mean",
                }
            ).dropna()

            if len(resampled) < 20:
                log.info(
                    "commentary.thin_resampled",
                    instrument=inst,
                    timeframe=tf,
                    rows=len(resampled),
                )
                result[tf] = "NEUTRAL"
                continue

            close = resampled["Close"]
            volume = resampled["Volume"]

            # SMA-20
            sma20 = close.rolling(20).mean()
            # EMA-20 slope (last vs previous)
            ema20 = close.ewm(span=20, adjust=False).mean()
            ema_slope = (ema20.iloc[-1] - ema20.iloc[-2]) if len(ema20) >= 2 else np.nan
            # RSI-14
            delta = close.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rs = gain / loss.replace(0, np.nan)
            rsi_series = 100 - (100 / (1 + rs))
            rsi = rsi_series.iloc[-1]
            # Volume avg-20
            vol_avg20 = volume.rolling(20).mean().iloc[-1]
            vol_current = volume.iloc[-1]

            current_close = close.iloc[-1]
            current_sma20 = sma20.iloc[-1]

            # NaN guard
            rsi = rsi if not np.isnan(rsi) else 50.0
            current_sma20 = current_sma20 if not np.isnan(current_sma20) else current_close
            ema_slope = ema_slope if not np.isnan(ema_slope) else 0.0
            vol_avg20 = vol_avg20 if not np.isnan(vol_avg20) else vol_current

            above_sma = current_close > current_sma20
            vol_confirm = vol_current >= vol_avg20
            ema_up = ema_slope > 0

            if rsi > 60 and above_sma and ema_up and vol_confirm:
                label = "STRONG"
            elif rsi < 40 and not above_sma and not ema_up:
                label = "WEAK"
            elif rsi < 40 and above_sma and ema_up:
                label = "RECOVERING"
            elif 40 <= rsi <= 60 and not vol_confirm:
                label = "CONSOLIDATING"
            else:
                label = "NEUTRAL"

            result[tf] = label

        except Exception as exc:
            log.warning(
                "commentary.timeframe_error",
                instrument=inst,
                timeframe=tf,
                error=str(exc),
            )
            result[tf] = "NEUTRAL"

    return result


def _compute_composite_score(classifications: dict[str, dict]) -> list[str]:
    """Rank instruments by composite z-score based on weekly + monthly label weights."""
    _LABEL_SCORE = {
        "STRONG": 3,
        "RECOVERING": 1,
        "NEUTRAL": 0,
        "CONSOLIDATING": -1,
        "WEAK": -3,
    }
    scores: dict[str, int] = {}
    for inst, info in classifications.items():
        w = _LABEL_SCORE.get(info.get("weekly", "NEUTRAL"), 0)
        m = _LABEL_SCORE.get(info.get("monthly", "NEUTRAL"), 0)
        scores[inst] = w * 2 + m  # weekly weighted 2x
    return sorted(scores, key=lambda k: scores[k], reverse=True)


# ── Handlers ──────────────────────────────────────────────────────────────────

def _handle_overview(req: CommentaryRequest) -> dict[str, Any]:
    """Cross-instrument overview commentary for the RITA Overview page."""
    classifications: dict[str, dict] = {}
    instruments_analyzed: list[str] = []

    for inst in _OVERVIEW_INSTRUMENTS:
        try:
            classifications[inst] = _classify_instrument(inst)
            instruments_analyzed.append(inst)
        except Exception as exc:
            log.warning(
                "commentary.overview_instrument_error",
                instrument=inst,
                error=str(exc),
            )
            classifications[inst] = {"weekly": "NEUTRAL", "monthly": "NEUTRAL"}

    rankings = _compute_composite_score(classifications)
    narrative_data = {
        "page": "overview",
        "classifications": classifications,
        "rankings": rankings,
    }
    commentary = _build_narrative(narrative_data)
    return {"commentary": commentary, "instruments_analyzed": instruments_analyzed}


def _handle_strategy(req: CommentaryRequest) -> dict[str, Any]:
    """Strategy rationale commentary for the RITA Strategy page."""
    if not req.instrument:
        raise HTTPException(
            status_code=400,
            detail="instrument is required for page='strategy'",
        )

    from rita.core.technical_analyzer import get_market_summary, get_sentiment_score
    from rita.core.strategy_engine import get_allocation_recommendation
    from rita.api.v1.workflow.chat import _get_df

    inst = req.instrument.upper()
    try:
        df = _get_df(inst)
        summary = get_market_summary(df)
        scored = get_sentiment_score(summary)
        alloc = get_allocation_recommendation(summary, scored)
    except Exception as exc:
        log.warning("commentary.strategy_data_error", instrument=inst, error=str(exc))
        commentary = (
            f"Strategy data for {inst} is temporarily unavailable. "
            "Check that market data CSV files are present and up to date."
        )
        return {"commentary": commentary, "instruments_analyzed": [inst]}

    narrative_data = {
        "page": "strategy",
        "instrument": inst,
        "recommendation": alloc.get("recommendation", "HOLD"),
        "allocation_pct": alloc.get("allocation_pct", 0),
        "rationale": alloc.get("rationale", ""),
        "primary_constraint": alloc.get("primary_constraint", ""),
    }
    commentary = _build_narrative(narrative_data)
    return {"commentary": commentary, "instruments_analyzed": [inst]}


# ── Dispatch table ────────────────────────────────────────────────────────────

_DISPATCH: dict[tuple[str, str], Callable] = {
    ("rita", "overview"): _handle_overview,
    ("rita", "strategy"): _handle_strategy,
}


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("", response_model=CommentaryResponse)
def generate_commentary(req: CommentaryRequest, db: Session = Depends(get_db)) -> CommentaryResponse:
    """Generate deterministic AI narrative commentary for the given app+page combination.

    Returns HTTP 400 for unknown app+page combos or if instrument is missing for
    pages that require it.  Never raises HTTP 500 — partial commentary returned
    on data errors.
    """
    global _consecutive_errors

    handler = _DISPATCH.get((req.app, req.page))
    if handler is None:
        raise HTTPException(
            status_code=400,
            detail=f"No handler registered for app='{req.app}' page='{req.page}'",
        )

    t0 = _time.perf_counter()
    status = "ok"
    commentary = "—"
    instruments_analyzed: list[str] = []

    try:
        result = handler(req)
        commentary = result["commentary"]
        instruments_analyzed = result["instruments_analyzed"]
        _consecutive_errors = 0
    except HTTPException:
        raise
    except Exception as exc:
        _consecutive_errors += 1
        status = "error"
        commentary = (
            "Commentary is temporarily unavailable. "
            "Market data will still display normally."
        )
        log.warning(
            "commentary.handler_error",
            app=req.app,
            page=req.page,
            error=str(exc),
            consecutive=_consecutive_errors,
        )
        if _consecutive_errors >= _ERROR_WARN_THRESHOLD:
            log.warning(
                "commentary.repeated_errors",
                consecutive=_consecutive_errors,
                threshold=_ERROR_WARN_THRESHOLD,
            )

    latency_ms = round((_time.perf_counter() - t0) * 1000, 1)

    # DB audit write
    try:
        log_entry = CommentaryLogCreate(
            id=str(uuid.uuid4()),
            app=req.app,
            page=req.page,
            instrument=req.instrument,
            latency_ms=latency_ms,
            status=status,
            commentary_preview=commentary[:200],
            timestamp=datetime.now(timezone.utc),
        )
        CommentaryLogRepository(db).create(log_entry)
    except Exception as exc:
        log.warning("commentary.audit_write_failed", error=str(exc))

    return CommentaryResponse(
        app=req.app,
        page=req.page,
        commentary=commentary,
        instruments_analyzed=instruments_analyzed,
        latency_ms=latency_ms,
    )
