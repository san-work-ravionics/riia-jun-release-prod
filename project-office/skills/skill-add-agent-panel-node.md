# Skill: Add Agent Panel Node

**Guardrail refs:** org · engineer-role · rita-project  
**Last validated against spec:** 2026-05-26  
**Spec source:** `Spec-Agent-Workflow.md` + `Spec_RITA_App.md`

## When to use this skill
Use when adding a new agent node to the RITA Agent Panel LangGraph system — a new analytical role in the 6-agent ASML investment simulation (e.g. a Macro Analyst, Execution Analyst, or Risk Manager node).

---

## Architecture Overview (read once — do not re-read source files)

The Agent Panel is a **LangGraph StateGraph** running server-side in `src/rita/api/experience/agent_panel.py`. It simulates a team of investment analysts collaborating on ASML position decisions over a 16-day period.

```
run_day POST /api/v1/agent-panel/run-day
    ↓
AgentState (TypedDict) — shared mutable state
    ↓
StateGraph node sequence:
  context_node → strategy_node → probability_node
      → portfolio_manager_node → compliance_node → narrator_node → END
    ↓
HITL gate — if proposal == "BUY", pause and emit hitl_required=True
    ↓
resume POST /api/v1/agent-panel/resume   ← human approve/reject
    ↓
plot GET /api/v1/agent-panel/plot        ← portfolio history chart
```

**Key files:**
| File | Contains |
|---|---|
| `src/rita/api/experience/agent_panel.py` | `AgentState`, all 6 node functions, `_build_graph()`, route handlers, `SESSION_DATA` |
| `dashboard/js/rita/agent-panel.js` | `apState`, TOTAL_DAYS=16, typewriter, HITL flow, `localStorage` history |
| `dashboard/js/rita/ai-compliance.js` | 3-tab compliance viewer (Governance/Guardrails/Trace) |

---

## AgentState TypedDict (shared state between nodes)

```python
class AgentState(TypedDict):
    # Inputs
    date: str
    price_data: dict         # {open, high, low, close, volume} for ASML

    # Agent outputs — written by each node
    regime: str              # context_node: Bull/Bear/Neutral
    policy: str              # strategy_node: recommended action
    probability: float       # probability_node: buy probability
    proposal: str            # portfolio_manager_node: BUY/HOLD/SELL
    compliance_status: str   # compliance_node: APPROVED/FLAGGED
    logs: list[str]          # all nodes append their reasoning here

    # HITL
    hitl_status: str         # "pending" | "approved" | "rejected" | ""

    # Portfolio state (persisted in SESSION_DATA, not the graph)
    cash: float
    holdings: int
    portfolio_value: float
    portfolio_history: list[float]
    cash_history: list[float]

    # Narrative
    collaboration_insight: str   # narrator_node: human-readable summary
```

---

## Rule 1: Node Function Signature

Every node function must accept `AgentState` and return a partial state dict:

```python
def my_new_node(state: AgentState) -> dict:
    # Read from state
    regime = state["regime"]

    # Compute the node's contribution
    result = "..."

    # Return ONLY the fields this node writes — do not overwrite unrelated fields
    return {
        "my_field": result,
        "logs": state["logs"] + [f"[MyAgent] {result}"],
    }
```

Node rules:
- **No external API calls** — all data from `state["price_data"]` or local calculations
- **Append to `logs`** — every node adds at least one entry to `logs` for the Compliance Trace tab
- **Return only your fields** — partial updates merge cleanly; overwriting all state breaks other nodes
- **Never modify `portfolio_history` directly** — that is owned by `portfolio_manager_node`

---

## Rule 2: Wiring into the StateGraph

```python
# In agent_panel.py — _build_graph()
def _build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    # Add all nodes
    graph.add_node("context", context_node)
    graph.add_node("strategy", strategy_node)
    graph.add_node("probability", probability_node)
    graph.add_node("portfolio_manager", portfolio_manager_node)
    graph.add_node("compliance", compliance_node)
    graph.add_node("narrator", narrator_node)
    graph.add_node("my_new_node", my_new_node)   # ← add here

    # Wire edges — position in sequence matters
    graph.add_edge(START, "context")
    graph.add_edge("context", "strategy")
    graph.add_edge("strategy", "probability")
    graph.add_edge("probability", "my_new_node")   # ← insert before portfolio_manager
    graph.add_edge("my_new_node", "portfolio_manager")
    graph.add_edge("portfolio_manager", "compliance")
    graph.add_edge("compliance", "narrator")
    graph.add_edge("narrator", END)

    memory = MemorySaver()
    return graph.compile(checkpointer=memory)
```

---

## Rule 3: AgentState Fields

If your new node requires a new output field:

1. **Add the field to `AgentState`** (TypedDict) with its type
2. **Initialise it in `SESSION_DATA`** — the server-side state dict that persists across `run_day` calls
3. **Include it in the `run_day` response** if the JS frontend needs to display it

Do not add fields to `AgentState` that are only used within a single node — use local variables instead.

---

## Rule 4: HITL Gate (only for proposal-changing nodes)

The HITL gate fires when `state["proposal"] == "BUY"`. If your new node changes the proposal, place it **before** `portfolio_manager_node` so the HITL check still runs at the right point.

The HITL flow is owned by the JS frontend (`agent-panel.js`). The backend signals `hitl_required: true` in the `run_day` response. Do not change this contract.

---

## Rule 5: Frontend Display

Each node's log line is displayed in the **AI Compliance → Trace tab** (`ai-compliance.js`). Log format:

```
[NodeName] Plain English explanation of what the agent concluded and why.
```

If you want a dedicated section in the Agent Panel UI for your node's output, edit `dashboard/js/rita/agent-panel.js` and update `Specs/Spec_JS_Code.md`.

---

## Step-by-Step

1. **Read `agent_panel.py`** (lines 1–150) — understand `AgentState` and existing node signatures
2. **Define your node function** following Rule 1
3. **Add new `AgentState` fields** if needed — Rule 3
4. **Register the node** in `_build_graph()` — Rule 2, insert at the correct sequence position
5. **Update `SESSION_DATA` initialisation** if you added new state fields
6. **Update the `run_day` response dict** if the frontend needs your new field
7. **Update `Specs/Spec_Python_Code.md`** — add the new node to the agent panel section
8. **Update `Specs/Spec_JS_Code.md`** — if the frontend renders the new node's output

---

## Files to Touch

| File | Action |
|---|---|
| `src/rita/api/experience/agent_panel.py` | Add node function, update `AgentState`, wire `_build_graph()`, update `SESSION_DATA` |
| `dashboard/js/rita/agent-panel.js` | Edit if node output needs new UI element |
| `Specs/Spec_Python_Code.md` | Update agent panel node table |
| `Specs/Spec_JS_Code.md` | Update if JS changes made |

---

## Definition of Done

- [ ] Node function accepts `AgentState`, returns partial state dict
- [ ] Node appends at least one entry to `logs`
- [ ] Node registered in `_build_graph()` at the correct sequence position
- [ ] New `AgentState` fields initialised in `SESSION_DATA`
- [ ] `run_day` response includes new fields if JS reads them
- [ ] No external API calls in the node — all data from state or local calculation
- [ ] `Specs/Spec_Python_Code.md` agent panel section updated
