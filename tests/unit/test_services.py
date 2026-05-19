"""Unit tests for ManoeuvreService and PortfolioService.

Uses the ``db_session`` fixture from conftest.py (in-memory SQLite, function-scoped).
All rita.* imports are deferred to inside test functions per project constraints.
"""

from __future__ import annotations

from datetime import date, datetime, timezone, timedelta


# ---------------------------------------------------------------------------
# ManoeuvreService tests
# ---------------------------------------------------------------------------


def _make_manoeuvre_create(
    *,
    timestamp: datetime | None = None,
    dt: date | None = None,
    month: str = "APR",
    action: str = "add",
    lot_key: str = "NIFTY26APR22700PE_L1",
):
    from rita.schemas.manoeuvres import ManoeuvreCreate

    ts = timestamp or datetime(2026, 4, 5, 10, 0, 0, tzinfo=timezone.utc)
    d = dt or ts.date()
    return ManoeuvreCreate(
        timestamp=ts,
        date=d,
        month=month,
        action=action,
        lot_key=lot_key,
    )


def test_record_returns_manoeuvre_with_id(db_session) -> None:
    """record() assigns a UUID manoeuvre_id and recorded_at."""
    from rita.services.manoeuvre_service import ManoeuvreService

    svc = ManoeuvreService(db_session)
    body = _make_manoeuvre_create()
    result = svc.record(body)

    assert result.manoeuvre_id is not None
    assert len(result.manoeuvre_id) == 36  # UUID4 string
    assert result.recorded_at is not None


def test_list_all_empty_initially(db_session) -> None:
    """list_all() returns [] on fresh DB."""
    from rita.services.manoeuvre_service import ManoeuvreService

    svc = ManoeuvreService(db_session)
    assert svc.list_all() == []


def test_list_all_after_record(db_session) -> None:
    """list_all() contains the recorded item."""
    from rita.services.manoeuvre_service import ManoeuvreService

    svc = ManoeuvreService(db_session)
    body = _make_manoeuvre_create(lot_key="NIFTY26APR22700CE_L1")
    svc.record(body)

    results = svc.list_all()
    assert len(results) == 1
    assert results[0].lot_key == "NIFTY26APR22700CE_L1"


def test_list_recent_respects_limit(db_session) -> None:
    """list_recent(n=2) with 5 records returns exactly 2."""
    from rita.services.manoeuvre_service import ManoeuvreService

    svc = ManoeuvreService(db_session)
    base_ts = datetime(2026, 4, 5, 9, 0, 0, tzinfo=timezone.utc)
    for i in range(5):
        svc.record(
            _make_manoeuvre_create(
                timestamp=base_ts + timedelta(minutes=i),
                lot_key=f"NIFTY_L{i}",
            )
        )

    results = svc.list_recent(n=2)
    assert len(results) == 2


def test_list_recent_is_sorted_desc(db_session) -> None:
    """list_recent() returns the most recent timestamp first."""
    from rita.services.manoeuvre_service import ManoeuvreService

    svc = ManoeuvreService(db_session)
    base_ts = datetime(2026, 4, 5, 9, 0, 0, tzinfo=timezone.utc)
    for i in range(3):
        svc.record(
            _make_manoeuvre_create(
                timestamp=base_ts + timedelta(hours=i),
                lot_key=f"NIFTY_L{i}",
            )
        )

    results = svc.list_recent(n=3)
    timestamps = [r.timestamp for r in results]
    assert timestamps == sorted(timestamps, reverse=True)


def test_list_by_date_filters_correctly(db_session) -> None:
    """list_by_date() only returns manoeuvres matching the target date."""
    from rita.services.manoeuvre_service import ManoeuvreService

    svc = ManoeuvreService(db_session)
    date_a = date(2026, 4, 5)
    date_b = date(2026, 4, 6)

    ts_a = datetime(2026, 4, 5, 10, 0, 0, tzinfo=timezone.utc)
    ts_b = datetime(2026, 4, 6, 10, 0, 0, tzinfo=timezone.utc)

    svc.record(_make_manoeuvre_create(timestamp=ts_a, dt=date_a, lot_key="NIFTY_A"))
    svc.record(_make_manoeuvre_create(timestamp=ts_a, dt=date_a, lot_key="NIFTY_A2"))
    svc.record(_make_manoeuvre_create(timestamp=ts_b, dt=date_b, lot_key="NIFTY_B"))

    results = svc.list_by_date(date_a)
    assert len(results) == 2
    assert all(r.date == date_a for r in results)

    results_b = svc.list_by_date(date_b)
    assert len(results_b) == 1
    assert results_b[0].lot_key == "NIFTY_B"


# ---------------------------------------------------------------------------
# PortfolioService tests
# ---------------------------------------------------------------------------


def _make_portfolio_create(
    *,
    dt: date | None = None,
    pnl_now: float = 0.0,
    lot_count: int = 2,
    underlying: str = "NIFTY",
):
    from rita.schemas.portfolio import PortfolioCreate

    d = dt or date(2026, 4, 5)
    return PortfolioCreate(
        date=d,
        underlying=underlying,
        pnl_now=pnl_now,
        lot_count=lot_count,
    )


def test_record_returns_portfolio_state(db_session) -> None:
    """record() returns a Portfolio with auto-generated portfolio_id."""
    from rita.services.portfolio_service import PortfolioService

    svc = PortfolioService(db_session)
    body = _make_portfolio_create(pnl_now=1500.0)
    result = svc.record(body)

    assert result.portfolio_id is not None
    assert len(result.portfolio_id) == 36  # UUID4 string
    assert result.recorded_at is not None
    assert result.pnl_now == pytest.approx(1500.0)


def test_get_latest_returns_most_recent(db_session) -> None:
    """get_latest() returns portfolio rows for the most recent date."""
    from rita.services.portfolio_service import PortfolioService

    svc = PortfolioService(db_session)
    svc.record(_make_portfolio_create(dt=date(2026, 4, 4), pnl_now=100.0))
    svc.record(_make_portfolio_create(dt=date(2026, 4, 5), pnl_now=200.0))
    svc.record(_make_portfolio_create(dt=date(2026, 4, 3), pnl_now=50.0))

    latest = svc.get_latest()
    assert len(latest) == 1
    assert latest[0].date == date(2026, 4, 5)
    assert latest[0].pnl_now == pytest.approx(200.0)


def test_get_by_date_returns_matching(db_session) -> None:
    """get_by_date() returns the correct record(s)."""
    from rita.services.portfolio_service import PortfolioService

    svc = PortfolioService(db_session)
    target = date(2026, 4, 5)
    svc.record(_make_portfolio_create(dt=target, pnl_now=999.0))
    svc.record(_make_portfolio_create(dt=date(2026, 4, 6), pnl_now=0.0))

    results = svc.get_by_date(target)
    assert len(results) == 1
    assert results[0].date == target
    assert results[0].pnl_now == pytest.approx(999.0)


def test_get_by_date_returns_none_when_missing(db_session) -> None:
    """get_by_date() returns [] for an unknown date."""
    from rita.services.portfolio_service import PortfolioService

    svc = PortfolioService(db_session)
    results = svc.get_by_date(date(2099, 1, 1))
    assert results == []


# ---------------------------------------------------------------------------
# pytest.approx import — needed for float assertions
# ---------------------------------------------------------------------------

import pytest  # noqa: E402 — placed after fixtures to satisfy linter ordering
