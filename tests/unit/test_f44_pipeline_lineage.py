"""Jarvis consumes the models the DS pipeline builds, as they are built.

The pipeline (``/api/v1/pipeline`` -> ``ml_dispatch``) writes ``rita_ddqn_v2_<inst>_<run id>.zip`` into
``<model.path>/<INST>/`` and trains on ``trading_env_v2.temporal_split`` (70 / 15 / 15 by row count), so a
model's windows are not fixed dates.  Jarvis finds the newest such model, reproduces that split on the bars
that existed the day the model was trained, replays each model on its own windows, and selects on the
windows every sleeve shares.  An exact-name lineage (``f34p25``) still wins when its file exists.
"""
# ruff: noqa: F811 — pytest fixtures imported from a sibling module are redefined as test params
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

import rita.services.goal_selection_service as svc_mod
from rita.config import ModelLineage, get_settings
from rita.core.goal_model_runs import LineageSplit, common_split, fraction_split
from rita.core.trading_env_v2 import temporal_split
from rita.models.instrument import InstrumentModel
from rita.repositories.model_artifact import ModelArtifactRepository
from rita.repositories.model_run_cache import ModelRunCacheRepository
from rita.services.goal_selection_service import GoalSelectionError, GoalSelectionService

from .f44_p3_helpers import SPLIT, FakeArtifacts, PolicyModel, indicator_frame

# ── config ─────────────────────────────────────────────────────────────────────

def test_registered_lineages_are_the_exact_name_one_then_the_pipeline_one():
    lins = get_settings().goal_selection.model_lineages
    assert len(lins) >= 2
    # all lineages except the last are exact-name (dates split)
    for lin in lins[:-1]:
        assert lin.split_rule == "dates", f"lineage {lin.name!r} expected dates split"
    pipe = lins[-1]
    assert pipe.name == "pipeline_v2" and pipe.split_rule == "fractions"
    assert pipe.pattern == "rita_ddqn_v2_{inst}_*.zip" and (pipe.train_frac, pipe.val_frac) == (0.70, 0.15)
    assert pipe.train_end is None                                      # no fixed dates: per model


def test_a_dates_lineage_must_carry_its_dates():
    with pytest.raises(ValidationError):
        ModelLineage(name="x", pattern="p.zip")
    ModelLineage(name="x", pattern="p.zip", split_rule="fractions")    # fractions need none
    ModelLineage(name="x", pattern="p.zip", train_end=date(2022, 12, 31), val_start=date(2023, 1, 1),
                 val_end=date(2024, 12, 31), backtest_start=date(2025, 1, 1))


# ── the pipeline's split, reproduced ───────────────────────────────────────────

def _frame(n: int, start: str = "2015-01-01") -> pd.DataFrame:
    return pd.DataFrame({"x": range(n)}, index=pd.bdate_range(start, periods=n))


@pytest.mark.parametrize("n", [100, 997, 1000, 4107])
def test_fraction_split_is_exactly_the_pipelines_temporal_split(n):
    df = _frame(n)
    train, val, test = temporal_split(df)
    s = fraction_split(df.index, df.index[-1].date())
    assert (s.train_end, s.val_start, s.val_end, s.backtest_start) == (
        train.index[-1].date(), val.index[0].date(), val.index[-1].date(), test.index[0].date())


def test_bars_after_the_training_day_are_not_part_of_the_models_split():
    """The price history keeps growing after a model is trained: only the bars it saw count."""
    df = _frame(1500)
    trained_on = df.index[999].date()
    assert fraction_split(df.index, trained_on) == fraction_split(df.index[:1000], trained_on)
    assert fraction_split(df.index, df.index[-1].date()).train_end > fraction_split(df.index, trained_on).train_end


def test_margin_pushes_the_training_end_and_fit_start_later_only():
    df = _frame(1000)
    base = fraction_split(df.index, df.index[-1].date())
    safe = fraction_split(df.index, df.index[-1].date(), margin_bars=5)
    days = [ts.date() for ts in df.index]
    assert safe.train_end == days[days.index(base.train_end) + 5]
    assert safe.val_start == days[days.index(base.val_start) + 5]
    assert (safe.val_end, safe.backtest_start) == (base.val_end, base.backtest_start)   # the test window is untouched


