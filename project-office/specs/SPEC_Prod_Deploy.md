# SPEC — Production Deployment

**Last updated:** 2026-07-06 (three-repo rationalization — agentic-firm + aug-release + jun-release as siblings)
**Status:** Live on AWS EC2

---

## Three Repos — Local Layout

```
riia-jun-demo/                           ← parent working directory (not a repo)
├── riia-agentic-firm/                   ← Repo 1: project management (private, not pushed)
│   ├── project-office/
│   ├── .claude/
│   └── git-key.txt                      ← PAT for prod pushes
├── riia-aug-release/                    ← Repo 2: Aug release code (own .git)
└── riia-jun-release/                    ← Repo 3: Jun release code (own .git → riia-jun-release-prod)
```

| | Code repo (aug) | Prod repo |
|---|---|---|
| **Purpose** | Development, code versioning | What gets deployed to EC2 |
| **Root path (local Mac)** | `/Users/sgawde/work/riia-jun-demo/riia-aug-release/` | Same repo, pushed to prod remote |
| **GitHub remote (origin)** | `https://github.com/san-work-ravionics/riia-aug-release-prod.git` | — |
| **GitHub remote (prod)** | `https://github.com/san-work-ravionics/riia-jun-release-prod.git` | Deploy pipeline runs here |
| **Push account** | `san-work-ravionics` (PAT in `../riia-agentic-firm/git-key.txt`) | Same PAT, inline credential helper |
| **GitHub Actions** | None (dev backup only) | `deploy.yaml` — builds Docker image, deploys to EC2 |

**Rule:** Any code fix that needs to go live must be pushed to the **prod repo** (`riia-jun-release-prod`). The `/aws-production-deploy` skill handles this — it pushes from `riia-aug-release/` (which has its own `.git`) to the prod remote using the PAT credential helper.

**Own `.git`:** `riia-aug-release/` is a standalone git repo. Deploy is a direct `git push prod HEAD:master` — no subtree or temporary git needed.

---

## How Deployment Works

1. `/aws-production-deploy` pushes from `riia-aug-release/` repo to `riia-jun-release-prod` → `master` branch
2. GitHub Actions picks up `.github/workflows/deploy.yaml`
3. `test` job: lint + unit tests + integration tests + e2e (advisory)
4. `build-and-push` job: builds Docker image → pushes to GHCR
5. `deploy` job: rsyncs `data/raw/` + `data/input/` to `/opt/rita_input/` on EC2 → pulls new image → restarts container
6. Health check polls `http://<EC2_IP>/health` from the **GitHub Actions runner** (not SSH) for up to 3 minutes

**Deploy pipeline structure (updated 2026-05-26):** The deploy job runs four short SSH calls:
1. **Free EC2 disk** — `docker stop rita` + `docker rm rita` + `docker image prune -af` + `df -h`. Running BEFORE the pull so the old image becomes unused and can be freed. Prevents "no space left on device" on `libtorch_cpu.so` extraction.
2. **Pull image** — `docker login ghcr.io` + `docker pull` (network I/O only, now against clean disk)
3. **Swap container** — `docker run -d` (stop/rm already done in step 1)
4. **Health check** — polled from the runner via HTTP, no SSH

**Instrument CSV auto-sync (added 2026-05-20):** The `deploy` job now checks out the repo and rsyncs instrument CSVs to EC2 before container restart. To add a new instrument's data to EC2: commit the CSV files to `data/raw/{TICKER}/` and `data/input/{TICKER}/` in the prod repo — the next push deploys them automatically. No manual SCP needed.

---

## Making a Fix — Step by Step

```bash
# 1. Edit files inside riia-aug-release/
#    (this is its own git repo — commit directly)

# 2. Deploy to prod using the skill
#    Run /aws-production-deploy from riia-agentic-firm/ — it handles staging, committing, and pushing to prod

# 3. Or manually push to prod:
cd /Users/sgawde/work/riia-jun-demo/riia-aug-release
export GIT_KEY=$(tr -d ' \r\n' < ../riia-agentic-firm/git-key.txt)
git -c credential.helper= \
  -c credential.helper='!f() { echo username=x-access-token; echo "password=$GIT_KEY"; }; f' \
  push prod HEAD:master

# 4. Watch the deploy
#    https://github.com/san-work-ravionics/riia-jun-release-prod/actions
```

