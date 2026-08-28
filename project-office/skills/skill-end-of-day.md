# Skill: End-of-Day Routine

**Guardrail refs:** org · pm-role  
**Last validated against spec:** 2026-05-26

## When to use this skill
Use when completing a sprint day — marking tasks done, updating the roadmap, publishing to Confluence, and committing all artifacts. All 4 steps are mandatory. Do not mark a day done until all 4 are complete.

---

## Step 1 — Update PLAN_STATUS.md

File: `riia-agentic-firm/PLAN_STATUS.md`

1. Find today's row in the sprint table (search for `| Day N |`)
2. Change `[ ]` to `[x]` in the Status column
3. Add a brief entry in the Notes column — what was actually delivered (e.g. "3 skill files + /fix-bug command committed")
4. Update the `**Last updated:**` date at the top to today's date
5. If this is the last day of a sprint, update the sprint header to `## Sprint N — COMPLETE`

---

## Step 2 — Session Run Log + Metrics Refresh

After every session that touches feature work, ensure Agent Build data is current.

### 2a — Write a session run log if needed

Check whether today's work already has a run log in `riia-ai-org/agent-ops/runs/`:
- If the session was a full `/enhance` run, the orchestrator already wrote one — skip 2a.
- If the session was a direct fix, cosmetic change, or multi-session continuation **without** a `/enhance` run log, write one now at:
  `riia-ai-org/agent-ops/runs/run-{YYYYMMDD-HHMM}.json`

Run log format for direct/manual work:
```json
{
  "run_id": "{YYYYMMDD-HHMM}",
  "app": "{rita|fno|ops|ds}",
  "request": "{one-line description of what was done}",
  "skill_file": "n/a",
  "agents": [
    {
      "role": "engineer",
      "status": "pass",
      "steps_required": 3,
      "steps_completed": 3,
      "adherence_score": 1.0,
      "token_estimate": {rough estimate},
      "grounding_checks": {
        "branch_created": false,
        "code_changed": true,
        "spec_updated": {true|false},
        "ruff_passed": true,
        "contract_matches_architect": true
      },
      "failure_modes": [],
      "notes": "{what was changed and why, commit hash}"
    }
  ],
  "overall_status": "pass",
  "total_tokens_estimated": {same as token_estimate},
  "duration_minutes": {estimate},
  "branch": "master",
  "merge_status": "merged",
  "merge_commit": "{short hash from git log}"
}
```

### 2b — Regenerate metrics.json

Always run this after writing or confirming a run log:
```bash
# Run from workspace root: riia-agentic-firm/
python riia-ai-org/agent-ops/aggregate_metrics.py
```

Capture stdout. If any `[ALERT]` lines appear, note them in the session summary. The Agent Builds dashboard reads `metrics.json` on next load — no further action needed.

---

## Step 3 — Publish Confluence Sprint Board

Identify the current sprint number N from PLAN_STATUS.md.

```bash
# Run from the workspace root: riia-agentic-firm/
CONFLUENCE_EMAIL=contact@ravionics.nl python project-office/confluence/sprint-boards/publish_sprint{N}_board.py
```

The script must have today's day added to the deliverables section with status `Done` before running.

**If the script doesn't exist yet**, create it following the pattern from an existing sprint board script:
- Parent: `SECTION["sprint_boards"]` → `65077274`
- Add a row for today's deliverables with status `Done`
- Run `create_page()` on first run; hardcode the returned `PAGE_ID`; use `update_page()` on subsequent runs

**Confluence rules (never violate):**
- Plain HTML only — no `ac:structured-macro` tags (returns HTTP 400)
- Run from project root with `CONFLUENCE_EMAIL` env var set
- Hardcode `PAGE_ID` after first run — never leave it as `None`

---

## Step 4 — Skill Drift Check

Check whether any spec file changed recently without a matching skill file update.

```bash
# Run from workspace root
git log --since="7 days ago" --name-only --pretty=format: -- project-office/specs/ | sort -u | grep -v '^$'
```

For each spec file listed in the output:
1. Identify the matching skill file from this table:

| Spec changed | Matching skill file |
|---|---|
| `Spec_RITA_App.md` | `skill-add-rita-feature.md`, `skill-add-fno-feature.md`, `skill-add-ops-feature.md` |
| `Spec_JS_Code.md` | `skill-add-rita-feature.md`, `skill-add-fno-feature.md`, `skill-add-ops-feature.md`, `skill-fix-js-bug.md` |
| `Spec_Python_Code.md` | `skill-add-api-endpoint.md` |
| `Spec_DB.md` | `skill-add-db-model.md`, `skill-add-api-endpoint.md` |
| `Spec_Chat_Feature.md` | `skill-add-chat-intent.md` |
| `Spec-Agent-Workflow.md` | `skill-add-agent-panel-node.md` |
| `SPEC_Prod_Deploy.md` | `skill-ops-engineer.md`, `skill-model-build-debug.md` |

2. Read the `Last validated against spec:` date from the matching skill file header.
3. Compare to the date of the spec file's most recent commit:
   ```bash
   git log -1 --format="%ai" -- project-office/specs/{SpecFile}.md
   ```
4. If the skill's validated date is **earlier** than the spec's last commit:
   - Flag: `[DRIFT] {skill-file}.md not updated after {SpecFile}.md changed on {date}`
   - Add to the git commit message: `note: skill drift detected — {skill-file} needs update`

If no drift is found: report `✓ Skill drift check — all skill files current.`
If drift is found: report the flags and note that the skill files should be updated in the next session.

**Drift does not block the commit** — it is a warning, not a gate.

---

## Step 5 — Git Commit

Stage all files changed today:
```bash
git add <specific files>   # never git add -A — list files explicitly
git status                 # verify only intended files are staged
```

Commit format:
```
<type>(<scope>): <what was delivered today>

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

Types: `feat` (new feature), `fix` (bug fix), `docs` (documentation), `chore` (maintenance), `test` (tests), `refactor`

After committing:
```bash
git status   # must show: nothing to commit, working tree clean
git log --oneline -3   # confirm commit appears
```

---

## Guardrails

- **Never skip steps** — all 5 are mandatory every session
- **Do not mark the day done in PLAN_STATUS.md before steps 2, 3, 4, 5 are done**
- **Do not commit until the app starts end-to-end** — `python riia-jun-release/start.py` must run without errors before committing code changes
- **Absolute dates only** — convert "today", "Thursday" etc. to `YYYY-MM-DD` in PLAN_STATUS.md notes
- **Do not push** — only commit locally unless the user explicitly asks to push

---

## Definition of Done

- [ ] Step 1 — PLAN_STATUS.md: notes entry added for today's work, Last updated date correct
- [ ] Step 2 — Session run log: run log written to `riia-ai-org/agent-ops/runs/` (or confirmed existing from /enhance); metrics.json refreshed
- [ ] Step 3 — Confluence sprint board: script ran without HTTP errors (or skipped with blocker noted if no script exists)
- [ ] Step 4 — Skill drift check: drift check run; any flags noted in commit message
- [ ] Step 5 — Git: clean working tree, commit message matches format, no untracked files left
