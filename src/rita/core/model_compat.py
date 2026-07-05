"""RITA Core — cross-version DQN model loading.

Model zips under ``models/`` may be trained on a machine with newer libraries
than the serving venv. Currently: training on Windows / Python 3.12 / numpy
2.4 / SB3 2.7 / gymnasium 1.2 vs. serving on numpy 1.26 / SB3 2.4 /
gymnasium 1.0 (numpy cannot be upgraded locally — torch 2.2.2 pins numpy<2).

Three version skews break a plain ``DQN.load`` on such zips:

1. numpy 2.x pickles reference ``numpy._core.numeric`` — numpy 1.26 ships only
   a partial ``numpy._core`` stub without it.
2. numpy 2.x pickles pass the BitGenerator *class* to
   ``numpy.random._pickle.__bit_generator_ctor``; numpy 1.x expects its name.
3. gymnasium 1.2 space pickles and SB3 2.7 schedule classes
   (``FloatSchedule``/``LinearSchedule``) do not exist locally, so
   ``observation_space``/``action_space``/schedules fail to deserialize.

``load_dqn_compat`` handles all three: it installs idempotent pickle shims for
(1) and (2), tries a plain load, and on failure retries with SB3's
``custom_objects`` escape hatch — rebuilding the spaces from the saved q-net
weight shapes (obs dim = first-layer input, action dim = last-layer output)
and substituting constant schedules, which inference never consults.
"""

from __future__ import annotations

import importlib
import io
import sys
import zipfile

import numpy as np
import structlog
from gymnasium import spaces
from stable_baselines3 import DQN

logger = structlog.get_logger(__name__)

# numpy.core submodules missing from numpy 1.26's numpy._core stub that
# numpy 2.x pickles are known to reference.
_NUMPY_CORE_ALIASES = (
    "numeric",
    "fromnumeric",
    "shape_base",
    "function_base",
    "getlimits",
    "einsumfunc",
    "numerictypes",
)

_shims_installed = False


def ensure_numpy2_pickle_compat() -> None:
    """Install shims so pickles written under numpy 2.x load under numpy 1.x.

    Idempotent and a no-op on environments where numpy already resolves the
    referenced modules (e.g. after a future numpy>=2 upgrade).
    """
    global _shims_installed
    if _shims_installed:
        return

    for sub in _NUMPY_CORE_ALIASES:
        alias = f"numpy._core.{sub}"
        if alias in sys.modules:
            continue
        try:
            importlib.import_module(alias)
        except ImportError:
            try:
                sys.modules[alias] = importlib.import_module(f"numpy.core.{sub}")
            except ImportError:
                continue

    nrp = importlib.import_module("numpy.random._pickle")
    original_ctor = nrp.__bit_generator_ctor

    def _compat_bit_generator_ctor(bit_generator="MT19937"):
        if isinstance(bit_generator, type):
            bit_generator = bit_generator.__name__
        return original_ctor(bit_generator)

    nrp.__bit_generator_ctor = _compat_bit_generator_ctor
    _shims_installed = True


def _constant_lr_schedule(_progress: float) -> float:
    return 1e-4


def _constant_exploration_schedule(_progress: float) -> float:
    return 0.05


def _spaces_from_qnet(model_path: str) -> tuple[spaces.Box, spaces.Discrete]:
    """Rebuild obs/action spaces from the q-net weight shapes in the zip."""
    import torch

    with zipfile.ZipFile(model_path) as zf:
        state = torch.load(
            io.BytesIO(zf.read("policy.pth")), map_location="cpu", weights_only=False
        )
    weight_keys = sorted(
        (k for k in state if k.startswith("q_net.q_net.") and k.endswith(".weight")),
        key=lambda k: int(k.split(".")[2]),
    )
    if not weight_keys:
        raise ValueError(f"No q-net linear weights found in {model_path}")
    n_obs = int(state[weight_keys[0]].shape[1])
    n_actions = int(state[weight_keys[-1]].shape[0])
    # Bounds must match RIIATradingEnv / RIIATradingEnvV2, which both clip
    # observations to [-3, 3] float32.
    obs_space = spaces.Box(low=-3.0, high=3.0, shape=(n_obs,), dtype=np.float32)
    return obs_space, spaces.Discrete(n_actions)


def load_dqn_compat(model_path: str) -> DQN:
    """Load a DQN zip, tolerating models saved under newer library versions."""
    ensure_numpy2_pickle_compat()
    try:
        return DQN.load(model_path)
    except Exception as exc:  # noqa: BLE001 — retry any deserialization failure
        logger.warning(
            "model_compat.plain_load_failed",
            model_path=model_path,
            error=str(exc),
        )
    obs_space, action_space = _spaces_from_qnet(model_path)
    model = DQN.load(
        model_path,
        custom_objects={
            "observation_space": obs_space,
            "action_space": action_space,
            "lr_schedule": _constant_lr_schedule,
            "exploration_schedule": _constant_exploration_schedule,
        },
    )
    logger.info(
        "model_compat.custom_objects_load",
        model_path=model_path,
        n_obs=obs_space.shape[0],
        n_actions=int(action_space.n),
    )
    return model
