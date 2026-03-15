"""Aggregate discovery/fetch/workspace stats into JSON + Markdown reports."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .utils import now_utc_iso


def load_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


@dataclass(slots=True)
class ReportInputs:
    candidates_summary: Path
    selection_summary: Path
    fetch_summary: Path
    snapshots_summary: Path
    workspace_manifest: Path
    cgcs_seed_pool: Path


def build_report(inputs: ReportInputs) -> dict[str, object]:
    candidate_summary = load_json(inputs.candidates_summary)
    selection_summary = load_json(inputs.selection_summary)
    fetch_summary = load_json(inputs.fetch_summary)
    snapshot_summary = load_json(inputs.snapshots_summary)
    workspace_count = count_jsonl(inputs.workspace_manifest)
    cgcs_count = count_jsonl(inputs.cgcs_seed_pool)
    report = {
        "generated_at": now_utc_iso(),
        "candidate_stage": candidate_summary,
        "selection_stage": selection_summary,
        "fetch_stage": fetch_summary,
        "snapshot_stage": snapshot_summary,
        "workspace_stage": {
            "workspace_count": workspace_count,
            "cgcs_seed_pool": cgcs_count,
        },
    }
    return report


def build_markdown(report: dict[str, object]) -> str:
    candidate_stage = report.get("candidate_stage", {})
    selection_stage = report.get("selection_stage", {})
    fetch_stage = report.get("fetch_stage", {})
    snapshot_stage = report.get("snapshot_stage", {})
    workspace_stage = report.get("workspace_stage", {})
    lines = [
        "# Public Repo Acquisition Snapshot",
        "",
        f"- Candidates discovered: {candidate_stage.get('total_candidates', 'n/a')} across "
        f"{len(candidate_stage.get('languages', {}))} languages",
        f"- Selected pool size: {selection_stage.get('selected', 'n/a')} (target {selection_stage.get('target', 'n/a')})",
        f"- Fetch status: {fetch_stage.get('successful', 0)} success / {fetch_stage.get('failed', 0)} failed",
        f"- Snapshots built: {snapshot_stage.get('snapshots', 0)} with tests in {snapshot_stage.get('with_tests', 0)} repos",
        f"- Workspace manifests: {workspace_stage.get('workspace_count', 0)} entries; CGCS seed subset: {workspace_stage.get('cgcs_seed_pool', 0)}",
        "",
        "This pool is a bootstrap engineering resource for CGCS/runtime testing and does not replace the "
        "Topcoder recovery goals. Metrics describe the current repository acquisition path only.",
    ]
    return "\n".join(lines) + "\n"

