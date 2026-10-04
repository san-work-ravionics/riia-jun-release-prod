# ADR-004: Hedge-plan write served under the Experience URL prefix

| Field | Value |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-10-05 |
| **Feature** | F40 (Phase 2) |
| **Relates to** | ADR-001 (three-tier API), ADR-002 (repository pattern) |

---

## Context

F29 placed `PUT /api/v1/experience/fno/hedge-plan` under the Experience prefix as a single-table upsert. F39 (live as v1.2.29-31) built the unified Hedge Workflow on top of it. F40 Phase 2 gives the save more than one responsibility: merge with the stored plan (preserve `last_step` / `selections` when omitted), enrich with server-side market data, validate client context, append a row to the append-only `user_hedge_plan_history` table, and commit both writes in one transaction.

By the ADR-001 decision tree (rule 2: multi-table + logic) this is a **Workflow-tier** operation. However `guardrails/project.md` section 1 only allows dashboard JS to call Experience, Portfolio and a short list of Workflow prefixes; a new `/api/v1/workflow/...` path would be a policy change plus a breaking rename of an endpoint that deployed JS and the e2e suite already call.

## Decision

Keep the URL. The route is thin (auth, Pydantic parse, call the service, map to HTTP). `HedgePlanService.save()` (`services/hedge_plan_service.py`) owns the unit of work: key lookup, preserve-on-omit merge, market-block enrichment, context validation/truncation, the history append, and the single `db.commit()` with rollback on any failure. Repositories never commit (ADR-002).

This is a recorded **ADR-001 exception**: the Experience prefix contains exactly one write endpoint, the hedge-plan PUT. Every other Experience endpoint remains read-only, including `GET /hedge-plan`, `GET /hedge-plan/history` and (Phase 3) `GET /position-value`.

The history export is a separate System-tier endpoint, `GET /api/v1/system/hedge-plan-history`, role-gated with `RequireRole("can_access_ops")` (first use of `RequireRole`). It reads one table through its repository; CSV flattening lives in `services/hedge_history_export.py`. Dashboard JS never calls it.

## Consequences

- No JS or e2e breakage; the URL is unchanged.
- Spec_RITA_App lists the PUT as the one Experience write endpoint.
- If a later ADR allows a workflow prefix to dashboard JS, the route moves and the service is unchanged.
- No autosave dedupe: every PUT appends a history row (user decision, F40 Phase 2). `trigger` ("explicit" | "autosave") records the origin so analysis can filter.

## Alternatives rejected

- Move the route to `/api/v1/workflow/fno/hedge-plan`: breaks the JS allow-list policy and deployed clients.
- Put enrichment and history append in the route: violates ADR-002 (no business logic or multi-repo orchestration in routes).
