# FnO Dashboard — Functional Scenario Tests

**File:** `tests/e2e/test_fno_scenarios.py`
**Type:** Functional e2e — pure HTTP, no browser

---

## Test Map

| UC | FnO Section | Test | API Endpoint | Expected |
|---|---|---|---|---|
| UC-F01 | Dashboard | `test_fno_dashboard_health` | `GET /health` | `{status: "ok"}` |
| UC-F01 | Dashboard | `test_fno_dashboard_portfolio_summary` | `GET /api/v1/portfolio/summary` | 200 + KPI payload |
| UC-F02 | Positions | `test_fno_positions` | `GET /api/experience/fno/` | 200 + positions/snapshots |
| UC-F03 | Margin Tracker | `test_fno_margin` | `GET /api/experience/fno/` | 200 |
| UC-F04 | Risk & Greeks | `test_fno_greeks` | `GET /api/experience/fno/` | 200 + snapshots |
| UC-F05 | Risk-Reward | `test_fno_risk_reward_price_history` | `GET /api/v1/portfolio/price-history` | 200 + list |
| UC-F06 | Hedge Radar | `test_fno_hedge_history` | `GET /api/v1/portfolio/hedge-history` | 200 + list |
| UC-F07 | Hedge History | `test_fno_hedge_history_list` | `GET /api/v1/portfolio/hedge-history` | 200 + list |
| UC-F08 | Manoeuvre | `test_fno_manoeuvre_groups` | `GET /api/v1/portfolio/man-groups` | 200 + list |
| UC-F08 | Manoeuvre | `test_fno_manoeuvre_snapshot` | `POST /api/v1/portfolio/man-snapshot` | 200/201/422 |
| UC-F08 | Manoeuvre | `test_fno_manoeuvre_pnl_history` | `GET /api/v1/portfolio/man-pnl-history` | 200 + list |

---

## Pre-run Expectations

| UC | Section | Expected | Reason |
|---|---|---|---|
| UC-F01 | Dashboard | PASS (health) / FAIL (summary) | `/api/v1/portfolio/summary` not implemented |
| UC-F02 | Positions | PASS | `/api/experience/fno/` exists |
| UC-F03 | Margin Tracker | PASS | via `/api/experience/fno/` |
| UC-F04 | Risk & Greeks | PASS | via `/api/experience/fno/` |
| UC-F05 | Risk-Reward | FAIL | `/api/v1/portfolio/price-history` not implemented |
| UC-F06 | Hedge Radar | FAIL | `/api/v1/portfolio/hedge-history` not implemented |
| UC-F07 | Hedge History | FAIL | `/api/v1/portfolio/hedge-history` not implemented |
| UC-F08 | Manoeuvre | FAIL | `/api/v1/portfolio/man-groups`, `man-snapshot`, `man-pnl-history` not implemented |

**Predicted: ~4 pass, ~7 fail**
