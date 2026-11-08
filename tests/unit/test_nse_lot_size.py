"""NSE lot-size lookup tolerates exchange suffixes and the M&M spelling (open bug from 2026-06)."""
import pytest

from rita.core.portfolio_engine import NSE_LOT_SIZE, nse_lot_size


@pytest.mark.parametrize("instrument", ["MM", "mm", "M&M", "M&M.NS", "m&m.ns", "MM.NS", " MM "])
def test_mm_resolves_to_the_mm_lot_size(instrument):
    assert nse_lot_size(instrument) == NSE_LOT_SIZE["MM"]


def test_suffixed_symbol_resolves():
    assert nse_lot_size("RELIANCE.NS") == NSE_LOT_SIZE["RELIANCE"]


def test_unknown_instrument_is_none():
    assert nse_lot_size("ASML") is None
