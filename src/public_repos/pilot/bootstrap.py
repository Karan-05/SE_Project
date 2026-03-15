"""Bootstrap helpers for repairing pilot workspaces."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass(slots=True)
class CommandResult:
    status: str
    returncode: Optional[int]
    duration: float
    stdout: str
    stderr: str


@dataclass(slots=True)
class BootstrapReport:
    success: bool
    commands_run: list[str] = field(default_factory=list)
    note: str | None = None
    failure_reason: str | None = None


def _run_command(cmd: str, cwd: Path, timeout: float = 180.0) -> CommandResult:
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        status = "passed" if proc.returncode == 0 else "failed"
        return CommandResult(
            status=status,
            returncode=proc.returncode,
            duration=round(time.monotonic() - start, 2),
            stdout=proc.stdout[-2000:],
            stderr=proc.stderr[-2000:],
        )
    except subprocess.TimeoutExpired:
        return CommandResult(
            status="timeout",
            returncode=None,
            duration=round(time.monotonic() - start, 2),
            stdout="",
            stderr=f"Command timed out after {timeout}s",
        )
    except Exception as exc:  # pragma: no cover - defensive
        return CommandResult(
            status="error",
            returncode=None,
            duration=round(time.monotonic() - start, 2),
            stdout="",
            stderr=str(exc),
        )


def ensure_python_packaging_stack(local_path: Path) -> BootstrapReport:
    commands = [
        f"{sys.executable} -m ensurepip --upgrade",
        f"{sys.executable} -m pip install --upgrade pip setuptools wheel build",
    ]
    report = BootstrapReport(success=True)
    for cmd in commands:
        result = _run_command(cmd, local_path)
        report.commands_run.append(cmd)
        if result.status != "passed":
            report.success = False
            report.failure_reason = f"python_bootstrap_failed:{result.stderr or result.stdout}"
            break
    if report.success:
        report.note = "python packaging stack refreshed"
    return report


def _parse_package_manager_field(package_json: Path) -> str | None:
    if not package_json.exists():
        return None
    try:
        payload = json.loads(package_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    value = payload.get("packageManager")
    if not isinstance(value, str):
        return None
    return value.split("@", 1)[0].strip().lower() or None


def detect_node_package_manager(local_path: Path, manifest_default: str | None) -> str | None:
    package_json = local_path / "package.json"
    field_value = _parse_package_manager_field(package_json)
    if field_value:
        return field_value
    if manifest_default:
        return manifest_default
    if (local_path / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (local_path / "yarn.lock").exists():
        return "yarn"
    if (local_path / "package-lock.json").exists():
        return "npm"
    return None


def enable_corepack_manager(local_path: Path, manager: str) -> BootstrapReport:
    corepack = shutil.which("corepack")
    if not corepack:
        return BootstrapReport(success=False, failure_reason="corepack_not_available")
    commands = [
        f"{corepack} enable {manager}",
        f"{corepack} prepare {manager}@latest --activate",
    ]
    report = BootstrapReport(success=True)
    for cmd in commands:
        result = _run_command(cmd, local_path)
        report.commands_run.append(cmd)
        if result.status != "passed":
            report.success = False
            report.failure_reason = f"{manager}_corepack_failed:{result.stderr or result.stdout}"
            break
    if report.success:
        report.note = f"{manager} activated via corepack"
    return report


def ensure_node_package_manager(local_path: Path, manifest_default: str | None) -> BootstrapReport:
    manager = detect_node_package_manager(local_path, manifest_default)
    if not manager:
        return BootstrapReport(success=False, failure_reason="unknown_node_package_manager")
    if manager in {"pnpm", "yarn"}:
        return enable_corepack_manager(local_path, manager)
    if manager == "npm":
        # npm is bundled with Node — nothing to do as long as node exists.
        node = shutil.which("node")
        npm = shutil.which("npm")
        if node and npm:
            return BootstrapReport(success=True, note="npm already available", commands_run=[])
        return BootstrapReport(success=False, failure_reason="npm_missing_runtime")
    return BootstrapReport(success=False, failure_reason=f"unsupported_manager_{manager}")
