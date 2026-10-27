"""F44 P4 — JourneyService state machine (§2.1, rev 1 B1/A5, rev 2 N1, rev 3).

Transitions, disallowed events, the active-row rule + partial unique index, compare-and-set on
``version``, the count from ``reselections_next``, B1 restart rules, N1 plan_year_start /
segments, rev 3 carry-over and the lazy year reset.
"""
# ruff: noqa: F811 — pytest fixtures imported from a sibling module are redefined as test params
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from rita.models.jarvis import UserJourneyModel
from rita.services.journey_service import JourneyError, JourneyService, clip_segments, plan_is_newer

from .f44_p4_helpers import (
    PLAN_T0,
    goal,
    goal_in,
    holding,
    journey_db,  # noqa: F401 — fixture
    required,
    save_in,
    selection,
    tracking,
)

U = "alice"
D1 = date(2026, 3, 2)


def _to_tracking(svc: JourneyService, entry: date = D1, sel=None):
    sel = sel or selection()
    j = svc.save(U, save_in("start", goal=goal_in(goal())))
    j = svc.save(U, save_in("select", selection=sel, expected_version=j.version))
    return svc.save(U, save_in("track", tracking=tracking(sel, entry), as_of=entry, expected_version=j.version))


def _propose(svc, j, used=0, on=date(2026, 4, 1)):
    prop = selection(holdings=[holding("E3", 100)])
    return svc.save(U, save_in("propose", proposal=required("reselect_proposed", "ok", ytd=-0.08, used=used,
                                                             proposal=prop),
                               trigger="behind_target", as_of=on, expected_version=j.version))


# ── transitions ────────────────────────────────────────────────────────────────

def test_happy_path_transitions(journey_db):
    svc = JourneyService(journey_db)
    assert svc.get_current(U, "europe") is None
    j = svc.save(U, save_in("start", goal=goal_in(goal())))
    assert j.state == "goal_loaded" and j.version == 1 and j.goal_return == 0.0775 and j.currency == "EUR"
    j = svc.save(U, save_in("select", selection=selection(), expected_version=1))
    assert j.state == "selected" and j.version == 2 and j.target_return == 0.0775
    j = svc.save(U, save_in("track", tracking=tracking(selection(), D1), as_of=D1, expected_version=2))
    assert j.state == "tracking" and j.plan_year_start == D1
    assert len(j.segments) == 1 and j.segments[0].from_ == D1 and j.segments[0].to is None
    assert j.segments[0].model_dump()["from"] == D1        # serialised by alias
    j = _propose(svc, j)
    assert j.state == "reselect_proposed" and j.reselect_count == 1 and j.reselect_year == 2026
    assert j.reselections[-1].event == "proposed"
    j = svc.save(U, save_in("decline", expected_version=j.version))
    assert j.state == "tracking" and j.proposal is None and j.reselect_count == 1   # count stays spent
    j = svc.save(U, save_in("back_to_plan", reason="cap", expected_version=j.version))
    assert j.state == "back_to_plan" and j.back_to_plan_reason == "cap"


def test_select_without_holdings_is_cant_reach(journey_db):
    svc = JourneyService(journey_db)
    svc.save(U, save_in("start", goal=goal_in(goal())))
    j = svc.save(U, save_in("select", selection=selection(closest=True)))
    assert j.state == "cant_reach"
    with pytest.raises(JourneyError) as e:
        svc.save(U, save_in("track", tracking=tracking(selection(), D1)))
    assert e.value.code == "invalid_input"


def test_no_plan_start_is_no_goal(journey_db):
    j = JourneyService(journey_db).save(U, save_in("start", goal=goal_in(goal(saved=False))))
    assert j.state == "no_goal" and j.goal_return is None


