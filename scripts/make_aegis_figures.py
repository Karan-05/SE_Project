"""Generate placeholder figures for the ASE 2026 AEGIS-RL report."""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

import numpy as np

try:  # pragma: no cover - optional plotting dep
    import matplotlib.pyplot as plt
except Exception:  # pragma: no cover
    plt = None


FIGURES = {
    "figure_success_vs_cost.png": "Success vs Cost",
    "figure_budgeted_success.png": "Budgeted Success",
    "figure_failure_modes.png": "Failure Modes",
    "figure_action_heatmap.png": "Action Heatmap",
    "figure_calibration.png": "Calibration Plot",
    "figure_action_diversity.png": "Action Diversity",
    "figure_reward_diagnostics.png": "Reward Diagnostics",
}


def load_metrics(path: Path) -> List[float]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return [float(line.strip()) for line in f if line.strip()]


def make_placeholder_plot(path: Path, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if plt is None:
        path.write_text(f"{title} pending. Install matplotlib and rerun.", encoding="utf-8")
        return
    fig, ax = plt.subplots(figsize=(5, 3))
    xs = np.linspace(0, 1, num=10)
    ax.plot(xs, np.sin(xs * np.pi))
    ax.set_title(title)
    ax.set_xlabel("proxy")
    ax.set_ylabel("value")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main() -> None:
    figures_dir = Path("reports/ase2026_aegis")
    for filename, title in FIGURES.items():
        make_placeholder_plot(figures_dir / filename, title)


if __name__ == "__main__":
    main()