---

## GitHub Secrets (prod repo)

| Secret | Used for |
|---|---|
| `SSH_PRIVATE_KEY` | SSH into EC2 to run docker commands |
| `AWS_EC2_IP` | EC2 instance IP address |
| `RITA_JWT_SECRET` | App JWT signing key |
| `GOOGLE_CLIENT_ID` | OAuth login |
| `GOOGLE_CLIENT_SECRET` | OAuth login |
| `RITA_BASE_URL` | OAuth callback URL — must be `http://<EC2_IP>` (no trailing slash, no https) |
| `GHCR_PAT` | GitHub PAT for `san-work-ravionics` with `read:packages` scope — lets EC2 pull private GHCR images |

---

## EC2 Data Layout

```
/opt/rita_input/          ← bind-mounted as /app/data (read-only)
├── agent-ops/
├── input/
│   ├── DAILY-DATA/       ← nifty_manual.csv, banknifty_manual.csv, orders/positions CSVs
│   ├── ASML/ NVIDIA/ RELIANCE/ SBIN/ ASRNL/ ATO/ AEX/ DJI/ IXIC/
│   └── ...               ← synced from prod repo data/input/ on each deploy
├── output/
└── raw/
    ├── NIFTY/ BANKNIFTY/ ASML/ NVIDIA/   ← original 4 (manually uploaded)
    ├── RELIANCE/ SBIN/ ASRNL/ ATO/ AEX/ DJI/ IXIC/  ← synced from prod repo on deploy
    └── ...               ← new instruments added by committing CSV + pushing

/opt/rita_output/         ← bind-mounted as /app/rita_output (read-write)
```

---

## Observability (added 2026-05-23)

### Container logs — CloudWatch
Docker uses the `awslogs` driver. Logs stream to **CloudWatch → Log groups → `/rita/app` → stream `rita-container`**.
No SSH needed. The EC2 instance has an IAM role (`rita-ec2-role`) with `CloudWatchLogsFullAccess`.

**Never `docker logs` over SSH to debug production** — on a 1 GB instance, SSH + log streaming causes OOM and kills the container.

### Alarms — SNS email to contact@ravionics.nl
| Alarm | Trigger | Action |
|---|---|---|
| `rita-cpu-high` | CPU > 80% for 10 min | Email alert |
| `rita-status-check-failed` | EC2 status check fails | Email alert |

Terraform resources for both alarms and the SNS topic are in `terraform/main.tf`.

### After attaching a new IAM role to EC2
The `awslogs` Docker log driver reads credentials from the EC2 instance metadata service. The IAM role must be attached **before** the first deploy that uses `awslogs`, otherwise `docker run` hangs trying to reach CloudWatch and the SSH session times out with "Broken pipe".

---

## EC2 Instance Setup Checklist (first boot / after rebuild)

Run these once after any new EC2 instance is provisioned — before the first deploy.

```bash
# SSH in with the terraform key
ssh -i terraform/generated-key.pem -o StrictHostKeyChecking=no ubuntu@<EC2_IP>

# 1. Add 2GB swap — t3.micro has 1GB RAM; docker pull OOMs without it
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h   # confirm Swap: 2.0Gi

# 2. Verify authorized_keys matches the terraform-generated key
#    (the GitHub SSH_PRIVATE_KEY secret must match this key)
cat ~/.ssh/authorized_keys
```

**After rebuilding the EC2 instance with Terraform:** the `generated-key.pem` changes.
Update the `SSH_PRIVATE_KEY` GitHub secret to match — see "Rotating the SSH key" below.

**After provisioning:** also attach the `rita-ec2-role` IAM instance profile via
AWS Console → EC2 → Instance → Actions → Security → Modify IAM role, and create
the CloudWatch log group `/rita/app` with 30-day retention before the first deploy.

