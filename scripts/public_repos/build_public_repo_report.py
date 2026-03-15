#!/usr/bin/env python3
"""Build JSON + Markdown summaries for the public repo acquisition pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.public_repos.reporting import ReportInputs, build_markdown, build_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="If set, resolve all input/output defaults relative to this directory.",
    )
    parser.add_argument("--candidates-summary", type=Path, default=None)
    parser.add_argument("--selection-summary", type=Path, default=None)
    parser.add_argument("--fetch-summary", type=Path, default=None)
    parser.add_argument("--snapshots-summary", type=Path, default=None)
    parser.add_argument("--workspace-manifest", type=Path, default=None)
    parser.add_argument("--cgcs-seed-pool", type=Path, default=None)
    parser.add_argument("--report-json", type=Path, default=None)
    parser.add_argument("--report-markdown", type=Path, default=None)
    return parser.parse_args()


def _resolve(explicit: Path | None, out_dir: Path | None, rel_name: str, fallback: str) -> Path:
    if explicit is not None:
        return explicit
    if out_dir is not None:
        return out_dir / rel_name
    return Path(fallback)


def main() -> None:
    args = parse_args()
    d = args.out_dir
    inputs = ReportInputs(
        candidates_summary=_resolve(args.candidates_summary, d, "repo_candidates_summary.json", "data/public_repos/repo_candidates_summary.json"),
        selection_summary=_resolve(args.selection_summary, d, "repo_selection_summary.json", "data/public_repos/repo_selection_summary.json"),
        fetch_summary=_resolve(args.fetch_summary, d, "repo_fetch_summary.json", "data/public_repos/repo_fetch_summary.json"),
        snapshots_summary=_resolve(args.snapshots_summary, d, "repo_snapshots_summary.json", "data/public_repos/repo_snapshots_summary.json"),
        workspace_manifest=_resolve(args.workspace_manifest, d, "workspace_manifest.jsonl", "data/public_repos/workspace_manifest.jsonl"),
        cgcs_seed_pool=_resolve(args.cgcs_seed_pool, d, "cgcs_seed_pool.jsonl", "data/public_repos/cgcs_seed_pool.jsonl"),
    )
    report_json = _resolve(args.report_json, d, "public_repo_report.json", "data/public_repos/public_repo_report.json")
    report_markdown = _resolve(args.report_markdown, None, "", "reports/ase2026_aegis/public_repo_snapshot.md")
    report = build_report(inputs)
    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    report_markdown.parent.mkdir(parents=True, exist_ok=True)
    report_markdown.write_text(build_markdown(report), encoding="utf-8")
    print(f"[public-repos] Report updated → {report_json}")


if __name__ == "__main__":
    main()
