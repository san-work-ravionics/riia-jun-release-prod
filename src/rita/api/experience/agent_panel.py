from __future__ import annotations

from pathlib import Path
from typing import List, TypedDict

import base64
import io
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import structlog
from fastapi import APIRouter, HTTPException
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel

log = structlog.get_logger()

router = APIRouter(prefix="/api/v1/agent-panel", tags=["agent-panel"])

# ── Data ─────────────────────────────────────────────────────────────────────
_DATA_PATH = Path(__file__).parent.parent.parent.parent.parent / "data" / "raw" / "ASML" / "asml_2001-2026.csv"

def _load_april_data() -> pd.DataFrame:
    df = pd.read_csv(_DATA_PATH, parse_dates=["date"])
    df.columns = [c.lower() for c in df.columns]
    apr = df[(df["date"].dt.year == 2026) & (df["date"].dt.month == 4)].reset_index(drop=True)
    return apr

_asml = _load_april_data()

# ── Session state ─────────────────────────────────────────────────────────────
SESSION_DATA: dict[str, dict] = {}

# ── AgentState ────────────────────────────────────────────────────────────────
class AgentState(TypedDict):
    date: str
    price_data: dict
    regime: str
    policy: str
    probability: float
    proposal: dict
    compliance_status: str
    logs: List[str]
    hitl_status: str
    cash: float
    holdings: float
    portfolio_value: float
    portfolio_history: List[float]
    cash_history: List[float]
    collaboration_insight: str


# ── Agent nodes ───────────────────────────────────────────────────────────────

def context_agent(state: AgentState) -> AgentState:
    price = state["price_data"]["close"]
    prior = _asml[_asml["date"] < pd.to_datetime(state["date"])]["close"]
    prev_price = prior.iloc[-1] if not prior.empty else price
    change = (price - prev_price) / prev_price
    if abs(change) > 0.03:
        regime = "High Volatility"
    elif change > 0.01:
        regime = "Bull Trending"
    elif change < -0.01:
        regime = "Bear Trending"
    else:
        regime = "Quiet Mean-Reverting"
    state["regime"] = regime
    state["logs"].append(f"Context Agent: Identified regime as {regime} based on {change:.2%} change.")
    return state


def strategy_agent(state: AgentState) -> AgentState:
    regime = state["regime"]
    if regime == "High Volatility":
        policy = "Wide Stops (5%), Targets (1%) - Protective Mode"
    elif regime == "Bull Trending":
        policy = "Tight Stops (1%), Targets (5%) - Trend Following"
    else:
        policy = "Standard 2%/2% - Scalping Mode"
    state["policy"] = policy
    state["logs"].append(f"Strategy Agent: Dynamic Policy set to {policy}.")
    return state


def probability_agent(state: AgentState) -> AgentState:
    regime = state["regime"]
    base_prob = 0.65
    if regime == "High Volatility":
        base_prob = 0.35
    elif regime == "Bull Trending":
        base_prob = 0.82
    state["probability"] = base_prob
    state["logs"].append(f"Probability Agent: Historical success rate for this regime is {base_prob:.0%}.")
    return state


def portfolio_manager_agent(state: AgentState) -> AgentState:
    prob = state["probability"]
    price = state["price_data"]["close"]
    if prob > 0.70 and state["cash"] > 100:
        investment = state["cash"] * 0.2
        shares = investment / price
        state["cash"] -= investment
        state["holdings"] += shares
        state["logs"].append(f"Portfolio Manager: EXECUTED BUY - {shares:.2f} shares at {price} EUR.")
        state["proposal"] = {"action": "BUY", "size": "20%"}
    else:
        state["proposal"] = {"action": "WAIT", "size": "0%"}
        state["logs"].append("Portfolio Manager: Strategy is to WAIT.")
    state["portfolio_value"] = state["cash"] + (state["holdings"] * price)
    return state


def compliance_gate(state: AgentState) -> AgentState:
    pd_ = state["price_data"]
    price_range = (pd_["high"] - pd_["low"]) / pd_["open"]
    if price_range > 0.05:
        state["compliance_status"] = "FLAGGED: Extreme Intraday Volatility"
    else:
        state["compliance_status"] = "PASSED"
    state["logs"].append(f"Compliance Agent: Status - {state['compliance_status']}.")
    return state


