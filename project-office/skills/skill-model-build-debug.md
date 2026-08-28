# Skill: Model Build Debugger — RITA DQN Training Pipeline

**Use for:** Diagnosing failed, stuck, or silent failures in the RITA Double-DQN training and backtest pipeline
**Knowledge base:** `project-office/ops-deployments/DEPLOYMENT_KNOWLEDGE.md` — read the **Known Model Build Failure Patterns** section before every debug session, write after every new incident
**Guardrail refs:** org · engineer-role · rita-project  
**Last validated against spec:** 2026-05-26  
**Spec source:** `SPEC_Prod_Deploy.md`

---

## Role Identity

The Model Build Debugger knows the full RITA training pipeline end-to-end: how data is loaded, how the Double-DQN trains, where artifacts are written, and how failures manifest silently in a background thread. This skill gives Claude the context to triage a stuck or failed build without the user needing to explain the internals.

**Before any debug action:** Read `DEPLOYMENT_KNOWLEDGE.md` — the Known Model Build Failure Patterns section. Check if the symptom matches a known pattern first.

**After any new incident:** Write a new entry to `DEPLOYMENT_KNOWLEDGE.md` under that section — symptom, root cause, fix, prevention rule.

---

## Trigger Conditions

Use this skill when the user reports:
- Training run stuck in `pending` or `running` status
- Pipeline button appears to do nothing (no spinner, no status update)
- Pipeline triggered but no `.zip` model file appears
- Training appears to complete but metrics are zero or suspicious
- Container exits or OOM-kills during a training run
- Backtest never starts after pipeline triggers
- Wrong instrument trained (active instrument misconfigured)
- `training_history.csv` not updated after a run
- `401 Unauthorized` on `POST /api/v1/pipeline` in browser console
- `PermissionError` or `pipeline.failed` immediately after 202 Accepted
- Any `ml_dispatch.*`, `pipeline.*`, or `training_tracker.*` log errors

---

## Pipeline Architecture — Know This Before Debugging

```
POST /api/v1/pipeline
  └─ _run_pipeline_job() [daemon thread]
       ├─ Step 1: find_instrument_csv() → load_ohlcv_csv()
       ├─ Step 2: calculate_indicators()
       ├─ Step 3: train_agent() or train_best_of_n()  →  saves {model_version}_{run_id[:8]}.zip
       ├─ Step 4: run_episode(model, val_df)           →  Sharpe, MDD, return
       ├─ Step 4b: run_episode(model, train_df)        →  train-phase metrics
       └─ Step 5: TrainingTracker.record_round()       →  training_history.csv
                  WorkflowService._run_training_job()  →  DB training_runs row
```

**Critical:** The entire pipeline runs in a **daemon thread**. Exceptions are caught at the top level (`pipeline.failed` log event) but swallowed — the API returns 202 immediately. A silent crash leaves the DB run in `running` state indefinitely.

---

## Key Artifact Paths (inside container)

| Artifact | Container path | EC2 host path |
|---|---|---|
| Model ZIPs | `/app/rita_output/models/{INSTRUMENT}/` | `/opt/rita_output/models/{INSTRUMENT}/` |
| Training history CSV | `/app/rita_output/models/{INSTRUMENT}/training_history.csv` | `/opt/rita_output/models/{INSTRUMENT}/training_history.csv` |
| Backtest output | `/app/rita_output/data/{INSTRUMENT}/` | `/opt/rita_output/data/{INSTRUMENT}/` |
| Input OHLCV CSVs | `/app/data/raw/{INSTRUMENT}/` | `/opt/rita_input/raw/{INSTRUMENT}/` (read-only) |
| Input processed CSVs | `/app/data/input/{INSTRUMENT}/` | `/opt/rita_input/input/{INSTRUMENT}/` (read-only) |

---

## Key Log Event Names (grep these in `docker logs rita`)

| Event name | Meaning |
|---|---|
| `ml_dispatch.load_data` | Step 1 started |
| `ml_dispatch.data_loaded` | CSV loaded; shows row count |
| `ml_dispatch.indicators_computed` | Step 2 done |
| `ml_dispatch.training_start` | Step 3 started; shows timesteps + n_seeds |
| `ml_dispatch.training_complete` | Model ZIP saved |
| `ml_dispatch.validation_complete` | Step 4 done; shows Sharpe + MDD |
| `ml_dispatch.train_episode_complete` | Step 4b done |
| `pipeline.submitted` | Thread launched (API side) |
| `pipeline.reuse_model` | Skipped training; reused existing ZIP |
| `pipeline.failed` | Top-level thread crash — look for `exc_info` on the next line |
| `training_tracker.round_recorded` | Step 5 done; training_history.csv updated |
| `instrument.selected` | Active instrument changed |
| `instrument_defaults.not_found` | No per-instrument YAML config found |

