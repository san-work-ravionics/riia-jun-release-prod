"""RITA Core — RL Diagnostic Insights Engine (Feature 32, Phase 3.6)

Rule-based threshold -> improvement-action mapping for each of the 10
scorecard parameters computed by ``rl_scorecard.compute_scorecard()``.
Improvement-action text is taken directly from REQUIREMENTS.md Phase 3.6
("Improvement signal when bad" column) so the dashboard surfaces the same
guidance an engineer reading the spec would get.

``generate_insights()`` always returns one entry per parameter (10 total) —
covers both "this needs attention" (fail/warn) and "this is healthy" (pass)
so the dashboard can render a complete pass/warn/fail grid, not just problems.
Sorted worst-first: fail -> warn -> info (insufficient data) -> pass.
"""
from __future__ import annotations

from typing import Any

_SEVERITY_RANK = {"fail": 0, "warn": 1, "info": 2, "pass": 3}


def _insight(parameter: str, label: str, severity: str, message: str) -> dict[str, Any]:
    return {"parameter": parameter, "label": label, "severity": severity, "message": message}


def _insight_f1(functional: dict) -> dict[str, Any]:
    v = functional["F1_sharpe_test"]["value"]
    if v is None:
        return _insight("F1", "Sharpe Ratio (Test)", "info", "Insufficient data to compute test Sharpe.")
    if v < 1.0:
        return _insight("F1", "Sharpe Ratio (Test)", "fail",
                         f"Sharpe {v} below 1.0 -> reward misalignment, insufficient signal, or wrong features.")
    return _insight("F1", "Sharpe Ratio (Test)", "pass", f"Sharpe {v} meets the > 1.0 target.")


def _insight_f2(functional: dict) -> dict[str, Any]:
    v = functional["F2_max_drawdown_test"]["value"]
    if v is None:
        return _insight("F2", "Max Drawdown (Test)", "info", "Insufficient data to compute test MDD.")
    if v <= -0.10:
        return _insight("F2", "Max Drawdown (Test)", "fail",
                         f"MDD {v*100:.1f}% worse than -10% -> MDD penalty too weak or hedge action not being used.")
    return _insight("F2", "Max Drawdown (Test)", "pass", f"MDD {v*100:.1f}% within the -10% limit.")


def _insight_f3(functional: dict) -> dict[str, Any]:
    per_regime = functional["F3_market_regime_performance"]
    bear = per_regime.get("bear", {})
    bull = per_regime.get("bull", {})
    if bear.get("sharpe") is None and bull.get("sharpe") is None:
        return _insight("F3", "Market Regime Performance", "info",
                         "Insufficient per-regime data (bull/bear) to assess regime performance.")
    if bear.get("sharpe") is not None and bear["sharpe"] < 0:
        return _insight("F3", "Market Regime Performance", "warn",
                         "Poor Sharpe in bear regime -> not using hedge action when it matters; "
                         "a model that scores well overall but fails in bear is dangerous.")
    if bull.get("sharpe") is not None and bear.get("sharpe") is not None and bear["sharpe"] > bull["sharpe"]:
        return _insight("F3", "Market Regime Performance", "warn",
                         "Good in bear, weaker in bull -> possible over-hedging outside downturns.")
    return _insight("F3", "Market Regime Performance", "pass",
                     "Per-regime Sharpe does not indicate regime-blindness.")


def _insight_f4(functional: dict) -> dict[str, Any]:
    v = functional["F4_win_rate"]["value"]
    if v is None:
        return _insight("F4", "Win Rate", "info", "Insufficient data to compute win rate.")
    if v < 0.45:
        return _insight("F4", "Win Rate", "fail",
                         f"Win rate {v*100:.1f}% below 45% -> not learning directional signal.")
    return _insight("F4", "Win Rate", "pass", f"Win rate {v*100:.1f}% at or above the 45% floor.")


def _insight_f5(functional: dict) -> dict[str, Any]:
    v = functional["F5_baseline_relative"]["overall"]
    if v is None:
        return _insight("F5", "Baseline Relative Performance", "info", "Insufficient data vs static baseline.")
    if v < 0.0:
        return _insight("F5", "Baseline Relative Performance", "fail",
                         f"Relative performance {v:.2f} negative -> RL worse than static rule overall. "
                         "Check the per-regime breakdown for WHERE it loses value.")
    return _insight("F5", "Baseline Relative Performance", "pass",
                     f"RL beats the static baseline overall (relative {v:.2f}).")


