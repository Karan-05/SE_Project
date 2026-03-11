"""Run a reproducible prompt-tuning iteration for real-repo benchmarks."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import re
import shutil
import sys
from typing import List, Sequence

import pandas as pd

from src.config import PathConfig
from src.decomposition.runners.run_real_repo_benchmark import BenchmarkPaths, run_real_repo_benchmark


def _parse_list(raw: str | None) -> List[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _aggregate_metrics(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    return (
        df.groupby("strategy")
        .agg(
            task_count=("task_id", "count"),
            pass_rate=("pass_rate", "mean"),
            final_success_rate=("final_pass", "mean"),
            localization_precision=("localization_precision", "mean"),
            localization_recall=("localization_recall", "mean"),
            target_recall=("target_file_recall", "mean"),
            target_precision=("target_file_precision", "mean"),
            multi_file_edit_rate=("multi_file_edit", "mean"),
            multi_file_attempt_rate=("multi_file_attempt_rate", "mean"),
            avg_attempt_file_count=("avg_attempt_file_count", "mean"),
            ground_truth_recall=("ground_truth_recall", "mean"),
            under_localized_gt=("under_localized_ground_truth", "mean"),
            under_localized_targets=("under_localized_targets", "mean"),
        )
        .reset_index()
    )


def _top_tokens(series: pd.Series, limit: int = 3) -> str:
    counts: dict[str, int] = {}
    for value in series.fillna(""):
        for token in str(value).split(","):
            token = token.strip()
            if not token:
                continue
            counts[token] = counts.get(token, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    return ", ".join(name for name, _ in ordered[:limit])


def _render_iteration_summary(
    df: pd.DataFrame,
    prev_df: pd.DataFrame | None,
    notes: str,
    meta: dict[str, object],
) -> str:
    agg = _aggregate_metrics(df)
    prev = _aggregate_metrics(prev_df) if prev_df is not None else pd.DataFrame()
    lines: List[str] = [
        f"# Prompt Tuning Iteration {meta['iteration_name']}",
        "",
        f"- Timestamp (UTC): {meta['timestamp']}",
        f"- Mode: {meta['mode']}",
        f"- Strategies: {', '.join(meta['strategies'])}",
        f"- Task sources: {', '.join(meta['task_sources']) or 'default'}",
        f"- Notes: {notes or 'n/a'}",
        "",
    ]
    if agg.empty:
        lines.append("No benchmark rows were generated.")
        return "\n".join(lines) + "\n"
    lines.append("## Strategy Metrics")
    lines.append("| Strategy | Tasks | Final Pass | Target Recall | Target Precision | Multi-File Edit | Multi-File Attempt | Avg Files | Under-loc GT | Under-loc Targets |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for _, row in agg.iterrows():
        lines.append(
            "| {strategy} | {tasks:.0f} | {final_pass:.2f} | {target_recall:.2f} | {target_precision:.2f} | "
            "{mf_edit:.2f} | {mf_attempt:.2f} | {avg_files:.2f} | {ul_gt:.2f} | {ul_targets:.2f} |".format(
                strategy=row["strategy"],
                tasks=row["task_count"],
                final_pass=row["final_success_rate"],
                target_recall=row["target_recall"],
                target_precision=row["target_precision"],
                mf_edit=row["multi_file_edit_rate"],
                mf_attempt=row["multi_file_attempt_rate"],
                avg_files=row["avg_attempt_file_count"],
                ul_gt=row["under_localized_gt"],
                ul_targets=row["under_localized_targets"],
            )
        )
    lines.append("")
    if not prev.empty:
        merged = agg.merge(prev, on="strategy", suffixes=("_new", "_prev"))
        lines.append("## Delta vs Previous Iteration")
        for _, row in merged.iterrows():
            delta = row["final_success_rate_new"] - row["final_success_rate_prev"]
            lines.append(
                f"- {row['strategy']}: final_pass Δ={delta:.2f} "
                f"(new={row['final_success_rate_new']:.2f}, prev={row['final_success_rate_prev']:.2f})"
            )
        lines.append("")
    lines.append("## Dominant Failures")
    fail_series = df["dominant_failing_tests"] if "dominant_failing_tests" in df else pd.Series(dtype=str)
    mode_series = df["dominant_failure_modes"] if "dominant_failure_modes" in df else pd.Series(dtype=str)
    lines.append(f"- Top failing tests: {_top_tokens(fail_series) or 'n/a'}")
    lines.append(f"- Top failure modes: {_top_tokens(mode_series) or 'n/a'}")
    return "\n".join(lines) + "\n"


def _default_sources(mode: str) -> List[Path]:
    cfg = PathConfig()
    default_root = cfg.experiments_dir / "real_repo_tasks" / "dev"
    default_topcoder = cfg.experiments_dir / "real_repo_tasks" / "topcoder"
    legacy_manifest = cfg.experiments_dir / "decomposition" / "real_repo_tasks.jsonl"
    sources: List[Path] = []
    if mode == "real_world_research" and default_topcoder.exists():
        sources.append(default_topcoder)
    elif default_root.exists():
        sources.append(default_root)
    elif legacy_manifest.exists():
        sources.append(legacy_manifest)
    return sources


def _slugify(label: str | None) -> str:
    if not label:
        return "tuning"
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", label.strip())
    return cleaned or "tuning"


def main() -> None:
    parser = argparse.ArgumentParser(description="Record a prompt-tuning iteration for real-repo benchmarks.")
    parser.add_argument("--mode", choices=["dev", "real_world_research"], default="real_world_research")
    parser.add_argument("--reports-mode", choices=["dev", "real_world_research"], default=None, help="Override where reports are written.")
    parser.add_argument("--strategies", type=str, default="contract_first,failure_mode_first")
    parser.add_argument("--tasks-file", action="append", type=Path, default=[])
    parser.add_argument("--task-root", action="append", type=Path, default=[])
    parser.add_argument("--datasets", type=str, default=None)
    parser.add_argument("--exclude-datasets", type=str, default=None)
    parser.add_argument("--max-tasks", type=int, default=None)
    parser.add_argument("--require-reportable", action="store_true")
    parser.add_argument("--exclude-fixtures", action="store_true")
    parser.add_argument("--skip-oracle", action="store_true")
    parser.add_argument("--label", type=str, default=None)
    parser.add_argument("--notes", type=str, default=None)
    args = parser.parse_args()

    strategies = _parse_list(args.strategies)
    if not strategies:
        raise ValueError("Provide at least one strategy via --strategies.")
    sources: List[Path] = list(args.tasks_file or [])
    sources.extend(args.task_root or [])
    if not sources:
        sources = _default_sources(args.mode)
    if not sources:
        raise RuntimeError("No task sources found. Specify --tasks-file or --task-root.")
    include = _parse_list(args.datasets)
    exclude = _parse_list(args.exclude_datasets)
    iteration_timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    iteration_name = f"{iteration_timestamp}_{_slugify(args.label)}"
    paths_mode = args.reports_mode or args.mode
    paths = BenchmarkPaths(paths_mode)
    prompt_root = paths.root / "prompt_tuning"
    prompt_root.mkdir(parents=True, exist_ok=True)
    previous_runs = sorted([d for d in prompt_root.iterdir() if d.is_dir()])
    prev_dir = previous_runs[-1] if previous_runs else None

    df = run_real_repo_benchmark(
        sources,
        strategies=strategies,
        mode=args.mode,
        include_datasets=include,
        exclude_datasets=exclude,
        max_tasks=args.max_tasks,
        require_reportable=args.require_reportable,
        exclude_fixtures=args.exclude_fixtures,
        include_oracle=not args.skip_oracle,
        paths=paths,
    )

    iteration_dir = prompt_root / iteration_name
    iteration_dir.mkdir(parents=True, exist_ok=False)
    artifacts = [
        paths.csv,
        paths.case_md,
        paths.summary_md,
        paths.preflight_md,
        paths.preflight_json,
    ]
    for artifact in artifacts:
        if artifact.exists():
            shutil.copy(artifact, iteration_dir / artifact.name)
    meta = {
        "iteration_name": iteration_name,
        "timestamp": iteration_timestamp,
        "mode": args.mode,
        "reports_mode": paths_mode,
        "strategies": strategies,
        "task_sources": [str(src) for src in sources],
        "datasets": include,
        "exclude_datasets": exclude,
        "max_tasks": args.max_tasks,
        "require_reportable": args.require_reportable,
        "exclude_fixtures": args.exclude_fixtures,
        "include_oracle": not args.skip_oracle,
        "notes": args.notes or "",
        "command": " ".join(sys.argv),
    }
    (iteration_dir / "iteration_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    prev_df = None
    if prev_dir and (prev_dir / "strategy_comparison.csv").exists():
        prev_df = pd.read_csv(prev_dir / "strategy_comparison.csv")
    summary_text = _render_iteration_summary(df, prev_df, args.notes or "", meta)
    (iteration_dir / "iteration_summary.md").write_text(summary_text, encoding="utf-8")
    print(f"Stored prompt-tuning artifacts in {iteration_dir}")


if __name__ == "__main__":  # pragma: no cover
    main()
