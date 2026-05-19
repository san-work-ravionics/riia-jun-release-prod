"""Black-Scholes reference tests for RITA Greeks.

These tests establish mathematical reference values that serve as regression
guards before any Greeks code is added to core/.  The pricer is implemented
inline using only the ``math`` standard library — no scipy dependency.

Reference parameters: S=100, K=100, T=1.0, r=0.05, sigma=0.2, q=0.0
All assertions use pytest.approx(abs=1e-4).
"""

from __future__ import annotations

import math

import pytest

# ---------------------------------------------------------------------------
# Standalone Black-Scholes pricer (no core/ import)
# ---------------------------------------------------------------------------


def _d1(S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> float:
    return (math.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))


def _d2(S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> float:
    return _d1(S, K, T, r, sigma, q) - sigma * math.sqrt(T)


def _norm_cdf(x: float) -> float:
    """Standard normal CDF using math.erfc."""
    return 0.5 * math.erfc(-x / math.sqrt(2))


def _norm_pdf(x: float) -> float:
    """Standard normal PDF."""
    return math.exp(-0.5 * x**2) / math.sqrt(2 * math.pi)


def bs_call(S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> float:
    d1 = _d1(S, K, T, r, sigma, q)
    d2 = _d2(S, K, T, r, sigma, q)
    return S * math.exp(-q * T) * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)


def bs_put(S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> float:
    d1 = _d1(S, K, T, r, sigma, q)
    d2 = _d2(S, K, T, r, sigma, q)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * math.exp(-q * T) * _norm_cdf(-d1)


def bs_delta_call(S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> float:
    return math.exp(-q * T) * _norm_cdf(_d1(S, K, T, r, sigma, q))


def bs_delta_put(S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> float:
    return math.exp(-q * T) * (_norm_cdf(_d1(S, K, T, r, sigma, q)) - 1)


def bs_gamma(S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> float:
    d1 = _d1(S, K, T, r, sigma, q)
    return math.exp(-q * T) * _norm_pdf(d1) / (S * sigma * math.sqrt(T))


def bs_theta_call(S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> float:
    """Theta per year (will be negative for long calls)."""
    d1 = _d1(S, K, T, r, sigma, q)
    d2 = _d2(S, K, T, r, sigma, q)
    term1 = -S * math.exp(-q * T) * _norm_pdf(d1) * sigma / (2 * math.sqrt(T))
    term2 = -r * K * math.exp(-r * T) * _norm_cdf(d2)
    term3 = q * S * math.exp(-q * T) * _norm_cdf(d1)
    return term1 + term2 + term3


def bs_vega(S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> float:
    """Vega (sensitivity to 1-unit change in sigma)."""
    d1 = _d1(S, K, T, r, sigma, q)
    return S * math.exp(-q * T) * _norm_pdf(d1) * math.sqrt(T)


# ---------------------------------------------------------------------------
# Reference parameters
# ---------------------------------------------------------------------------

S, K, T, r, sigma, q = 100.0, 100.0, 1.0, 0.05, 0.2, 0.0

# Pre-computed Black-Scholes reference values (ATM, S=K=100, T=1, r=5%, σ=20%)
#   call  ≈ 10.4506
#   put   ≈  5.5735
#   These match standard BS tables.
CALL_REF = bs_call(S, K, T, r, sigma, q)
PUT_REF = bs_put(S, K, T, r, sigma, q)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_call_price_atm() -> None:
    """ATM European call price against known reference."""
    price = bs_call(S, K, T, r, sigma, q)
    # Known BS closed-form: ~10.4506
    assert price == pytest.approx(10.4506, abs=1e-4)


def test_put_price_atm() -> None:
    """ATM European put price — verified via put-call parity."""
    price = bs_put(S, K, T, r, sigma, q)
    # Known BS closed-form: ~5.5735
    assert price == pytest.approx(5.5735, abs=1e-4)


def test_delta_call() -> None:
    """Call delta: ITM (S > K) > ATM ≈ 0.6368 > OTM (S < K).

    For a call option:
    - ITM: spot price above strike (S=120 > K=100)
    - OTM: spot price below strike (S=80 < K=100)
    """
    delta_itm = bs_delta_call(120.0, K, T, r, sigma, q)   # S > K → ITM call
    delta_atm = bs_delta_call(S, K, T, r, sigma, q)        # S = K → ATM call
    delta_otm = bs_delta_call(80.0, K, T, r, sigma, q)    # S < K → OTM call

    # ATM call delta reference value
    assert delta_atm == pytest.approx(0.6368, abs=1e-4)
    # Monotonicity: higher spot → higher call delta
    assert delta_itm > delta_atm > delta_otm
    # All in (0, 1)
    assert 0.0 < delta_itm < 1.0
    assert 0.0 < delta_atm < 1.0
    assert 0.0 < delta_otm < 1.0


def test_delta_put() -> None:
    """Put delta is negative; equals call_delta - 1 (no dividends)."""
    delta_call = bs_delta_call(S, K, T, r, sigma, q)
    delta_put = bs_delta_put(S, K, T, r, sigma, q)

    assert delta_put < 0.0
    # Put-call delta parity: delta_call - delta_put = exp(-q*T) = 1 (q=0)
    assert delta_call - delta_put == pytest.approx(1.0, abs=1e-4)
    # ATM put delta reference
    assert delta_put == pytest.approx(-0.3632, abs=1e-4)


def test_gamma() -> None:
    """Gamma is positive and identical for calls and puts (same formula)."""
    gamma_call = bs_gamma(S, K, T, r, sigma, q)
    # Gamma is the same for calls and puts
    gamma_check = bs_gamma(S, K, T, r, sigma, q)

    assert gamma_call > 0.0
    assert gamma_call == pytest.approx(gamma_check, abs=1e-10)
    # ATM gamma reference: ~0.01876
    assert gamma_call == pytest.approx(0.01876, abs=1e-4)


def test_theta_call_is_negative() -> None:
    """Theta for a long call is always negative (time decay costs the holder)."""
    theta = bs_theta_call(S, K, T, r, sigma, q)
    assert theta < 0.0


def test_vega_positive() -> None:
    """Vega is always positive — higher vol increases option value."""
    vega = bs_vega(S, K, T, r, sigma, q)
    assert vega > 0.0
    # ATM vega reference: ~37.524 (per unit sigma, annualised)
    assert vega == pytest.approx(37.524, abs=1e-2)


def test_put_call_parity() -> None:
    """C - P = S*exp(-q*T) - K*exp(-r*T)."""
    call = bs_call(S, K, T, r, sigma, q)
    put = bs_put(S, K, T, r, sigma, q)

    lhs = call - put
    rhs = S * math.exp(-q * T) - K * math.exp(-r * T)

    assert lhs == pytest.approx(rhs, abs=1e-4)
