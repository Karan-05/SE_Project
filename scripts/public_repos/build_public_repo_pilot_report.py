#!/usr/bin/env python3
"""Build a full pipeline report for the public repo pilot benchmark.

Aggregates stage summaries into:
  <out-dir>/pilot_report.json
  reports/ase2026_aegis/public_repo_pilot_snapshot.md
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def _safe_int(obj: Optional[Dict[str, Any]], key: str) -> int:
    if not obj:
        return 0
    return int(obj.get(key) or 0)


def _format_pairs(pairs: Optional[Any]) -> str:
    if not pairs:
        return "| — | — |"
    return "\n".join(f"| {key} | {value} |" for key, value in pairs)


def build_report(pilot_dir: Path, reports_dir: Path, eval_summary_path: Path) -> Dict[str, Any]:
    subset_summary = (
        _load_json(pilot_dir / "cgcs_pilot_subset_summary.json")
        or _load_json(pilot_dir / "pilot_subset_summary.json")
        or {}
    )
    validation_summary = (
        _load_json(pilot_dir / "workspace_validation_summary.json")
        or _load_json(pilot_dir / "validation_summary.json")
        or {}
    )
    task_gen_summary = (
        _load_json(pilot_dir / "tasks_summary.json")
        or _load_json(pilot_dir / "task_generation_summary.json")
        or {}
    )
    run_summary = (
        _load_json(reports_dir / "summary.json")
        or _load_json(pilot_dir / "pilot_run_summary.json")
        or {}
    )
    trace_quality = (
        _load_json(reports_dir / "trace_quality_summary.json")
        or _load_json(pilot_dir / "trace_quality_summary.json")
        or {}
    )
    eval_summary = _load_json(eval_summary_path) or {}

    aggregate_trace = (trace_quality.get("aggregate") or {})

    return {
        "pipeline_stages": {
            "subset_selection": {
                "pool_size": _safe_int(subset_summary, "pool_size"),
                "selected": _safe_int(subset_summary, "selected_count"),
                "languages": subset_summary.get("languages") or {},
            },
            "workspace_validation": {
                "total": _safe_int(validation_summary, "total"),
                "runnable": _safe_int(validation_summary, "runnable"),
                "missing": _safe_int(validation_summary, "missing_workspace"),
                "missing_tests": _safe_int(validation_summary, "missing_tests"),
            },
            "task_generation": {
                "tasks_generated": _safe_int(task_gen_summary, "tasks_generated"),
                "skipped": _safe_int(task_gen_summary, "skipped"),
                "mutations_per_task": task_gen_summary.get("mutations_per_task") or 1,
                "mutation_families": task_gen_summary.get("mutation_families") or {},
            },
            "pilot_run": {
                "total_runs": _safe_int(run_summary, "total_runs"),
                "status_counts": run_summary.get("status_counts") or {},
                "strategies": run_summary.get("strategies") or [],
            },
            "trace_quality": {
                "tasks_audited": _safe_int(aggregate_trace, "tasks_audited"),
                "rounds_total": _safe_int(aggregate_trace, "rounds_total"),
                "rounds_with_contract_items": _safe_int(aggregate_trace, "rounds_with_contract_items"),
                "rounds_with_active_clause": _safe_int(aggregate_trace, "rounds_with_active_clause"),
                "rounds_ready_for_strict": _safe_int(aggregate_trace, "rounds_ready_for_strict"),
                "rounds_with_regression_guards": _safe_int(aggregate_trace, "rounds_with_regression_guards"),
                "top_missing_fields": trace_quality.get("top_missing_fields") or [],
                "top_failure_categories": trace_quality.get("top_failure_categories") or [],
            },
            "eval_pack": {
                "total_eval_items": _safe_int(eval_summary, "total_eval_items"),
                "non_placeholder": _safe_int(eval_summary, "non_placeholder"),
                "with_contract_items": _safe_int(eval_summary, "with_contract_items"),
                "splits": eval_summary.get("splits") or {},
            },
        }
    }


def build_markdown(report: Dict[str, Any]) -> str:
    stages = report.get("pipeline_stages") or {}

    subset = stages.get("subset_selection") or {}
    validation = stages.get("workspace_validation") or {}
    tasks = stages.get("task_generation") or {}
    run = stages.get("pilot_run") or {}
    trace = stages.get("trace_quality") or {}
    eval_pack = stages.get("eval_pack") or {}

    lang_table = "\n".join(
        f"| {lang} | {count} |"
        for lang, count in sorted((subset.get("languages") or {}).items())
    )

    return f"""# Public Repo Pilot Benchmark — Snapshot

