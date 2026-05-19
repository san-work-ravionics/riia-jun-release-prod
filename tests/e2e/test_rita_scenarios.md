# RITA Dashboard — Functional Scenario Tests

**File:** `tests/e2e/test_rita_scenarios.py`
**Type:** Functional e2e — pure HTTP via `requests`, no browser
**Server:** Real uvicorn started by `conftest.py` (same as smoke tests)

---

## Test Map

| UC | RITA Section | Test | API Endpoint | Expected |
|---|---|---|---|---|
| UC-01 | Overview | `test_overview_health` | `GET /health` | `{status: "ok"}` |
| UC-01 | Overview | `test_overview_readiness` | `GET /readyz` | `{status: "ready"}` |
| UC-01 | Overview | `test_overview_metrics` | `GET /api/v1/metrics/summary` | `{api_requests, pipeline, training}` |
| UC-02 | Financial Goal | `test_financial_goal_performance_summary` | `GET /api/v1/performance-summary` | 200 + KPI payload |
| UC-03 | Market Signals | `test_market_signals` | `GET /api/v1/market-signals` | 200 + list |
| UC-04 | Scenarios | `test_scenarios_load_data` | `GET /api/v1/backtest-daily` | 200 + list |
| UC-04 | Scenarios | `test_scenarios_submit_backtest` | `POST /api/v1/backtest` | 200/201/202 |
| UC-05 | Performance | `test_performance_summary` | `GET /api/v1/performance-summary` | 200 + KPI payload |
| UC-05 | Performance | `test_performance_backtest_daily` | `GET /api/v1/backtest-daily` | 200 + list |
| UC-06 | Trade Journal | `test_trade_journal` | `GET /api/v1/risk-timeline?phase=all` | 200 + list |
| UC-07 | Trade Diagnostics | `test_trade_diagnostics_daily` | `GET /api/v1/backtest-daily` | 200 + list |
| UC-08 | Explainability | `test_explainability_shap` | `GET /api/v1/shap` | 200 + feature list |
| UC-09 | Risk View | `test_risk_timeline` | `GET /api/v1/risk-timeline` | 200 + list |
| UC-10 | Training Progress | `test_training_history` | `GET /api/v1/training-history` | 200 + list |
| UC-10 | Training Progress | `test_training_submit` | `POST /api/v1/workflow/train` | 200/201/202 + run_id |
| UC-11 | Observability | `test_observability_drift` | `GET /api/v1/drift` | `{health, report}` |
| UC-11 | Observability | `test_observability_step_log` | `GET /api/v1/step-log` | 200 + list |
| UC-12 | MCP Calls | `test_mcp_calls` | `GET /api/v1/mcp-calls` | 200 + list (may be empty) |
| UC-13 | Audit | `test_audit_training_history` | `GET /api/v1/training-history` | 200 + list |
| UC-13 | Audit | `test_audit_step_log` | `GET /api/v1/step-log` | 200 + list |

---

## Pre-run Expectations

| UC | Section | Expected Result | Reason |
|---|---|---|---|
| UC-01 | Overview | PASS | `/health`, `/readyz`, `/api/v1/metrics/summary` all implemented |
| UC-02 | Financial Goal | FAIL | `/api/v1/performance-summary` not implemented |
| UC-03 | Market Signals | FAIL | `/api/v1/market-signals` not implemented |
| UC-04 | Scenarios | FAIL | `/api/v1/backtest-daily`, `POST /api/v1/backtest` not implemented |
| UC-05 | Performance | FAIL | `/api/v1/performance-summary`, `/api/v1/backtest-daily` not implemented |
| UC-06 | Trade Journal | FAIL | `/api/v1/risk-timeline` not implemented |
| UC-07 | Trade Diagnostics | FAIL | `/api/v1/backtest-daily` not implemented |
| UC-08 | Explainability | FAIL | `/api/v1/shap` not implemented |
| UC-09 | Risk View | FAIL | `/api/v1/risk-timeline` not implemented |
| UC-10 | Training Progress | PASS (partial) | `/api/v1/training-history` missing; `POST /api/v1/workflow/train` exists |
| UC-11 | Observability | PASS | `/api/v1/drift`, `/api/v1/step-log` both implemented |
| UC-12 | MCP Calls | PASS | `/api/v1/mcp-calls` implemented (returns empty list) |
| UC-13 | Audit | FAIL (partial) | `/api/v1/training-history` missing; `/api/v1/step-log` exists |

**Predicted: ~8 pass, ~12 fail**

---

## Defect Register (pre-run)

| DEF | Endpoint Missing | Affects UC | Priority |
|---|---|---|---|
| DEF-001 | `GET /api/v1/performance-summary` | UC-02, UC-05 | P1 — core feature |
| DEF-002 | `GET /api/v1/backtest-daily` | UC-04, UC-05, UC-07 | P1 — core feature |
| DEF-003 | `GET /api/v1/training-history` | UC-10, UC-13 | P1 — core feature |
| DEF-004 | `GET /api/v1/risk-timeline` | UC-06, UC-09 | P2 |
| DEF-005 | `GET /api/v1/market-signals` | UC-03 | P2 |
| DEF-006 | `POST /api/v1/backtest` | UC-04 | P2 |
| DEF-007 | `GET /api/v1/shap` | UC-08 | P3 — requires model file |