@pytest.mark.parametrize("n,margin", [(1, 0), (3, 0), (100, 40)])    # no train bars / no fit window / margin eats the fit window
def test_too_few_bars_cannot_reproduce_a_split(n, margin):
    df = _frame(n)
    with pytest.raises(ValueError):
        fraction_split(df.index, df.index[-1].date(), margin_bars=margin)


def _split(tr, vs, ve, bs):
    return LineageSplit(date.fromisoformat(tr), date.fromisoformat(vs), date.fromisoformat(ve), date.fromisoformat(bs))


def test_common_split_is_the_windows_every_sleeve_is_out_of_sample_on():
    a = _split("2021-06-01", "2021-06-02", "2023-11-03", "2023-11-06")
    b = _split("2022-02-01", "2022-02-02", "2023-08-21", "2024-01-02")
    assert common_split([a, b]) == _split("2022-02-01", "2022-02-02", "2023-08-21", "2024-01-02")
    assert common_split([a]) == a and common_split([a, a]) == a              # identical splits are unchanged


def test_common_split_needs_overlapping_fit_windows():
    early = _split("2019-01-01", "2019-01-02", "2020-06-30", "2020-07-01")
    late = _split("2021-01-01", "2021-01-02", "2022-06-30", "2022-07-01")
    with pytest.raises(ValueError):
        common_split([early, late])
    with pytest.raises(ValueError):
        common_split([])


# ── the repository: newest pipeline model and the day it was trained ───────────

def _touch(path: Path, when: str) -> Path:
    path.write_bytes(b"zip")
    ts = datetime.fromisoformat(when).timestamp()
    os.utime(path, (ts, ts))
    return path


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "ASML").mkdir()
    return ModelArtifactRepository(tmp_path, tmp_path), tmp_path / "ASML"


def _lin(name):
    return next(lin for lin in get_settings().goal_selection.model_lineages if lin.name == name)


def test_find_takes_the_newest_pipeline_model(repo):
    r, folder = repo
    _touch(folder / "rita_ddqn_v2_asml_aaaa1111.zip", "2026-03-01")
    new = _touch(folder / "rita_ddqn_v2_asml_bbbb2222.zip", "2026-04-15")
    assert r.find("ASML", _lin("pipeline_v2")) == new


def test_find_leaves_the_exact_name_file_to_its_own_lineage(repo):
    r, folder = repo
    f34 = _touch(folder / "rita_ddqn_v2_asml_f34p25.zip", "2026-05-01")
    pipe = _touch(folder / "rita_ddqn_v2_asml_cccc3333.zip", "2026-02-01")        # older, still the pipeline's
    assert r.find("ASML", _lin("f34p25")) == f34
    assert r.find("ASML", _lin("pipeline_v2")) == pipe


def test_find_ignores_other_models_and_missing_folders(repo):
    r, folder = repo
    _touch(folder / "pipeline-14705f79_14705f79.zip", "2026-04-15")               # older pipeline naming (v1 env)
    _touch(folder / "rita_ddqn_asta_asml_dddd4444.zip", "2026-04-15")             # another engine
    assert r.find("ASML", _lin("pipeline_v2")) is None
    assert r.find("NIFTY", _lin("pipeline_v2")) is None and r.find("NIFTY", _lin("f34p25")) is None


def test_trained_on_reads_the_pipeline_run_row(repo):
    r, folder = repo
    model = _touch(folder / "rita_ddqn_v2_asml_bbbb2222.zip", "2026-11-08")       # file time is later (restored copy)
    (folder / "training_history.csv").write_text(
        "round,timestamp,source,notes\n"
        "1,2026-04-15 16:00:24,trained,run_id=bbbb2222\n"
        "2,2026-06-01 10:00:00,loaded_existing,run_id=bbbb2222\n"                 # a re-evaluation, not the training
        "3,2026-05-01 09:00:00,trained,run_id=eeee5555\n")
    assert r.trained_on("ASML", model) == date(2026, 4, 15)