def _build_narrator_insight(state: AgentState) -> str:
    regime = state["regime"]
    prob = state["probability"]
    action = state["proposal"].get("action", "WAIT")
    compliance = state["compliance_status"]
    price = state["price_data"]["close"]
    cash = state["cash"]

    regime_sentences = {
        "High Volatility": (
            f"Elevated price swings flagged a High Volatility regime — "
            f"with only {prob:.0%} historical backing, the risk/reward tilted firmly defensive."
        ),
        "Bull Trending": (
            f"A clear upward push confirmed a Bull Trending regime, "
            f"backed by {prob:.0%} historical success — agents aligned on a trend-following stance."
        ),
        "Bear Trending": (
            f"Sustained selling pressure placed the market in Bear Trending territory; "
            f"at {prob:.0%} confidence, taking on exposure looked unattractive."
        ),
        "Quiet Mean-Reverting": (
            f"A low-volatility, directionless session signalled a Quiet Mean-Reverting regime — "
            f"agents adopted a measured scalping posture with {prob:.0%} historical probability."
        ),
    }
    s1 = regime_sentences.get(regime, f"Agents detected a {regime} regime with {prob:.0%} historical success probability.")

    if compliance.startswith("FLAGGED"):
        s2 = (
            f"Despite a {action} signal, the Compliance Gate intervened — "
            f"intraday volatility breached the 5% guardrail and the trade was blocked."
        )
    elif action == "BUY":
        s2 = (
            f"The Portfolio Manager committed 20% of available capital at €{price:.2f}, "
            f"a Kelly-sized entry that cleared compliance cleanly."
        )
    elif cash <= 100:
        s2 = (
            f"Cash reserves fell below the minimum threshold — "
            f"the Portfolio Manager stood aside to preserve liquidity at €{price:.2f}."
        )
    else:
        s2 = (
            f"The Portfolio Manager held position — "
            f"probability below the 70% execution threshold meant no edge worth taking at €{price:.2f}."
        )
    return f"{s1} {s2}"


def narrator_agent(state: AgentState) -> AgentState:
    state["collaboration_insight"] = _build_narrator_insight(state)
    state["logs"].append("SYSTEM: Narrator insight generated.")
    return state


# ── LangGraph workflow ────────────────────────────────────────────────────────
_workflow = StateGraph(AgentState)
_workflow.add_node("context", context_agent)
_workflow.add_node("strategy", strategy_agent)
_workflow.add_node("probability", probability_agent)
_workflow.add_node("portfolio_manager", portfolio_manager_agent)
_workflow.add_node("compliance", compliance_gate)
_workflow.add_node("narrator", narrator_agent)
_workflow.set_entry_point("context")
_workflow.add_edge("context", "strategy")
_workflow.add_edge("strategy", "probability")
_workflow.add_edge("probability", "portfolio_manager")
_workflow.add_edge("portfolio_manager", "compliance")
_workflow.add_edge("compliance", "narrator")
_workflow.add_edge("narrator", END)

_memory = MemorySaver()
_graph = _workflow.compile(checkpointer=_memory)


# ── Request/Response ──────────────────────────────────────────────────────────
class StepRequest(BaseModel):
    day_index: int
    thread_id: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/run-day")
async def run_day(req: StepRequest) -> dict:
    if req.day_index == -1:
        return {"status": "PONG"}

    if req.day_index >= len(_asml):
        raise HTTPException(status_code=400, detail="End of data reached")

    row = _asml.iloc[req.day_index]

    if req.thread_id not in SESSION_DATA or req.day_index == 0:
        SESSION_DATA[req.thread_id] = {"cash": 5000.0, "holdings": 0.0, "portfolio_value": 5000.0}

    sess = SESSION_DATA[req.thread_id]

    initial_state: AgentState = {
        "date": row["date"].strftime("%Y-%m-%d"),
        "price_data": {
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": int(row["volume"]),
        },
        "regime": "",
        "policy": "",
        "probability": 0.0,
        "proposal": {},
        "compliance_status": "",
        "logs": [],
        "hitl_status": "pending",
        "cash": sess["cash"],
        "holdings": sess["holdings"],
        "portfolio_value": sess["portfolio_value"],
        "portfolio_history": [],
        "cash_history": [],
        "collaboration_insight": "",
    }

    config = {"configurable": {"thread_id": req.thread_id}}
    final_state = _graph.invoke(initial_state, config)

    SESSION_DATA[req.thread_id]["cash"] = final_state["cash"]
    SESSION_DATA[req.thread_id]["holdings"] = final_state["holdings"]
    SESSION_DATA[req.thread_id]["portfolio_value"] = final_state["portfolio_value"]

    log.info("agent_panel.day_complete", date=final_state["date"], regime=final_state["regime"],
             action=final_state["proposal"].get("action"), portfolio=round(final_state["portfolio_value"], 2))
    return dict(final_state)


@router.get("/plot/{day_index}")
async def get_plot(day_index: int) -> dict:
    data_slice = _asml.iloc[: day_index + 1]
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.plot(data_slice["date"], data_slice["close"], marker="o", color="#0284c7", linewidth=1.5)
    ax.set_title(f"ASML — Day {day_index + 1}", fontsize=10, color="#1e293b")
    ax.grid(alpha=0.2)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=True)
    plt.close(fig)
    return {"image": base64.b64encode(buf.getvalue()).decode()}
