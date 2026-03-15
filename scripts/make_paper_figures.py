#!/usr/bin/env python3
"""Generate CGCS figures for the ASE paper."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import matplotlib.pyplot as plt

from src.config import PathConfig


def _load_records(path: Path) -> List[Dict[str, object]]:
    if not path.exists():
        return []
    records: List[Dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def _average_pass_rate(records: List[Dict[str, object]]) -> float:
    if not records:
        return 0.0
    total = 0.0
    for record in records:
        metrics = record.get("outcome_metrics", {}) or {}
        total += float(metrics.get("pass_rate") or 0.0)
    return total / len(records)


def build_figure(dataset_dir: Path, output_path: Path) -> Path:
    splits = ("train", "dev", "test")
    values = []
    for split in splits:
        records = _load_records(dataset_dir / f"{split}.jsonl")
        values.append(_average_pass_rate(records))
    fig, ax = plt.subplots(figsize=(6, 4))
    bars = ax.bar(splits, values, color=["#4e79a7", "#f28e2b", "#e15759"])
    ax.set_ylim(0, 1)
    ax.set_ylabel("Average pass rate")
    ax.set_title("CGCS clause discharge success by split")
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.01, f"{value:.2f}", ha="center", va="bottom")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)
    return output_path


def main() -> None:  # pragma: no cover
    dataset_dir = Path("data") / "cgcs"
    output_path = PathConfig().reports_root / "ase2026_aegis" / "figure_cgcs_pass_rate.png"
    build_figure(dataset_dir, output_path)
    print(f"Wrote CGCS figure to {output_path}")


if __name__ == "__main__":
    main()