@pytest.mark.parametrize("history", [None, "round,timestamp,notes\n1,2026-04-15 16:00:24,run_id=zzzz9999\n",
                                     "not,a,history\n1,2,3\n", "round,timestamp,notes\n1,garbage,run_id=bbbb2222\n"])
def test_trained_on_falls_back_to_the_file_time(repo, history):
    r, folder = repo
    model = _touch(folder / "rita_ddqn_v2_asml_bbbb2222.zip", "2026-04-20")
    if history is not None:
        (folder / "training_history.csv").write_text(history)
    assert r.trained_on("ASML", model) == date(2026, 4, 20)


def test_split_for_uses_fixed_dates_or_the_reproduced_split(repo):
    r, folder = repo
    model = _touch(folder / "rita_ddqn_v2_asml_bbbb2222.zip", "2026-04-15")
    (folder / "training_history.csv").write_text("round,timestamp,source,notes\n1,2026-04-15 16:00:24,trained,run_id=bbbb2222\n")
    idx = pd.bdate_range("2010-01-01", "2026-11-06")
    f34 = r.split_for(_lin("f34p25"), "ASML", model, idx)
    assert f34 == LineageSplit(date(2022, 12, 31), date(2023, 1, 1), date(2024, 12, 31), date(2025, 1, 1))
    pipe = r.split_for(_lin("pipeline_v2"), "ASML", model, idx)
    assert pipe == fraction_split(idx, date(2026, 4, 15), 0.70, 0.15, 5)      # the history row's day, not the file's
    assert pipe != f34 and pipe.val_end > pipe.val_start and pipe.backtest_start > pipe.val_end


# ── the service: each model on its own windows ─────────────────────────────────

END = "2026-06-30"


def _add(db, inst, cc="NL"):
    db.add(InstrumentModel(instrument_id=inst, name=inst, exchange="X", country_code=cc, is_available=True,
                           created_at=datetime.now(timezone.utc)))


@dataclass
class LineageArtifacts(FakeArtifacts):
    """A fake repository that knows which lineage each instrument's model belongs to."""

    owner: dict[str, str] = field(default_factory=dict)             # inst → "f34p25" | "pipeline_v2" | "both"
    splits: dict[str, LineageSplit | Exception] = field(default_factory=dict)

    def find(self, instrument, lineage):
        who = self.owner.get(instrument)
        if instrument not in self.models or who is None:
            return None
        return Path(f"/fake/{instrument}.zip") if who in (lineage.name, "both") else None

    def split_for(self, lineage, instrument, model_path, index):
        s = self.splits.get(instrument, self.split)
        if isinstance(s, Exception):
            raise s
        return s


@pytest.fixture(autouse=True)
def _fresh_memo():
    svc_mod.clear_memo()
    yield
    svc_mod.clear_memo()


@pytest.fixture
def world(db_session, tmp_path):
    for inst in ("E1", "E2", "E3", "E4"):
        _add(db_session, inst)
    db_session.commit()
    fa = LineageArtifacts()
    # calm after the earliest training end used below, so no model trips the data-integrity rule
    fa.frames = {i: indicator_frame(seed=n, end=END, drift=0.0003 + 0.0002 * n, calm_after=EARLY.train_end)
                 for n, i in enumerate(("E1", "E2", "E3", "E4"))}
    fa.models = {i: PolicyModel() for i in ("E1", "E2", "E3", "E4")}
    cache = ModelRunCacheRepository(tmp_path / "cache")
    return db_session, fa, cache


def _svc(world):
    db, fa, cache = world
    return GoalSelectionService(db, artifacts=fa, cache=cache)


EARLY = _split("2022-06-30", "2022-07-01", "2024-03-29", "2024-04-01")
LATE = _split("2022-12-30", "2023-01-02", "2024-12-31", "2025-01-02")


def test_a_pipeline_only_instrument_gets_a_sleeve(world):
    _, fa, _ = world
    fa.owner = {"E1": "pipeline_v2", "E2": "pipeline_v2"}
    fa.splits = {"E1": EARLY, "E2": LATE}
    lr = _svc(world).location_runs("europe")
    assert set(lr.runs) == {"E1", "E2"} and lr.lineage_name == "pipeline_v2"
    assert lr.runs["E1"]["medium"].lineage == "pipeline_v2"