---

## Rotating the SSH key

If the `SSH_PRIVATE_KEY` GitHub secret and the key on EC2 get out of sync, CI fails with:
```
Connection closed by <IP> port 22
Error: Process completed with exit code 255
```

Fix:
```python
# Run this locally to update the secret via GitHub API
# (requires: pip install PyNaCl)
import base64, json, urllib.request
from nacl import encoding, public

PAT = "<GHCR_PAT>"          # san-work-ravionics PAT with repo scope
REPO = "san-work-ravionics/riia-jun-release-prod"
SECRET_NAME = "SSH_PRIVATE_KEY"
KEY_FILE = "riia-jun-release/terraform/generated-key.pem"

with open(KEY_FILE) as f:
    secret_value = f.read()

headers = {"Authorization": f"token {PAT}", "Accept": "application/vnd.github+json",
           "X-GitHub-Api-Version": "2022-11-28"}
req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/actions/secrets/public-key", headers=headers)
with urllib.request.urlopen(req) as r:
    pk = json.loads(r.read())

encrypted = public.SealedBox(public.PublicKey(base64.b64decode(pk["key"]))).encrypt(secret_value.encode())
payload = json.dumps({"encrypted_value": base64.b64encode(encrypted).decode(), "key_id": pk["key_id"]}).encode()
req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/actions/secrets/{SECRET_NAME}",
    data=payload, headers={**headers, "Content-Type": "application/json"}, method="PUT")
with urllib.request.urlopen(req) as r:
    print(f"HTTP {r.status}")  # 204 = success
```

---

## Docker / EC2 Ops Commands

```bash
# SSH in
ssh -i terraform/generated-key.pem -o StrictHostKeyChecking=no ubuntu@<EC2_IP>

# !! Do NOT run docker logs over SSH on prod — use CloudWatch instead !!
# AWS Console → CloudWatch → Log groups → /rita/app → rita-container

# Check volume mounts
docker inspect rita --format '{{json .HostConfig.Binds}}'

# Restart container manually
docker restart rita

# Check disk — keep > 8 GB free or docker pull will fail
df -h /
sudo du -sh /var/lib/containerd/

# Free disk: remove old images + clean containerd blobs from failed pulls
docker image prune -a -f
# If containerd blobs are large (sudo du -sh /var/lib/containerd/io.containerd.content.v1.content/):
sudo systemctl stop docker
sudo rm -rf /var/lib/containerd/io.containerd.content.v1.content/ingest/
sudo mkdir -p /var/lib/containerd/io.containerd.content.v1.content/ingest/
sudo systemctl start docker
# Then retrigger deploy with an empty commit
```

---

## Common Past Failures

