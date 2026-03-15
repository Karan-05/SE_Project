#!/usr/bin/env python3
"""Audit CGCS trace quality for the public-repo pilot runs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from src.public_repos.pilot.trace_quality import audit_runs_root


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, default=Path("reports/decomposition/public_repo_pilot/runs"))
    parser.add_argument("--out-dir", type=Path, default=Path("reports/decomposition/public_repo_pilot"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    per_run, aggregate = audit_runs_root(args.runs_root)

    missing = aggregate.get("missing_field_counts", {})
    failure_categories = aggregate.get("failure_categories", {})
    top_missing: List[Tuple[str, int]] = sorted(missing.items(), key=lambda kv: kv[1], reverse=True)[:5]
    top_failures: List[Tuple[str, int]] = sorted(
        (item for item in failure_categories.items() if item[1] > 0),
        key=lambda kv: kv[1],
        reverse=True,
    )[:5]

    summary = {
        "aggregate": aggregate,
        "per_run": per_run,
        "top_missing_fields": top_missing,
        "top_failure_categories": top_failures,
    }

    out_path = args.out_dir / "trace_quality_summary.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    md_path = args.out_dir / "trace_quality_summary.md"
    md_lines = [
        "# Public Repo Pilot — Trace Quality",
        "",
        f"* Strategy runs audited: {aggregate.get('strategy_runs_audited', 0)}",
        f"* Total rounds: {aggregate.get('rounds_total', 0)}",
        f"* Rounds with contract items: {aggregate.get('rounds_with_contract_items', 0)}",
        f"* Rounds with active clause: {aggregate.get('rounds_with_active_clause', 0)}",
        f"* Rounds with regression guards: {aggregate.get('rounds_with_regression_guards', 0)}",
        f"* Rounds ready for strict dataset: {aggregate.get('rounds_ready_for_strict', 0)}",
        "",
        "## Top Missing Fields",
        "| Field | Missing Rounds |",
        "|---|---|",
    ]
    if top_missing:
        for field, count in top_missing:
            md_lines.append(f"| {field} | {count} |")
    else:
        md_lines.append("| — | — |")
    md_lines += [
        "",
        "## Top Failure Categories",
        "| Category | Count |",
        "|---|---|",
    ]
    if top_failures:
        for category, count in top_failures:
            md_lines.append(f"| {category} | {count} |")
    else:
        md_lines.append("| — | — |")
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(f"[trace-audit] Audited {aggregate.get('strategy_runs_audited', 0)} strategy runs")
    print(f"[trace-audit] rounds_total={aggregate.get('rounds_total', 0)}")
    print(f"[trace-audit] rounds_with_contract_items={aggregate.get('rounds_with_contract_items', 0)}")
    print(f"[trace-audit] rounds_ready_for_strict={aggregate.get('rounds_ready_for_strict', 0)}")
    print(f"[trace-audit] Summary → {out_path}")
    print(f"[trace-audit] Markdown → {md_path}")


if __name__ == "__main__":
    main()
