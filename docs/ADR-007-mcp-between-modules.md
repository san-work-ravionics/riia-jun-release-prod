# ADR-007: MCP Between Modules (Feature 44 P0)

| Field | Value |
|---|---|
| **Status** | Accepted 2026-10-25 (Design Review passed; user go-ahead for P1). Module renamed Assistant → **Jarvis** the same day |
| **Date** | 2026-10-25 |
| **Feature** | 44 — Jarvis: one conversation from goal to tracked portfolio |
| **Supersedes** | The unauthenticated SSE transport (`interfaces/mcp_sse_app.py`, `main.py:395-396`) |
| **Related** | ADR-001 (three-tier API), ADR-002 (repository pattern), ADR-008 (Jarvis chat model); `Spec_MCP_Server.md`; F44 `REQUIREMENTS.md` § "MCP between modules" |

---

## Context

F44 adds Jarvis, an assistant module that walks a user from the expected return on What I Need to a tracked, hedged
portfolio. To do that it has to read from four modules (What I Need, Portfolio, FnO, Market). The user
agreed (2026-10-25) that **modules talk to each other through MCP tools**, not through direct imports or
REST calls, and that MCP is secured with the same JWT as the dashboards.

Current state (verified in code 2026-10-25):

- One MCP `Server("rita")` in `interfaces/mcp_tools.py` with three un-namespaced tools: `ask_rita`,
  `rita_market_overview`, `rita_monitor`. Two transports share it: stdio (`rita_mcp_server.py`, Claude
  Desktop local) and SSE mounted in FastAPI (`/mcp/sse` + `/mcp/messages`).
- **`/mcp/sse` and `/mcp/messages` have no auth** — anyone who can reach the box can call the tools.
  They are mounted before the JWT-protected workflow routers and take no dependency.
- `ask_rita` reaches into a **route module** (`rita.api.v1.workflow.chat._get_df`) — the tool layer
  currently depends on the API layer, the opposite of ADR-001.
- Tools return Markdown strings only — nothing a template or another module can read reliably.
- Calls are logged to the `mcp_calls` table by `core/mcp_logger.py` (not CSV as `Spec_MCP_Server.md`
  still says) with no caller, transport or user.
- Installed SDK is `mcp 1.27.1` (`pyproject.toml`: `mcp>=1.0,<2`); it has the streamable HTTP session
  manager and in-memory client/server streams. SSE is deprecated in the MCP spec in favour of
  streamable HTTP.
- Prod is a t3.micro (1 GB + 2 GB swap): no room for extra processes per module.

---

## Decision

### 1. One MCP server, namespaced tools per module

- RITA keeps **one** MCP server instance inside the FastAPI process. Each module registers its tools
  under its own namespace: `whatineed.*`, `portfolio.*`, `fno.*`, `market.*`, `journey.*`.
- **Module ownership** (who owns which namespace and which services a tool may call):

  | Namespace | Module | Wraps (services / core) |
  |---|---|---|
  | `whatineed.*` | What I Need (Invest Game) | `services/retirement_plan_service.py`, `core/retirement_plan.py` |
  | `portfolio.*` | Portfolio Builder | `services/user_portfolio_service.py`, `core/portfolio_optimizer.py`, portfolio analytics (after extraction, §6) |
  | `fno.*` | FnO | `services/position_value_service.py`, `services/hedge_plan_service.py`, `services/kite_middleware_client.py` |
  | `market.*` | Market data / RITA analysis | `core/technical_analyzer.py`, `core/classifier.py`, market-data reads, `services/data_refresh.py` |
  | `journey.*` | Jarvis (new, P4) | new journey service (ADR-008) |

- The full tool list with inputs, outputs and mapped services is in `Spec_MCP_Server.md` § "F44 tool
  catalogue" (added in P0). It is the contract P1–P6 build against.

### 2. Tools wrap services — never routes

- A tool handler calls a **service** (or a pure `core/` function); it never imports a router module and
  never touches a repository or the DB directly (ADR-002 applies to tools exactly as to routes).
- Where the logic a tool needs lives in a route module today (portfolio analytics, portfolio hedge,
  the chat `_get_df` loader), it is **extracted into a service first**; the route and the tool then
  both call that service. No behaviour change in the route.
- Each tool call opens its own DB session and closes it when done (same rule as background threads,
  Spec_DB §5) — a tool never borrows a request-scoped session.

### 3. Structured results

- Every namespaced tool declares an **output schema** taken from a Pydantic response model and returns
  structured content (JSON). A short text rendering is included for clients that only show text.
- Money fields always carry their `currency`; rates are fractions; every result carries an `as_of` date
  where it reads market data. ADR-008 templates and other modules consume the structured part only.
- Errors come back as MCP tool errors with a stable `code` (`not_found`, `forbidden`, `invalid_input`,
  `unavailable`) — never as prose inside a success result.

### 4. Transports

| Caller | Transport | Auth |
|---|---|---|
| Another RITA module, Jarvis (same process) | **In-memory** client ↔ server streams (MCP SDK) — no network, no extra process, no extra RAM | Identity of the already-authenticated HTTP request is passed through (§5) |
| Claude Desktop / external MCP clients (prod or local) | **Streamable HTTP at `/mcp`**, stateless, JSON responses (no long-lived streams, so no nginx buffering change) | `Authorization: Bearer <RITA JWT>` — same token as the dashboards |
| Claude Desktop, local stdio | stdio (`rita_mcp_server.py`, unchanged process) | None (local process) — **exposes only tools that need no user** (Auth `none` in the catalogue, plus the legacy aliases as today) |