---

## Pre-Debug Checklist — Run These First

Before diving into container logs, rule out the two most common silent failures:

**1. Cloudflare serving stale JS (BUILD-PATTERN-009)**
```bash
curl -sI https://riia.ravionics.nl/dashboard/js/shared/api.js | grep -i cf-cache-status
```
If result is `CF-Cache-Status: HIT` → users are getting old JS. Fix: Cloudflare Dashboard → Caching → Purge Everything. Then ask user to hard-refresh (`Cmd+Shift+R`).

**2. User JWT expired (60-min TTL)**
Check the nginx access log for real browser traffic:
```bash
ssh -i riia-jun-release/terraform/generated-key.pem -o StrictHostKeyChecking=no ubuntu@<EC2_IP> \
  "tail -50 /var/log/nginx/access.log | grep -v '127.0.0.1'"
```
If only `GET /health` requests appear from `172.69.x.x` (Cloudflare IPs) — no POSTs, no instrument calls — the user's token is likely expired or JS is stale. Distinguish using the Cloudflare cache check above.

**3. Production config paths correct**
```bash
ssh -i riia-jun-release/terraform/generated-key.pem -o StrictHostKeyChecking=no ubuntu@<EC2_IP> \
  "docker exec rita python3 -c \"from rita.config import settings; print('model:', settings.model.path)\""
```
Expected: `/app/rita_output/models`. If it shows `models` (relative) → BUILD-PATTERN-010 — `production.yaml` missing absolute path override.

---

## EC2 Diagnostic Commands

```bash
# SSH in
ssh -i riia-jun-release/terraform/generated-key.pem -o StrictHostKeyChecking=no ubuntu@<EC2_IP>

# Tail last 200 lines of container log, filtered to pipeline events
docker logs rita --tail 200 2>&1 | grep -E "ml_dispatch|pipeline|training_tracker|instrument"

# Real browser traffic (nginx access log — exclude local curl from 127.0.0.1)
tail -100 /var/log/nginx/access.log | grep -v '127.0.0.1'

# Check model ZIPs for an instrument
ls -lh /opt/rita_output/models/NIFTY/

# Read last row of training history CSV
tail -2 /opt/rita_output/models/NIFTY/training_history.csv

# Check active instrument in DB (sqlite3)
sqlite3 /opt/rita_output/rita.db "SELECT value FROM config_overrides WHERE key='active_instrument_id';"

# Check training run status in DB
sqlite3 /opt/rita_output/rita.db "SELECT run_id, status, started_at, ended_at FROM training_runs ORDER BY recorded_at DESC LIMIT 5;"

# Check container memory usage (OOM indicator)
docker stats rita --no-stream

# Check EC2 system memory
free -h

# Generate a fresh JWT for testing (use actual user email from users table)
docker exec rita python3 -c "from rita.auth import create_access_token; print(create_access_token('user@email.com'))"

# Test pipeline endpoint with valid JWT
curl -s -X POST http://localhost/api/v1/pipeline \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <TOKEN>" \
  -d '{"instrument":"NIFTY","force_retrain":true,"n_seeds":1,"timesteps":100000}'

# Check who is in the users table
sqlite3 /opt/rita_output/rita.db "SELECT id, last_login_date FROM users ORDER BY last_login_date DESC LIMIT 5;"
```

---

## Definition of Done for Any Debug Session

- [ ] Known Model Build Failure Patterns section of `DEPLOYMENT_KNOWLEDGE.md` checked first
- [ ] Root cause identified (not just "it failed")
- [ ] Fix applied and pipeline re-triggered (or escalation path identified)
- [ ] If new failure pattern: appended to `DEPLOYMENT_KNOWLEDGE.md` with symptom + root cause + fix + prevention
- [ ] If existing pattern recurred: `Recurrences` counter incremented in `DEPLOYMENT_KNOWLEDGE.md`
