from __future__ import annotations

import numpy as np

import numpy as np

from src.rl.aegis_belief import BeliefEncoder, BeliefEncoderConfig
from src.rl.aegis_graph_memory import GraphSummary


def test_belief_encoder_updates_calibration() -> None:
    encoder = BeliefEncoder(observation_dim=25, config=BeliefEncoderConfig(feature_dim=16))
    obs = np.zeros(25, dtype=np.float32)
    info = {"uncertainty_summary": [0.1, 0.1]}
    graph = GraphSummary(visit_ratio=0.2, unresolved_dependencies=1, frontier_size=2, evidence_diversity=0.3, locality_score=0.4, coverage_entropy=0.5)
    budget = np.ones(8, dtype=np.float32) * 0.5
    belief = encoder.encode(obs, info, graph, budget, option_history=[])
    metrics_before = encoder.calibration.miscalibration()
    updated = encoder.update_calibration(outcome=True, realized_cost=0.3, belief=belief)
    assert "brier" in metrics_before
    assert "brier" in updated


def test_belief_encoder_distinguishes_states() -> None:
    encoder = BeliefEncoder(observation_dim=4, config=BeliefEncoderConfig(feature_dim=8))
    encoder.success_weights = np.zeros_like(encoder.success_weights)
    encoder.success_weights[0] = 5.0
    graph = GraphSummary(visit_ratio=0.2, unresolved_dependencies=1, frontier_size=1, evidence_diversity=0.3, locality_score=0.4, coverage_entropy=0.5)
    budget = np.ones(8, dtype=np.float32) * 0.5
    obs_easy = np.array([1.0, 1.0, 1.0, 1.0], dtype=np.float32)
    obs_hard = -np.ones(4, dtype=np.float32)
    info = {"uncertainty_summary": [0.1]}
    belief_easy = encoder.encode(obs_easy, info, graph, budget, option_history=[])
    belief_hard = encoder.encode(obs_hard, info, graph, budget, option_history=[])
    assert belief_easy.success_probability > belief_hard.success_probability
