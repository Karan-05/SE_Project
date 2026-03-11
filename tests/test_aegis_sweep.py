from __future__ import annotations

from pathlib import Path

from experiments.run_aegis_sweep import run_sweep


class Args:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.episodes = 1
        self.lightweight = True
        self.curriculum = False
        self.max_configs = 1


def test_sweep_runner_writes_outputs(tmp_path: Path) -> None:
    args = Args(tmp_path)
    run_sweep(args)
    sweep_dir = tmp_path / "sweeps"
    assert (sweep_dir / "sweep_results.csv").exists()
    assert (sweep_dir / "top_configs.csv").exists()
