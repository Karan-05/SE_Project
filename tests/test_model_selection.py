from __future__ import annotations

from pathlib import Path

from experiments.run_aegis_rl import _write_model_selection_decision, _write_final_summary


def _sample_summaries():
    return [
        {"method": "aegis_full", "success_rate": 0.5, "avg_reward": 1.0, "avg_steps": 6.0, "avg_tokens": 100.0, "avg_constraint": 0.1},
        {"method": "aegis_no_graph", "success_rate": 0.45, "avg_reward": 0.0, "avg_steps": 5.5, "avg_tokens": 95.0, "avg_constraint": 0.1},
        {"method": "baseline", "success_rate": 0.3, "avg_reward": -1.0, "avg_steps": 4.0, "avg_tokens": 80.0, "avg_constraint": 0.0},
    ]


def test_model_selection_file_created(tmp_path: Path) -> None:
    path = tmp_path / "decision.md"
    _write_model_selection_decision(_sample_summaries(), path)
    assert path.exists()
    assert "headline method" in path.read_text().lower()


def test_final_summary_created(tmp_path: Path) -> None:
    path = tmp_path / "final.md"
    _write_final_summary(_sample_summaries(), path)
    assert path.exists()
    assert "Top Methods".lower() in path.read_text().lower()
