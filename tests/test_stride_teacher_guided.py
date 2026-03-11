from __future__ import annotations

import numpy as np

from src.rl.aegis_env import AegisEnvConfig
from src.rl.stride_agents import StrideGate, StrideGateConfig, build_stride_features
from src.rl.stride_dataset import StrideDatasetConfig, build_stride_teacher_dataset, load_stride_dataset


def test_stride_dataset_collects_states(tmp_path) -> None:
    env_config = AegisEnvConfig(use_reduced_action_space=True, enable_hierarchy=False)
    dataset_config = StrideDatasetConfig(episodes=1)
    path, summary = build_stride_teacher_dataset(tmp_path, env_config, dataset_config=dataset_config)
    rows = load_stride_dataset(path)
    assert summary.total_steps == len(rows)
    assert any(row.get("override_label", 0) in (0, 1) for row in rows)


def test_stride_gate_updates() -> None:
    observation = np.zeros(10, dtype=np.float32)
    features = build_stride_features(
        observation,
        teacher_index=0,
        action_dim=3,
        manager_features={"success_probability": 0.1, "uncertainty": 0.8, "expected_cost": 0.5},
        extra_features=[0.2, 0.0],
    )
    gate = StrideGate(len(features), config=StrideGateConfig(hidden_dim=8, lr=0.1))
    before = gate.predict(features)
    gate.update(features, 1.0, weight=2.0)
    after = gate.predict(features)
    assert after > before
