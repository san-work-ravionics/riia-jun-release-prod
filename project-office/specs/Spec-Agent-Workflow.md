---
  Agent Workflow � Command Showcase & Gap Analysis

  1. Initiation � Financial Goal Agent

  Showcase commands (chat on Market Analysis page):
  "What returns can I expect in 1 year from Nifty?"
  "How much will Nifty give in 5 years?"
  "What is the median 3-month return for Nifty?"
  Mapped to: return_1y/3y/5y intents ? get_period_return_estimates(df, period_days) in data_loader.py ? rolling
  percentile windows over 25-year history
  Also: POST /api/v1/goal on the Rita dashboard (Goal card) sets quantitative target + feasibility check
  Gap: Goal is set but not persisted as a constraint that subsequent agents check against (e.g., Strategy agent doesn't
  know the user's stated 15% return target when deciding allocation)

  ---
  2. Research � Sentiment Analyst

  Showcase commands:
  "What is the current market sentiment?"
  "Is the market bullish or bearish?"
  "Overall market mood Nifty"
  Mapped to: market_sentiment intent ? get_market_summary() + get_sentiment_score() in technical_analyzer.py �
  aggregates RSI/MACD/BB/EMA/ATR into a score from -6 to +6
  Gap: Sentiment is derived entirely from price technicals � no news feed, no NSE FII/DII flow data, no earnings
  calendar. The "Sentiment Analyst" role is partially filled by a proxy.

  ---
  3. Research � Technical Analyst

  Showcase commands:
  "What is the RSI reading today?"
  "How volatile is Nifty right now?"
  "What direction is Nifty trending?"
  "EMA trend direction today"
  Mapped to: rsi_reading, volatility_check, trend_direction intents ? get_market_summary() � RSI-14, ATR-14,
  EMA-5/13/26/50, MACD, Bollinger all computed
  Also: GET /api/v1/market-signals + 7 charts on Market Signals section
  Status: Best-covered agent in the system. ?

  ---
  4. Design � Strategy Analyst

  Showcase commands:
  "Can I invest in Nifty now?"
  "What allocation should I have in Nifty?"
  "Safe investment approach for Nifty"
  "I can tolerate high risk in Nifty"
  Mapped to: invest_now, allocation_level, conservative_strategy, aggressive_strategy ? get_allocation_recommendation()
  in strategy_engine.py � outputs recommendation + allocation % + rationale
  Gap: All four strategies map to the same signal-based allocator � there is no separate Value Investing path (P/E,
  fundamentals) vs Momentum path vs Long-Term horizon path. The hint: conservative/aggressive param shifts the threshold
   but doesn't change the strategy type.

  ---
  5. Evaluation � Scenario Analyst

  Showcase commands:
  "What if Nifty falls 10 percent?"
  "What if Nifty crashes 20 percent?"
  "What if Nifty rallies 10 percent?"
  "Sideways market scenario Nifty"
  Mapped to: stress_crash_10/20, stress_rally_10, stress_flat ? simulate_stress_scenarios() in performance.py � compares
   RITA vs Conservative/Moderate/Aggressive profiles, flags MDD breach
  Also: Scenario Backtest section in Rita dashboard (POST /api/v1/backtest)
  Gap: Scenario analyst triggers derivatives trade when MDD > 10% � chat flags the breach (breach_note: YES) but there
  is no downstream action that creates an FnO hedge order. The bridge from Evaluation ? Execution is missing.

  ---
  6. Execution � Execution Analyst

  Showcase commands: (no chat intents exist for this agent)
  Mapped to: FnO dashboard � positions, orders, Greeks, margin tracker, hedge history
  Gap: Largest gap. No chat intents for execution. No API endpoint that takes a signal recommendation and
  places/suggests a trade. FnO data is manually imported from CSVs � no automated execution loop from Strategy/Scenario
  output.

  ---
  7. Feedback � Outcome Analyst

  Showcase commands:
  "How has RITA model performed historically?"
  "Compare conservative vs aggressive portfolios"
  "Why did RITA recommend this strategy?"
  "What signals led to this allocation?"
  Mapped to: backtest_performance ? _load_perf_summary() reads performance_summary.csv; portfolio_compare ?
  build_portfolio_comparison(); explain_decision ? full signal breakdown with override reason
  Gap: Feedback is read-only reporting � there is no closed-loop mechanism that feeds trade outcomes back to adjust the
  goal feasibility check or strategy thresholds. The explain_decision intent shows the signal breakdown but doesn't
  auto-tune the confidence threshold or allocation bands.

  ---
  Summary Table

  ??????????????????????????????????????????????????????????????????????????????????????????????????????????????????
  ?    Agent    ?            Chat Intents            ?          Backend Functions           ?        Status        ?
  ??????????????????????????????????????????????????????????????????????????????????????????????????????????????????
  ? Financial   ? return_1m/3m/6m/1y/3y/5y           ? get_period_return_estimates()        ? ? Covered            ?
  ? Goal        ?                                    ?                                      ?                      ?
  ??????????????????????????????????????????????????????????????????????????????????????????????????????????????????
  ? Sentiment   ? market_sentiment, trend_direction  ? get_sentiment_score()                ? ? Proxy only (no     ?
  ? Analyst     ?                                    ?                                      ? news/flow data)      ?
  ??????????????????????????????????????????????????????????????????????????????????????????????????????????????????
  ? Technical   ? rsi_reading, volatility_check,     ? get_market_summary()                 ? ? Well covered       ?
  ? Analyst     ? trend_direction                    ?                                      ?                      ?
  ??????????????????????????????????????????????????????????????????????????????????????????????????????????????????
  ? Strategy    ? invest_now, allocation_level,      ?                                      ? ? Single allocator,  ?
  ? Analyst     ? conservative/aggressive            ? get_allocation_recommendation()      ? no strategy type     ?
  ?             ?                                    ?                                      ? split                ?
  ??????????????????????????????????????????????????????????????????????????????????????????????????????????????????
  ? Scenario    ? stress_crash_10/20,                ? simulate_stress_scenarios()          ? ? Covered            ?
  ? Analyst     ? stress_rally_10, stress_flat       ?                                      ?                      ?
  ??????????????????????????????????????????????????????????????????????????????????????????????????????????????????
  ? Execution   ? none                               ? FnO CSVs only                        ? ? Gap � no chat, no  ?
  ? Analyst     ?                                    ?                                      ? automation           ?
  ??????????????????????????????????????????????????????????????????????????????????????????????????????????????????
  ? Outcome     ? backtest_performance,              ? _load_perf_summary(),                ? ? Read-only, no      ?
  ? Analyst     ? portfolio_compare,                 ? build_portfolio_comparison()         ? closed loop          ?
  ?             ? explain_decision                   ?                                      ?                      ?
  ??????????????????????????????????????????????????????????????????????????????????????????????????????????????????

  Key structural gap: The Scenario ? Execution bridge. When breach_note = YES (MDD > 10%), the system flags it in chat
  but has no path to suggest or record a hedging trade.

  ---
  Agent Performance Feedback Loop

  Each pipeline run produces a run JSON written to riia-ai-org/agent-ops/runs/. After the run, aggregate_metrics.py
  reads all run files and writes metrics.json with 7 metric sections: task_completion, quality, token_forecasting,
  efficiency, reliability, hitl, and agentic.

  The feedback loop operates as follows:

  1. Run completes — agents write their outputs to run JSON including grounding_checks, failure_modes, hitl_events,
     and (optionally) human_score from the TechWriter score prompt.
  2. FC code logged — if an agent fires a failure code (e.g., FC-PARTIAL-IMPL, FC-SPEC-DRIFT), it is recorded in
     agents[].failure_modes[] in the run JSON.
  3. aggregate_metrics.py flags breach — on next run of the script, threshold alerts fire to stdout:
     - Any FC code total > 3: "[ALERT] FC-{code} has fired {N} times — review skill file rule"
     - Any role first_pass_rate < 0.70: "[ALERT] {role} first-pass rate {N}% — grounding checks need review"
     - CSAT < 3.5 (non-null): "[ALERT] CSAT {N}/5 below threshold — review last 3 runs"
     - Token forecast error > 35%: "[ALERT] Token forecast off by {N}% on average — recalibrate multipliers"
  4. Skill file rule updated — engineer reviews the alert, identifies the root cause, and adds or tightens a
     guardrail rule in the relevant skill file (e.g., skill-add-ops-feature.md). The update is recorded in
     skill_version_history[] in metrics.json with fields: improvement_applied, before_first_pass_rate,
     after_first_pass_rate.
  5. Next run improves — the updated skill file is loaded by the next agent session, which now follows the
     tightened rule. first_pass_rate and CSAT trend upward in subsequent runs.
  6. Forecast multiplier calibrated — token_forecasting.avg_forecast_error_pct is monitored across runs. If
     consistently above 35%, the per-role historical averages (PM 7612, Arch 9975, Eng 31112, QA 11300, TW 6650)
     used by the token-forecast endpoint are recalibrated to reflect actual observed costs.

  The Ops dashboard Agent Builds page (ops.html sec-agent-builds) surfaces this loop in four panels:
  Panel A (KPI cards: TSR, CSAT, forecast error, HITL rate), Panel B (forecast vs actual bar chart),
  Panel C (metric trend lines: TSR, grounding, CSAT, context adherence), and Panel D (run table with FC badge
  column). The pre-run token estimate widget (Estimate Token Budget) calls GET /api/experience/ops/token-forecast
  to project token cost before a run begins, using historical run data segmented by feature_type and complexity.

  ---
  Feature 32 — Investment-Workflow Agent Performance Instrumentation (Phases 1+2)

  NOTE: This is DISTINCT from the Ops "Agent Builds" feedback loop above. That loop measures the /enhance
  DEV pipeline (PM/Architect/Engineer/QA agents) via the agent_builds tables. Feature 32 measures the 7
  TRADING-DECISION agents listed in this document (the chat/investment-workflow agents) via a new
  agent_performance table — a different concern with a different data source.

  Instrumentation (Phase 1): the chat classifier (core/classifier.py) records one agent_performance row per
  resolved investment-workflow agent intent. After classify() + dispatch() build the chat response, the chat
  route (api/v1/workflow/chat.py) calls classifier.record_agent_performance(result) — a fire-and-forget hook:
    - Wrapped in a broad try/except that swallows everything and logs at debug via structlog (never raises).
    - Only fires when the resolved intent maps to one of the 7 agents (INTENT_TO_AGENT.get → None → skip silently).
    - The DB write runs off the request's critical path on a daemon background thread that opens its OWN
      SessionLocal() and closes it in finally (the request's Session is never shared across threads), so no
      latency is added to the chat response and the response content is never mutated.
    - Only fires for non-low-confidence results.

  Canonical intent → agent_name mapping (module constant INTENT_TO_AGENT in core/classifier.py). The 7
  agent_name values (CANONICAL_AGENTS) are reused verbatim by the Phase 2 endpoint so the dashboard always
  shows all 7 agents even with zero rows:
    - Financial Goal    ← return_1m, return_3m, return_6m, return_1y, return_3y, return_5y
    - Sentiment Analyst ← market_sentiment
    - Technical Analyst ← trend_direction, rsi_reading, volatility_check
    - Strategy Analyst  ← allocation_level, conservative_strategy, aggressive_strategy, portfolio_compare
    - Scenario Analyst  ← stress_crash_10, stress_crash_20, stress_rally_10, stress_flat
    - Execution Analyst ← invest_now, explain_decision
    - Outcome Analyst   ← backtest_performance, backtest_1y_return

  Dashboard (Phase 2): GET /api/v1/experience/rita/agent-performance (Experience tier, read-only) returns a
  per-agent KPI summary (invocation_count_30d, gap_status, outcome_match_rate, trend_vs_prior_30d) for all 7
  agents, rendered in the rita.html sec-agent-performance section by dashboard/js/rita/agent-performance.js.
  outcome_status is always NULL in Phases 1+2 (backfillable later, Phase 3+), so outcome_match_rate is None and
  the UI renders an em-dash rather than a misleading 0%.