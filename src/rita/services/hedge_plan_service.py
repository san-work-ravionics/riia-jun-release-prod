"""HedgePlanService — save/read the hedge plan and archive every save (F40 Phase 2).

ADR-002: all data access goes through repositories.  This service owns the unit of
work for the hedge-plan PUT: plan upsert (preserve-on-omit merge), server-side market
enrichment, client-context validation, the append-only history row, and exactly one
``db.commit()`` (with rollback on any failure).

Every PUT appends one history row (no dedupe — each save is a user action).
``trigger`` ("explicit" | "autosave") is recorded on the row.  Per-instrument
``ann_vol_pct`` is computed only for explicit saves (bounds the cost of autosaves).
"""
from __future__ import annotations

import math
import statistics
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy.orm import Session

from rita.config import get_settings
from rita.core.portfolio_engine import INSTRUMENT_CCY
from rita.models.user import UserModel
from rita.models.user_hedge_plan import UserHedgePlanModel
from rita.models.user_hedge_plan_history import UserHedgePlanHistoryModel
from rita.repositories.market_data import MarketDataCacheRepository
from rita.repositories.user_hedge_plan import UserHedgePlanRepo
from rita.repositories.user_hedge_plan_history import UserHedgePlanHistoryRepo
from rita.repositories.user_portfolio import UserPortfolioRepo
from rita.repositories.user_portfolio_key import UserPortfolioKeyRepo
from rita.schemas.user_hedge_plan import (
    MAX_CONTEXT_INSTRUMENTS,
    HedgeContext,
    HedgeContextInstrument,
    HedgePlanCreate,
    HedgePlanOut,
)

log = structlog.get_logger(__name__)

_VOL_WINDOW = 252
_VOL_MIN_CLOSES = 30


class PortfolioKeyNotFound(LookupError):
    """The user has no portfolio key — PUT maps this to HTTP 404."""


