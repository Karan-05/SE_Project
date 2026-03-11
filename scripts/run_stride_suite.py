"""Batch runner for STRIDE variants with automatic metric aggregation."""
from __future__ import annotations

import argparse
import csv
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = PROJECT_ROOT / "results" / "aegis_rl"
METRICS_FILE = RESULTS_DIR / "stride_metrics.csv"


def _ensure_py_path(env: dict[str, str]) -> dict[str, str]:
    updated = env.copy()
    current = updated.get("PYTHONPATH")
    root_str = str(PROJECT_ROOT)
    if current:
        if root_str not in current.split(os.pathsep):
            updated["PYTHONPATH"] = os.pathsep.join([root_str, current])
    else:
        updated["PYTHONPATH"] = root_str
    return updated


def _run_variant(
    variant: str,
    episodes: int,
    seeds: Iterable[int],
    dataset_episodes: int,
    notes: str,
    full_action_space: bool,
    rebuild_dataset: bool,
    override_threshold: float,
    tag_suffix: str = "",
) -> None:
    cmd = [
        sys.executable,
        "experiments/run_stride_aegis.py",
        "--variant",
        variant,
        "--episodes",
        str(episodes),
        "--dataset-episodes",
        str(dataset_episodes),
        "--seeds",
        *map(str, seeds),
        "--notes",
        notes,
    ]
    if full_action_space:
        cmd.append("--full-action-space")
    if rebuild_dataset:
        cmd.append("--rebuild-dataset")
    if override_threshold is not None:
        cmd.extend(["--override-threshold", str(override_threshold)])
    env = _ensure_py_path(os.environ)
    subprocess.run(cmd, check=True, cwd=PROJECT_ROOT, env=env)
    variant_metrics = RESULTS_DIR / f"metrics_{variant}{tag_suffix}.csv"
    shutil.copy(METRICS_FILE, variant_metrics)


def _merge_metrics(variant_files: List[Path]) -> None:
    header: List[str] | None = None
    rows: List[List[str]] = []
    for file_path in variant_files:
        if not file_path.exists():
            continue
        with file_path.open("r", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            try:
                file_header = next(reader)
            except StopIteration:
                continue
            if header is None:
                header = file_header
            for row in reader:
                rows.append(row)
    if not header:
        raise RuntimeError("No STRIDE metrics were produced; ensure variants ran successfully.")
    METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with METRICS_FILE.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def _rebuild_tables() -> None:
    env = _ensure_py_path(os.environ)
    subprocess.run(
        [sys.executable, "scripts/make_stride_tables.py"],
        check=True,
        cwd=PROJECT_ROOT,
        env=env,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run STRIDE variants and refresh reports.")
    parser.add_argument(
        "--variants",
        nargs="+",
        default=["stride_without_uncertainty_features", "stride_gate_plus_residual"],
        help="Variants to run sequentially (default: teacher imitation + residual).",
    )
    parser.add_argument("--episodes", type=int, default=32, help="Episodes per seed.")
    parser.add_argument("--dataset-episodes", type=int, default=256, help="Episodes for disagreement dataset.")
    parser.add_argument("--seeds", nargs="+", type=int, default=[0, 1, 2, 3, 4], help="Seed list for each variant.")
    parser.add_argument("--notes", type=str, default="automated stride suite", help="Notes recorded alongside metrics.")
    parser.add_argument(
        "--full-action-space",
        action="store_true",
        help="Propagate --full-action-space to the underlying runner.",
    )
    parser.add_argument(
        "--rebuild-dataset",
        action="store_true",
        help="Force regeneration of the disagreement dataset before running variants.",
    )
    parser.add_argument("--override-threshold", type=float, default=0.6, help="Threshold passed to STRIDE runner.")
    parser.add_argument(
        "--residual-thresholds",
        nargs="+",
        type=float,
        default=None,
        help="Optional list of override thresholds to sweep for residual variants (e.g., 0.6 0.7 0.8).",
    )
    args = parser.parse_args()
    unique_variants = []
    for variant in args.variants:
        if variant not in unique_variants:
            unique_variants.append(variant)
    variant_files: List[Path] = []
    for variant in unique_variants:
        thresholds = [args.override_threshold]
        if args.residual_thresholds and "residual" in variant:
            thresholds = args.residual_thresholds
        for threshold in thresholds:
            suffix = ""
            note = args.notes
            if threshold != args.override_threshold or (args.residual_thresholds and "residual" in variant):
                suffix = f"_thr{threshold}".replace(".", "p")
                note = f"{args.notes} (thr={threshold:.2f})"
            _run_variant(
                variant,
                episodes=args.episodes,
                seeds=args.seeds,
                dataset_episodes=args.dataset_episodes,
                notes=note,
                full_action_space=args.full_action_space,
                rebuild_dataset=args.rebuild_dataset,
                override_threshold=threshold,
                tag_suffix=suffix,
            )
            variant_files.append(RESULTS_DIR / f"metrics_{variant}{suffix}.csv")
    _merge_metrics(variant_files)
    _rebuild_tables()


if __name__ == "__main__":
    main()
