from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.benchmarks.toh import env as toh_env
from src.benchmarks.toh import run as toh_run


def test_optimal_moves_formula():
    assert toh_env.optimal_moves(0) == 0
    assert toh_env.optimal_moves(1) == 1
    assert toh_env.optimal_moves(4) == (2 ** 4) - 1


def test_illegal_move_raises():
    env = toh_env.TowerOfHanoiEnv(n_disks=3)
    assert env.is_legal((0, 1))
    with pytest.raises(ValueError):
        env.apply_move((1, 0))  # peg 1 empty → illegal


def test_full_decomposition_solves_small_instance():
    metrics = toh_run.run_episode(
        "full_decomposition",
        n_disks=4,
        seed=0,
        token_budget=None,
        max_steps=100,
    )
    assert metrics["success"] == 1
    assert metrics["moves_taken"] == metrics["optimal_moves"]
    assert metrics["token_estimate"] > 0


def test_select_then_decompose_is_deterministic():
    metric_a = toh_run.run_episode(
        "select_then_decompose",
        n_disks=5,
        seed=42,
        token_budget=120,
        max_steps=400,
    )
    metric_b = toh_run.run_episode(
        "select_then_decompose",
        n_disks=5,
        seed=42,
        token_budget=120,
        max_steps=400,
    )
    for key in ["n_disks", "strategy", "moves_taken", "optimal_moves", "token_estimate", "success"]:
        assert metric_a[key] == metric_b[key]


def test_run_benchmark_outputs(tmp_path: Path):
    out_dir = tmp_path / "toh"
    runs, summary = toh_run.run_benchmark(
        out_dir,
        seeds=[0],
        min_disks=4,
        max_disks=4,
        strategies=["full_decomposition", "select_then_decompose"],
        token_budget=150,
        max_steps_multiplier=3.0,
    )
    assert (out_dir / "tower_of_hanoi_runs.csv").exists()
    assert (out_dir / "tower_of_hanoi_summary.csv").exists()
    assert (out_dir / "table_toh.tex").exists()
    assert isinstance(runs, pd.DataFrame)
    assert isinstance(summary, pd.DataFrame)