- **Cross-module calls go through the in-memory client** (Portfolio → `whatineed.get_goal`, FnO →
  `portfolio.get_holdings`, Jarvis → everything). Calls *inside* one module stay direct function
  calls — MCP is the boundary between modules, not inside them.
- Synchronous service code must be able to make an in-process MCP call (services and SQLAlchemy sessions
  are synchronous; the MCP client is async) — the mechanism is in the P1 task brief.
- The streamable HTTP session manager is started and stopped with the app lifespan.

### 5. Auth on `/mcp` — the user comes from the token, never from a tool argument

- `/mcp` is guarded by the **same JWT validation as `get_current_user`** (same secret, algorithm, expiry,
  the `rita-dev` dev subject accepted only when `settings.env == "development"`). Missing / invalid /
  expired token → HTTP 401 with `WWW-Authenticate: Bearer`, before any MCP message is processed.
- The resolved user is placed in a per-call context the tool handlers read. **No tool takes a `user_id`
  argument** — an external client cannot ask for someone else's data by passing an id.
- Each tool declares the access it needs, mirroring the route it parallels: today the user-data routes
  (`/api/v1/workflow/user-portfolio`, `/position-value`, `/hedge-plan`, the retirement plan) require an
  authenticated user and no RBAC flag, so their tools do the same; a tool that parallels a flag-gated
  route (e.g. ops → `can_access_ops`) checks that flag. Missing access → `forbidden`.
- In-memory calls carry the identity of the HTTP request that started them; a background job (P6 EOD)
  runs with an explicit system identity that can only call the tools whose Auth includes `system` in the
  catalogue.
- Local dev follows the existing pattern: the dashboard / Jarvis gets its JWT via `shared/api.js` +
  `shared/dev-auth.js` (401 → `ensureDevToken(true)` → retry once). Claude Desktop against localhost
  uses a dev token in the `mcp-remote` `Authorization` header.

### 6. Securing today's open `/mcp/sse`

- **First change in P1, before anything else ships:** `/mcp/sse` and `/mcp/messages` get the same JWT
  gate as `/mcp`. This closes the hole even if the rest of P1 slips.
- They are **deprecated** from the same release (`/health` reports `mcp.sse: deprecated`), kept for one
  release so an existing `mcp-remote …/mcp/sse` config keeps working with a token, then **removed in P4**.

### 7. Logging

- Every call — in-memory, HTTP, stdio, SSE — goes through the one dispatch path that writes `mcp_calls`
  via `mcp_logger`, and stays visible in `GET /api/v1/mcp-calls` and the RITA "MCP Calls" section.
- `mcp_calls` gains `transport` (`memory` / `http` / `stdio` / `sse`), `caller` (`jarvis`,
  `module:<name>`, `external`, `system`) and `user_id` (nullable). Args/result summaries stay truncated
  and **never include `personal_*` table data or message text** (counts and ids only).

### 8. Read-only

- Tools return data and proposals. The **only** write any tool performs is saving Jarvis's
  journey record (`journey.save`, ADR-008). Nothing places orders, edits What I Need or saves a
  portfolio on the user's behalf.

### 9. Legacy tool names

- `ask_rita`, `rita_market_overview`, `rita_monitor` stay as aliases of `market.ask`, `market.overview`
  and `market.monitor` for one release (Claude Desktop configs keep working), then are removed with SSE.

### Lot sizes

Lot sizes come from `settings.instruments.*` — never hardcoded. No tool takes or returns a hardcoded
lot size; `fno.*` tools read them from settings (or, per the Zerodha decision, from the Kite
instrument master through fno-margin-fetch).

---

## Consequences

**Easier**
- One place to see every cross-module call (who, which tool, how long, ok/error) — the MCP Calls view.
- Jarvis and Claude Desktop use the *same* tools with the *same* auth; the Claude option (ADR-008
  P5) needs no extra integration — it gets the tool definitions as they are.
- Structured results make ADR-008's rule "every number in a reply comes from a tool result" checkable.
- The open `/mcp/sse` hole is closed in the first P1 commit.

**Harder**
- An in-memory MCP hop costs more than a function call (message encode/decode, ~ms). Acceptable for
  user-facing requests; not to be used in tight loops — batch inputs into one tool call instead.
- Sync services calling an async client need the bridge helper; a mistake there can block the event
  loop. P1 tests must cover it.
- Some logic must be moved out of route modules into services before it can be a tool (portfolio
  analytics, portfolio hedge, chat data loader) — extra refactor work in P1/P3/P6.
- Claude Desktop users against prod must paste a JWT that expires (`jwt_expiry_minutes`); long-lived
  MCP tokens are out of scope.
- `mcp_calls` needs a migration (3 nullable columns) in P1.
- `market.refresh_eod` (P6) fetches data from Kite (via fno-margin-fetch) and yfinance inside the app.
  The user agreed the daily India fetch (2026-10-25), but `org.md` §3 forbids external data calls from
  application code — P6 must record that exception in the guardrail before the job ships.

---

## Alternatives Considered

| Alternative | Why rejected |
|---|---|
| Direct Python imports between modules | Works today but couples modules, gives no single log of cross-module calls, and is not what the user agreed. |
| REST calls between modules over localhost | Extra HTTP hop + JWT re-validation per call inside the same process; still needs a separate external surface for Claude Desktop. |
| One MCP server process per module | Several Python processes with their own imports — does not fit a 1 GB t3.micro; adds startup ordering. |
| Keep SSE and only add auth | SSE is deprecated in the MCP spec; streamable HTTP is in the installed SDK and supports stateless JSON responses that need no nginx streaming config. |
| `user_id` as a tool argument checked against the token | Two sources of identity that can disagree; one missed check leaks another user's data. Identity from the token only. |
