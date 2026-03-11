from __future__ import annotations

from pathlib import Path

from src.rl.stride_metrics import StrideMetricsLogger, aggregate_stride_summary


def test_stride_metrics_logger(tmp_path: Path) -> None:
    logger = StrideMetricsLogger(tmp_path)
    logger.record_episode(
        method="stride_gate_only",
        seed=0,
        episode=0,
        reward=5.0,
        success=True,
        steps=4,
        cost_ratio=0.5,
        override_stats={
            "override_rate": 0.25,
            "override_win_rate": 0.5,
            "override_regret_rate": 0.25,
            "harmful_fraction": 0.25,
            "beneficial_fraction": 0.5,
        },
        budgeted_success=1.0,
        action_entropy=0.6,
    )
    logger.record_override(
        method="stride_gate_only",
        seed=0,
        episode=0,
        step=1,
        teacher_macro="direct_solve",
        chosen_macro="research_context",
        reward=1.0,
        override=True,
        win=True,
        regret=False,
        reason="test",
    )
    logger.save()
    assert (tmp_path / "stride_metrics.csv").exists()
    assert (tmp_path / "stride_overrides.csv").exists()
    assert (tmp_path / "stride_seed_summary.csv").exists()
    assert (tmp_path / "stride_debug_log.md").exists()


def test_aggregate_stride_summary_handles_empty() -> None:
    summary = aggregate_stride_summary([])
    assert summary["success_rate"] == 0.0
