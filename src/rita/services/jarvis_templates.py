"""Jarvis reply templates (F44 P4, design §3 / §6 + revision 1 copy).

Versioned ids ``<intent>.<outcome>.v1``.  **Every slot comes from a tool field** — the chat
service formats tool values with the formatters below and nothing else; the golden test
reformats every numeric tool field with the same formatters and checks that every number in a
reply is one of them (``number_tokens``).

Formatting: rates ``{:.1%}``, money ``"{currency} {:,.0f}"``, dates ISO, counts as integers.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

VERSION = "v1"


# ── formatters (the only way a number gets into a reply) ───────────────────────

def fmt_rate(x: float | None) -> str:
    return "n/a" if x is None else f"{float(x):.1%}"


def fmt_money(currency: str, x: float | None) -> str:
    return "n/a" if x is None else f"{currency} {float(x):,.0f}"


def fmt_date(d: date | datetime | str | None) -> str:
    if d is None:
        return "n/a"
    if isinstance(d, datetime):
        return d.date().isoformat()
    if isinstance(d, date):
        return d.isoformat()
    return str(d)[:10]


def fmt_num(x: float | int | None) -> str:
    """Counts / years / whole percentages: ``25`` · ``25.5``."""
    if x is None:
        return "n/a"
    return f"{float(x):g}"


def fmt_mix(holdings: Iterable[Any]) -> str:
    """``NIFTY 60%, NVIDIA 40%`` from tool holdings (``instrument_id``, ``allocation_pct``)."""
    parts = []
    for h in holdings:
        iid = h["instrument_id"] if isinstance(h, dict) else h.instrument_id
        pct = h["allocation_pct"] if isinstance(h, dict) else h.allocation_pct
        parts.append(f"{iid} {fmt_num(pct)}%")
    return ", ".join(parts)


def number_tokens(values: Iterable[Any], currencies: Iterable[str] = ()) -> set[str]:
    """Every string the formatters could make from ``values`` (golden-test provenance set)."""
    out: set[str] = set()
    curs = list(currencies)
    for v in values:
        if isinstance(v, bool) or v is None:
            continue
        if isinstance(v, (int, float)):
            for x in (v, abs(v)):
                out.add(fmt_rate(x))
                out.add(fmt_num(x))
            for c in curs:
                out.add(fmt_money(c, v))
        elif isinstance(v, (date, datetime)):
            out.add(fmt_date(v))
        elif isinstance(v, str) and len(v) >= 10 and v[4:5] == "-" and v[7:8] == "-":
            out.add(v[:10])
    return out


# ── copy (design §6 + revision 1; PROPOSED, see the P4a report) ────────────────

LOCATION_NAMES = {"europe": "Europe", "india": "India", "us": "US"}

ACTION_LABELS = {"cash": "In cash", "half": "Half invested", "full": "Fully invested",
                 "hedged": "Invested, hedged"}

REASON_LABELS = {
    "no_model": "no model", "retrain_needed": "model needs retraining (price history rewritten)",
    "data_integrity": "price data failed a check", "stale_data": "price data out of date",
    "bad_data": "bad price data", "no_data": "no price data", "load_failed": "model failed to load",
    "feature_mismatch": "model doesn't fit the data",
}

SOURCE_LABELS = {"saved": "Your saved portfolio", "model_sleeves": "RITA's model sleeves (no amounts)",
                 "mixed": "Your saved portfolio and RITA's model sleeves"}

# NEW copy (not in design §6) — flagged in the P4a report for approval:
WHAT_IF_STATUS = {"on_track": "still on track", "reselect_proposed": "a re-selection would be proposed",
                  "back_to_plan": "you would be sent back to What I Need"}

TEMPLATES: dict[str, str] = {
    "take_goal.loaded": ("Your {location} goal from What I Need: {goal_return} a year over {horizon} "
                         "years, aiming for {goal_value} at retirement. Say \"build my portfolio\" "
                         "to pick instruments."),
    "take_goal.no_plan": ("You have no saved plan for {location}. Save one on What I Need, then say "
                          "\"use my goal\"."),
    "take_goal.same_plan": ("Your plan hasn't changed since {plan_updated_at}. Update it on What I "
                            "Need to start again."),
    "notice.plan_changed": ("Your What I Need plan changed on {plan_updated_at}. Say \"use my goal\" "
                            "to start from it."),
    "build.meets": ("RITA's models meet your {target} goal in {location}: {mix}. On the test window "
                    "({test_start} to {as_of}) this mix returned {test_return} a year, with a worst "
                    "drop of {test_mdd}. The weights come from a solver over the models, not from a "
                    "model."),
    "build.test_short": ("This mix reaches {target} on {fit_start}–{fit_end} ({fit_return}) but "
                         "returned {test_return} on the test window — {gap} short. {mix}."),
    "build.cant_reach": ("RITA's models can't reach {target} in {location}. The closest mix is {mix}: "
                         "{fit_return} on the fit window, {test_return} on the test window. The best "
                         "any mix reaches is {cap_fit}. You can lower your goal on What I Need."),
    "build.none_eligible": "No {location} instrument has a usable model right now: {excluded}.",
    "why.mix": ("Each instrument's own DDQN model was replayed at {n_tolerances} risk levels; the "
                "{tolerance} level gave the least risk that still meets {target}."),
    "why.line": ("{instrument} {allocation}% — model return {fit_return} (fit), {test_return} (test), "
                 "worst drop {test_mdd}, today: {action}."),
    "why.excluded": "Left out: {list}.",
    "track.started": ("Tracking from {entry_date}. Each holding's stop loss is a {limit} drop of its "
                      "model sleeve from its peak; the peak resets when a new model episode starts "
                      "(next: {next_reset})."),
    "progress.on_track": ("{source}: {ytd} since {year_start}; the path to your {goal_return} goal is "
                          "at {target_to_date} today. For the rest of the year you need {required} — "
                          "on track."),
    "progress.reselect": ("You're behind: {ytd} since {year_start}. To still make {goal_return} this "
                          "year you need {required} for the rest of it. RITA's models can do it with "
                          "{mix} (test return {test_return}). This is re-selection {n} of {max}. Say "
                          "\"yes\" to switch or \"no\" to keep your mix."),
    "progress.back_to_plan.year_end": "The plan year has ended — review your goal on What I Need.",
    "progress.back_to_plan.count": ("Both re-selections for this year are used — review your goal on "
                                    "What I Need."),
    "progress.back_to_plan.cap": ("No mix of RITA's models can reach {required} — the best is "
                                  "{cap_fit}. Review your goal on What I Need."),
    "progress.back_to_plan.test_shortfall": ("The re-selection would miss {required} on the test "
                                             "window — review your goal on What I Need."),
    "progress.no_data": "No closing prices since {entry_date} yet — check back after the next close.",
    "what_if_sl.result": ("If every holding fell to its stop loss today, this year would stand at "
                          "{ytd}. You'd need {required} for the rest of the year: {status}. Nothing "
                          "is saved — this is a what-if."),
    "what_if_sl.line": "{instrument}: {sl_distance} to its stop loss.",
    "show_hedge.plan": ("Your FnO hedge plan covers {n} instrument(s) at {coverage}% coverage. Open "
                        "FnO to change it."),
    "show_hedge.none": "You have no saved hedge plan. FnO's Hedge Workflow builds one.",
    "change_goal.info": ("Jarvis doesn't change your goal. It is {goal_return} a year on What I Need "
                         "— change it there."),
    "confirm.accepted": "Switched for the rest of the year: {mix}, target {effective}.",
    "decline.kept": ("Kept your current mix. The re-selection still counts: {n} of {max} used this "
                     "year."),
    "help.menu": ("I read your goal, pick instruments that meet it, explain the pick, track it and "
                  "tell you what a stop loss would mean. Try one of these:"),
    "fallback.low_confidence": "I didn't catch that. Try one of these:",
    "state_prompt.none": "Start with your goal: say \"use my goal\".",
    "state_prompt.no_goal": "Start with your goal: say \"use my goal\".",
    "state_prompt.goal_loaded": "Next: \"build my portfolio\".",
    "state_prompt.selected": "Next: \"track it\", or ask \"why these instruments\".",
    "state_prompt.cant_reach": "Change your goal on What I Need, or ask for the closest mix.",
    "state_prompt.tracking": "Ask \"how am I doing\" or \"what if a stop loss hits\".",
    "state_prompt.reselect_proposed": "Say \"yes\" to switch or \"no\" to keep your mix.",
    "state_prompt.back_to_plan": "Review your goal on What I Need, then say \"use my goal\".",
    "error.unavailable": "{tool} isn't answering right now. Try again in a minute.",
}

CHIPS: dict[str, tuple[str, str]] = {
    "take_goal": ("Use my goal", "use my goal"),
    "build_selection": ("Build my portfolio", "build my portfolio"),
    "why_this_pick": ("Why this pick?", "why these instruments"),
    "track": ("Track it", "track it"),
    "progress": ("How am I doing?", "how am I doing"),
    "what_if_sl": ("What if a stop loss hits?", "what if a stop loss hits"),
    "show_hedge": ("My hedge plan", "show my hedge plan"),
    "confirm": ("Yes, switch", "yes"),
    "decline": ("No, keep it", "no"),
}

STATE_CHIPS: dict[str, tuple[str, ...]] = {
    "none": ("take_goal",),
    "no_goal": ("take_goal",),
    "goal_loaded": ("build_selection", "show_hedge"),
    "selected": ("track", "why_this_pick", "build_selection"),
    "cant_reach": ("why_this_pick", "take_goal"),
    "tracking": ("progress", "what_if_sl", "why_this_pick", "show_hedge"),
    "reselect_proposed": ("confirm", "decline", "why_this_pick"),
    "back_to_plan": ("take_goal",),
}


def template_id(key: str) -> str:
    return f"{key}.{VERSION}"


def render(key: str, **slots: str) -> tuple[str, str]:
    """``(text, template_id)``.  Slots must already be formatted strings."""
    return TEMPLATES[key].format(**slots), template_id(key)


def chips_for(state: str | None) -> list[dict[str, str]]:
    return [{"label": CHIPS[k][0], "text": CHIPS[k][1]} for k in STATE_CHIPS.get(state or "none", ())]
