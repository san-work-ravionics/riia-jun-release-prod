"""JourneyService — the Jarvis journey state machine (F44 P4 §2 + revisions 1–3).

Events (``journey.save``), always checked against the stored row, never the client's state:

| event        | from                                   | to                                  |
|--------------|----------------------------------------|-------------------------------------|
| start        | no active row, or a strictly newer plan | goal_loaded / no_goal (soft-replace) |
| select       | goal_loaded, selected, cant_reach      | selected (holdings) / cant_reach     |
| track        | selected                               | tracking                            |
| propose      | tracking                               | reselect_proposed                   |
| accept       | reselect_proposed                      | tracking                            |
| decline      | reselect_proposed                      | tracking                            |
| back_to_plan | tracking, reselect_proposed            | back_to_plan                        |

- **B1** ``start`` carries ``reselect_count`` / ``reselect_year`` (same year) and — rev 3 — the
  ``plan_year_start`` and ``segments`` (an open segment stays open: the old mix is still held).
- **N1** ``plan_year_start`` s is set on the first ``track`` of a plan year and never moved by
  ``accept``; ``segments`` chain the held mixes so ytd covers exactly [s, as_of].
- **P3-2** lazy year reset: when the year has changed, ``get_current`` shows ``reselect_count = 0``
  and ``plan_year_start = Jan 1`` with segments clipped (an open segment restarts on Jan 1 with the
  same holdings); persisted on the next save.
- **A5** compare-and-set on ``version``; ``start`` relies on the partial unique index.

ADR-002: rows only through ``repositories/jarvis.py``.  The service owns the transaction.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from rita.config import get_settings
from rita.models.jarvis import SCHEMA_VERSION, UserJourneyModel
from rita.repositories.jarvis import UserJourneyRepo
from rita.schemas.jarvis import JourneyOut, JourneySaveIn, SegmentOut
from rita.services.user_portfolio_service import location_currency

log = structlog.get_logger(__name__)

ALLOWED_FROM: dict[str, tuple[str, ...]] = {
    "select": ("goal_loaded", "selected", "cant_reach"),
    "track": ("selected",),
    "propose": ("tracking",),
    "accept": ("reselect_proposed",),
    "decline": ("reselect_proposed",),
    "back_to_plan": ("tracking", "reselect_proposed"),
}


class JourneyError(Exception):
    """A coded failure: ``invalid_input`` | ``not_found``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def plan_is_newer(goal_updated: datetime | None, journey_updated: datetime | None) -> bool:
    """Strictly newer What I Need plan (B1).  A plan when the journey had none counts as newer."""
    g, j = _utc(goal_updated), _utc(journey_updated)
    if g is None:
        return False
    return j is None or g > j


def _seg_dict(seg: SegmentOut | dict) -> dict:
    if isinstance(seg, SegmentOut):
        return seg.model_dump(mode="json")
    return dict(seg)


def clip_segments(segments: list[dict], s: date) -> list[dict]:
    """Segments relevant from ``s``: closed ones ending on or before ``s`` are dropped; one that
    started before ``s`` restarts at ``s`` with the same holdings (rev 3 P3-2)."""
    out = []
    for seg in segments:
        to = date.fromisoformat(seg["to"]) if seg.get("to") else None
        if to is not None and to <= s:
            continue
        frm = date.fromisoformat(seg["from"])
        if frm < s:
            seg = {**seg, "from": s.isoformat()}
        out.append(seg)
    return out


def year_reset(row_values: dict[str, Any], today: date) -> dict[str, Any]:
    """The lazy year reset applied to a row's values (not persisted here)."""
    v = dict(row_values)
    if v.get("reselect_year") is not None and v["reselect_year"] != today.year:
        v["reselect_count"] = 0
        v["reselect_year"] = None
    pys = v.get("plan_year_start")
    if pys is not None and today.year > pys.year:
        s = date(today.year, 1, 1)
        v["plan_year_start"] = s
        v["segments"] = clip_segments(list(v.get("segments") or []), s)
    return v


_ROW_FIELDS = ("journey_id", "location", "currency", "state", "back_to_plan_reason", "goal_return",
               "horizon_years", "goal_value", "plan_updated_at", "target_return", "reselect_count",
               "reselect_year", "selection", "proposal", "tracking", "reselections", "segments",
               "plan_year_start", "previous_journey_id", "version", "updated_at", "user_id",
               "is_active")


def _values(row: UserJourneyModel) -> dict[str, Any]:
    return {k: getattr(row, k) for k in _ROW_FIELDS}