@pytest.mark.parametrize("event,kw", [
    ("track", {}), ("propose", {}), ("accept", {}), ("decline", {}), ("back_to_plan", {"reason": "cap"}),
])
def test_disallowed_events_from_goal_loaded(journey_db, event, kw):
    svc = JourneyService(journey_db)
    svc.save(U, save_in("start", goal=goal_in(goal())))
    with pytest.raises(JourneyError) as e:
        svc.save(U, save_in(event, **kw))
    assert e.value.code == "invalid_input"


def test_event_without_journey_is_not_found(journey_db):
    with pytest.raises(JourneyError) as e:
        JourneyService(journey_db).save(U, save_in("select", selection=selection()))
    assert e.value.code == "not_found"


def test_save_input_forbids_user_id_and_extra():
    from pydantic import ValidationError

    from rita.schemas.jarvis import JourneySaveIn
    with pytest.raises(ValidationError):
        JourneySaveIn(location="europe", event="start", user_id="bob")


def test_count_comes_from_reselections_next(journey_db):
    svc = JourneyService(journey_db)
    j = _to_tracking(svc)
    j = _propose(svc, j, used=1)                  # P3 says next = 2
    assert j.reselect_count == 2


# ── active row / concurrency ───────────────────────────────────────────────────

def test_partial_unique_index_blocks_second_active_row(journey_db):
    svc = JourneyService(journey_db)
    svc.save(U, save_in("start", goal=goal_in(goal())))
    now = datetime.now(timezone.utc)
    journey_db.add(UserJourneyModel(journey_id="dup", user_id=U, location="europe", currency="EUR",
                                    state="goal_loaded", is_active=True, version=1, reselect_count=0,
                                    reselections=[], segments=[], created_at=now, updated_at=now))
    with pytest.raises(IntegrityError):
        journey_db.commit()
    journey_db.rollback()


def test_stale_expected_version_is_refused(journey_db):
    svc = JourneyService(journey_db)
    j = svc.save(U, save_in("start", goal=goal_in(goal())))
    svc.save(U, save_in("select", selection=selection(), expected_version=j.version))
    with pytest.raises(JourneyError) as e:
        svc.save(U, save_in("select", selection=selection(), expected_version=j.version))
    assert e.value.code == "invalid_input" and "reload" in e.value.message


def test_concurrent_accept_one_wins(journey_db):
    svc = JourneyService(journey_db)
    j = _propose(svc, _to_tracking(svc))
    prop = j.proposal.proposal
    a = save_in("accept", tracking=tracking(prop, date(2026, 4, 2)), as_of=date(2026, 4, 2),
                expected_version=j.version)
    first = svc.save(U, a)
    assert first.state == "tracking"
    with pytest.raises(JourneyError) as e:               # the second tab still holds the old version
        svc.save(U, a)
    assert e.value.code == "invalid_input"


# ── B1 restart ─────────────────────────────────────────────────────────────────

def test_restart_same_plan_is_refused(journey_db):
    svc = JourneyService(journey_db)
    svc.save(U, save_in("start", goal=goal_in(goal())))
    with pytest.raises(JourneyError) as e:
        svc.save(U, save_in("start", goal=goal_in(goal())))
    assert e.value.code == "invalid_input"
    older = goal(updated=PLAN_T0 - timedelta(days=1))
    with pytest.raises(JourneyError):
        svc.save(U, save_in("start", goal=goal_in(older)))


def test_restart_newer_plan_carries_reselect_count(journey_db):
    svc = JourneyService(journey_db)
    j = _propose(svc, _to_tracking(svc), on=date.today())
    old_id = j.journey_id
    newer = goal(updated=PLAN_T0 + timedelta(days=30), r=0.065)
    j2 = svc.save(U, save_in("start", goal=goal_in(newer), as_of=date.today()))
    assert j2.journey_id != old_id and j2.previous_journey_id == old_id
    assert j2.reselect_count == 1 and j2.reselect_year == date.today().year
    assert j2.state == "goal_loaded" and j2.goal_return == 0.065 and j2.reselections == []
    old = journey_db.get(UserJourneyModel, old_id)
    assert old.is_active is False and old.state == "closed"


