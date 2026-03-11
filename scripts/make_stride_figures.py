"""Create STRIDE diagnostic figures."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, List

import os

if os.environ.get("STRIDE_FIG_FORCE_PLACEHOLDER") == "1":
    plt = None
else:
    try:  # pragma: no cover - optional dependency
        import matplotlib.pyplot as plt
    except Exception:  # pragma: no cover - fallback if matplotlib unavailable
        plt = None

from PIL import Image, ImageDraw, ImageFont


def _load_rows(path: Path) -> List[Dict[str, float]]:
    rows: List[Dict[str, float]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k: float(v) if k not in {"method"} else v for k, v in row.items()})
    return rows


def _group_by_method(rows: List[Dict[str, float]]) -> Dict[str, List[Dict[str, float]]]:
    grouped: Dict[str, List[Dict[str, float]]] = {}
    for row in rows:
        grouped.setdefault(str(row["method"]), []).append(row)
    return grouped


def _aggregate(records: List[Dict[str, float]]) -> Dict[str, float]:
    if not records:
        return {}
    keys = ["success", "override_rate", "override_win_rate", "override_regret_rate", "cost_ratio"]
    summary = {key: sum(r.get(key, 0.0) for r in records) / len(records) for key in keys}
    return summary


def _plot_scatter(x: List[float], y: List[float], labels: List[str], xlabel: str, ylabel: str, title: str, path: Path) -> None:
    if plt is None:
        _write_placeholder(path, title, [f"{lbl}: ({xi:.2f}, {yi:.2f})" for lbl, xi, yi in zip(labels, x, y)])
        return
    try:
        plt.figure(figsize=(6, 4))
        plt.scatter(x, y, c="tab:blue")
        for xi, yi, label in zip(x, y, labels):
            plt.text(xi, yi, label, fontsize=8)
        plt.xlabel(xlabel)
        plt.ylabel(ylabel)
        plt.title(title)
        plt.grid(True, linestyle=":", linewidth=0.5)
        plt.tight_layout()
        plt.savefig(path)
        plt.close()
    except Exception:
        _write_placeholder(path, title, [f"{lbl}: ({xi:.2f}, {yi:.2f})" for lbl, xi, yi in zip(labels, x, y)])


def _plot_bar(labels: List[str], values: List[float], ylabel: str, title: str, path: Path) -> None:
    if plt is None:
        _write_placeholder(path, title, [f"{lbl}: {val:.2f}" for lbl, val in zip(labels, values)])
        return
    try:
        plt.figure(figsize=(6, 4))
        plt.bar(labels, values, color="tab:orange")
        plt.ylabel(ylabel)
        plt.title(title)
        plt.xticks(rotation=30, ha="right")
        plt.tight_layout()
        plt.savefig(path)
        plt.close()
    except Exception:
        _write_placeholder(path, title, [f"{lbl}: {val:.2f}" for lbl, val in zip(labels, values)])


def _write_placeholder(path: Path, title: str, lines: List[str]) -> None:
    width, height = 640, 360
    image = Image.new("RGB", (width, height), color=(245, 245, 245))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    draw.text((10, 10), title, fill=(0, 0, 0), font=font)
    y = 40
    for line in lines[:12]:
        draw.text((10, y), line, fill=(40, 40, 40), font=font)
        y += 20
    image.save(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate STRIDE figures.")
    parser.add_argument("--metrics-path", type=Path, default=Path("results/aegis_rl/stride_metrics.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("reports/ase2026_aegis"))
    args = parser.parse_args()
    rows = _load_rows(args.metrics_path)
    grouped = _group_by_method(rows)
    summaries = {method: _aggregate(records) for method, records in grouped.items() if records}
    if not summaries:
        return
    args.output_dir.mkdir(parents=True, exist_ok=True)
    methods = list(summaries.keys())
    override_path = args.output_dir / "stride_fig_override_value.png"
    success_vs_cost_path = args.output_dir / "stride_fig_success_vs_cost.png"
    regret_path = args.output_dir / "stride_fig_override_regret.png"
    x = [summaries[m]["override_rate"] for m in methods]
    y = [summaries[m]["override_win_rate"] for m in methods]
    _plot_scatter(x, y, methods, "Override rate", "Override win rate", "Override Value Curve", override_path)
    succ = [summaries[m]["success"] for m in methods]
    cost = [summaries[m]["cost_ratio"] for m in methods]
    _plot_scatter(cost, succ, methods, "Avg cost ratio", "Success rate", "Success vs Cost", success_vs_cost_path)
    regrets = [summaries[m]["override_regret_rate"] for m in methods]
    _plot_bar(methods, regrets, "Override regret rate", "Override Regret", regret_path)


if __name__ == "__main__":
    main()
