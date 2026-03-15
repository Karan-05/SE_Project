#!/usr/bin/env python3
"""Validate pilot-subset workspaces by attempting bootstrap + install + build + test."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

MAX_CAPTURE = 2000
FINAL_SUCCESSES = {"runnable", "runnable_without_build"}


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


def _write_jsonl(path: Path, records: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def _write_json(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def _read_package_manifest(local_path: Path) -> Dict[str, Any]:
    package_json = local_path / "package.json"
    if not package_json.exists():
        return {}
    try:
        payload = json.loads(package_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_package_manager_field(manifest: Dict[str, Any]) -> tuple[str | None, str | None]:
    raw_value = str(manifest.get("packageManager") or "").strip()
    if not raw_value:
        return None, None
    if "@" not in raw_value:
        return raw_value, None
    name, version = raw_value.split("@", 1)
    name = name.strip()
    version = version.strip()
    return (name or None), (version or None)


def _has_workspace_protocol(manifest: Dict[str, Any]) -> bool:
    workspaces = manifest.get("workspaces")
    if isinstance(workspaces, list) and workspaces:
        return True
    if isinstance(workspaces, dict) and workspaces.get("packages"):
        return True
    sections = (
        "dependencies",
        "devDependencies",
        "peerDependencies",
        "optionalDependencies",
        "resolutions",
    )
    for section in sections:
        deps = manifest.get(section)
        if not isinstance(deps, dict):
            continue
        for value in deps.values():
            if isinstance(value, str) and value.strip().startswith("workspace:"):
                return True
    return False


def _sanitize_version_tuple(raw: str) -> tuple[int, int, int]:
    cleaned = raw.strip().lstrip("vV")
    parts = cleaned.split(".")
    numbers: list[int] = []
    for part in parts:
        digits = "".join(ch for ch in part if ch.isdigit())
        numbers.append(int(digits) if digits else 0)
    while len(numbers) < 3:
        numbers.append(0)
    return tuple(numbers[:3])


def _parse_node_engine_requirement(spec: str) -> tuple[int, int, int] | None:
    if not spec:
        return None
    lowered = spec.lower()
    minimums = re.findall(r">=\s*(\d+(?:\.\d+){0,2})", lowered)
    if minimums:
        return _sanitize_version_tuple(minimums[-1])
    caret_caps = re.findall(r"\^\s*(\d+(?:\.\d+){0,2})", lowered)
    if caret_caps:
        return _sanitize_version_tuple(caret_caps[-1])
    plain = re.findall(r"(\d+(?:\.\d+){0,2})", lowered)
    if plain:
        return _sanitize_version_tuple(plain[0])
    return None


def _get_node_version() -> tuple[str, tuple[int, int, int] | None]:
    try:
        proc = subprocess.run(
            ["node", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return "", None
    output = (proc.stdout or proc.stderr or "").strip()
    if not output:
        return "", None
    return output, _sanitize_version_tuple(output)


def _classify_npm_failure(stderr: str) -> str | None:
    lower = (stderr or "").lower()
    if "eresolve" in lower or "peer dep" in lower or "peer dependency" in lower:
        return "peer_dependency"
    if "integrity" in lower or "sha512" in lower or "eintegrity" in lower:
        return "integrity"
    return None


def _truncate(value: str, limit: int = MAX_CAPTURE) -> str:
    if not value:
        return ""
    if len(value) <= limit:
        return value
    return value[-limit:]


def _run_cmd(cmd: str, cwd: Path, timeout: float) -> Dict[str, Any]:
    if not cmd:
        return {"status": "skipped", "returncode": None, "duration": 0.0, "stdout": "", "stderr": ""}
    start = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        duration = time.monotonic() - start
        status = "passed" if result.returncode == 0 else "failed"
        return {
            "status": status,
            "returncode": result.returncode,
            "duration": round(duration, 2),
            "stdout": _truncate(result.stdout),
            "stderr": _truncate(result.stderr),
        }
    except subprocess.TimeoutExpired:
        duration = time.monotonic() - start
        return {
            "status": "timeout",
            "returncode": None,
            "duration": round(duration, 2),
            "stdout": "",
            "stderr": f"Command timed out after {timeout}s",
        }
    except Exception as exc:  # pragma: no cover
        duration = time.monotonic() - start
        return {
            "status": "error",
            "returncode": None,
            "duration": round(duration, 2),
            "stdout": "",
            "stderr": str(exc),
        }


def _attempt_npm_fallback(
    original_cmd: str,
    cwd: Path,
    timeout: float,
    stderr: str,
    rescue_actions: List[str],
) -> Dict[str, Any] | None:
    reason = _classify_npm_failure(stderr)
    if not reason:
        return None
    if reason == "peer_dependency":
        fallback_cmd = original_cmd if "--legacy-peer-deps" in original_cmd else f"{original_cmd} --legacy-peer-deps"
        rescue_actions.append("npm_legacy_peer_deps")
        result = _run_cmd(fallback_cmd, cwd, timeout)
        result.update(
            {
                "fallback_command": fallback_cmd,
                "original_command": original_cmd,
                "fallback_reason": reason,
                "fallback_helped": result["status"] == "passed",
            }
        )
        return result
    if reason == "integrity":
        rescue_actions.append("npm_cache_clean")
        clean_result = _run_cmd("npm cache clean --force", cwd, timeout)
        if clean_result["status"] != "passed":
            clean_result.update(
                {
                    "fallback_command": "npm cache clean --force",
                    "original_command": original_cmd,
                    "fallback_reason": reason,
                    "fallback_helped": False,
                }
            )
            return clean_result
        rescue_actions.append("npm_install_retry")
        retry_result = _run_cmd(original_cmd, cwd, timeout)
        retry_result.update(
            {
                "fallback_command": "npm cache clean --force",
                "original_command": original_cmd,
                "fallback_reason": reason,
                "fallback_helped": retry_result["status"] == "passed",
            }
        )
        return retry_result
    return None


def _empty_stage(status: str, reason: str | None = None) -> Dict[str, Any]:
    payload = {"status": status, "returncode": None, "duration": 0.0, "stdout": "", "stderr": ""}
    if reason:
        payload["reason"] = reason
    return payload


def _parse_filter(value: str | None) -> set[str]:
    if not value:
        return set()
    items = {item.strip().lower() for item in value.split(",") if item.strip()}
    return items


def _should_skip_entry(entry: Dict[str, Any], languages: set[str], repo_filters: set[str]) -> bool:
    if languages:
        lang = str(entry.get("language") or "").lower()
        if lang not in languages:
            return True
    if repo_filters:
        repo_key = str(entry.get("repo_key") or "")
        if not any(fragment in repo_key for fragment in repo_filters):
            return True
    return False


def _missing_required_tools(required_tools: Sequence[str]) -> list[str]:
    missing: list[str] = []
    for tool in required_tools:
        normalized = str(tool).strip()
        if not normalized:
            continue
        if normalized == "java":
            if shutil.which("java") is None:
                missing.append("java")
        elif shutil.which(normalized) is None:
            missing.append(normalized)
    return missing


def _tool_failure_category(tool: str) -> str:
    if tool in {"pnpm", "yarn", "npm"}:
        return "missing_node_package_manager"
    if tool == "poetry":
        return "missing_python_packaging_tool"
    if tool == "mvn":
        return "missing_maven"
    if tool == "java":
        return "jdk_mismatch"
    return "missing_tool"


def _pick_snippets(failure_stage: str | None, install: Dict[str, Any], build: Dict[str, Any], test: Dict[str, Any]) -> tuple[str, str]:
    order: list[Dict[str, Any]] = []
    if failure_stage == "install":
        order = [install, build, test]
    elif failure_stage == "build":
        order = [build, test, install]
    elif failure_stage == "test":
        order = [test, build, install]
    else:
        order = [test, build, install]
    for stage in order:
        stdout = stage.get("stdout") or ""
        stderr = stage.get("stderr") or ""
        if stdout or stderr:
            return stdout, stderr
    return "", ""


@dataclass(slots=True)
class ValidationSettings:
    bootstrap_mode: str
    skip_build_if_missing: bool
    skip_install_if_prepared: bool
    timeout_seconds: float


def validate_workspace(entry: Dict[str, Any], settings: ValidationSettings) -> Dict[str, Any]:
    repo_key = str(entry.get("repo_key") or "")
    local_path = Path(str(entry.get("local_path") or ""))
    language = str(entry.get("language") or "unknown").lower()
    package_manager = entry.get("package_manager")
    build_system = entry.get("build_system")
    install_cmd = str(entry.get("install_command") or "")
    build_cmd = str(entry.get("build_command") or "")
    test_cmd = str(entry.get("test_command") or "")
    bootstrap_commands = [cmd for cmd in entry.get("bootstrap_commands", []) if cmd]
    bootstrap_required = bool(entry.get("bootstrap_required"))
    required_tools = [tool for tool in entry.get("required_tools", []) if tool]

    record: Dict[str, Any] = {
        "repo_key": repo_key,
        "repo_url": entry.get("repo_url"),
        "workspace_id": entry.get("workspace_id"),
        "pilot_rank": entry.get("pilot_rank"),
        "selection_reason": entry.get("selection_reason"),
        "language": language,
        "build_system": build_system,
        "package_manager": package_manager,
        "test_frameworks": entry.get("test_frameworks", []),
        "local_path": str(local_path),
        "required_tools": required_tools,
    }
    record["package_manager_spec"] = entry.get("package_manager_spec")

    package_manifest = _read_package_manifest(local_path)
    manifest_pm, manifest_pm_version = _parse_package_manager_field(package_manifest)
    workspace_protocol = _has_workspace_protocol(package_manifest)
    if manifest_pm and not record.get("package_manager_spec"):
        record["package_manager_spec"] = manifest_pm_version

    engine_requirements: Dict[str, str] = {}
    runtime_versions: Dict[str, str] = {}
    rescue_actions: List[str] = []
    rescueable = False
    hard_blocked = False
    hard_block_reason = ""

    install_result = _empty_stage("skipped")
    build_result = _empty_stage("skipped")
    test_result = _empty_stage("skipped")
    bootstrap_result = _empty_stage("skipped")
    failure_category = ""
    failure_detail = ""
    runnable_reason = ""
    failure_stage: str | None = None
    total_duration = 0.0

    if manifest_pm and manifest_pm != package_manager:
        package_manager = manifest_pm
    if workspace_protocol and (not package_manager or package_manager == "npm"):
        package_manager = "yarn"
    if package_manager in {"yarn", "pnpm"} and (not install_cmd or install_cmd.startswith("npm")):
        install_cmd = f"{package_manager} install"
        rescue_actions.append(f"use_{package_manager}_install")
        rescueable = True
    record["package_manager"] = package_manager

    def _finalize(verdict: str) -> Dict[str, Any]:
        stdout_snippet, stderr_snippet = _pick_snippets(failure_stage, install_result, build_result, test_result)
        record.update({
            "install": install_result,
            "build": build_result,
            "test": test_result,
            "bootstrap": bootstrap_result,
            "bootstrap_required": bootstrap_required,
            "bootstrap_reason": entry.get("bootstrap_reason"),
            "bootstrap_category": entry.get("bootstrap_category"),
            "install_status": install_result.get("status"),
            "build_status": build_result.get("status"),
            "test_status": test_result.get("status"),
            "final_verdict": verdict,
            "failure_category": failure_category,
            "failure_detail": failure_detail,
            "bootstrap_applied": bootstrap_result.get("status") not in {"skipped", None},
            "bootstrap_commands_run": bootstrap_result.get("commands_run", []),
            "command_plan": {
                "bootstrap": bootstrap_commands,
                "install": install_cmd or "",
                "build": build_cmd or "",
                "test": test_cmd or "",
            },
            "stdout_snippet": stdout_snippet,
            "stderr_snippet": stderr_snippet,
            "duration_seconds": round(total_duration, 2),
            "runnable_verdict_reason": runnable_reason,
            "is_runnable": verdict in FINAL_SUCCESSES,
            "rescueable": rescueable,
            "hard_blocked": hard_blocked,
            "hard_block_reason": hard_block_reason,
            "rescue_actions_attempted": rescue_actions[:],
            "engine_requirements": engine_requirements,
            "actual_runtime_versions": runtime_versions,
        })
        return record

    node_engine_spec = ""
    if isinstance(package_manifest.get("engines"), dict):
        node_engine_spec = str(package_manifest["engines"].get("node") or "").strip()
        if node_engine_spec:
            engine_requirements["node"] = node_engine_spec
    node_version_str, node_version_tuple = ("", None)
    if language == "node":
        node_version_str, node_version_tuple = _get_node_version()
        if node_version_str:
            runtime_versions["node"] = node_version_str
    if node_engine_spec:
        required_tuple = _parse_node_engine_requirement(node_engine_spec)
        if required_tuple and node_version_tuple:
            if node_version_tuple < required_tuple:
                hard_blocked = True
                hard_block_reason = "node_engine_mismatch"
                failure_category = "node_engine_mismatch"
                failure_detail = f"requires {node_engine_spec} but current runtime is {node_version_str or 'unknown'}"
                runnable_reason = "node_engine_mismatch"
                return _finalize("blocked_by_environment")

    if not local_path.exists():
        failure_category = "missing_workspace"
        failure_detail = "workspace directory missing"
        runnable_reason = "workspace_missing"
        return _finalize("blocked_by_environment")

    unsupported_reason = entry.get("unsupported_reason")
    if unsupported_reason:
        failure_category = unsupported_reason
        failure_detail = str(unsupported_reason)
        runnable_reason = "unsupported_repo_type"
        return _finalize("unsupported_repo_type")

    missing_tools = _missing_required_tools(required_tools)
    if missing_tools:
        failure_category = _tool_failure_category(missing_tools[0])
        failure_detail = f"missing tooling: {', '.join(missing_tools)}"
        runnable_reason = "missing_tooling"
        rescueable = True
        return _finalize("blocked_by_environment")

    corepack_needed = any("corepack" in cmd for cmd in bootstrap_commands)
    if corepack_needed and shutil.which("corepack") is None:
        failure_category = "missing_corepack"
        failure_detail = "corepack executable not available"
        runnable_reason = "missing_corepack"
        rescueable = True
        return _finalize("blocked_by_environment")

    if bootstrap_required:
        if settings.bootstrap_mode != "safe":
            failure_category = entry.get("bootstrap_category") or "bootstrap_required"
            failure_detail = entry.get("bootstrap_reason") or "bootstrap disabled"
            runnable_reason = "bootstrap_disabled"
            return _finalize("blocked_by_environment")
        bootstrap_duration = 0.0
        commands_run: list[str] = []
        for cmd in bootstrap_commands:
            cmd_result = _run_cmd(cmd, local_path, settings.timeout_seconds)
            bootstrap_duration += cmd_result.get("duration") or 0.0
            commands_run.append(cmd)
            if cmd_result["status"] != "passed":
                bootstrap_result = dict(cmd_result)
                bootstrap_result["commands_run"] = commands_run
                failure_category = entry.get("bootstrap_category") or "bootstrap_failed"
                failure_detail = f"bootstrap command failed: {cmd}"
                runnable_reason = "bootstrap_failed"
                total_duration += bootstrap_duration
                failure_stage = "bootstrap"
                return _finalize("blocked_by_environment")
        bootstrap_result = {"status": "passed", "commands_run": commands_run, "duration": round(bootstrap_duration, 2)}
        total_duration += bootstrap_duration

    if settings.skip_install_if_prepared:
        install_result = _empty_stage("skipped", "flag_skip_install")
    elif install_cmd:
        install_result = _run_cmd(install_cmd, local_path, settings.timeout_seconds)
        total_duration += install_result.get("duration") or 0.0
        if install_result["status"] != "passed":
            fallback_result = None
            if package_manager == "npm" and settings.bootstrap_mode == "safe":
                fallback_result = _attempt_npm_fallback(
                    install_cmd,
                    local_path,
                    settings.timeout_seconds,
                    install_result.get("stderr") or install_result.get("stdout") or "",
                    rescue_actions,
                )
            if fallback_result:
                install_result = fallback_result
                total_duration += install_result.get("duration") or 0.0
                rescueable = True
            if install_result["status"] != "passed":
                failure_category = "dependency_install_failed" if install_result["status"] == "failed" else f"install_{install_result['status']}"
                failure_detail = install_result.get("stderr") or install_result.get("stdout") or ""
                runnable_reason = "install_failure"
                if install_result.get("fallback_reason") == "integrity" and not install_result.get("fallback_helped"):
                    hard_blocked = True
                    hard_block_reason = "npm_integrity_failure"
                failure_stage = "install"
                return _finalize("blocked_by_dependency_resolution")
    else:
        install_result = _empty_stage("skipped", "missing_install_command")

    build_missing = not build_cmd
    if build_missing:
        build_result = _empty_stage("skipped", "missing_build_command")
        if not settings.skip_build_if_missing and build_system:
            failure_category = "missing_build_command"
            failure_detail = "build command was not inferred"
            runnable_reason = "missing_build_command"
            failure_stage = "build"
            return _finalize("blocked_by_command_inference")
    else:
        build_result = _run_cmd(build_cmd, local_path, settings.timeout_seconds)
        total_duration += build_result.get("duration") or 0.0
        if build_result["status"] != "passed":
            failure_category = "build_script_failed" if build_result["status"] == "failed" else f"build_{build_result['status']}"
            failure_detail = build_result.get("stderr") or build_result.get("stdout") or ""
            runnable_reason = "build_failed"
            failure_stage = "build"
            return _finalize("blocked_by_environment")

    if not test_cmd:
        test_result = _empty_stage("skipped", "missing_test_command")
        failure_category = "missing_test_command"
        failure_detail = "no test command available"
        runnable_reason = "missing_test_command"
        failure_stage = "test"
        return _finalize("blocked_by_command_inference")

    test_result = _run_cmd(test_cmd, local_path, settings.timeout_seconds)
    total_duration += test_result.get("duration") or 0.0
    if test_result["status"] == "passed":
        runnable_reason = "tests_passed_without_build" if build_missing else "tests_passed"
        final_verdict = "runnable_without_build" if build_missing else "runnable"
        return _finalize(final_verdict)

    failure_category = "test_command_failed" if test_result["status"] == "failed" else f"test_{test_result['status']}"
    failure_detail = test_result.get("stderr") or test_result.get("stdout") or ""
    runnable_reason = "tests_failed"
    failure_stage = "test"
    return _finalize("blocked_by_environment")


def build_summary(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    verdicts = Counter(r.get("final_verdict", "unknown") for r in results)
    failures = Counter(r.get("failure_category", "") for r in results)
    languages = Counter(r.get("language", "unknown") for r in results)
    return {
        "total": len(results),
        "verdict_counts": dict(verdicts),
        "failure_counts": dict(failures),
        "language_counts": dict(languages),
        "runnable": verdicts.get("runnable", 0),
        "runnable_without_build": verdicts.get("runnable_without_build", 0),
    }


def _merge_subset_with_manifest(
    subset_entry: Dict[str, Any],
    manifest_by_repo: Dict[str, Dict[str, Any]],
    manifest_by_workspace: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    repo_key = str(subset_entry.get("repo_key") or "")
    workspace_id = str(subset_entry.get("workspace_id") or "")
    manifest_entry = manifest_by_workspace.get(workspace_id) or manifest_by_repo.get(repo_key) or {}
    merged = dict(manifest_entry)
    merged.update(subset_entry)
    return merged


def _write_markdown(report_path: Path, results: Sequence[Dict[str, Any]], summary: Dict[str, Any]) -> None:
    lines = [
        "# Public Repo Pilot — Workspace Validation",
        "",
        f"Total repos: {summary.get('total', 0)}",
        f"Runnable: {summary.get('runnable', 0)}",
        f"Runnable without build: {summary.get('runnable_without_build', 0)}",
        "",
        "| Rank | Repo | Lang | Install | Build | Test | Verdict | Failure |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for record in sorted(results, key=lambda r: int(r.get("pilot_rank") or 0)):
        lines.append(
            f"| {record.get('pilot_rank', '-')} "
            f"| {record.get('repo_key', '')} "
            f"| {record.get('language', '')} "
            f"| {record.get('install_status', '')} "
            f"| {record.get('build_status', '')} "
            f"| {record.get('test_status', '')} "
            f"| {record.get('final_verdict', '')} "
            f"| {record.get('failure_category', '')} |"
        )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subset", type=Path, default=Path("data/public_repos/pilot/cgcs_pilot_subset.jsonl"))
    parser.add_argument("--workspace-manifest", type=Path, default=Path("data/public_repos/workspace_manifest.jsonl"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/public_repos/pilot"))
    parser.add_argument("--report-dir", type=Path, default=Path("reports/decomposition/public_repo_pilot"))
    parser.add_argument("--bootstrap-mode", choices=("off", "safe"), default="off")
    parser.add_argument("--skip-build-if-missing", action="store_true")
    parser.add_argument("--skip-install-if-already-prepared", action="store_true")
    parser.add_argument("--max-failures", type=int, default=0, help="Stop after this many non-runnable verdicts (0 = no limit)")
    parser.add_argument("--timeout-seconds", type=float, default=240.0)
    parser.add_argument("--language-filter", type=str, default="", help="Comma-separated language buckets to include")
    parser.add_argument("--repo-filter", type=str, default="", help="Comma-separated substrings to match repo_key")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    subset_entries = _load_jsonl(args.subset)
    manifest_entries = _load_jsonl(args.workspace_manifest)
    manifest_by_repo = {str(entry.get("repo_key") or ""): entry for entry in manifest_entries}
    manifest_by_workspace = {str(entry.get("workspace_id") or ""): entry for entry in manifest_entries}
    print(f"[validate-workspaces] Considering {len(subset_entries)} repos ...")

    language_filter = _parse_filter(args.language_filter)
    repo_filters = _parse_filter(args.repo_filter)
    settings = ValidationSettings(
        bootstrap_mode=args.bootstrap_mode,
        skip_build_if_missing=args.skip_build_if_missing,
        skip_install_if_prepared=args.skip_install_if_already_prepared,
        timeout_seconds=args.timeout_seconds,
    )

    entries = [
        _merge_subset_with_manifest(entry, manifest_by_repo, manifest_by_workspace)
        for entry in subset_entries
        if not _should_skip_entry(entry, language_filter, repo_filters)
    ]
    print(f"[validate-workspaces] Running validation for {len(entries)} filtered repos ...")
    results: List[Dict[str, Any]] = []
    failure_count = 0
    for entry in entries:
        repo_key = entry.get("repo_key", "?")
        print(f"  → {repo_key}", flush=True)
        result = validate_workspace(entry, settings)
        results.append(result)
        verdict = result["final_verdict"]
        print(f"     verdict={verdict} failure={result.get('failure_category')}")
        if verdict not in FINAL_SUCCESSES:
            failure_count += 1
            if args.max_failures and failure_count >= args.max_failures:
                print(f"[validate-workspaces] Max failures reached ({args.max_failures}); stopping early.")
                break

    out_results = args.out_dir / "workspace_validation.jsonl"
    out_summary = args.out_dir / "workspace_validation_summary.json"
    _write_jsonl(out_results, results)
    summary = build_summary(results)
    _write_json(out_summary, summary)
    report_path = args.report_dir / "workspace_validation.md"
    _write_markdown(report_path, results, summary)
    print(f"[validate-workspaces] Results → {out_results}")
    print(f"[validate-workspaces] Summary → {out_summary}")
    print(f"[validate-workspaces] Report → {report_path}")


if __name__ == "__main__":
    main()