def test_the_exact_name_lineage_wins_when_both_files_exist(world):
    _, fa, _ = world
    fa.owner = {"E1": "both", "E2": "pipeline_v2"}
    lr = _svc(world).location_runs("europe")
    assert lr.runs["E1"]["medium"].lineage == "f34p25" and lr.runs["E2"]["medium"].lineage == "pipeline_v2"
    assert lr.lineage_name == "f34p25+pipeline_v2"


def test_each_model_is_replayed_on_its_own_windows_and_selected_on_the_common_one(world):
    _, fa, _ = world
    fa.owner = {"E1": "pipeline_v2", "E2": "pipeline_v2"}
    fa.splits = {"E1": EARLY, "E2": LATE}
    s = _svc(world)
    lr = s.location_runs("europe")
    assert lr.runs["E1"]["medium"].window_start > EARLY.train_end                    # its own training end
    assert lr.runs["E1"]["medium"].window_start <= LATE.train_end
    assert lr.runs["E2"]["medium"].window_start > LATE.train_end
    assert lr.split == common_split([EARLY, LATE])                                   # the selection window
    assert s.instrument_runs("E1").split == EARLY and s.instrument_runs("E2").split == LATE   # sleeve trace uses each


def test_identical_splits_leave_the_selection_window_as_before(world):
    _, fa, _ = world
    fa.owner = {"E1": "f34p25", "E2": "f34p25"}
    assert _svc(world).location_runs("europe").split == SPLIT


def test_no_model_names_every_registered_lineage(world):
    _, fa, _ = world
    fa.owner = {"E1": "f34p25"}
    out = _svc(world).location_runs("europe")
    gone = {e.instrument_id: e for e in out.excluded}["E3"]
    assert gone.reason == "no_model" and "f34p25" in gone.detail and "pipeline_v2" in gone.detail


def test_a_split_that_cannot_be_reproduced_excludes_the_instrument_with_the_reason(world):
    _, fa, _ = world
    fa.owner = {"E1": "pipeline_v2", "E2": "pipeline_v2"}
    fa.splits = {"E1": EARLY, "E2": ValueError("only 12 bars up to 2026-04-15: cannot reproduce the model's windows")}
    out = _svc(world).location_runs("europe")
    bad = {e.instrument_id: e for e in out.excluded}["E2"]
    assert bad.reason == "no_data" and "cannot reproduce" in bad.detail and set(out.runs) == {"E1"}
    assert _svc(world).instrument_runs("E2").excluded.reason == "no_data"


def test_models_whose_fit_windows_never_overlap_are_unavailable_not_guessed(world):
    _, fa, _ = world
    fa.owner = {"E1": "pipeline_v2", "E2": "pipeline_v2"}
    # E1 was trained on a short history (fit window 2021 H2); E2 on a long one (fit window 2023-2024): no shared day
    fa.splits = {"E1": _split("2021-06-30", "2021-07-01", "2021-12-31", "2022-01-03"), "E2": LATE}
    fa.frames["E1"] = indicator_frame(seed=0, start="2019-01-01", end=END, calm_after=date(2021, 6, 30))   # a long pre-train history
    with pytest.raises(GoalSelectionError) as e:
        _svc(world).location_runs("europe")
    assert e.value.code == "unavailable" and "do not overlap" in e.value.message


def test_a_retrained_model_is_replayed_again_not_served_from_the_old_windows(world):
    """The cache key carries the split, so a new pipeline run (new file, new training day) never reuses old replays."""
    _, fa, cache = world
    fa.owner = {"E1": "pipeline_v2"}
    fa.splits = {"E1": EARLY}
    a = _svc(world).location_runs("europe").runs["E1"]["medium"]
    fa.splits = {"E1": LATE}                                  # a newer run of the pipeline: a later training end
    svc_mod.clear_memo()
    b = _svc(world).location_runs("europe").runs["E1"]["medium"]
    assert EARLY.train_end < a.window_start <= LATE.train_end < b.window_start
