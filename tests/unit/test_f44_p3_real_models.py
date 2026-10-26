"""F44 P3 — real f34p25 models (slow; skipped when the zips are not on this machine).

- R2-5: the AEX f34p25 replay on the lineage val years with ``run_episode_v2`` (default path)
  reproduces the training_history val_sharpe 0.499 / val_mdd −7.17 % — model, env config and
  data resolve to what was trained (run after step 0; AEX is not rewritten).
- Europe preset goal (7.675 %) on the real models: runtime (cold / warm) and the verdict.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

import rita.services.goal_selection_service as svc_mod
from rita.config import get_settings
from rita.core.instrument_config import load_instrument_env_config
from rita.core.trading_env_v2 import run_episode_v2
from rita.models.instrument import InstrumentModel
from rita.repositories.model_artifact import ModelArtifactRepository
from rita.repositories.model_run_cache import ModelRunCacheRepository
from rita.services.goal_selection_service import GoalSelectionService

EUROPE = {"AEX": "NL", "ASML": "NL", "ASRNL": "NL", "ATO": "FR"}
_MODELS = Path(get_settings().model.path)
_HAVE = all((_MODELS / i / f"rita_ddqn_v2_{i.lower()}_f34p25.zip").is_file() for i in EUROPE)

pytestmark = [pytest.mark.slow,
              pytest.mark.skipif(not _HAVE, reason="f34p25 model zips not present")]


def test_aex_val_replay_reproduces_training_history():
    repo = ModelArtifactRepository.from_settings()
    lineage = get_settings().goal_selection.model_lineages[0]
    split = repo.lineage_split(lineage)
    model = repo.load(repo.find("AEX", lineage))
    df = repo.load_indicator_frame("AEX").df
    val = df.loc[str(split.val_start):str(split.val_end)]
    perf = run_episode_v2(model, val, "medium", load_instrument_env_config("AEX"))["performance"]
    assert perf["sharpe_ratio"] == pytest.approx(0.499, abs=0.01)
    assert perf["max_drawdown_pct"] == pytest.approx(-7.17, abs=0.1)


def test_europe_preset_goal_on_real_models(db_session, tmp_path, capsys):
    for inst, cc in EUROPE.items():
        db_session.add(InstrumentModel(instrument_id=inst, name=inst, exchange="X",
                                       country_code=cc, is_available=True,
                                       created_at=datetime.now(timezone.utc)))
    db_session.commit()
    cache = ModelRunCacheRepository(tmp_path / "cache")
    svc_mod.clear_memo()
    t0 = time.perf_counter()
    out = GoalSelectionService(db_session, cache=cache).select_for_goal("europe", 0.07675)
    cold = time.perf_counter() - t0
    svc_mod.clear_memo()
    t0 = time.perf_counter()
    again = GoalSelectionService(db_session, cache=cache).select_for_goal("europe", 0.07675)
    warm = time.perf_counter() - t0
    svc_mod.clear_memo()

    assert again == out                                         # deterministic, disk cache
    assert {e.instrument_id: e.reason for e in out.excluded}.get("ATO") in (
        "retrain_needed", "data_integrity")
    assert out.cap_fit > 0 and out.as_of >= out.test_window.start
    if out.holdings:
        assert sum(h.allocation_pct for h in out.holdings) == 100
        assert out.fit_return >= 0.07675
    with capsys.disabled():
        print(f"\n[europe real-model] cold={cold:.2f}s warm={warm:.2f}s meets_goal={out.meets_goal} "
              f"tau={out.tolerance} holdings={[(h.instrument_id, h.allocation_pct, h.model_action) for h in out.holdings]} "
              f"fit={out.fit_return} test={out.test_return} test_mdd={out.test_mdd} "
              f"tolerance_sensitive={out.tolerance_sensitive} cap_fit={out.cap_fit} "
              f"cap_test={out.cap_test} excluded={[(e.instrument_id, e.reason) for e in out.excluded]}")
