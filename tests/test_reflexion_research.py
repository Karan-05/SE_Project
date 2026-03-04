from __future__ import annotations

from src.research.reflexion import ReflexionConfig, run_reflexion_experiment


def test_reflexion_experiment_metrics() -> None:
    tasks = [
        {"id": "a", "complexity": 1.0},
        {"id": "b", "complexity": 2.0},
    ]
    metrics = run_reflexion_experiment(tasks, ReflexionConfig(enable_memory=True, enable_rl=True, enable_repair=True), seed=0)
    assert "pass_rate" in metrics
    assert "failure_taxonomy" in metrics
    assert metrics["memory_enabled"] is True