| Symptom | Root cause | Fix |
|---|---|---|
| `bash: line 1: ***: No such file or directory` on deploy | Dockerfile built venv at `/build/venv` — shebang paths invalid in runtime | Use `/app` as builder WORKDIR so shebang = `/app/venv/bin/python` |
| `bash: line 1: ***: No such file or directory` in Deploy step (exit 127) | `KEY='value' bash << 'ENDSSH'` SSH pattern breaks when secret values contain special characters | Use unquoted heredoc: `bash -s << ENDSSH` — GitHub Actions expands `${{ secrets.* }}` locally before sending over SSH |
| Deploy step fails silently; old container keeps running | EC2 has no GHCR credentials — `docker pull` fails because GHCR packages are private | Add `GHCR_PAT` secret; add `echo '${{ secrets.GHCR_PAT }}' \| docker login ghcr.io` before `docker pull` in deploy step |
| OAuth callback fails on EC2 (`Error 400: invalid_request`, `redirect_uri=https://...`) | `RITA_BASE_URL` secret set to `https://` but EC2 has no TLS cert | Set `RITA_BASE_URL` to `http://<EC2_IP>` (no https, no trailing slash); also ensure this exact URL is registered in Google Cloud Console authorized redirect URIs |
| Google OAuth callback returns 500 — `JWTClaimsError: No access_token provided to compare against at_hash claim` | `jose.jwt.decode()` validates the `at_hash` claim in Google's ID token even when `verify_signature=False`; requires an `access_token` we don't pass | Replace `jwt.decode(id_token, "", options=...)` with `jwt.get_unverified_claims(id_token)` — safe since the token came via server-to-server TLS |
| Volume mount → app can't find data files | Volume was `/app/rita_input` but Dockerfile copies to `/app/data` | Volume mount must be `/opt/rita_input:/app/data:ro` |
| No deploy triggered after push | Pushed to wrong remote (e.g. dev repo), not prod repo | Always push code fixes from `riia-aug-release/` to the `prod` remote, not origin |
| `Connection closed by <IP> port 22` (exit 255) on deploy SSH step | `SSH_PRIVATE_KEY` secret is stale — doesn't match the public key in `~/.ssh/authorized_keys` on EC2 (happens after Terraform recreates the instance and generates a new key pair) | Re-run the "Rotating the SSH key" script above; then push an empty commit to retrigger |
| `docker pull` hangs; instance becomes unresponsive; deploy times out | t3.micro has 1GB RAM — no swap means the kernel OOM-kills docker pull mid-download | Add 2GB swap before first deploy (see "EC2 Instance Setup Checklist"); swap persists across reboots via `/etc/fstab` |
| `chat_monitor.csv` write fails in production; chat endpoint returns 500 | `data/output` is inside the read-only `/app/data` bind mount on EC2; `chat_monitor.py` was writing there | `chat.monitor_dir` config key now points to `rita_output/` (read-write mount); wrap `_log_query` in try/except so a write failure doesn't break chat |
| `client_loop: send disconnect: Broken pipe` (exit 255) mid-deploy after `docker pull` completes | Single long-running SSH heredoc is alive when the OOM spike hits during container swap — kernel kills sshd | Split deploy into 3 short SSH calls: (1) pull, (2) `docker run -d`, (3) health poll via HTTP from runner. `-d` returns immediately so SSH closes before memory spike |
| `docker run` hangs silently; deploy times out with "Broken pipe" | `awslogs` log driver initialises synchronously — if no IAM role is attached to the EC2 instance, it blocks indefinitely trying to reach CloudWatch | Attach `rita-ec2-role` IAM instance profile to EC2 **before** the first deploy that uses `awslogs`; see EC2 Instance Setup Checklist |
| `failed to extract layer … libcufft.so.12: no space left on device` | `sentence-transformers` → PyTorch → full NVIDIA CUDA stack installed in image (~7 GB); disk fills after 1–2 failed pull attempts leave blobs in `/var/lib/containerd/` | Pre-install CPU-only torch in Dockerfile with `--extra-index-url https://download.pytorch.org/whl/cpu`; image drops from ~9 GB to ~2 GB. Clean dead blobs: stop Docker, remove `ingest/` contents, recreate dir, restart Docker |
| `mkdir /var/lib/containerd/…/ingest/…: no such file or directory` on next pull after cleanup | Deleting the `ingest/` directory itself (rather than its contents) leaves containerd unable to create sub-entries | Always recreate the directory after cleanup: `sudo mkdir -p …/ingest/` then `sudo systemctl restart docker` |
| Geography panel empty; no instruments shown | `startup seed` block raises `sqlite3.OperationalError: near "?": syntax error` on `UPDATE instruments … WHERE instrument_id IN :ids` — SQLite does not support tuple binding via SQLAlchemy `text()` | Replace the single `IN :ids` statement with a per-id loop: `for id in ids: db.execute(text("… WHERE instrument_id = :id"), {"id": id})` |
| `write …/libtorch_cpu.so: no space left on device` during `docker pull` | EC2 disk full — each deploy pushes a new ~2.89 GB image without removing old ones; after several deploys the volume fills | SSH in → `docker image prune -a -f` → confirm free space → re-trigger deploy. **Permanent fix:** `deploy.yaml` now stops the old container + prunes images BEFORE the pull on every deploy |
| GitHub Actions run stuck `queued` for 30+ min; new pushes create zero runs; `workflow_dispatch` returns HTTP 500 | Manual "Re-run jobs" click on a queued/failed run puts a re-run in GitHub's pre-queue limbo — API and UI cannot cancel or delete it | Deploy via EC2 Local Build (see section above). Add `workflow_dispatch` to `deploy.yaml` to enable manual dispatch without a push. Never click "Re-run jobs" on an active run. |
| Unit test fails immediately: `AssertionError: gateway.html is missing required element id="card-onboarding"` (or any `test_required_id_present` failure) | HTML file was edited locally but **not committed** to the prod repo. The test was updated to expect the new ID, but CI checks out the remote — which still has the old markup. Runs complete in ~2m30s (fail fast, no Docker build). | Commit the HTML file change to `riia-jun-release/` and push. Always stage + commit HTML alongside the test that validates it. |
| Backtest fails with `ModuleNotFoundError: No module named 'numpy._core.numeric'` (or SB3 `Can't get attribute 'FloatSchedule'` / gymnasium `state must be a dict` warnings) at `DQN.load` | Model zips were trained under a different ML stack than the serving env (zips record theirs in `system_info.txt`; e.g. numpy 2.4 pickles don't load under numpy 1.26). Unpinned deps meant each `docker build` resolved whatever was latest, so prod could drift from the training stack at any rebuild. | `rita/core/model_compat.py::load_dqn_compat` handles cross-version loads at runtime; `constraints-prod.txt` (applied via `pip install -c` in the Dockerfile) pins the prod ML stack to the training-machine versions. When retraining under newer libs, update `constraints-prod.txt` in the same commit as the new model zips. |

---

## GitHub Actions Frozen Queue — Recovery

**Symptom:** Workflow run stays `queued` for 30+ minutes; new pushes create zero runs; API cancel returns 409 "Cannot cancel a workflow re-run that has not yet queued"; `workflow_dispatch` API returns HTTP 500.

**Root cause:** Manually clicking "Re-run jobs" on a queued/failed run puts a re-run object into GitHub's internal pre-queue limbo. GitHub cannot cancel or delete it via API or UI. It blocks all new runs until it self-clears (hours).

**Immediate action:** Deploy via EC2 Local Build (below) — this bypasses GitHub Actions entirely.

**When Actions unsticks:** trigger via `workflow_dispatch` (now in `deploy.yaml` permanently):
```bash
curl -s -X POST \
  -H "Authorization: Bearer <PAT>" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/san-work-ravionics/riia-jun-release-prod/actions/workflows/279526444/dispatches" \
  -d '{"ref": "master"}'
# HTTP 204 = dispatched. HTTP 500 = limbo still active, retry in a few minutes.
```

---

## EC2 Local Build — Emergency Deploy (when GitHub Actions unavailable)

Bypasses the pipeline entirely. Builds the Docker image on the EC2 instance itself.
**Pre-condition:** ≥ 10 GB free disk. Run disk cleanup first (step 2).

```bash
# 1. SSH in
ssh -i terraform/generated-key.pem -o StrictHostKeyChecking=no ubuntu@<EC2_IP>

# 2. Clean disk — old images must go first (running container image is protected by Docker)
docker image prune -a -f
df -h /    # target < 50% used

# 3. Note current container env vars (needed to restart with new image)
docker inspect rita --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -E 'RITA|GOOGLE'

# 4. Clone latest prod repo
rm -rf /tmp/rita-build
git clone --depth 1 https://<PAT>@github.com/san-work-ravionics/riia-jun-release-prod.git /tmp/rita-build
git -C /tmp/rita-build log --oneline -1   # confirm HEAD SHA

# 5. Build in background (~20–30 min on t3.micro)
nohup docker build -t rita:local /tmp/rita-build > /tmp/rita-build.log 2>&1 &

# 6. Poll progress
tail -f /tmp/rita-build.log   # watch for "#25 DONE" = image ready

# 7. Swap container
docker stop rita && docker rm rita
docker run -d --name rita --restart unless-stopped \
  -p 127.0.0.1:8000:8000 \
  -e RITA_ENV=production \
  -e RITA_JWT_SECRET='<from step 3>' \
  -e RITA_GOOGLE_CLIENT_ID='<from step 3>' \
  -e RITA_GOOGLE_CLIENT_SECRET='<from step 3>' \
  -e RITA_BASE_URL='<from step 3>' \
  -v /opt/rita_input:/app/data:ro \
  -v /opt/rita_output:/app/rita_output \
  --memory 900m \
  --log-driver awslogs \
  --log-opt awslogs-region=ap-south-1 \
  --log-opt awslogs-group=/rita/app \
  --log-opt awslogs-stream=rita-container \
  rita:local

# 8. Health check
curl http://localhost/health   # expect {"status":"ok"}
```

**Memory behaviour on t3.micro (1 GB RAM + 2 GB swap):**
- torch CPU wheel install: swap peaks at ~700 MB — normal, it recedes after install
- venv COPY + layer export: disk-bound, not RAM-bound, takes ~10 min silently
- If OOM kills the build: `sudo swapon /swapfile` then retry from step 5

**Log milestones:**
| Log line | What it means |
|---|---|
| `#9 DONE` | torch installed (~37 s) |
| `#10 DONE 147s` | all app packages installed |
| `#11 DONE` | embedding model downloaded |
| `#14 All checks passed!` | ruff lint clean |
| `#25 exporting layers` | final image write (~5–10 min silent) |
| `#25 DONE` | image ready — proceed to step 7 |

---

## Test Results in the Ops Dashboard

The **Test Results** page in the Ops dashboard shows the results from the CI run that produced the currently-running Docker image — not tests run on the EC2 instance itself.

**Flow:**

1. `test` job runs `pytest tests/unit/`, `tests/integration/`, and e2e suites on the GitHub Actions runner, writing JUnit XML files to `test-results/{unit,integration,e2e/{rita,fno,ops}}/latest.xml`
2. `test` job uploads those XMLs as a GitHub Actions artifact (`test-results`)
3. `build-and-push` job downloads the artifact and includes it in the Docker build context
4. `Dockerfile` line `COPY test-results/ /app/test-results/` bakes the XMLs into the image as static files
5. On production, `GET /api/v1/test-results` reads those static files from `/app/test-results/` inside the running container

**What this means in practice:**
- Timestamps on the Test Results page are from the CI run, not from the running server
- A new deploy always refreshes the test results — they reflect the pipeline that built the current image
- If a test is advisory (`continue-on-error: true` in `deploy.yaml`), its failures appear in the XML but did not block the deploy

**e2e tests are advisory** — the hard gate is unit + integration. All four e2e suites run with `continue-on-error: true` so failures there do not block build or deploy.

---

## Diagnosing CI Failures with `gh` CLI

The `gh` CLI is installed at `/usr/local/bin/gh` (Mac). To inspect a failed CI run without opening a browser:

```bash
# List recent runs
GH_TOKEN="<PAT>" gh run list --repo san-work-ravionics/riia-jun-release-prod --limit 10

# View job breakdown of a specific run
GH_TOKEN="<PAT>" gh run view <run-id> --repo san-work-ravionics/riia-jun-release-prod

# Show only the failed step logs
GH_TOKEN="<PAT>" gh run view <run-id> --repo san-work-ravionics/riia-jun-release-prod --log-failed

# Watch a run live until it completes
GH_TOKEN="<PAT>" gh run watch <run-id> --repo san-work-ravionics/riia-jun-release-prod --exit-status
```

A run that completes in ~2m30s and only the `test` job ran (build-and-push skipped) means a unit or integration test failed — the e2e steps never get to run. Check `--log-failed` to see which assertion failed.

---

## Deployment Workflow File Location

- **Prod repo:** `riia-jun-release-prod` on GitHub — `.github/workflows/deploy.yaml`
- **Local code:** `riia-aug-release/` — its own git repo at `/Users/sgawde/work/riia-jun-demo/riia-aug-release/`