def test_count_resets_only_on_new_year(journey_db):
    svc = JourneyService(journey_db)
    j = _propose(svc, _to_tracking(svc), on=date(2025, 11, 1))
    assert j.reselect_count == 1 and j.reselect_year == 2025
    same = svc.get_current(U, "europe", today=date(2025, 12, 31))
    assert same.reselect_count == 1
    nxt = svc.get_current(U, "europe", today=date(2026, 1, 2))
    assert nxt.reselect_count == 0 and nxt.reselect_year is None
    newer = goal(updated=PLAN_T0 + timedelta(days=30))
    j2 = svc.save(U, save_in("start", goal=goal_in(newer), as_of=date(2026, 1, 5)))
    assert j2.reselect_count == 0                     # carried only within the same year


def test_plan_is_newer_rule():
    t = PLAN_T0
    assert plan_is_newer(t, None) and plan_is_newer(t + timedelta(seconds=1), t)
    assert not plan_is_newer(t, t) and not plan_is_newer(None, t)
    assert plan_is_newer(t.replace(tzinfo=None) + timedelta(hours=1), t)   # naive = UTC


# ── N1 / rev 3 ─────────────────────────────────────────────────────────────────

def test_plan_year_start_not_moved_by_accept(journey_db):
    svc = JourneyService(journey_db)
    j = _propose(svc, _to_tracking(svc, entry=D1))
    acc = date(2026, 4, 2)
    j = svc.save(U, save_in("accept", tracking=tracking(j.proposal.proposal, acc), as_of=acc,
                            expected_version=j.version))
    assert j.plan_year_start == D1
    assert [(s.from_, s.to, s.cause) for s in j.segments] == [(D1, acc, "track"), (acc, None, "accept")]
    assert j.segments[1].holdings[0].instrument_id == "E3"
    assert j.tracking[0].entry_date == acc            # SL entry rebases; ytd does not
    assert j.target_return == 0.0913 and j.reselections[-1].event == "accepted"


def test_restart_carries_segments_no_gap(journey_db):
    svc = JourneyService(journey_db)
    today = date.today()
    entry = date(today.year, 1, 2) if today > date(today.year, 1, 2) else today
    j = _to_tracking(svc, entry=entry)
    newer = goal(updated=PLAN_T0 + timedelta(days=60))
    j2 = svc.save(U, save_in("start", goal=goal_in(newer), as_of=today))
    assert j2.plan_year_start == j.plan_year_start
    assert len(j2.segments) == 1 and j2.segments[0].to is None          # still held → still open
    sel = selection(holdings=[holding("E2", 100)])
    j2 = svc.save(U, save_in("select", selection=sel, as_of=today, expected_version=j2.version))
    j3 = svc.save(U, save_in("track", tracking=tracking(sel, today), as_of=today, expected_version=j2.version))
    assert j3.plan_year_start == j.plan_year_start
    assert j3.segments[0].to == today and j3.segments[1].from_ == today   # closed where the next opens


def test_year_reset_clips_segments(journey_db):
    svc = JourneyService(journey_db)
    j = _to_tracking(svc, entry=date(2025, 6, 2))
    assert j.plan_year_start == date(2025, 6, 2)
    cur = svc.get_current(U, "europe", today=date(2026, 2, 1))
    assert cur.plan_year_start == date(2026, 1, 1)
    assert len(cur.segments) == 1 and cur.segments[0].from_ == date(2026, 1, 1) and cur.segments[0].to is None


def test_clip_segments_drops_closed_before_s():
    segs = [{"from": "2025-03-01", "to": "2025-09-01", "holdings": [], "cause": "track"},
            {"from": "2025-09-01", "to": None, "holdings": [], "cause": "accept"}]
    out = clip_segments(segs, date(2026, 1, 1))
    assert out == [{"from": "2026-01-01", "to": None, "holdings": [], "cause": "accept"}]
