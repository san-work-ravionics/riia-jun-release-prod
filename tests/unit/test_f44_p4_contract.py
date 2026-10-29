"""F44 P4 — the contract fixture ``fixtures/f44_p4_contract.json`` (rev 1 B3, rev 2 N4).

One example per chat card kind (all 10), A1–A6, JourneyOut and (P4c) G_geography: the committed file equals the
generator output (``f44_p4_contract_gen``) and every payload validates against its schema.  P4b's
FC-004 checks every JS field read against this file.
"""
from __future__ import annotations

import json

from pydantic import TypeAdapter

from rita.schemas.geography import GeographyOverviewResponse
from rita.schemas.jarvis import (
    CARD_KINDS,
    CardOut,
    InstrumentPageOut,
    JourneyOut,
    MessageOut,
    PortfolioPageOut,
    SessionOut,
    StateOut,
    WarmupOut,
)

from .f44_p4_contract_gen import FIXTURE, render

MODELS = {"A1_warmup": WarmupOut, "A2_session": SessionOut, "A3_message": MessageOut, "A4_state": StateOut,
          "A5_portfolio": PortfolioPageOut, "A6_instrument": InstrumentPageOut,
          "A6_instrument_excluded": InstrumentPageOut, "journey": JourneyOut,
          "G_geography": GeographyOverviewResponse}


def test_f44_p4_contract_fixture_is_current():
    assert FIXTURE.read_text(encoding="utf-8") == render(), \
        "regenerate: python -m tests.unit.f44_p4_contract_gen"


def test_f44_p4_contract_fixture_validates():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for key, model in MODELS.items():
        assert model.model_validate(data[key]).model_dump(mode="json") == data[key], key
    adapter = TypeAdapter(CardOut)
    assert set(data["cards"]) == set(CARD_KINDS) and len(CARD_KINDS) == 10
    for kind, card in data["cards"].items():
        assert adapter.validate_python(card).kind == kind


def test_segments_serialise_with_from():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    seg = data["journey"]["segments"][0]
    assert "from" in seg and "from_" not in seg


def test_unknown_card_kind_is_rejected():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        TypeAdapter(CardOut).validate_python({"kind": "chart", "data": {}})
