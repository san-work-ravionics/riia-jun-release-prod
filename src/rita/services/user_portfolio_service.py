"""Service layer for User Portfolio Store.

F44 P2 — multi-currency portfolios:
- A portfolio belongs to one ``location`` (europe | india | us) and is held in that location's
  currency (``retirement_plan.locations.<loc>.currency`` in config).  ``location=None`` is the
  legacy cross-geography portfolio, held in EUR (Portfolio Builder still saves this way).
- The currency is always derived server-side; a client cannot set it.
- With a location, every holding must be an instrument of that location (else ``ValueError``
  → 422 ``instrument X is not in location Y``).
- One active portfolio per (user, location) (D1); ``None`` is its own bucket.
- ``total_value_eur`` (deprecated) is still written: the EUR value via ``FxService``, or None
  when no FX rate is cached.

The module-level ``portfolio_*`` / ``holding_cash`` helpers are the one place readers get the
P2 fields with the legacy fallbacks (``total_value ?? total_value_eur``, ``cash ?? cash_eur``,
currency EUR when unset).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from rita.config import get_settings
from rita.core.geography import country_to_location
from rita.models.user_portfolio import UserPortfolioModel
from rita.repositories.instrument import InstrumentRepository
from rita.repositories.user_portfolio import UserPortfolioRepo
from rita.repositories.user_portfolio_key import UserPortfolioKeyRepo
from rita.schemas.user_portfolio import HoldingItem, UserPortfolioOut
from rita.services.fx_service import FxService

LEGACY_CURRENCY = "EUR"

# Instrument → location: the instrument's country through the shared geography rule
# (rita.core.geography — the same buckets as the RITA geography overview), else its currency.
_CCY_LOCATION = {"INR": "india", "USD": "us", "EUR": "europe"}


# ── reader helpers (legacy fallbacks) ─────────────────────────────────────────

def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def portfolio_currency(row: Any) -> str:
    """Portfolio currency; EUR for legacy rows (and anything without a string currency)."""
    c = getattr(row, "currency", None)
    return c if isinstance(c, str) and c else LEGACY_CURRENCY


def portfolio_location(row: Any) -> str | None:
    loc = getattr(row, "location", None)
    return loc if isinstance(loc, str) and loc else None


def portfolio_total(row: Any) -> float | None:
    """Total value in the portfolio currency: ``total_value``, else the legacy ``total_value_eur``
    (only meaningful for an EUR portfolio)."""
    tv = _num(getattr(row, "total_value", None))
    if tv is not None:
        return tv
    if portfolio_currency(row) == LEGACY_CURRENCY:
        return _num(getattr(row, "total_value_eur", None))
    return None


def holding_cash(h: Any) -> float | None:
    """Leftover cash of a holding (dict or model): ``cash`` wins over the legacy ``cash_eur``."""
    get = h.get if isinstance(h, dict) else (lambda k: getattr(h, k, None))
    cash = _num(get("cash"))
    return cash if cash is not None else _num(get("cash_eur"))


# ── location rules ─────────────────────────────────────────────────────────────

def location_currency(location: str) -> str:
    """Currency of a location preset; ``ValueError`` for an unknown location."""
    locations = get_settings().retirement_plan.locations
    if location not in locations:
        raise ValueError(f"unknown location {location!r}")
    return locations[location].currency


def location_for_country(country: str | None) -> str | None:
    """Portfolio location for a country code / name (``None`` for the geography "Other" bucket)."""
    return country_to_location(country)


class UserPortfolioService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def instrument_location(self, instrument_id: str) -> str | None:
        """Location of an instrument from the instruments table (country, then currency)."""
        inst = InstrumentRepository(self._db).find_by_id(instrument_id.upper())
        if inst is None:
            return None
        loc = location_for_country(inst.country_code)
        if loc is None and inst.currency:
            loc = _CCY_LOCATION.get(inst.currency.upper())
        return loc

    def save(
        self,
        user_id: str,
        holdings: list[HoldingItem],
        name: str | None = None,
        total_value_eur: float | None = None,
        location: str | None = None,
        total_value: float | None = None,
    ) -> UserPortfolioOut:
        """Persist a new portfolio snapshot for (user, location) — soft-replaces the active one
        for that location only (D1)."""
        if not holdings:
            raise ValueError("holdings must not be empty")
        if round(sum(h.allocation_pct for h in holdings), 6) != 100.0:
            raise ValueError("allocation_pct must sum to 100")

        fx = FxService(self._db)
        if location is None:
            currency = LEGACY_CURRENCY
            native_total = total_value if total_value is not None else total_value_eur
        else:
            currency = location_currency(location)
            for h in holdings:
                if self.instrument_location(h.instrument_id) != location:
                    raise ValueError(f"instrument {h.instrument_id} is not in location {location}")
            native_total = total_value
            if native_total is None and total_value_eur is not None:
                native_total = fx.convert(total_value_eur, LEGACY_CURRENCY, currency)
        eur_total = native_total if currency == LEGACY_CURRENCY else fx.convert(native_total, currency, LEGACY_CURRENCY)

        stored = []
        for h in holdings:
            cash = h.cash
            if cash is None and currency == LEGACY_CURRENCY:
                cash = h.cash_eur
            stored.append({
                "instrument_id": h.instrument_id,
                "allocation_pct": h.allocation_pct,
                "shares": h.shares,
                "cash": cash,
                # legacy key, one release: only meaningful for an EUR portfolio
                "cash_eur": cash if currency == LEGACY_CURRENCY else None,
            })

        resolved_name = name.strip() if name else "My Portfolio"
        key = UserPortfolioKeyRepo(self._db).find_or_create(user_id)
        repo = UserPortfolioRepo(self._db)
        repo.deactivate_for_key_and_location(key.key_id, location)

        # Python timestamp with microseconds (naive UTC, like CURRENT_TIMESTAMP): func.now() has
        # 1-second resolution on SQLite, so same-second saves tied (review #8).
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        new_row = UserPortfolioModel(
            portfolio_id=str(uuid.uuid4()),
            created_at=now,
            updated_at=now,
            key_id=key.key_id,
            name=resolved_name,
            holdings=stored,
            currency=currency,
            location=location,
            total_value=native_total,
            total_value_eur=eur_total,
            is_active=True,
        )
        repo.insert(new_row)

        self._db.commit()
        self._db.refresh(new_row)
        return UserPortfolioOut.model_validate(new_row)

    def get_all(self, user_id: str) -> list[UserPortfolioOut]:
        """All active portfolios across every location bucket, most-recent first."""
        key = UserPortfolioKeyRepo(self._db).find_by_user_id(user_id)
        if key is None:
            return []
        rows = UserPortfolioRepo(self._db).find_all_active_by_key_id(key.key_id)
        return [UserPortfolioOut.model_validate(row) for row in rows]

    def get(self, user_id: str, location: str | None = None) -> UserPortfolioOut | None:
        """Active portfolio for the user.

        ``location`` given → that location's active portfolio; omitted → the most recently
        saved active portfolio of any location (pre-P2 behaviour for single-portfolio readers).
        """
        key = UserPortfolioKeyRepo(self._db).find_by_user_id(user_id)
        if key is None:
            return None
        repo = UserPortfolioRepo(self._db)
        row = (repo.find_active_by_key_id(key.key_id) if location is None
               else repo.find_active_by_key_and_location(key.key_id, location))
        if row is None:
            return None
        return UserPortfolioOut.model_validate(row)