def _out(values: dict[str, Any]) -> JourneyOut:
    v = {k: values.get(k) for k in _ROW_FIELDS if k not in ("user_id", "is_active")}
    v["tracking"] = v.get("tracking") or []
    v["reselections"] = v.get("reselections") or []
    v["segments"] = v.get("segments") or []
    v["reselect_count"] = v.get("reselect_count") or 0
    v["max_reselections"] = get_settings().goal_selection.max_reselections_per_year
    return JourneyOut.model_validate(v)


class JourneyService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = UserJourneyRepo(db)

    # ── read ───────────────────────────────────────────────────────────────────

    def get_current(self, user_id: str, location: str, today: date | None = None) -> JourneyOut | None:
        row = self._repo.get_active(user_id, location)
        if row is None:
            return None
        return _out(year_reset(_values(row), today or date.today()))

    # ── write ──────────────────────────────────────────────────────────────────

    def save(self, user_id: str, inp: JourneySaveIn, today: date | None = None) -> JourneyOut:
        as_of = inp.as_of or today or date.today()
        try:
            if inp.event == "start":
                return self._start(user_id, inp, as_of)
            return self._apply(user_id, inp, as_of)
        except IntegrityError as exc:
            self._db.rollback()
            raise JourneyError("invalid_input", "journey changed — reload") from exc

    def _start(self, user_id: str, inp: JourneySaveIn, as_of: date) -> JourneyOut:
        if inp.goal is None:
            raise JourneyError("invalid_input", "start needs the goal")
        goal = inp.goal
        active = self._repo.get_active(user_id, inp.location)
        if active is not None and not plan_is_newer(goal.plan_updated_at, active.plan_updated_at):
            raise JourneyError("invalid_input", "the What I Need plan has not changed since this journey started")
        if inp.expected_version is not None and active is not None and active.version != inp.expected_version:
            raise JourneyError("invalid_input", "journey changed — reload")

        now = datetime.now(timezone.utc)
        carry: dict[str, Any] = {"reselect_count": 0, "reselect_year": None,
                                 "plan_year_start": None, "segments": []}
        latest = self._repo.latest_any(user_id, inp.location)
        if latest is not None:
            if latest.reselect_year == as_of.year:
                carry["reselect_count"] = latest.reselect_count or 0
                carry["reselect_year"] = latest.reselect_year
            if latest.plan_year_start is not None and latest.plan_year_start.year == as_of.year:
                carry["plan_year_start"] = latest.plan_year_start
                carry["segments"] = list(latest.segments or [])
        if active is not None:
            if self._repo.close(active.journey_id, active.version, now) == 0:
                self._db.rollback()
                raise JourneyError("invalid_input", "journey changed — reload")
            self._db.flush()
        saved = bool(goal.saved and goal.goal_return is not None)
        row = UserJourneyModel(
            journey_id=str(uuid.uuid4()), user_id=user_id, location=inp.location,
            currency=location_currency(inp.location), state="goal_loaded" if saved else "no_goal",
            is_active=True, plan_updated_at=goal.plan_updated_at,
            goal_return=goal.goal_return if saved else None,
            horizon_years=goal.horizon_years if saved else None,
            goal_value=goal.goal_value if saved else None,
            target_return=None, selection=None, proposal=None, tracking=None, reselections=[],
            previous_journey_id=latest.journey_id if latest is not None else None,
            version=1, schema_version=SCHEMA_VERSION, app_version=get_settings().app.version,
            created_at=now, updated_at=now, **carry,
        )
        self._repo.insert(row)
        self._db.commit()
        log.info("journey.started", location=inp.location, state=row.state,
                 carried_count=carry["reselect_count"], carried_segments=len(carry["segments"]))
        return _out(_values(row))

    def _apply(self, user_id: str, inp: JourneySaveIn, as_of: date) -> JourneyOut:
        row = self._repo.get_active(user_id, inp.location)
        if row is None:
            raise JourneyError("not_found", "no active journey for this location")
        allowed = ALLOWED_FROM[inp.event]
        if row.state not in allowed:
            raise JourneyError("invalid_input", f"{inp.event} is not allowed in state {row.state}")
        expected = inp.expected_version if inp.expected_version is not None else row.version
        cur = year_reset(_values(row), as_of)
        new = getattr(self, f"_ev_{inp.event}")(cur, inp, as_of)
        new["updated_at"] = datetime.now(timezone.utc)
        changed = {k: v for k, v in new.items() if k in _ROW_FIELDS and k not in ("journey_id", "version")}
        if self._repo.cas_update(row.journey_id, expected, changed) == 0:
            self._db.rollback()
            raise JourneyError("invalid_input", "journey changed — reload")
        self._db.commit()
        self._db.expire_all()
        log.info("journey.event", journey_event=inp.event, location=inp.location, state=new["state"])
        fresh = self._repo.get(row.journey_id)
        return _out(_values(fresh))

    # ── events (pure on the value dict) ────────────────────────────────────────

    @staticmethod
    def _ev_select(v: dict, inp: JourneySaveIn, _as_of: date) -> dict:
        if inp.selection is None:
            raise JourneyError("invalid_input", "select needs the selection")
        sel = inp.selection
        v.update(selection=sel.model_dump(mode="json"), target_return=sel.target_return,
                 state="selected" if sel.holdings else "cant_reach")
        return v

    @staticmethod
    def _ev_track(v: dict, inp: JourneySaveIn, as_of: date) -> dict:
        if not inp.tracking:
            raise JourneyError("invalid_input", "track needs the tracking entries")
        entry = min(t.entry_date for t in inp.tracking)
        s = v.get("plan_year_start")
        if s is None or s.year != entry.year:
            s = max(date(entry.year, 1, 1), entry)
        segments = []
        for seg in v.get("segments") or []:
            seg = dict(seg)
            if seg.get("to") is None:
                seg["to"] = entry.isoformat()
            segments.append(seg)
        segments.append({"from": entry.isoformat(), "to": None, "cause": "track",
                         "holdings": [{"instrument_id": t.instrument_id, "allocation_pct": t.allocation_pct,
                                       "tolerance": t.tolerance} for t in inp.tracking]})
        v.update(tracking=[t.model_dump(mode="json") for t in inp.tracking], state="tracking",
                 plan_year_start=s, segments=clip_segments(segments, s))
        return v

    @staticmethod
    def _ev_propose(v: dict, inp: JourneySaveIn, as_of: date) -> dict:
        p = inp.proposal
        if p is None or p.status != "reselect_proposed" or p.proposal is None:
            raise JourneyError("invalid_input", "propose needs a reselect_proposed required_return result")
        events = list(v.get("reselections") or [])
        events.append({"at": as_of.isoformat(), "event": "proposed", "from_return": v.get("target_return"),
                       "to_return": p.effective_return, "trigger": inp.trigger or "behind_target"})
        v.update(proposal=p.model_dump(mode="json"), reselect_count=p.reselections_next,
                 reselect_year=as_of.year, reselections=events, state="reselect_proposed")
        return v

    @staticmethod
    def _ev_accept(v: dict, inp: JourneySaveIn, as_of: date) -> dict:
        p = v.get("proposal") or {}
        sel = p.get("proposal")
        if not sel or not inp.tracking:
            raise JourneyError("invalid_input", "accept needs the stored proposal and the rebased tracking")
        segments = []
        for seg in v.get("segments") or []:
            seg = dict(seg)
            if seg.get("to") is None:
                seg["to"] = as_of.isoformat()
            segments.append(seg)
        segments.append({"from": as_of.isoformat(), "to": None, "cause": "accept",
                         "holdings": [{"instrument_id": h["instrument_id"], "allocation_pct": h["allocation_pct"],
                                       "tolerance": h["tolerance"]} for h in sel.get("holdings", [])]})
        events = list(v.get("reselections") or [])
        events.append({"at": as_of.isoformat(), "event": "accepted", "from_return": v.get("target_return"),
                       "to_return": p.get("effective_return"), "trigger": None})
        # N1: plan_year_start is never moved by accept.
        v.update(selection=sel, target_return=p.get("effective_return"), proposal=None,
                 tracking=[t.model_dump(mode="json") for t in inp.tracking], segments=segments,
                 reselections=events, state="tracking")
        return v

    @staticmethod
    def _ev_decline(v: dict, _inp: JourneySaveIn, as_of: date) -> dict:
        events = list(v.get("reselections") or [])
        events.append({"at": as_of.isoformat(), "event": "declined", "from_return": v.get("target_return"),
                       "to_return": None, "trigger": None})
        v.update(proposal=None, reselections=events, state="tracking")
        return v

    @staticmethod
    def _ev_back_to_plan(v: dict, inp: JourneySaveIn, _as_of: date) -> dict:
        if inp.reason is None:
            raise JourneyError("invalid_input", "back_to_plan needs the reason")
        v.update(back_to_plan_reason=inp.reason, proposal=None, state="back_to_plan")
        return v
