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

# F45 Phase D — the retirement-plan buckets (same names as the What I Need tab)
BUCKET_LABELS = {"idx": "Index fund", "eq": "Equity", "com": "Commodities", "alt": "Alternate"}

TEMPLATES: dict[str, str] = {
    "show_hedge.plan": ("Your FnO hedge plan covers {n} instrument(s) at {coverage}% coverage. Open "
                        "FnO to change it."),
    # Saved-data answers: the overall saved plan and the saved portfolio, every region together.
    "saved.plan": "Your overall plan: {list}.{missing}",
    "saved.plan.none": "You have no saved plan yet. Save one on What I Need in the Invest Game.",
    "saved.portfolio": "Your saved portfolio, by region:",
    "saved.portfolio.line": "{region}: {mix}.",
    "saved.portfolio.none": "You have no saved portfolio yet. Save one in RITA.",
    "saved.progress": "Your saved portfolio against your saved plan:",
    "saved.progress.line": "{region}: {ytd} this year against {target} to date.",
    "saved.progress.line_none": "{region}: no measured return yet, prices after {entry} are needed.",
    "saved.hedge.pointer": "A hedge is built in FnO. Open it to review.",
    "wn.no_plan": ("You have no saved retirement plan for {location}. Save one on What I Need, then "
                   "ask again."),
    "wn.no_data": ("None of your {n_buckets} buckets has performance data yet — check back after the "
                   "next close."),
    "wn.on_track.ok": ("{n_on_track} of {n_buckets} buckets are on track against the return your plan "
                       "needs so far; {n_no_data} have no performance data yet."),
    "wn.on_track.risk": ("{n_at_risk} of {n_buckets} buckets are more than {threshold} behind the "
                         "return your plan needs so far: {list}. {n_on_track} are on track and "
                         "{n_no_data} have no performance data yet."),
    "wn.no_buckets": "Your saved plan has no asset lines to track yet. Add them on What I Need.",
    "wn.bucket.not_in_plan": "Your plan has no {bucket} line, so there is nothing to compare.",
    "wn.bucket.which": "Which bucket? Index fund, Equity, Commodities or Alternate.",
    "wn.bucket.which_of": "You named more than one bucket ({list}). Which one should I look at?",
    "wn.bucket.empty": ("You hold no {bucket} instruments yet, so there is nothing to compare with "
                        "your plan."),
    "wn.bucket.no_data": "{bucket}: no performance data yet — check back after the next close.",
    "wn.bucket.ok": ("{bucket}: {ytd} so far against {target} that your plan needs to date — on "
                     "track, gap {gap}."),
    "wn.bucket.risk": ("{bucket}: {ytd} so far against {target} that your plan needs to date — gap "
                       "{gap}, past the {threshold} limit. Open FnO to review a hedge."),
    "wn.hedge.none": "No bucket is more than {threshold} behind your plan, so there is no hedge signal.",
    "wn.hedge.none_partial": ("No measured bucket is more than {threshold} behind your plan, so there is no hedge signal. "
                              "{n_no_data} bucket(s) have no data yet and could not be checked."),
    "wn.hedge.signal": ("{n_at_risk} bucket(s) at risk: {list}. A hedge is built in FnO — open it to "
                        "review. Jarvis doesn't compute one."),
    "wn.hedge.list": "{n_at_risk} of {n_buckets} buckets need a look. Open FnO to review a hedge.",
    "wn.hedge.line": "{bucket}: {ytd} against {target} to date (gap {gap}).",
    "help.menu": ("I answer from the plan and the portfolio you have saved, across all your regions: your "
                  "plan, your holdings, how you are doing against the plan and what to hedge. Try one of "
                  "these:"),
    "fallback.low_confidence": "I didn't catch that. Try one of these:",
    "error.unavailable": "{tool} isn't answering right now. Try again in a minute.",
}

CHIPS: tuple[tuple[str, str], ...] = (
    ("My plan", "use my goal"),
    ("My portfolio", "build my portfolio"),
    ("How am I doing?", "how am I doing"),
    ("How do I protect it?", "show my hedge plan"),
)


def template_id(key: str) -> str:
    return f"{key}.{VERSION}"


def render(key: str, **slots: str) -> tuple[str, str]:
    """``(text, template_id)``.  Slots must already be formatted strings."""
    return TEMPLATES[key].format(**slots), template_id(key)


def chips() -> list[dict[str, str]]:
    """The fixed follow-up chips: the same four starting questions whatever was just asked."""
    return [{"label": label, "text": text} for label, text in CHIPS]
