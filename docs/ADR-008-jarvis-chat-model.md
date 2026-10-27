# ADR-008: Jarvis Chat Model + Claude Option (Feature 44 P0)

| Field | Value |
|---|---|
| **Status** | Accepted 2026-10-25 (Design Review passed; user go-ahead for P1). Module renamed Assistant → **Jarvis** the same day |
| **Date** | 2026-10-25 |
| **Feature** | 44 — Jarvis |
| **Supersedes** | — |
| **Related** | ADR-007 (MCP between modules); `Spec_Chat_Feature.md`; `core/classifier.py`; F44 `REQUIREMENTS.md` § "Chat model" |

---

## Context

Jarvis is a conversation: take the goal from What I Need → build a selection that meets it →
explain the pick → track it in FnO → react when a stop loss is hit. The user agreed (2026-10-25):

- the chat runs on the **local MiniLM model RITA already has** (`core/classifier.py`, all-MiniLM-L6-v2,
  offline, baked into the image, local and prod) — no Ollama, no LLM box;
- the user enters **nothing new** — the only input is the expected return already on What I Need;
- Claude API is an **option only, off by default**.

What exists: `classify(query)` matches a message to one of 20 fixed RITA intents by cosine similarity over
seed phrases (threshold 0.42) and `dispatch()` runs a deterministic handler that returns Markdown. It has
no notion of conversation state, slots, or a journey. A provider-switch pattern exists in
`~/work/voice-to-summary/llm_provider.py` (explicit arg > env > default; `claude` = Anthropic SDK).

Because every number Jarvis shows (goal return, CAGR, MDD, SL, r′) comes from a calculation, a
generative model is not needed to *produce* answers — only to *understand* the message.

---

## Decision

### 1. Understanding: MiniLM journey intents + rule-based slots

- A **separate journey intent set** for Jarvis, classified with the same MiniLM model and the
  same cosine method, with its own seed phrases. The existing 20 RITA intents and `/api/v1/chat` are
  unchanged (no regression on the RITA chat, its golden tests or `agent_performance`).
- Journey intents (P4 seeds; names indicative):

  | Intent | Meaning |
  |---|---|
  | `take_goal` | Use my What I Need plan / what do I need to earn |
  | `build_selection` | Pick the instruments / build my portfolio |
  | `why_this_pick` | Why these instruments / why this mix |
  | `cant_reach` | What if it can't reach my goal / what's the closest |
  | `track` | Track it / show my levels / how is it doing |
  | `what_if_sl` | What if a stop loss hits |
  | `show_hedge` | How do I protect it / hedge suggestions |
  | `change_goal` | Set my return to X% — answered with "change it on What I Need" (Jarvis never edits the plan) |
  | `help` | What can you do / greeting |

