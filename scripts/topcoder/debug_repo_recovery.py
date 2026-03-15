#!/usr/bin/env python3
"""Debugging utilities for Topcoder repo recovery coverage."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Iterable

SUCCESS_STATUSES = {"cloned", "updated", "archive_downloaded"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-candidates", type=Path, default=Path("data/topcoder/artifact_candidates.jsonl"))
    parser.add_argument("--repo-candidates", type=Path, default=Path("data/topcoder/repo_candidates.jsonl"))
    parser.add_argument("--fetch-manifest", type=Path, default=Path("data/topcoder/repo_fetch_manifest.jsonl"))
    parser.add_argument("--json-output", type=Path, default=Path("data/topcoder/repo_recovery_debug.json"))
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("reports/ase2026_aegis/repo_recovery_debug.md"),
    )
    parser.add_argument("--top-n", type=int, default=10)
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict]:
    entries: list[dict] = []
    if not path.exists():
        return entries
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def _format_table(rows: Iterable[tuple[str, object]]) -> list[str]:
    lines = ["| Item | Value |", "| --- | --- |"]
    for key, value in rows:
        if isinstance(value, (dict, list)):
            value_str = json.dumps(value)
        else:
            value_str = value
        lines.append(f"| {key} | {value_str} |")
    return lines


def build_markdown(report: dict, top_n: int) -> str:
    lines: list[str] = ["# Repo Recovery Debug", ""]
    lines.append("## Artifact Host Distribution")
    lines.append("")
    lines.extend(_format_table(report["artifact_stage"]["top_hosts"]))
    lines.append("")

    lines.append("## Artifact Types")
    lines.append("")
    lines.extend(_format_table(report["artifact_stage"]["top_artifact_types"]))
    lines.append("")

    lines.append("## Rejection Reasons")
    lines.append("")
    lines.extend(_format_table(report["fetch_stage"]["top_rejection_reasons"]))
    lines.append("")

    lines.append("## Clone Success Rate by Host")
    lines.append("")
    lines.extend(_format_table(report["fetch_stage"]["clone_host_stats"]))
    lines.append("")

    lines.append("## Archive Success Rate by Host")
    lines.append("")
    lines.extend(_format_table(report["fetch_stage"]["archive_host_stats"]))
    lines.append("")

    lines.append("## Example False Repo Candidates")
    lines.append("")
    for example in report["examples"]["false_repo_candidates"]:
        lines.append(f"- `{example['normalized_repo_key']}` – {example['rejection_reason']} – {example['candidate_urls'][:1]}")
    if not report["examples"]["false_repo_candidates"]:
        lines.append("- None recorded")
    lines.append("")
    lines.append("## Example Successful Recoveries")
    lines.append("")
    for example in report["examples"]["successful_recoveries"]:
        lines.append(f"- `{example['normalized_repo_key']}` – {example['clone_status']} – {example['source_origin']}")
    if not report["examples"]["successful_recoveries"]:
        lines.append("- None recorded")
    lines.append("")
    lines.append(f"Top lists limited to {top_n} entries. Consult the JSON artifact for full counts.")
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    artifact_candidates = load_jsonl(args.artifact_candidates)
    fetch_entries = load_jsonl(args.fetch_manifest)

    artifact_host_counts = Counter((entry.get("host") or "unknown") for entry in artifact_candidates)
    artifact_type_counts = Counter((entry.get("artifact_type") or "unknown") for entry in artifact_candidates)
    top_hosts = artifact_host_counts.most_common(args.top_n)
    top_artifact_types = artifact_type_counts.most_common(args.top_n)

    rejection_reasons = Counter(
        (entry.get("rejection_reason") or "unknown")
        for entry in fetch_entries
        if entry.get("clone_status") == "rejected"
    )
    clone_host_attempts: dict[str, int] = {}
    clone_host_success: dict[str, int] = {}
    archive_host_attempts: dict[str, int] = {}
    archive_host_success: dict[str, int] = {}
    successful_recoveries: list[dict] = []
    false_repo_examples: list[dict] = []

    for entry in fetch_entries:
        host = entry.get("repo_host") or "unknown"
        status = entry.get("clone_status")
        if status == "rejected" and len(false_repo_examples) < args.top_n:
            false_repo_examples.append(
                {
                    "normalized_repo_key": entry.get("normalized_repo_key"),
                    "rejection_reason": entry.get("rejection_reason"),
                    "candidate_urls": entry.get("candidate_urls") or [],
                }
            )
        if status in SUCCESS_STATUSES and len(successful_recoveries) < args.top_n:
            successful_recoveries.append(
                {
                    "normalized_repo_key": entry.get("normalized_repo_key"),
                    "clone_status": status,
                    "source_origin": entry.get("source_origin"),
                }
            )
        origin = entry.get("source_origin")
        if origin == "clone":
            clone_host_attempts[host] = clone_host_attempts.get(host, 0) + 1
            if status in {"cloned", "updated"}:
                clone_host_success[host] = clone_host_success.get(host, 0) + 1
        if origin == "archive":
            archive_host_attempts[host] = archive_host_attempts.get(host, 0) + 1
            if status == "archive_downloaded":
                archive_host_success[host] = archive_host_success.get(host, 0) + 1

    def _rate_rows(attempts: dict[str, int], success: dict[str, int]) -> list[tuple[str, object]]:
        rows: list[tuple[str, object]] = []
        for host, attempt_count in sorted(attempts.items(), key=lambda item: item[1], reverse=True)[: args.top_n]:
            success_count = success.get(host, 0)
            rate = success_count / attempt_count if attempt_count else 0.0
            rows.append((host, {"attempts": attempt_count, "success": success_count, "rate": round(rate, 3)}))
        return rows

    report = {
        "artifact_stage": {
            "top_hosts": top_hosts,
            "top_artifact_types": top_artifact_types,
        },
        "fetch_stage": {
            "top_rejection_reasons": rejection_reasons.most_common(args.top_n),
            "clone_host_stats": _rate_rows(clone_host_attempts, clone_host_success),
            "archive_host_stats": _rate_rows(archive_host_attempts, archive_host_success),
        },
        "examples": {
            "false_repo_candidates": false_repo_examples,
            "successful_recoveries": successful_recoveries,
        },
    }
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    with args.json_output.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    markdown = build_markdown(report, args.top_n)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    with args.markdown_output.open("w", encoding="utf-8") as handle:
        handle.write(markdown)
    print(f"Repo recovery debug JSON -> {args.json_output}")
    print(f"Repo recovery debug markdown -> {args.markdown_output}")


if __name__ == "__main__":
    main()