def _insight_t1(technical: dict) -> dict[str, Any]:
    v = technical["T1_action_entropy"]["value"]
    if v is None:
        return _insight("T1", "Action Entropy", "info", "Insufficient data to compute action entropy.")
    if v < 0.5:
        return _insight("T1", "Action Entropy", "fail",
                         f"Entropy {v} below 0.5 -> policy collapsed to one action. Tune epsilon/entropy bonus.")
    if v > 1.8:
        return _insight("T1", "Action Entropy", "warn",
                         f"Entropy {v} above 1.8 -> near-random, not converged. Tune epsilon/entropy bonus.")
    return _insight("T1", "Action Entropy", "pass", f"Entropy {v} in the healthy 0.5-1.8 band.")


def _insight_t2(technical: dict) -> dict[str, Any]:
    v = technical["T2_train_test_sharpe_gap"]["value"]
    if v is None:
        return _insight("T2", "Train-Test Sharpe Gap", "info", "Insufficient data to compute the gap.")
    if v > 0.3:
        return _insight("T2", "Train-Test Sharpe Gap", "fail",
                         f"Gap {v} above 0.3 -> overfitting. Reduce capacity, add regularization, more data.")
    return _insight("T2", "Train-Test Sharpe Gap", "pass", f"Gap {v} within the <= 0.3 band.")


def _insight_t3(technical: dict) -> dict[str, Any]:
    v = technical["T3_reward_convergence_pct"]["value"]
    if v is None:
        return _insight("T3", "Reward Convergence Rate", "info", "Insufficient episode data to assess convergence.")
    if v > 80.0:
        return _insight("T3", "Reward Convergence Rate", "warn",
                         f"Convergence at {v}% of episodes -> needs more training steps or lower LR.")
    if v < 20.0:
        return _insight("T3", "Reward Convergence Rate", "warn",
                         f"Convergence at {v}% of episodes -> converging too fast, may be stuck in a local optimum.")
    return _insight("T3", "Reward Convergence Rate", "pass", f"Converged at {v}% of episodes -- healthy range.")


def _insight_t4(technical: dict) -> dict[str, Any]:
    v = technical["T4_seed_consistency_cv"]["value"]
    if v is None:
        return _insight("T4", "Seed Consistency (Sharpe CV)", "info",
                         "Insufficient seeds to compute consistency (need >= 2).")
    if v > 0.5:
        return _insight("T4", "Seed Consistency (Sharpe CV)", "fail",
                         f"CV {v} above 0.5 -> unstable across seeds. Increase seeds, lower LR, simplify network.")
    return _insight("T4", "Seed Consistency (Sharpe CV)", "pass", f"CV {v} at or below the 0.5 threshold.")


def _insight_t5(technical: dict) -> dict[str, Any]:
    blind = technical["T5_per_regime_action_distribution"]["regime_blind"]
    if blind is None:
        return _insight("T5", "Per-Regime Action Distribution", "info",
                         "Insufficient per-regime data to assess regime-blindness.")
    if blind:
        return _insight("T5", "Per-Regime Action Distribution", "fail",
                         "Action distribution is nearly identical across regimes (JSD < 0.05) -> regime-blind; "
                         "needs regime features or longer training.")
    return _insight("T5", "Per-Regime Action Distribution", "pass",
                     "Action distribution meaningfully differs across regimes.")


_RULES = (
    _insight_f1, _insight_f2, _insight_f3, _insight_f4, _insight_f5,
    _insight_t1, _insight_t2, _insight_t3, _insight_t4, _insight_t5,
)


def generate_insights(scorecard: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate one insight per scorecard parameter (10 total), sorted worst-first.

    Args:
        scorecard: the dict returned by ``rl_scorecard.compute_scorecard()``
            (must contain ``functional`` and ``technical`` sections).

    Returns:
        List of ``{"parameter", "label", "severity", "message"}`` dicts, one
        per parameter (F1-F5, T1-T5), ordered fail -> warn -> info -> pass.
    """
    functional = scorecard.get("functional", {})
    technical = scorecard.get("technical", {})

    insights: list[dict[str, Any]] = []
    for rule in _RULES:
        try:
            section = functional if rule.__name__.startswith("_insight_f") else technical
            insights.append(rule(section))
        except (KeyError, TypeError) as exc:
            param = rule.__name__.replace("_insight_", "").upper()
            insights.append(_insight(param, param, "info", f"Could not evaluate: {exc}"))

    insights.sort(key=lambda i: _SEVERITY_RANK.get(i["severity"], 99))
    return insights