- **Slots** (numbers, %, amounts with currency, years / ages, instrument names, location) are parsed by
  deterministic rules, not by a model. A slot only *selects* what to show (e.g. "what if NIFTY hits its
  SL"); it never overrides a number that comes from a tool.
- **Journey state machine** (persisted in `user_journeys.state`, Spec_DB): `no_goal → goal_loaded →
  selected | cant_reach → tracking → reselect_proposed → tracking …`, and `→ back_to_plan` when the
  stop-loss guard trips (2 re-selections used, or *r′* capped at the best historical CAGR): from there
  Jarvis only points back to What I Need until a newer plan is saved. Each state lists the intents it
  accepts; an intent that does not fit the state gets the state's next-step prompt instead.
- **Low confidence** (below the threshold, tuned on the P4 golden set; starts at 0.42): reply with the
  top suggestions for the current state as chips — never guess. With the Claude option on, hand the
  message to Claude instead (§3).

### 2. Replies: templates filled only from MCP tool results

- Each intent has a **tool plan** — the MCP tools (ADR-007, in-memory client, user's identity) it calls —
  and a set of **versioned reply templates**, one per outcome (e.g. `build_selection.meets_goal`,
  `build_selection.cant_reach`).
- Templates are filled **only** from the structured results of the tool calls made for that message.
  Money is formatted in the result's `currency`; rates as %, with the `as_of` date where market data
  is involved.
- The reply carries the ids of the tool calls it used (stored in `jarvis_messages.tool_calls`), so
  every number on screen can be traced to a logged MCP call.
- Jarvis page renders the structured results with the existing module renders (plan view,
  holdings table, σ bands) — the template text is the short explanation around them.

### 3. Claude option: provider switch, off by default

- Config `jarvis.llm.provider`: `off` (default, every environment) | `claude`. Same precedence as the
  existing pattern: config / env override, nothing hardcoded. Model name in config (default the Haiku
  tier, `claude-haiku-5-5`).
- On only when the provider is `claude` **and** `ANTHROPIC_API_KEY` is present in the environment
  (`SecretStr`, prod secrets only, never in YAML). Otherwise `/health` reports `claude_option: off` and
  Jarvis behaves exactly as with `off`.
- **When used:** only for messages MiniLM cannot map (low confidence) or explicit free-text questions.
  The journey intents above never go to Claude.
- **What Claude gets:** the message, a short journey-state summary (state, location, currency, goal
  return, horizon — no names, no email) and the read-only MCP tool definitions. Claude's tool calls run
  through the same in-memory MCP client with the user's identity and are logged like any other.
  `journey.save` is **not** offered to Claude. Never sent: `personal_*` data, raw What I Need inputs,
  other users' data, message history beyond the current session.
- **Number check:** every number in Claude's reply must appear in a tool result of that turn; if not,
  the reply is dropped and the templated "couldn't answer — try one of these" reply is shown.
- **Cost guard:** per-user daily token cap (config) counted in `jarvis_sessions`; over the cap → the
  provider is treated as `off` for that user until the next day.
- **Streaming:** SSE from FastAPI only on the Claude path (nginx `proxy_buffering off` on that one
  location). The MiniLM path returns one JSON reply.

### 4. Tests

- **Golden journeys** in CI against the MiniLM path: scripted conversations per location (EUR / INR /
  USD), each asserting intent, state transition, tool calls and that every number in the reply equals a
  value in the tool results.
- Claude option: an eval run outside CI (needs a key and costs money) with the same golden set plus
  free-text prompts; it never gates CI.

---

## Consequences

**Easier**
- Runs fully locally and in prod on what is already in the image; no new RAM, no API cost by default.
- Answers are deterministic and auditable: same state + same data → same reply; every number traceable
  to an `mcp_calls` row.
- The Claude option is additive — switching it off removes nothing the journey needs.

**Harder**
- Only the phrasings covered by the seeds are understood; anything else gets suggestion chips (or Claude
  when on). Seed coverage must grow from the low-confidence log.
- Templates must be written and maintained per intent × outcome × currency formatting.
- With the Claude option on, the user's message and a state summary leave the box to the Anthropic API.
  This is an explicit, documented opt-in (off by default) — the org guardrail on external services
  (`org.md` §3, §7) needs a recorded exception when it is first switched on in prod (P5).

---

## Alternatives Considered

| Alternative | Why rejected |
|---|---|
| Claude as the primary chat model | API cost per message, a key in prod, user data leaving the box by default; the user chose local-first. |
| Local generative LLM (Ollama / small instruct model) | No RAM on a 1 GB t3.micro; slow on CPU; rejected by the user. |
| Add the journey intents to the existing 20 RITA intents | Changes RITA chat behaviour and its tests; journey intents only make sense with journey state. |
| Fine-tune MiniLM on journey phrases | Not needed for ~10 intents; seed phrases + threshold are enough and need no training pipeline. |
| Regex-only intent matching | Brittle on phrasing; MiniLM is already loaded and handles paraphrase. Regex stays for slots only. |

---

## Consequences note — F44 P4a (2026-10-27)

- **Journey intent set** (`core/journey_intents.py`, separate index on the shared MiniLM singleton
  `classifier._get_model()`; the 23 RITA intents are unchanged): take_goal, change_goal,
  build_selection, cant_reach, why_this_pick, track, **progress**, **confirm**, **decline**,
  what_if_sl, show_hedge, help. Below `CONFIDENCE_THRESHOLD` (0.42) the reply is state chips; in
  `reselect_proposed` a yes/no slot maps to confirm/decline.
- **`tracking` shape.** `user_journeys.tracking` is a list of per-holding rows
  (`instrument_id, allocation_pct, tolerance, entry_date, entry_close, sl_drawdown_limit,
  episode_start, episode_length, model_sha12`), and `segments` records each holding mix with its
  date range so year-to-date P&L chains saved and model-sleeve returns day by day.
- Every number in a reply comes from a tool result field (`services/jarvis_templates.py`); templates
  carry ids (`<intent>.<outcome>.v1`), logged with counts and ids only — never goal amounts or text.
