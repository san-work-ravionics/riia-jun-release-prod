"""Unit tests for rita.core.rl_diagnostics (Feature 32, Phase 3.6).

Covers: one insight generated per scorecard parameter (10 total), correct
severity classification (fail/warn/info/pass) at representative values for
each of the 10 parameters, and worst-first sort ordering.
"""
from __future__ import annotations

from rita.core.rl_diagnostics import generate_insights


def _base_scorecard() -> dict:
    """A fully-healthy scorecard — every parameter inside its healthy range."""
    return {
        "functional": {
            "F1_sharpe_test": {"value": 1.5, "healthy": True},
            "F2_max_drawdown_test": {"value": -0.05, "healthy": True},
            "F3_market_regime_performance": {
                "bull": {"sharpe": 1.2, "n_days": 40, "note": None},
                "bear": {"sharpe": 0.8, "n_days": 30, "note": None},
                "sideways": {"sharpe": 0.5, "n_days": 20, "note": None},
            },
            "F4_win_rate": {"value": 0.55, "healthy": True},
            "F5_baseline_relative": {"overall": 0.3, "healthy": True, "per_regime": {}},
        },
        "technical": {
            "T1_action_entropy": {"value": 1.2, "max_possible": 2.0, "healthy": True},
            "T2_train_test_sharpe_gap": {"value": 0.1, "healthy": True},
            "T3_reward_convergence_pct": {"value": 50.0, "healthy": True},
            "T4_seed_consistency_cv": {"value": 0.2, "healthy": True},
            "T5_per_regime_action_distribution": {"regime_blind": False},
        },
    }


def test_generate_insights_returns_one_per_parameter():
    insights = generate_insights(_base_scorecard())
    params = {i["parameter"] for i in insights}
    assert params == {"F1", "F2", "F3", "F4", "F5", "T1", "T2", "T3", "T4", "T5"}
    assert len(insights) == 10


def test_all_healthy_scorecard_yields_all_pass():
    insights = generate_insights(_base_scorecard())
    assert all(i["severity"] == "pass" for i in insights)


def test_sorted_worst_first():
    sc = _base_scorecard()
    sc["functional"]["F1_sharpe_test"] = {"value": 0.4, "healthy": False}  # fail
    sc["technical"]["T1_action_entropy"] = {"value": 1.9, "max_possible": 2.0, "healthy": False}  # warn
    insights = generate_insights(sc)
    severities = [i["severity"] for i in insights]
    # fail(es) must precede warn(s) must precede pass(es)
    rank = {"fail": 0, "warn": 1, "info": 2, "pass": 3}
    ranks = [rank[s] for s in severities]
    assert ranks == sorted(ranks)
    assert severities[0] == "fail"


# ── F1 ──────────────────────────────────────────────────────────────────────

def test_f1_fail_below_1_0():
    sc = _base_scorecard()
    sc["functional"]["F1_sharpe_test"] = {"value": 0.6, "healthy": False}
    insight = next(i for i in generate_insights(sc) if i["parameter"] == "F1")
    assert insight["severity"] == "fail"
    assert "reward misalignment" in insight["message"] or "0.6" in insight["message"]


def test_f1_pass_above_1_0():
    sc = _base_scorecard()
    insight = next(i for i in generate_insights(sc) if i["parameter"] == "F1")
    assert insight["severity"] == "pass"


# ── F2 ──────────────────────────────────────────────────────────────────────

def test_f2_fail_worse_than_minus_10pct():
    sc = _base_scorecard()
    sc["functional"]["F2_max_drawdown_test"] = {"value": -0.15, "healthy": False}
    insight = next(i for i in generate_insights(sc) if i["parameter"] == "F2")
    assert insight["severity"] == "fail"


def test_f2_pass_within_limit():
    sc = _base_scorecard()
    insight = next(i for i in generate_insights(sc) if i["parameter"] == "F2")
    assert insight["severity"] == "pass"


# ── F3 ──────────────────────────────────────────────────────────────────────

def test_f3_warn_poor_bear_sharpe():
    sc = _base_scorecard()
    sc["functional"]["F3_market_regime_performance"]["bear"] = {"sharpe": -0.5, "n_days": 30, "note": None}
    insight = next(i for i in generate_insights(sc) if i["parameter"] == "F3")
    assert insight["severity"] == "warn"