class HedgePlanService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._keys = UserPortfolioKeyRepo(db)
        self._plans = UserHedgePlanRepo(db)
        self._history = UserHedgePlanHistoryRepo(db)
        self._portfolios = UserPortfolioRepo(db)
        self._market = MarketDataCacheRepository(db)

    # ── save ────────────────────────────────────────────────────────────────
    def save(self, user: UserModel, body: HedgePlanCreate) -> HedgePlanOut:
        key = self._keys.find_by_user_id(user.id)
        if key is None:
            raise PortfolioKeyNotFound("No portfolio key found")

        now = datetime.now(timezone.utc)
        try:
            plan = UserHedgePlanModel(
                key_id=key.key_id,
                hedged_ids=list(body.hedged_ids),
                coverage=body.coverage,
                scenario_tab=body.scenario_tab,
                duration="1y",  # business rule: always 1-year horizon
                last_step=body.last_step,  # None = preserve (first insert -> "exposure")
                selections=body.selections,  # None = preserve
                updated_at=now,
            )
            self._plans.upsert(plan)
            stored = self._plans.find_by_key_id(key.key_id)

            self._history.append(self._build_history_row(user, key.key_id, body, stored, now))
            self._db.commit()  # exactly one commit for plan + history
        except Exception:
            self._db.rollback()
            raise

        return HedgePlanOut.model_validate(stored)

    # ── history row ─────────────────────────────────────────────────────────
    def _build_history_row(
        self,
        user: UserModel,
        key_id: str,
        body: HedgePlanCreate,
        stored: UserHedgePlanModel,
        now: datetime,
    ) -> UserHedgePlanHistoryModel:
        ctx = self._parse_context(body.context)
        explicit = body.trigger == "explicit"
        selections = stored.selections or {}
        hedged = set(stored.hedged_ids or [])

        portfolio = self._portfolios.find_active_by_key_id(key_id)
        holdings = list(portfolio.holdings or []) if portfolio is not None else []

        ctx_by_id = {c.instrument_id: c for c in ctx.instruments}
        instruments: list[dict[str, Any]] = []
        seen: set[str] = set()
        cash_total = 0.0
        for h in holdings:
            iid = str(h.get("instrument_id", ""))
            if not iid:
                continue
            seen.add(iid)
            cash_total += float(h.get("cash_eur") or 0.0)
            instruments.append(
                self._instrument_block(
                    iid, h, iid in hedged, selections.get(iid), ctx_by_id.get(iid), explicit
                )
            )
        for iid in stored.hedged_ids or []:  # hedged but not in the active portfolio
            if iid not in seen:
                instruments.append(
                    self._instrument_block(iid, {}, True, selections.get(iid), ctx_by_id.get(iid), explicit)
                )

        return UserHedgePlanHistoryModel(
            history_id=str(uuid.uuid4()),
            key_id=key_id,
            user_id=user.id,
            saved_at=now,
            trigger=body.trigger,
            source=body.source,
            last_step=stored.last_step,
            scenario_tab=stored.scenario_tab,
            coverage=stored.coverage,
            duration=stored.duration,
            hedged_ids=list(stored.hedged_ids or []),
            selections=dict(stored.selections) if stored.selections else None,
            instruments=instruments,
            portfolio={
                "total_value_eur": portfolio.total_value_eur if portfolio is not None else None,
                "cash_eur": round(cash_total, 2) if portfolio is not None else None,
                "n_holdings": len(holdings),
            },
            margin=ctx.margin,
            schema_version=1,
            app_version=get_settings().app.version,
        )

    def _instrument_block(
        self,
        iid: str,
        holding: dict,
        hedged: bool,
        strategy: str | None,
        client: HedgeContextInstrument | None,
        explicit: bool,
    ) -> dict[str, Any]:
        shares = holding.get("shares")
        shares = int(shares) if isinstance(shares, (int, float)) and shares > 0 else None
        currency = INSTRUMENT_CCY.get(iid.upper())  # unmapped -> None (no default, no FX)
        spot = spot_date = value = ann_vol = None
        if currency is not None:
            try:
                row = self._market.find_latest(iid)
                if row is not None:
                    spot = float(row.close)
                    spot_date = row.date.isoformat()
                    if shares is not None:
                        value = round(shares * spot, 2)
                if explicit:
                    ann_vol = self._ann_vol_pct(iid)
            except Exception as exc:  # enrichment must never fail a save
                log.warning("hedge_plan.enrich_failed", instrument_id=iid, error=str(exc))
        block: dict[str, Any] = {
            "instrument_id": iid,
            "hedged": hedged,
            "strategy": strategy,
            "shares": shares,
            "allocation_pct": float(holding.get("allocation_pct") or 0.0),
            "currency": currency,
            "spot": spot,
            "spot_date": spot_date,
            "position_value": value,
            "ann_vol_pct": ann_vol,
        }
        c = client.model_dump() if client is not None else {}
        for f in ("strike_pct", "strike_label", "premium_pct", "cost_source",
                  "hedge_type", "risk_score", "protected_pct"):
            block[f] = c.get(f)
        return block

    def _ann_vol_pct(self, iid: str) -> float | None:
        closes = self._market.find_recent_closes(iid, _VOL_WINDOW + 1)
        if len(closes) < _VOL_MIN_CLOSES:
            return None
        rets = [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes)) if closes[i - 1]]
        if len(rets) < 2:
            return None
        return round(statistics.stdev(rets) * math.sqrt(252) * 100, 4)

    @staticmethod
    def _parse_context(raw: Any) -> HedgeContext:
        """Lenient parse: invalid context is dropped, oversize truncated — never raises."""
        if not isinstance(raw, dict):
            return HedgeContext()
        items: list[HedgeContextInstrument] = []
        raw_items = raw.get("instruments")
        if isinstance(raw_items, list):
            if len(raw_items) > MAX_CONTEXT_INSTRUMENTS:
                log.warning("hedge_plan.context_truncated", received=len(raw_items))
            for r in raw_items[:MAX_CONTEXT_INSTRUMENTS]:
                try:
                    items.append(HedgeContextInstrument.model_validate(r))
                except Exception:
                    log.warning("hedge_plan.context_item_dropped")
        margin = raw.get("margin")
        return HedgeContext(instruments=items, margin=margin if isinstance(margin, dict) else None)

    # ── reads ───────────────────────────────────────────────────────────────
    def history_for_user(self, user: UserModel, limit: int = 50, trigger: str | None = None) -> list:
        key = self._keys.find_by_user_id(user.id)
        if key is None:
            return []
        return self._history.list_by_key_id(key.key_id, limit=limit, trigger=trigger)
