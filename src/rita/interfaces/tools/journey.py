"""``journey.*`` — the Jarvis goal journey (owner: ``services/journey_service.py``; F44 P4).

``journey.save`` is the only MCP write in F44: it applies one state-machine event to the
caller's own journey (no ``user_id`` argument — the user is the call identity).  The service
checks every event against the stored row, never against state sent by the client, and uses
compare-and-set on ``version`` (``expected_version``).  Not offered to Claude in P5."""
from __future__ import annotations

from rita.interfaces.tools._base import ToolContext, ToolError, ToolSpec
from rita.schemas.jarvis import JourneyGetIn, JourneyOut, JourneySaveIn


def _journey_call(fn):
    from rita.services.journey_service import JourneyError

    try:
        return fn()
    except JourneyError as exc:
        raise ToolError(exc.code, exc.message) from exc


def get_current(inp: JourneyGetIn, ctx: ToolContext) -> JourneyOut:
    from rita.services.journey_service import JourneyService

    user = ctx.require_user()
    with ctx.session() as db:
        out = JourneyService(db).get_current(user.id, inp.location)
    if out is None:
        raise ToolError("not_found", f"no journey for {inp.location}")
    return out


def save(inp: JourneySaveIn, ctx: ToolContext) -> JourneyOut:
    from rita.services.journey_service import JourneyService

    user = ctx.require_user()
    with ctx.session() as db:
        return _journey_call(lambda: JourneyService(db).save(user.id, inp))


_AUTH = frozenset({"user", "system"})

TOOLS = [
    ToolSpec(
        name="journey.get_current",
        description=(
            "The signed-in user's active Jarvis journey for a location (europe | india | us): "
            "state, goal (from What I Need), RITA's selection, tracked holdings and their "
            "sleeve-drawdown stop loss, re-selections used this plan year, segments. "
            "not_found if none."
        ),
        input_model=JourneyGetIn,
        output_model=JourneyOut,
        handler=get_current,
        auth=_AUTH,
        text=lambda o: f"Journey {o.location}: state {o.state}, {o.reselect_count} re-selection(s) used.",
        summary=lambda o: f"state={o.state} version={o.version}",
    ),
    ToolSpec(
        name="journey.save",
        description=(
            "Apply one event (start | select | track | propose | accept | decline | back_to_plan) "
            "to the signed-in user's journey for a location. A disallowed event, a stale "
            "expected_version or a restart on an unchanged plan → invalid_input."
        ),
        input_model=JourneySaveIn,
        output_model=JourneyOut,
        handler=save,
        auth=_AUTH,
        text=lambda o: f"Journey {o.location} saved: state {o.state}.",
        summary=lambda o: f"state={o.state} version={o.version}",
    ),
]
