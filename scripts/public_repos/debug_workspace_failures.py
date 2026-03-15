#!/usr/bin/env python3
"""Aggregate workspace validation failures to highlight remediation opportunities."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List

DEFAULT_SAFE_BOOTSTRAP_FAILURES = {
    "missing_python_build_module",
    "missing_python_packaging_tool",
    "bootstrap_required",
    "bootstrap_failed",
    "missing_node_package_manager",
}
COMMAND_INFERENCE_FAILURES = {
    "missing_build_command",
    "missing_test_command",
    "command_inference_error",
}


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    if not path.exists():
        return records
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _signature(text: str) -> str:
    if not text:
        return ""
    first_line = text.strip().splitlines()[0].strip()
    return first_line[:200]


def _collect_counts(records: Iterable[Dict[str, Any]], field: str) -> Dict[str, int]:
    counter = Counter(str(record.get(field) or "unknown") for record in records)
    return dict(counter)


def _extract_candidates(records: Iterable[Dict[str, Any]], categories: set[str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for record in records:
        failure_category = str(record.get("failure_category") or "")
        if failure_category in categories:
            rows.append({
                "repo_key": record.get("repo_key"),
                "failure_category": failure_category,
                "final_verdict": record.get("final_verdict"),
                "language": record.get("language"),
                "package_manager": record.get("package_manager"),
                "notes": record.get("failure_detail"),
            })
    return rows


def _build_markdown(report_path: Path, payload: Dict[str, Any]) -> None:
    lines = [
        "# Public Repo Pilot — Workspace Failure Debug",
        "",
        f"Total validations: {payload['total']}",
        f"Runnable: {payload['verdict_counts'].get('runnable', 0)}",
        f"Runnable without build: {payload['verdict_counts'].get('runnable_without_build', 0)}",
        "",
        "## Failure categories",
        "| Failure | Count |",
        "|---|---|",
    ]
    for failure, count in sorted(payload["failure_counts"].items(), key=lambda item: item[1], reverse=True):
        lines.append(f"| {failure or 'passed'} | {count} |")
    lines += [
        "",
        "## Language breakdown",
        "| Language | Count |",
        "|---|---|",
    ]
    for lang, count in sorted(payload["language_counts"].items(), key=lambda item: item[1], reverse=True):
        lines.append(f"| {lang} | {count} |")
    lines += [
        "",
        "## Package managers",
        "| Package manager | Count |",
        "|---|---|",
    ]
    for pkg, count in sorted(payload["package_manager_counts"].items(), key=lambda item: item[1], reverse=True):
        lines.append(f"| {pkg} | {count} |")
    lines += [
        "",
        "## Build systems",
        "| Build system | Count |",
        "|---|---|",
    ]
    for build, count in sorted(payload["build_system_counts"].items(), key=lambda item: item[1], reverse=True):
        lines.append(f"| {build} | {count} |")
    lines += [
        "",
        "## Top stderr signatures",
    ]
    if payload["stderr_signatures"]:
        for entry in payload["stderr_signatures"]:
            repos = ", ".join(entry["repos"])
            lines.append(f"- `{entry['signature'] or '(empty stderr)'}` — {entry['count']} repos ({repos})")
    else:
        lines.append("- No stderr captured.")

    lines += [
        "",
        "## Remediation focus",
        "### Safe bootstrap candidates",
    ]
    if payload["safe_bootstrap_candidates"]:
        for row in payload["safe_bootstrap_candidates"]:
            lines.append(f"- {row['repo_key']} ({row['failure_category']}) — {row.get('notes') or 'bootstrap gap'}")
    else:
        lines.append("- None detected.")

    lines += [
        "",
        "### Command inference fixes",
    ]
    if payload["command_inference_candidates"]:
        for row in payload["command_inference_candidates"]:
            lines.append(f"- {row['repo_key']} ({row['failure_category']}) — {row.get('notes') or 'missing command'}")
    else:
        lines.append("- None detected.")

    lines += [
        "",
        "### Unsupported repos",
    ]
    if payload["unsupported_repos"]:
        for row in payload["unsupported_repos"]:
            lines.append(f"- {row['repo_key']} — {row.get('failure_category')}")
    else:
        lines.append("- None detected.")

    lines.append("")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/public_repos/pilot/workspace_validation.jsonl"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/public_repos/pilot"))
    parser.add_argument("--report-dir", type=Path, default=Path("reports/decomposition/public_repo_pilot"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = _load_jsonl(args.input)
    if not records:
        raise SystemExit(f"No validation records found at {args.input}")

    failure_counts = Counter(str(r.get("failure_category") or "") for r in records)
    language_counts = Counter(str(r.get("language") or "unknown") for r in records)
    package_manager_counts = Counter(str(r.get("package_manager") or "unknown") for r in records)
    build_system_counts = Counter(str(r.get("build_system") or "unknown") for r in records)

    signature_map: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"count": 0, "repos": []})
    for record in records:
        sig = _signature(record.get("stderr_snippet") or "")
        entry = signature_map[sig]
        entry["count"] += 1
        repo_key = str(record.get("repo_key") or "")
        if repo_key:
            entry["repos"].append(repo_key)

    stderr_signatures = [
        {"signature": sig, "count": info["count"], "repos": sorted(info["repos"])[:5]}
        for sig, info in signature_map.items()
    ]
    stderr_signatures.sort(key=lambda item: item["count"], reverse=True)
    stderr_signatures = stderr_signatures[:10]

    safe_bootstrap = _extract_candidates(records, DEFAULT_SAFE_BOOTSTRAP_FAILURES)
    command_inference = _extract_candidates(records, COMMAND_INFERENCE_FAILURES)
    unsupported = [
        {
            "repo_key": r.get("repo_key"),
            "failure_category": r.get("failure_category"),
            "final_verdict": r.get("final_verdict"),
        }
        for r in records
        if r.get("final_verdict") == "unsupported_repo_type"
    ]

    payload = {
        "total": len(records),
        "verdict_counts": dict(Counter(r.get("final_verdict", "unknown") for r in records)),
        "failure_counts": dict(failure_counts),
        "language_counts": dict(language_counts),
        "package_manager_counts": dict(package_manager_counts),
        "build_system_counts": dict(build_system_counts),
        "stderr_signatures": stderr_signatures,
        "safe_bootstrap_candidates": safe_bootstrap,
        "command_inference_candidates": command_inference,
        "unsupported_repos": unsupported,
    }
    out_json = args.out_dir / "workspace_failure_debug.json"
    report_path = args.report_dir / "workspace_failure_debug.md"
    _write_json(out_json, payload)
    _build_markdown(report_path, payload)
    print(f"[workspace-debug] JSON → {out_json}")
    print(f"[workspace-debug] Report → {report_path}")


if __name__ == "__main__":
    main()
