"""RITA Core — Jarvis journey intents on the local MiniLM model (F44 P4, ADR-008).

Its own seed list and its own seed index, encoded with ``classifier._get_model()`` — the RITA
chat classifier's singleton, so MiniLM is loaded at most once per process.  ``classifier.py`` and
its 20 RITA intents are unchanged.  Cosine match against the seeds; below the threshold
(``jarvis.intent_threshold`` = the existing ``classifier.CONFIDENCE_THRESHOLD``) the result is
low-confidence and Jarvis never guesses or calls a tool.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np

JOURNEY_INTENTS: dict[str, list[str]] = {
    "take_goal": [
        "use my goal", "what do I need to earn", "load my What I Need plan",
        "start with my retirement goal", "take my goal from What I Need", "use my plan",
        "start from my goal", "what return does my plan need", "load my goal",
        "begin with my saved plan",
    ],
    "build_selection": [
        "build my portfolio", "pick instruments for my goal", "which instruments should I hold",
        "select instruments for me", "build a portfolio for my goal", "what should I invest in",
        "make me a portfolio", "choose the instruments", "create my selection",
        "find a mix that meets my goal",
    ],
    "why_this_pick": [
        "why these instruments", "why this mix", "explain the pick", "why did you pick these",
        "explain the selection", "why these weights", "what is behind this pick",
        "how was this chosen", "explain why",
    ],
    "cant_reach": [
        "what if it can't reach my goal", "what's the closest", "show the closest mix",
        "what if my goal is too high", "what can you reach", "closest you can get",
        "what is the best you can do", "goal not reachable",
    ],
    "track": [
        "track it", "start tracking", "show my levels", "track this portfolio",
        "follow these instruments", "begin tracking", "show my stop losses", "monitor it",
    ],
    "progress": [
        "how am I doing", "am I on track", "check my progress", "did a stop loss hit",
        "how is my portfolio doing", "am I behind", "progress this year", "how far am I",
        "status of my plan", "is my goal still on track",
    ],
    "what_if_sl": [
        "what if a stop loss hits", "what if NIFTY hits its stop", "what if stops are hit",
        "what happens if a stop loss triggers", "stop loss scenario",
        "what if everything falls to its stop", "simulate a stop loss",
        "what if my stop loss is hit", "what if the stop is triggered",
    ],
    "show_hedge": [
        "how do I protect it", "hedge suggestions", "show my hedge plan", "how can I hedge",
        "protect my portfolio", "my hedge plan", "hedging options", "downside protection",
    ],
    "change_goal": [
        "set my return to 9%", "change my goal", "lower my goal", "raise my target return",
        "update my goal", "use a different return", "change the target", "edit my goal",
    ],
    "confirm": [
        "yes", "switch to it", "use the new mix", "yes switch", "accept the new mix",
        "go ahead", "ok do it", "yes please",
    ],
    "decline": [
        "no", "keep my current mix", "don't switch", "no thanks", "keep it as it is",
        "stay with the current mix", "reject the new mix", "no keep it",
    ],
    # F45 Phase D — the What I Need portfolio tracker (retirement plan vs the saved portfolio, by bucket)
    "wn_on_track": [
        "am I on track for retirement", "is my retirement plan on track",
        "are my investments on track for my plan", "how are my retirement buckets doing",
        "am I ahead or behind on my retirement plan", "is my portfolio keeping up with my retirement targets",
        "are all my buckets on track", "how is my savings plan tracking",
        "am I meeting my retirement return targets", "retirement progress by bucket",
    ],
    "wn_bucket_status": [
        "how is my index doing", "show the index bucket", "how are my equities doing",
        "how is the equity bucket", "how are my commodities doing", "show my commodity bucket",
        "how is my alternate bucket", "status of my index fund",
        "how is my equity investment doing against its target", "show me the alternates bucket",
        "and the alternates", "what about my commodities", "tell me about my equity bucket",
    ],
    "wn_hedge_signal": [
        "do I need to hedge", "should I hedge my portfolio", "is any bucket at risk",
        "do I need a hedge right now", "is my portfolio at risk of missing my plan",
        "is there a hedge signal", "should I protect my investments", "am I behind enough to hedge",
        "any hedge warning", "is hedging needed",
    ],
    "wn_what_needs_hedging": [
        "what needs hedging", "which buckets need hedging", "which investments need a hedge",
        "what is at risk", "list the buckets that are behind", "which bucket is falling behind",
        "what should I hedge", "show me what needs protection", "which buckets are at risk",
        "what is behind target", "what part of my portfolio is at risk",
        "what in my plan is falling behind",
    ],
    "help": [
        "hi", "what can you do", "help", "hello", "how does this work", "what can I ask",
        "show me the options", "hey jarvis",
    ],
}

INTENT_NAMES: tuple[str, ...] = tuple(JOURNEY_INTENTS)


@dataclass(frozen=True)
class JourneyIntentResult:
    intent: str
    confidence: float
    low_confidence: bool


_index: np.ndarray | None = None
_index_intents: list[str] = []
_lock = threading.Lock()


def _encoder():
    """The shared MiniLM singleton (lazy; raises when the model path is not available)."""
    from rita.core.classifier import _get_model

    return _get_model()


def reset_index() -> None:
    """Drop the seed index (tests)."""
    global _index, _index_intents
    with _lock:
        _index = None
        _index_intents = []


def build_index() -> int:
    """Encode every seed once (idempotent); returns the number of intents."""
    global _index, _index_intents
    with _lock:
        if _index is None:
            seeds: list[str] = []
            mapping: list[str] = []
            for name, phrases in JOURNEY_INTENTS.items():
                for s in phrases:
                    seeds.append(s)
                    mapping.append(name)
            emb = _encoder().encode(seeds, normalize_embeddings=True, show_progress_bar=False)
            _index = np.asarray(emb, dtype=np.float32)
            _index_intents = mapping
    return len(JOURNEY_INTENTS)


def is_ready() -> bool:
    return _index is not None


def classify_journey(text: str, threshold: float) -> JourneyIntentResult:
    """Best-matching journey intent for ``text`` (cosine over normalised seed embeddings)."""
    build_index()
    q = np.asarray(_encoder().encode([text], normalize_embeddings=True,
                                     show_progress_bar=False)[0], dtype=np.float32)
    sims = (_index @ q).astype(float)
    best = int(np.argmax(sims))
    conf = float(sims[best])
    return JourneyIntentResult(intent=_index_intents[best], confidence=conf,
                               low_confidence=conf < threshold)
