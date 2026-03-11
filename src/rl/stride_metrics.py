"""Metrics helpers for STRIDE."""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List

import numpy as np


@dataclass
class OverrideEvent:
    method: str
    seed: int
    episode: int
    step: int
    teacher_macro: str
    chosen_macro: str
    reward: float
    override: int
    win: int
    regret: int
    reason: str

    def as_row(self) -> List[object]:
        return [
            self.method,
            self.seed,
            self.episode,
            self.step,
            self.teacher_macro,
            self.chosen_macro,
            self.reward,
            self.override,
            self.win,
            self.regret,
            self.reason,
        ]


class StrideMetricsLogger:
    """Collects override-aware metrics and writes reports."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path("results/aegis_rl")
        self.root.mkdir(parents=True, exist_ok=True)
        self.metrics: List[Dict[str, float]] = []
        self.override_events: List[OverrideEvent] = []
        self.seed_records: Dict[int, List[Dict[str, float]]] = defaultdict(list)
        self.debug_lines: List[str] = []

    def record_episode(
        self,
        method: str,
        seed: int,
        episode: int,
        reward: float,
        success: bool,
        steps: int,
        cost_ratio: float,
        override_stats: Dict[str, float],
        budgeted_success: float,
        action_entropy: float,
    ) -> None:
        row = {
            "method": method,
            "seed": seed,
            "episode": episode,
            "reward": reward,
            "success": float(success),
            "steps": steps,
            "cost_ratio": cost_ratio,
            "budgeted_success": budgeted_success,
            "override_rate": override_stats.get("override_rate", 0.0),
            "override_win_rate": override_stats.get("override_win_rate", 0.0),
            "override_regret_rate": override_stats.get("override_regret_rate", 0.0),
            "harmful_fraction": override_stats.get("harmful_fraction", 0.0),
            "beneficial_fraction": override_stats.get("beneficial_fraction", 0.0),
            "action_entropy": action_entropy,
        }
        self.metrics.append(row)
        self.seed_records[seed].append(row)
        self.debug_lines.append(
            f"[seed={seed} ep={episode}] reward={reward:.2f} success={int(success)} "
            f"override={row['override_rate']:.2f} win={row['override_win_rate']:.2f} regret={row['override_regret_rate']:.2f}"
        )

    def record_override(
        self,
        method: str,
        seed: int,
        episode: int,
        step: int,
        teacher_macro: str,
        chosen_macro: str,
        reward: float,
        override: bool,
        win: bool,
        regret: bool,
        reason: str,
    ) -> None:
        event = OverrideEvent(
            method=method,
            seed=seed,
            episode=episode,
            step=step,
            teacher_macro=teacher_macro,
            chosen_macro=chosen_macro,
            reward=float(reward),
            override=int(override),
            win=int(win),
            regret=int(regret),
            reason=reason,
        )
        self.override_events.append(event)

    def _metrics_path(self) -> Path:
        return self.root / "stride_metrics.csv"

    def _overrides_path(self) -> Path:
        return self.root / "stride_overrides.csv"

    def _seed_summary_path(self) -> Path:
        return self.root / "stride_seed_summary.csv"

    def _debug_path(self) -> Path:
        return self.root / "stride_debug_log.md"

    def save(self) -> None:
        if self.metrics:
            with self._metrics_path().open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(self.metrics[0].keys()))
                writer.writeheader()
                for row in self.metrics:
                    writer.writerow(row)
        if self.override_events:
            with self._overrides_path().open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(
                    ["method", "seed", "episode", "step", "teacher_macro", "chosen_macro", "reward", "override", "win", "regret", "reason"]
                )
                for event in self.override_events:
                    writer.writerow(event.as_row())
        if self.seed_records:
            rows: List[Dict[str, float]] = []
            for seed, episodes in self.seed_records.items():
                agg = aggregate_stride_summary(episodes)
                agg["seed"] = seed
                rows.append(agg)
            with self._seed_summary_path().open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                for row in rows:
                    writer.writerow(row)
        if self.debug_lines:
            self._debug_path().write_text("\n".join(self.debug_lines), encoding="utf-8")


def aggregate_stride_summary(metrics: List[Dict[str, float]]) -> Dict[str, float]:
    """Aggregate basic metrics with override-aware statistics."""
    if not metrics:
        return {
            "success_rate": 0.0,
            "avg_reward": 0.0,
            "avg_cost": 0.0,
            "avg_steps": 0.0,
            "override_rate": 0.0,
            "override_win_rate": 0.0,
            "override_regret_rate": 0.0,
            "harmful_fraction": 0.0,
            "beneficial_fraction": 0.0,
            "budgeted_success": 0.0,
            "action_entropy": 0.0,
        }
    success_rate = float(np.mean([row["success"] for row in metrics]))
    avg_reward = float(np.mean([row["reward"] for row in metrics]))
    avg_steps = float(np.mean([row["steps"] for row in metrics]))
    avg_cost = float(np.mean([row["cost_ratio"] for row in metrics]))
    budgeted_success = float(np.mean([row.get("budgeted_success", 0.0) for row in metrics]))
    override_rate = float(np.mean([row.get("override_rate", 0.0) for row in metrics]))
    override_win = float(np.mean([row.get("override_win_rate", 0.0) for row in metrics]))
    override_regret = float(np.mean([row.get("override_regret_rate", 0.0) for row in metrics]))
    harmful = float(np.mean([row.get("harmful_fraction", 0.0) for row in metrics]))
    beneficial = float(np.mean([row.get("beneficial_fraction", 0.0) for row in metrics]))
    action_entropy = float(np.mean([row.get("action_entropy", 0.0) for row in metrics]))
    return {
        "success_rate": success_rate,
        "avg_reward": avg_reward,
        "avg_cost": avg_cost,
        "avg_steps": avg_steps,
        "override_rate": override_rate,
        "override_win_rate": override_win,
        "override_regret_rate": override_regret,
        "harmful_fraction": harmful,
        "beneficial_fraction": beneficial,
        "budgeted_success": budgeted_success,
        "action_entropy": action_entropy,
    }


def summarize_variants(
    metrics_by_method: Dict[str, List[Dict[str, float]]],
    output_path: Path,
) -> None:
    rows = []
    for method, rows_list in metrics_by_method.items():
        summary = aggregate_stride_summary(rows_list)
        summary["method"] = method
        rows.append(summary)
    if not rows:
        return
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_json_summary(metrics: Iterable[Dict[str, float]], path: Path) -> None:
    summary = aggregate_stride_summary(list(metrics))
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