def test_f3_info_insufficient_data():
    sc = _base_scorecard()
    sc["functional"]["F3_market_regime_performance"] = {
        "bull": {"sharpe": None, "n_days": 2, "note": "insufficient_data"},
        "bear": {"sharpe": None, "n_days": 1, "note": "insufficient_data"},
        "sideways": {"sharpe": None, "n_days": 0, "note": "insufficient_data"},
    }
    insight = next(i for i in generate_insights(sc) if i["parameter"] == "F3")
    assert insight["severity"] == "info"


# ── F4 ──────────────────────────────────────────────────────────────────────

def test_f4_fail_below_45pct():
    sc = _base_scorecard()
    sc["functional"]["F4_win_rate"] = {"value": 0.30, "healthy": False}
    insight = next(i for i in generate_insights(sc) if i["parameter"] == "F4")
    assert insight["severity"] == "fail"


# ── F5 ──────────────────────────────────────────────────────────────────────

def test_f5_fail_negative_relative():
    sc = _base_scorecard()
    sc["functional"]["F5_baseline_relative"] = {"overall": -0.2, "healthy": False, "per_regime": {}}
    insight = next(i for i in generate_insights(sc) if i["parameter"] == "F5")
    assert insight["severity"] == "fail"


# ── T1 ──────────────────────────────────────────────────────────────────────

def test_t1_fail_collapsed_policy():
    sc = _base_scorecard()
    sc["technical"]["T1_action_entropy"] = {"value": 0.1, "max_possible": 2.0, "healthy": False}
    insight = next(i for i in generate_insights(sc) if i["parameter"] == "T1")
    assert insight["severity"] == "fail"


def test_t1_warn_near_random():
    sc = _base_scorecard()
    sc["technical"]["T1_action_entropy"] = {"value": 1.95, "max_possible": 2.0, "healthy": False}
    insight = next(i for i in generate_insights(sc) if i["parameter"] == "T1")
    assert insight["severity"] == "warn"


# ── T2 ──────────────────────────────────────────────────────────────────────

def test_t2_fail_overfitting():
    sc = _base_scorecard()
    sc["technical"]["T2_train_test_sharpe_gap"] = {"value": 0.45, "healthy": False}
    insight = next(i for i in generate_insights(sc) if i["parameter"] == "T2")
    assert insight["severity"] == "fail"


# ── T3 ──────────────────────────────────────────────────────────────────────

def test_t3_warn_too_slow():
    sc = _base_scorecard()
    sc["technical"]["T3_reward_convergence_pct"] = {"value": 85.0, "healthy": False}
    insight = next(i for i in generate_insights(sc) if i["parameter"] == "T3")
    assert insight["severity"] == "warn"


def test_t3_warn_too_fast():
    sc = _base_scorecard()
    sc["technical"]["T3_reward_convergence_pct"] = {"value": 10.0, "healthy": False}
    insight = next(i for i in generate_insights(sc) if i["parameter"] == "T3")
    assert insight["severity"] == "warn"


def test_t3_info_insufficient_data():
    sc = _base_scorecard()
    sc["technical"]["T3_reward_convergence_pct"] = {"value": None, "healthy": None, "note": "insufficient_data"}
    insight = next(i for i in generate_insights(sc) if i["parameter"] == "T3")
    assert insight["severity"] == "info"


# ── T4 ──────────────────────────────────────────────────────────────────────

def test_t4_fail_unstable():
    sc = _base_scorecard()
    sc["technical"]["T4_seed_consistency_cv"] = {"value": 0.7, "healthy": False}
    insight = next(i for i in generate_insights(sc) if i["parameter"] == "T4")
    assert insight["severity"] == "fail"


def test_t4_info_insufficient_seeds():
    sc = _base_scorecard()
    sc["technical"]["T4_seed_consistency_cv"] = {"value": None, "healthy": None, "note": "insufficient_seeds"}
    insight = next(i for i in generate_insights(sc) if i["parameter"] == "T4")
    assert insight["severity"] == "info"


# ── T5 ──────────────────────────────────────────────────────────────────────

def test_t5_fail_regime_blind():
    sc = _base_scorecard()
    sc["technical"]["T5_per_regime_action_distribution"] = {"regime_blind": True}
    insight = next(i for i in generate_insights(sc) if i["parameter"] == "T5")
    assert insight["severity"] == "fail"


def test_t5_info_insufficient_data():
    sc = _base_scorecard()
    sc["technical"]["T5_per_regime_action_distribution"] = {"regime_blind": None}
    insight = next(i for i in generate_insights(sc) if i["parameter"] == "T5")
    assert insight["severity"] == "info"