> **Engineering note**: This is a seeded-repair pilot benchmark built on the
> `data/public_repos/` acquisition pool.  It does **not** replace the Topcoder
> recovery funnel.  Its purpose is to validate CGCS harness instrumentation
> with real repos before the Topcoder corpus is fully available.

## Pipeline Funnel

| Stage | Input | Output |
|---|---|---|
| Subset selection | {subset.get('pool_size', '?')} seed repos | {subset.get('selected', '?')} pilot repos |
| Workspace validation | {subset.get('selected', '?')} repos | {validation.get('ok', '?')} ok |
| Task generation | {validation.get('ok', '?')} valid repos | {tasks.get('tasks_generated', '?')} tasks |
| Pilot run | {tasks.get('tasks_generated', '?')} tasks × {len(run.get('strategies', []))} strategies | {run.get('total_runs', '?')} runs |
| Eval pack | {run.get('ok', '?')} successful runs | {eval_pack.get('total_eval_items', '?')} eval items |

## Language Distribution (Selected Subset)

| Language | Count |
|---|---|
{lang_table or "| — | — |"}

## Trace Quality

| Metric | Count |
|---|---|
| Rounds total | {trace.get('rounds_total', 0)} |
| Rounds with contract items | {trace.get('rounds_with_contract_items', 0)} |
| Rounds with active clause | {trace.get('rounds_with_active_clause', 0)} |
| Rounds with regression guards | {trace.get('rounds_with_regression_guards', 0)} |
| Rounds ready for strict dataset | {trace.get('rounds_ready_for_strict', 0)} |

### Top Missing Fields

| Field | Missing Rounds |
|---|---|
{_format_pairs(trace.get('top_missing_fields'))}

### Top Failure Categories

| Category | Count |
|---|---|
{_format_pairs(trace.get('top_failure_categories'))}

## Eval Items

| Metric | Count |
|---|---|
| Total eval items | {eval_pack.get('total_eval_items', 0)} |
| Non-placeholder payloads | {eval_pack.get('non_placeholder', 0)} |
| With contract items | {eval_pack.get('with_contract_items', 0)} |
| Splits | {eval_pack.get('splits', {})} |

## Notes

- Mutations injected per task: {tasks.get('mutations_per_task', 1)}
- Strategies evaluated: {', '.join(run.get('strategies', []))}
- Pilot run status: {run.get('ok', 0)}/{run.get('total_runs', 0)} runs succeeded
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-dir", type=Path, default=Path("data/public_repos/pilot"))
    parser.add_argument("--reports-dir", type=Path, default=Path("reports/decomposition/public_repo_pilot"))
    parser.add_argument("--eval-summary", type=Path, default=Path("openai_artifacts/public_repo_eval_summary.json"))
    parser.add_argument("--report-json", type=Path, default=None)
    parser.add_argument("--report-markdown", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_report(args.pilot_dir, args.reports_dir, args.eval_summary)

    report_json = args.report_json or (args.pilot_dir / "pilot_report.json")
    report_md = args.report_markdown or Path("reports/ase2026_aegis/public_repo_pilot_snapshot.md")

    _write_json(report_json, report)
    report_md.parent.mkdir(parents=True, exist_ok=True)
    report_md.write_text(build_markdown(report), encoding="utf-8")
    print(f"[pilot-report] JSON → {report_json}")
    print(f"[pilot-report] Markdown → {report_md}")


if __name__ == "__main__":
    main()
