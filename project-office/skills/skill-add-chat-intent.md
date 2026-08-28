# Skill: Add Chat Intent

**Guardrail refs:** org · engineer-role · rita-project  
**Last validated against spec:** 2026-05-26  
**Spec source:** `Spec_Chat_Feature.md`

## When to use this skill
Use when adding a new conversational intent to the RITA chat assistant — a new query type the user can ask (e.g. "What is the current volatility?", "Show me the Greeks for my hedge position"). Covers adding seed phrases, a handler function, and wiring the dispatch mapping.

---

## Architecture Overview (read once — do not re-read source files)

The chat pipeline is **fully local** — no Claude/Anthropic API calls at runtime.

```
User query
    ↓
POST /api/v1/chat
    ↓
classifier.py: classify_intent(query)
    → sentence-transformers/all-MiniLM-L6-v2 (lazy-loaded, cached in _model)
    → cosine similarity against seed phrase embeddings
    → if best score < 0.42 → low_confidence fallback
    ↓
dispatch(intent, context) → handler function
    → deterministic calculation against live OHLCV data
    → returns structured response dict
    ↓
POST /api/v1/chat/warmup  ← called on UI open to pre-load the model
```

**Key files:**
| File | Contains |
|---|---|
| `src/rita/core/classifier.py` | Intent definitions (seed phrases), `classify_intent()`, `dispatch()`, all handler functions |
| `src/rita/api/v1/workflow/chat.py` | Route handlers for `POST /api/v1/chat` and `POST /api/v1/chat/warmup` |
| `dashboard/js/rita/chat.js` | Frontend — `sendChatMsg()`, `useChip()`, chip rendering |

---

## Existing Intents (20 total — do not duplicate)

| Intent key | Trigger phrases (examples) |
|---|---|
| `market_sentiment` | "What is the market sentiment?", "Is market bullish?" |
| `trend_direction` | "EMA trend direction", "Which way is Nifty trending?" |
| `rsi_reading` | "What is the RSI?", "Is Nifty overbought?" |
| `volatility_check` | "How volatile is Nifty?", "Current ATR" |
| `invest_now` | "Can I invest in Nifty now?", "Should I buy?" |
| `allocation_level` | "What allocation should I have?", "How much to invest?" |
| `conservative_strategy` | "Safe investment approach", "Low risk Nifty strategy" |
| `aggressive_strategy` | "High risk strategy", "Maximum growth allocation" |
| `stress_crash_10` | "What if Nifty falls 10 percent?" |
| `stress_crash_20` | "What if Nifty crashes 20 percent?" |
| `stress_rally_10` | "What if Nifty rallies 10 percent?" |
| `stress_flat` | "Sideways market scenario" |
| `backtest_performance` | "How has RITA performed?", "Show historical performance" |
| `portfolio_compare` | "Compare conservative vs aggressive portfolios" |
| `explain_decision` | "Why did RITA recommend this?", "What signals led to this?" |
| `return_1m` / `return_3m` / `return_6m` | "What returns can I expect in 1 month/3 months/6 months?" |
| `return_1y` / `return_3y` / `return_5y` | "What returns in 1/3/5 years?" |

---

## Rule 1: Adding a New Intent — Three Locations

Every new intent requires changes in exactly **three places** in `classifier.py`:

### 1. Add seed phrases to the intent definitions dict
```python
# In classifier.py — INTENTS dict (or equivalent structure)
INTENTS = {
    # ... existing intents ...
    "my_new_intent": [
        "seed phrase one",
        "seed phrase two",
        "seed phrase three",        # minimum 3, ideally 5-8 phrases
        "alternate wording",
        "question variation here",
    ],
}
```

Seed phrase rules:
- Write how a real user would type the query — colloquial, not technical
- Include at least one question form and one statement form
- Avoid overlapping with existing intents — test cosine similarity mentally
- Threshold is 0.42 — phrases that are too generic will trigger false positives

### 2. Add a handler function
```python
def _handle_my_new_intent(context: dict) -> dict:
    """Handler for my_new_intent."""
    # context contains: df (market signals DataFrame), settings
    df = context["df"]
    # ... perform deterministic calculation ...
    return {
        "intent": "my_new_intent",
        "response": "Your natural language response here",
        "data": {
            # structured data the frontend can use
        },
        "confidence": context.get("confidence", 0.0),
    }
```

Handler rules:
- **Deterministic only** — no LLM calls, no external API calls
- Use the OHLCV DataFrame passed in `context["df"]`
- Return `intent`, `response` (human-readable string), and optionally `data` (structured)
- Never raise — return a fallback response dict on error

### 3. Wire into dispatch()
```python
def dispatch(intent: str, context: dict) -> dict:
    handlers = {
        # ... existing mappings ...
        "my_new_intent": _handle_my_new_intent,
    }
    handler = handlers.get(intent)
    if handler is None:
        return _handle_low_confidence(context)
    return handler(context)
```

---

## Rule 2: Chat Chips (optional — add when intent has a quick-access use case)

Chat chips are the clickable suggestion buttons in the chat UI. Defined in `chat.js`:

```js
// dashboard/js/rita/chat.js
const CHIPS = [
    { label: "Market Sentiment", query: "What is the current market sentiment?" },
    // ... existing chips ...
    { label: "My New Intent", query: "Seed phrase that triggers my_new_intent" },
];
```

Only add a chip if the intent is commonly used — don't add chips for rare or advanced queries.

---

## Rule 3: API Endpoint Contracts

```
POST /api/v1/chat
Body:  { "query": "user's message", "instrument": "NIFTY" }
Response: {
    "intent": "my_new_intent",
    "response": "...",
    "confidence": 0.87,
    "data": { ... }   ← optional structured payload
}

POST /api/v1/chat/warmup
Body:  {}
Response: { "status": "ready" }
```

The route handler logs every query to the `alerts` table via `AlertsRepository` (for observability). Do not remove this logging. The old `chat_monitor.csv` file no longer exists — all chat logging goes through the DB.

---

## Step-by-Step

1. **Read `src/rita/core/classifier.py`** (targeted slice — find the `INTENTS` dict and `dispatch()` function)
2. **Check existing intents** — confirm your new intent doesn't overlap with the 20 above
3. **Write seed phrases** (5–8 varied phrases)
4. **Add intent key** to `INTENTS` dict
5. **Write handler function** `_handle_my_new_intent(context)`
6. **Wire into `dispatch()`** mapping
7. **Add chat chip** in `chat.js` if it's a commonly-used query
8. **Update spec** — add row to the intent table in `Specs/Spec_Chat_Feature.md`

---

## Files to Touch

| File | Action |
|---|---|
| `src/rita/core/classifier.py` | Edit — add to `INTENTS` dict, add handler fn, wire `dispatch()` |
| `dashboard/js/rita/chat.js` | Edit — add chip to `CHIPS` array (if needed) |
| `Specs/Spec_Chat_Feature.md` | Edit — add row to intents table |

---

## Definition of Done

- [ ] Seed phrases added (minimum 3, ideally 5–8)
- [ ] Handler returns `intent`, `response`, and `confidence` fields
- [ ] Intent wired into `dispatch()` — no `None` fallback for the new key
- [ ] Handler is deterministic — no LLM calls, no external APIs
- [ ] Chat chip added to `chat.js` if the intent is commonly used
- [ ] `Specs/Spec_Chat_Feature.md` intent table updated
