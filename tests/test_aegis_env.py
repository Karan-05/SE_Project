from __future__ import annotations

import numpy as np

from pathlib import Path

from src.rl.aegis_env import AegisEnvConfig, AegisWorkflowEnv, REDUCED_ACTIONS
from src.rl.aegis_state import AegisMacroOption


def test_aegis_env_runs_option_rollout() -> None:
    env = AegisWorkflowEnv(AegisEnvConfig())
    obs, info = env.reset()
    assert obs.shape == env.observation_space.shape
    mask = env.manager_action_mask()
    assert mask.shape[0] == env.action_space.n
    action = int(np.argmax(mask))
    next_obs, reward, done, truncated, info = env.step(action)
    assert next_obs.shape == env.observation_space.shape
    assert isinstance(reward, float)
    assert "manager_trace" in info
    assert "constraint_snapshot" in info
    assert "macro_option" in info
    assert "manager_option_histogram" in info
    assert "calibration_metrics" in info
    hist = info["manager_option_histogram"]
    assert len(hist) == env.action_space.n


def test_option_mask_respects_stagnation_and_submit_threshold() -> None:
    config = AegisEnvConfig()
    env = AegisWorkflowEnv(config)
    obs, info = env.reset()
    # force stagnation to exceed patience
    env._stagnation_steps = env.config.stagnation_patience  # type: ignore[attr-defined]
    belief = env._last_manager_observation.belief_state  # type: ignore[attr-defined]
    belief.success_probability = 0.2  # force low confidence submit
    belief.uncertainty_score = 0.5
    mask = env._compute_option_mask(belief, env.last_info)  # type: ignore[attr-defined]
    idx_map = env.macro_indices  # type: ignore[attr-defined]
    direct_idx = idx_map.get(AegisMacroOption.DIRECT_SOLVE)
    submit_idx = idx_map.get(AegisMacroOption.SUBMIT)
    assert direct_idx is not None
    assert submit_idx is not None
    assert mask[direct_idx] == 0.0
    assert mask[submit_idx] == 0.0


def test_reduced_action_space_config() -> None:
    env = AegisWorkflowEnv(AegisEnvConfig(use_reduced_action_space=True))
    assert env.action_space.n == len(env.macro_actions)
    assert set(env.macro_actions).issubset(set(REDUCED_ACTIONS))


def test_reward_diagnostics_written(tmp_path) -> None:
    config = AegisEnvConfig(reward_log_path=tmp_path / "diag.jsonl")
    env = AegisWorkflowEnv(config)
    obs, info = env.reset()
    action = env.macro_indices.get(AegisMacroOption.DIRECT_SOLVE, 0)
    env.step(action)
    log_path = tmp_path / "diag.jsonl"
    assert log_path.exists()
    assert log_path.read_text().strip()
