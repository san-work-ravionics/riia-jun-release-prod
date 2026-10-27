"""RITA Core — deterministic slot parsing for Jarvis chat messages (F44 P4, ADR-008).

Slots: a percent, a location, instruments from the location universe, and a yes / no.
**A parsed percent is never echoed or used as a number** — it is stored with the message only;
every number in a Jarvis reply comes from a tool result.  Pure: no I/O.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Iterable

_PERCENT_RE = re.compile(r"-?\d+(?:\.\d+)?\s*%")
_WORD_RE = re.compile(r"[a-z0-9_]+")

LOCATION_WORDS: dict[str, str] = {
    "europe": "europe", "eu": "europe", "eur": "europe",
    "india": "india", "inr": "india", "nse": "india",
    "us": "us", "usa": "us", "usd": "us", "america": "us",
}
YES_WORDS = frozenset({"yes", "yeah", "yep", "sure", "ok", "okay", "switch"})
NO_WORDS = frozenset({"no", "nope", "keep", "don't", "dont"})


@dataclass
class Slots:
    percent: float | None = None          # stored only — never used as a number
    location: str | None = None
    instruments: list[str] = field(default_factory=list)
    yes_no: str | None = None             # "yes" | "no" | None

    def to_dict(self) -> dict:
        return asdict(self)


def parse_slots(text: str, universe: Iterable[str] = ()) -> Slots:
    """Parse ``text``.  ``universe`` = the location's instrument ids (case-insensitive match)."""
    low = text.lower()
    out = Slots()
    m = _PERCENT_RE.search(low)
    if m:
        out.percent = float(m.group(0).replace("%", "").strip())
    words = _WORD_RE.findall(low)
    for w in words:
        if out.location is None and w in LOCATION_WORDS:
            out.location = LOCATION_WORDS[w]
    ids = {i.lower(): i for i in universe}
    for w in words:
        inst = ids.get(w)
        if inst is not None and inst not in out.instruments:
            out.instruments.append(inst)
    tokens = set(re.findall(r"[a-z']+", low))
    if tokens & YES_WORDS and not tokens & NO_WORDS:
        out.yes_no = "yes"
    elif tokens & NO_WORDS and not tokens & YES_WORDS:
        out.yes_no = "no"
    return out
