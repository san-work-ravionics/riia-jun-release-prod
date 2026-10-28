"""Builds the F44 P4 contract fixture (``fixtures/f44_p4_contract.json``): one example per chat
card kind, A1–A6 and JourneyOut — every list holds one element so every nested field the JS may
read is present (FC-004).  Run ``python -m tests.unit.f44_p4_contract_gen`` to rewrite it;
``test_f44_p4_contract.py`` checks the file equals this output and validates it.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from rita.schemas.jarvis import (
    AstaMethodOut,
    AstaTraceOut,
    InstrumentPageOut,
    JourneyOut,
    MessageOut,
    PortfolioPageOut,
    SessionOut,
    SleeveMethodOut,
    StateOut,
    WarmupOut,
)
from rita.services import jarvis_chat_service as C

from .f44_p4_helpers import goal, holding, required, selection, trace

FIXTURE = Path(__file__).parent / "fixtures" / "f44_p4_contract.json"
TS = datetime(2026, 10, 27, 9, 0, tzinfo=timezone.utc)
D = date(2026, 10, 23)


def cards() -> dict[str, dict]:
    sel = selection()
    prop = selection(target=0.0913, holdings=[holding("E3", 100)])
    rr = required("reselect_proposed", "ok", ytd=-0.041, proposal=prop)
    tr = trace("E1")
    return {
        "goal": C._goal_card(goal()),
        "selection": C._selection_card(sel),
        "closest": C._closest_card(selection(closest=True)),
        "why": {"kind": "why", "data": {"tolerance": "medium", "n_tolerances": 3, "rows": [{
            "instrument_id": "E1", "allocation_pct": 60, "fit_return": 0.1012, "test_return": 0.0856,
            "test_mdd": -0.1043, "today_action": "full"}], "excluded": [{"instrument_id": "ATO",
                                                                         "reason": "retrain_needed"}]}},
        "tracking": {"kind": "tracking", "data": {"entry_date": D.isoformat(), "sl_drawdown_limit": -0.1,
                                                  "next_reset": "2026-12-18", "holdings": [{
                                                      "instrument_id": "E1", "entry_close": 123.45,
                                                      "today_action": "full"}]}},
        "progress": C.JarvisChatService._progress_card("saved", D, date(2026, 3, 2), 0.031, 0.0412,
                                                        required(ytd=0.031)),
        "proposal": C.JarvisChatService._proposal_reply(_journey(), rr).cards[0],
        "what_if": {"kind": "what_if", "data": {"ytd_return": -0.04, "required_return": 0.12, "status": "on_track",
                                                "reason": "on_track", "rows": [{"instrument_id": "E1",
                                                                                "sl_distance": tr.sl_distance}]}},
        "hedge": {"kind": "hedge", "data": {"n_hedged": 2, "coverage": 50, "updated_at": TS.isoformat()}},
        "excluded": C._excluded_card([("ATO", "retrain_needed")]),
    }


def _journey() -> JourneyOut:
    sel = selection()
    return JourneyOut(
        journey_id="j-1", location="europe", currency="EUR", state="tracking", back_to_plan_reason=None,
        goal_return=0.0775, horizon_years=13.0, goal_value=264804.0, plan_updated_at=TS, target_return=0.0775,
        reselect_count=1, reselect_year=2026, max_reselections=2, selection=sel,
        proposal=required("reselect_proposed", "ok", ytd=-0.041, proposal=selection(holdings=[holding("E3", 100)])),
        tracking=[{"instrument_id": "E1", "allocation_pct": 60, "tolerance": "medium", "entry_date": "2026-03-02",
                   "entry_close": 123.45, "sl_drawdown_limit": -0.1, "episode_start": "2026-01-02",
                   "episode_length": 252, "model_sha12": "abc123def456"}],
        reselections=[{"at": "2026-04-01", "event": "proposed", "from_return": 0.0775, "to_return": 0.0913,
                       "trigger": "sl_hit"}],
        segments=[{"from": "2026-03-02", "to": None, "cause": "track",
                   "holdings": [{"instrument_id": "E1", "allocation_pct": 60, "tolerance": "medium"}]}],
        plan_year_start=date(2026, 3, 2), previous_journey_id="j-0", version=4, updated_at=TS)


def _pnl() -> dict:
    return {
        "location": "europe", "currency": "EUR", "source": "mixed", "as_of": D.isoformat(),
        "year_start": "2026-03-02", "entry_date": "2026-06-14", "goal_return": 0.0775, "ytd_return": 0.031,
        "target_to_date": 0.0412, "coverage": 0.95,
        "series": [{"date": D.isoformat(), "ret": 0.031, "source": "saved"}],
        "target_path": [{"date": D.isoformat(), "target": 0.0412}],
        "holdings": [{"instrument_id": "E1", "allocation_pct": 60.0, "return_since": 0.02, "status": "ok"}],
        "money": {"portfolio_id": "p1", "name": "My portfolio", "legacy_note": False, "value_entry": 10000.0,
                  "value_now": 10310.0, "pnl": 310.0, "return_since_entry": 0.031, "cash": 12.5,
                  "series": [{"date": D.isoformat(), "value": 10310.0, "pnl": 310.0}],
                  "holdings": [{"instrument_id": "E1", "shares": 40, "entry_close": 150.0, "last_close": 154.0,
                                "pnl": 160.0}]},
    }


def _asta() -> dict:
    sig = {"date": D.isoformat(), "signal": "BUY", "setup": "geo_pan", "confidence": 0.75, "mandatory_met": 3,
           "mandatory_total": 3, "optional_met": 2, "optional_total": 4, "stop_loss": 21800.0, "target": 23400.0}
    return AstaTraceOut(
        instrument_id="NIFTY", status="ok", model_sha12="3fc543eb0000", window_start="2022-07-25",
        window={"test_start": "2022-07-25", "test_end": "2026-08-28", "verified": True, "basis": "temporal_split"},
        training_record={"run_id": "3fc543eb", "test_sharpe": -0.156, "test_mdd": -0.0996, "test_return": 0.2294,
                         "test_trades": 340},
        pipeline_backtest={"run_id": "63ea8087", "status": "failed"}, as_of=D, today_action="cash",
        since=date(2026, 3, 2), return_since=0.012, last_signal=sig, model_note="training run 3fc543eb",
        live_replay_note="fresh replay").model_dump(mode="json")


def _rationale() -> dict:
    return {"date": D.isoformat(), "action": "full", "prev_action": "cash",
            "inputs": [{"name": "rsi_14", "raw": 55.0, "model_input": 0.55}],
            "state": [{"name": "prev_allocation", "value": 0.0}], "note": None}


def _level(v: float, basis: str) -> dict:
    return {"date": D.isoformat(), "value": v, "basis": basis}


def payloads() -> dict:
    cs = cards()
    j = _journey().model_dump(mode="json")
    reply = {"text": "…", "template_id": "track.started.v1", "intent": "track", "confidence": 0.93,
             "low_confidence": False, "chips": [{"label": "How am I doing?", "text": "how am I doing"}],
             "cards": list(cs.values()),
             "tool_calls": [{"tool": "journey.save", "mcp_call_id": "c-1", "status": "ok"}]}
    a5 = {"location": "europe", "currency": "EUR", "as_of": D.isoformat(), "pnl_source": "mixed",
          "perf": {**_pnl(), "pnl_source": "mixed"},
          "required": {"status": "on_track", "reason": "on_track", "required_return": 0.0913,
                       "effective_return": None, "reselections_used": 1, "max_reselections": 2},
          "journey_state": "tracking",
          "instruments": [{"instrument_id": "E1", "held": True, "selected": True, "allocation_pct": 60.0,
                           "shares": 40, "last_close": 154.0, "pnl": 160.0, "ret": 0.02, "model_action": "full",
                           "sl_distance": -0.0747, "sl_hit": False, "engines_available": ["rita", "fno", "asta"]}],
          "engines": [{"engine": "rita", "label": "RITA model (DDQN)", "model_based": True, "coverage": 1.0,
                       "return_since": 0.021, "target_to_date": 0.0412, "gap": -0.0202, "on_pace": False,
                       "status": "ok", "note": None}]}
    eng = {"engine": "rita", "status": "ok", "label": "RITA model (DDQN)", "model_based": True,
           "prices": [{"date": D.isoformat(), "close": 154.0}],
           "markers": [{"date": D.isoformat(), "kind": "entry", "close": 154.0}],
           "levels": {"entry": _level(150.0, "model"), "exit": _level(149.0, "model"),
                      "stop_loss": _level(0.945, "training limit"), "target": _level(160.0, "rule")},
           "series": {"sleeve_value": [1.02], "sl_line": [0.945], "band_upper": [160.0], "band_lower": [140.0]},
           "episode_starts": ["2026-01-02"], "rationale": _rationale(),
           "performance": {"return_since": 0.021, "since": "2026-03-02", "target_to_date": 0.0412, "gap": -0.0202},
           "method": SleeveMethodOut().model_dump(), "tolerance_rule": "selection", "asta": _asta()}
    # P4b FC-004: ``method`` is ``Any`` in InstrumentEngineOut — one example per shape the page service
    # emits (RITA SleeveMethodOut / excluded_reason, FnO text + currency + lookback_returns, ASTA).
    fno_method = {"text": "±1σ monthly band from the last 252 daily returns (statistical, not a model)",
                  "currency": "EUR", "lookback_returns": 252}
    fno = {**eng, "engine": "fno", "status": "levels_only", "label": "FnO σ levels — not a model",
           "model_based": False, "markers": [], "performance": None, "episode_starts": [],
           "method": fno_method, "tolerance_rule": None, "asta": None}
    asta = {**eng, "engine": "asta", "label": "ASTA model (NIFTY only)", "method": AstaMethodOut().model_dump(),
            "tolerance_rule": None, "series": {"sleeve_value": [], "sl_line": [], "band_upper": [], "band_lower": []}}
    excluded = {"engine": "rita", "status": "excluded", "label": "RITA model (DDQN)", "model_based": True,
                "method": {"excluded_reason": "retrain_needed"}}
    a4 = {"location": "europe", "location_name": "Europe", "currency": "EUR",
          "goal": goal().model_dump(mode="json"), "plan_stale": False, "journey": j,
          "session": {"session_id": "s-1", "status": "open", "last_activity_at": TS.isoformat()},
          "messages": [{"message_id": "m-1", "role": "assistant", "text": "…", "intent": "track",
                        "template_id": "track.started.v1", "created_at": TS.isoformat()}],
          "chips": [{"label": "How am I doing?", "text": "how am I doing"}], "chat_model": "ready",
          "live_holdings": [{"instrument_id": "E1", "model_action": "full", "invested_fraction": 1.0,
                             "sl_distance": -0.0747, "sl_hit": False, "next_reset": "2026-12-18",
                             "as_of": D.isoformat(), "status": "ok"}]}
    out = {
        "cards": cs,
        "journey": j,
        "A1_warmup": {"status": "ready", "intents": 12},
        "A2_session": {"session_id": "s-1", "started_at": TS.isoformat(), "reused": False},
        "A3_message": {"session_id": "s-1", "reply": reply, "journey": j},
        "A4_state": a4,
        "A5_portfolio": a5,
        "A6_instrument": {"instrument_id": "E1", "currency": "EUR", "as_of": D.isoformat(), "engines": [eng, fno, asta]},
        "A6_instrument_excluded": {"instrument_id": "ATO", "currency": "EUR", "as_of": D.isoformat(),
                                   "engines": [excluded, {**fno, "prices": []},
                                               {"engine": "asta", "status": "no_model", "label": "ASTA model (NIFTY only)",
                                                "model_based": True, "method": AstaMethodOut().model_dump()}]},
    }
    # normalise through the schemas (fills defaults; the file is exactly what the API serialises)
    out["A1_warmup"] = WarmupOut(**out["A1_warmup"]).model_dump(mode="json")
    out["A2_session"] = SessionOut(**out["A2_session"]).model_dump(mode="json")
    out["A3_message"] = MessageOut(**out["A3_message"]).model_dump(mode="json")
    out["A4_state"] = StateOut(**out["A4_state"]).model_dump(mode="json")
    out["A5_portfolio"] = PortfolioPageOut(**out["A5_portfolio"]).model_dump(mode="json")
    out["A6_instrument"] = InstrumentPageOut(**out["A6_instrument"]).model_dump(mode="json")
    out["A6_instrument_excluded"] = InstrumentPageOut(**out["A6_instrument_excluded"]).model_dump(mode="json")
    out["cards"] = {c["kind"]: c for c in out["A3_message"]["reply"]["cards"]}
    return out


def render() -> str:
    return json.dumps(payloads(), indent=1, sort_keys=True, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(render(), encoding="utf-8")
    print(f"wrote {FIXTURE}")
