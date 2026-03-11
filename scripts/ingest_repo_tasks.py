"""Build RepoTaskSpec manifests from local repo snapshots."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_challenge_table(path: Optional[Path]) -> Dict[str, Dict[str, str]]:
    if path is None:
        return {}
    records: Dict[str, Dict[str, str]] = {}
    with path.open("r", encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            key = row.get("task_id") or row.get("id")
            if not key:
                continue
            records[str(key)] = row
    return records


def _merge_metadata(payload: Dict[str, object], row: Dict[str, str]) -> Dict[str, object]:
    merged = dict(payload)
    prompt = str(merged.get("prompt") or merged.get("description") or row.get("description") or row.get("title") or "")
    merged["prompt"] = prompt
    merged.setdefault("dataset", row.get("track") or "Topcoder")
    merged.setdefault("dataset_source", row.get("platform") or "Topcoder")
    merged.setdefault("task_type", "bugfix")
    merged.setdefault("difficulty", row.get("difficulty") or "M")
    merged.setdefault("task_is_real_world", True)
    merged.setdefault("reportable", True)
    merged.setdefault("language", "python")
    return merged


def build_manifest(snapshot_root: Path, output: Path, *, challenge_table: Optional[Path] = None) -> List[Dict[str, object]]:
    """Write a consolidated JSONL manifest for repo-backed tasks."""

    records = _load_challenge_table(challenge_table)
    entries: List[Dict[str, object]] = []
    for manifest in sorted(snapshot_root.rglob("task.json")):
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        task_id = payload.get("task_id") or payload.get("id") or manifest.parent.name
        payload["task_id"] = str(task_id)
        metadata = payload.get("metadata") or {}
        gt_patch = metadata.get("ground_truth_patch")
        candidate_patch = manifest.parent / "ground_truth.patch"
        if (not gt_patch) and candidate_patch.exists():
            metadata["ground_truth_patch"] = str(candidate_patch.relative_to(PROJECT_ROOT))
        payload["metadata"] = metadata
        if records and task_id in records:
            payload = _merge_metadata(payload, records[str(task_id)])
        entries.append(payload)
    if not entries:
        raise RuntimeError(f"No task.json files found under {snapshot_root}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as fp:
        for entry in entries:
            fp.write(json.dumps(entry) + "\n")
    print(f"Wrote {len(entries)} tasks to {output}")
    return entries


def _expected_files(entry: Dict[str, object]) -> List[str]:
    metadata = entry.get("metadata") or {}
    expected = metadata.get("expected_files")
    if isinstance(expected, list) and expected:
        return [str(item) for item in expected]
    if entry.get("target_files"):
        return [str(item) for item in entry["target_files"]]
    return []


def summarize_tasks(entries: List[Dict[str, object]]) -> Dict[str, object]:
    if not entries:
        return {"task_count": 0}
    languages = sorted({str(entry.get("language") or "unknown") for entry in entries})
    frameworks = sorted({str(entry.get("framework") or "unknown") for entry in entries if entry.get("framework")})
    multi_file = sum(
        1
        for entry in entries
        if len(entry.get("target_files") or []) > 1 or bool((entry.get("metadata") or {}).get("multi_file_localization"))
    )
    with_ground_truth = sum(1 for entry in entries if (entry.get("metadata") or {}).get("ground_truth_patch"))
    expected_counts = [_expected_files(entry) for entry in entries]
    avg_expected = sum(len(files) for files in expected_counts) / len(entries)
    test_commands = {entry["task_id"]: entry.get("test_commands", []) for entry in entries if entry.get("task_id")}
    runtimes = {}
    for entry in entries:
        runtime = str(entry.get("runtime_family") or entry.get("language") or "unknown").lower()
        runtimes[runtime] = runtimes.get(runtime, 0) + 1
    reportable = sum(1 for entry in entries if entry.get("reportable"))
    fixtures = sum(1 for entry in entries if entry.get("task_is_fixture"))
    requires_network = sum(1 for entry in entries if entry.get("requires_network"))
    return {
        "task_count": len(entries),
        "languages": languages,
        "frameworks": frameworks,
        "runtime_families": runtimes,
        "multi_file_tasks": multi_file,
        "tasks_with_ground_truth": with_ground_truth,
        "average_expected_files": avg_expected,
        "test_commands_per_task": test_commands,
        "reportable_count": reportable,
        "fixture_count": fixtures,
        "requires_network_tasks": requires_network,
    }


def write_summary(entries: List[Dict[str, object]], summary_json: Optional[Path], summary_md: Optional[Path]) -> None:
    if not summary_json and not summary_md:
        return
    summary = summarize_tasks(entries)
    if summary_json:
        summary_json.parent.mkdir(parents=True, exist_ok=True)
        summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if summary_md:
        lines = [
            "# Topcoder Task Pack Summary",
            "",
            f"- Tasks: {summary.get('task_count', 0)}",
            f"- Languages: {', '.join(summary.get('languages', [])) or 'n/a'}",
            f"- Frameworks: {', '.join(summary.get('frameworks', [])) or 'n/a'}",
            f"- Runtime families: {summary.get('runtime_families', {})}",
            f"- Multi-file tasks: {summary.get('multi_file_tasks', 0)}",
            f"- Tasks with ground-truth patches: {summary.get('tasks_with_ground_truth', 0)}",
            f"- Reportable/fixtures: {summary.get('reportable_count', 0)} / {summary.get('fixture_count', 0)}",
            f"- Avg expected files: {summary.get('average_expected_files', 0):.2f}",
            f"- Tasks requiring network: {summary.get('requires_network_tasks', 0)}",
            "",
            "## Test Commands",
        ]
        for task_id, commands in summary.get("test_commands_per_task", {}).items():
            lines.append(f"- {task_id}: {commands}")
        summary_md.parent.mkdir(parents=True, exist_ok=True)
        summary_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(description="Construct repo-task manifest from snapshot directories.")
    parser.add_argument("--snapshots", type=Path, required=True, help="Directory containing <task>/task.json metadata.")
    parser.add_argument("--challenge-table", type=Path, default=None, help="Optional data/raw/tasks.csv file.")
    parser.add_argument("--output", type=Path, required=True, help="Output JSONL manifest.")
    parser.add_argument("--summary-json", type=Path, default=None, help="Optional JSON summary output path.")
    parser.add_argument("--summary-md", type=Path, default=None, help="Optional Markdown summary output path.")
    args = parser.parse_args()

    entries = build_manifest(args.snapshots, args.output, challenge_table=args.challenge_table)
    write_summary(entries, args.summary_json, args.summary_md)


if __name__ == "__main__":  # pragma: no cover
    main()
