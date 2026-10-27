"""F44 P4 — Jarvis journey intents (core/journey_intents) and slots (core/journey_slots).

The seed set / threshold checks use the real local MiniLM and are skipped when the model path is
absent (as the existing chat tests do).  Slots are pure.  The RITA classifier's 20 intents are
unchanged and the MiniLM singleton is shared.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from rita.core import journey_intents as ji
from rita.core.journey_slots import parse_slots

_SNAPSHOT = (Path.home() / ".cache/huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2/"
             "snapshots/c9745ed1d9f207416be6d2e6f8de32d1f16199bf")
_MODEL = os.environ.get("RITA_CHAT_EMBED_MODEL_PATH") or (str(_SNAPSHOT) if _SNAPSHOT.is_dir() else "")
needs_model = pytest.mark.skipif(not _MODEL or not Path(_MODEL).exists(), reason="local MiniLM not available")
THRESHOLD = 0.42


def test_seed_set_shape():
    assert len(ji.JOURNEY_INTENTS) == 12
    assert sum(len(v) for v in ji.JOURNEY_INTENTS.values()) >= 100
    assert set(ji.INTENT_NAMES) == {"take_goal", "build_selection", "why_this_pick", "cant_reach", "track",
                                    "progress", "what_if_sl", "show_hedge", "change_goal", "confirm",
                                    "decline", "help"}
    assert all(len(v) >= 8 for v in ji.JOURNEY_INTENTS.values())


def test_threshold_is_the_classifier_threshold():
    from rita.config import get_settings
    from rita.core import classifier

    assert get_settings().jarvis.intent_threshold == THRESHOLD
    assert getattr(classifier, "CONFIDENCE_THRESHOLD", THRESHOLD) == THRESHOLD


def test_rita_classifier_intents_unchanged():
    """P4 adds no RITA intent: classifier.py is untouched and keeps its own set (23 at HEAD; the
    design text says 20) and the journey set shares no intent name with it."""
    from rita.core import classifier

    assert len(classifier.INTENTS) == 23
    assert not set(ji.INTENT_NAMES) & {i.name for i in classifier.INTENTS} - {"help"}


@pytest.fixture
def real_model(monkeypatch):
    from rita.config import get_settings

    monkeypatch.setattr(get_settings().chat, "embed_model_path", _MODEL)
    ji.reset_index()
    yield
    ji.reset_index()


@needs_model
def test_shares_the_rita_minilm_singleton(real_model):
    from rita.core import classifier

    assert ji.build_index() == 12 and ji.is_ready()
    assert ji._encoder() is classifier._get_model()


@needs_model
def test_every_seed_maps_to_its_intent(real_model):
    for name, seeds in ji.JOURNEY_INTENTS.items():
        for s in seeds:
            r = ji.classify_journey(s, THRESHOLD)
            assert r.intent == name and not r.low_confidence, (s, r)


@needs_model
@pytest.mark.parametrize("text,intent", [
    ("please use the goal from my plan", "take_goal"),
    ("can you build a portfolio for me", "build_selection"),
    ("why did you choose these", "why_this_pick"),
    ("start tracking my portfolio", "track"),
    ("am I on track this year?", "progress"),
    ("what happens if the stop losses are hit", "what_if_sl"),
    ("show me my hedge plan", "show_hedge"),
    ("I want to change my goal", "change_goal"),
    ("yes switch", "confirm"),
    ("no, keep my mix", "decline"),
])
def test_paraphrases_reach_the_threshold(real_model, text, intent):
    r = ji.classify_journey(text, THRESHOLD)
    assert r.intent == intent and r.confidence >= THRESHOLD, r


@needs_model
@pytest.mark.parametrize("text", ["blorp zzz", "what's the weather in Amsterdam tomorrow",
                                  "recommend a pizza recipe", "qwerty asdf"])
def test_out_of_scope_is_low_confidence(real_model, text):
    assert ji.classify_journey(text, THRESHOLD).low_confidence


# ── slots ──────────────────────────────────────────────────────────────────────

def test_percent_slot_is_parsed_but_only_stored():
    s = parse_slots("set my return to 9.5 %", [])
    assert s.percent == 9.5 and s.to_dict()["percent"] == 9.5


@pytest.mark.parametrize("text,loc", [("my india plan", "india"), ("in EUR please", "europe"),
                                      ("for the usa", "us"), ("NSE stocks", "india"), ("no location", None)])
def test_location_slot(text, loc):
    assert parse_slots(text, []).location == loc


def test_instrument_slot_matches_the_universe_case_insensitively():
    s = parse_slots("what if nifty or Reliance hit their stop", ["NIFTY", "RELIANCE", "SBIN"])
    assert s.instruments == ["NIFTY", "RELIANCE"]
    assert parse_slots("what about ASML", ["NIFTY"]).instruments == []


@pytest.mark.parametrize("text,yn", [("yes", "yes"), ("ok switch", "yes"), ("no thanks", "no"),
                                     ("keep it", "no"), ("yes no", None), ("hello", None)])
def test_yes_no_slot(text, yn):
    assert parse_slots(text, []).yes_no == yn
