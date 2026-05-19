# Ops Dashboard — Functional Scenario Tests

**File:** `tests/e2e/test_ops_scenarios.py`
**Type:** Functional e2e — pure HTTP, no browser

---

## Test Map

| UC | Ops Section | Test | API Endpoint | Expected |
|---|---|---|---|---|
| UC-O01 | Overview | `test_ops_overview_health` | `GET /health` | `{status: "ok"}` |
| UC-O01 | Overview | `test_ops_overview_metrics` | `GET /metrics` | 200 + Prometheus text |
| UC-O01 | Overview | `test_ops_overview_step_log` | `GET /api/v1/step-log` | 200 + list |
| UC-O01 | Overview | `test_ops_overview_mcp_calls` | `GET /api/v1/mcp-calls` | 200 + list |
| UC-O01 | Overview | `test_ops_overview_data_prep_status` | `GET /api/v1/data-prep/status` | 200 |
| UC-O01 | Overview | `test_ops_overview_progress` | `GET /progress` | 200 |
| UC-O02 | Monitoring | `test_ops_monitoring_metrics_summary` | `GET /api/v1/metrics/summary` | 200 + structured JSON |
| UC-O02 | Monitoring | `test_ops_monitoring_step_log` | `GET /api/v1/step-log` | 200 + list |
| UC-O03 | CI/CD | `test_ops_cicd_step_log` | `GET /api/v1/step-log` | 200 + list |
| UC-O04 | Deploy | `test_ops_deploy_health` | `GET /health` | `{status: "ok"}` |
| UC-O04 | Deploy | `test_ops_deploy_training_history` | `GET /api/v1/training-history` | 200 + list |
| UC-O05 | Observability | `test_ops_observability_drift` | `GET /api/v1/drift` | 200 + `{health, report}` |
| UC-O05 | Observability | `test_ops_observability_mcp_calls` | `GET /api/v1/mcp-calls` | 200 + list |
| UC-O06 | Chat / Monitor | `test_ops_chat_monitor` | `GET /api/v1/chat/monitor` | 200 |
| UC-O07 | Daily Ops | `test_ops_daily_status` | `GET /api/v1/portfolio/man-daily-status` | 200 |
| UC-O07 | Daily Ops | `test_ops_daily_snapshot` | `POST /api/v1/portfolio/man-daily-snapshot` | 200/201/422 |

---

## Pre-run Expectations

| UC | Section | Expected | Reason |
|---|---|---|---|
| UC-O01 | Overview | PASS (health/metrics/step-log/mcp) / FAIL (data-prep, progress) | `/data-prep/status` and `/progress` not implemented |
| UC-O02 | Monitoring | PASS | `/api/v1/metrics/summary` and `/step-log` implemented |
| UC-O03 | CI/CD | PASS | `/api/v1/step-log` implemented |
| UC-O04 | Deploy | PASS (health) / FAIL (training-history) | `/api/v1/training-history` not implemented |
| UC-O05 | Observability | PASS | `/api/v1/drift` and `/mcp-calls` implemented |
| UC-O06 | Chat | FAIL | `/api/v1/chat/monitor` not implemented |
| UC-O07 | Daily Ops | FAIL | `/api/v1/portfolio/man-daily-status` not implemented |

**Predicted: ~10 pass, ~6 fail**
