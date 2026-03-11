"""Preflight validation for real-repo benchmarks."""
from __future__ import annotations

import json
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from src.providers import llm

from .setup import resolve_setup_plan
from .task import RepoTaskSpec


@dataclass
class PreflightCheck:
    """Single validation item."""

    name: str
    ok: bool
    message: str
    details: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        payload = {"name": self.name, "ok": self.ok, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


@dataclass
class PreflightReport:
    """Aggregate report for all preflight checks."""

    provider: str
    model: str
    mode: str
    task_sources: List[str]
    task_count: int
    checks: List[PreflightCheck]
    runtime_counts: Dict[str, int]
    requires_network: int
    provider_metadata: Dict[str, object] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def to_dict(self) -> Dict[str, object]:
        return {
            "provider": self.provider,
            "model": self.model,
            "mode": self.mode,
            "task_sources": self.task_sources,
            "task_count": self.task_count,
            "runtime_counts": self.runtime_counts,
            "requires_network_tasks": self.requires_network,
            "provider_metadata": self.provider_metadata,
            "checks": [check.to_dict() for check in self.checks],
            "ok": self.ok,
        }


def _command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def _check_provider(provider: str, mode: str) -> PreflightCheck:
    provider_lower = (provider or "").lower()
    provider_ok = bool(provider_lower) and (mode != "real_world_research" or not provider_lower.startswith("mock"))
    if not provider_lower:
        message = "Provider must be configured."
    elif provider_lower.startswith("mock") and mode == "real_world_research":
        message = "Mock provider is not allowed in real_world_research mode."
    else:
        message = f"LLM provider '{provider}' configured."
    return PreflightCheck(name="provider_configured", ok=provider_ok, message=message)


def _check_model(model: str, mode: str) -> PreflightCheck:
    model_lower = (model or "").lower()
    model_ok = bool(model_lower) and (mode != "real_world_research" or not model_lower.startswith("mock"))
    if not model_lower:
        message = "Model must be configured."
    elif model_lower.startswith("mock") and mode == "real_world_research":
        message = "Mock model is not allowed in real_world_research mode."
    else:
        message = f"LLM model '{model}' configured."
    return PreflightCheck(name="model_configured", ok=model_ok, message=message)


def _ollama_status() -> Dict[str, object]:
    details: Dict[str, object] = {}
    try:
        proc = subprocess.run(
            ["ollama", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except FileNotFoundError:
        details["error"] = "ollama CLI not found on PATH"
        return details
    except subprocess.TimeoutExpired:
        details["error"] = "ollama --version timed out"
        return details
    details["version_output"] = proc.stdout.strip() or proc.stderr.strip()
    details["returncode"] = proc.returncode
    if proc.returncode != 0:
        details["error"] = proc.stderr.strip()
    return details


def _check_local_provider_runtime(provider: str) -> PreflightCheck:
    provider = provider.lower()
    if provider != "ollama":
        return PreflightCheck(name="provider_runtime", ok=True, message="Local provider runtime not required.")
    details = _ollama_status()
    ok = details.get("error") is None
    message = "Ollama runtime reachable." if ok else details.get("error", "Unable to reach Ollama runtime.")
    return PreflightCheck(name="provider_runtime", ok=ok, message=message, details=details)


def _check_provider_ping() -> PreflightCheck:
    ok, message, latency, tokens = llm.validate_connection("Topcoder repo benchmark preflight ping")
    return PreflightCheck(
        name="provider_ping",
        ok=ok,
        message="LLM ping succeeded." if ok else f"LLM ping failed: {message}",
        details={"latency_sec": latency, "tokens_used": tokens, "response": message},
    )


def _check_task_sources(sources: Sequence[Path]) -> List[PreflightCheck]:
    checks: List[PreflightCheck] = []
    for source in sources:
        if source.exists():
            checks.append(PreflightCheck(name=f"source:{source}", ok=True, message="Task source found."))
        else:
            checks.append(
                PreflightCheck(name=f"source:{source}", ok=False, message="Task source missing.", details={"path": str(source)})
            )
    return checks


def _check_repo_paths(specs: Sequence[RepoTaskSpec]) -> PreflightCheck:
    missing = [spec.task_id for spec in specs if not spec.repo_path.exists()]
    if missing:
        return PreflightCheck(
            name="repo_paths",
            ok=False,
            message=f"{len(missing)} repo snapshots missing.",
            details={"tasks": missing[:8]},
        )
    return PreflightCheck(name="repo_paths", ok=True, message="All repo snapshots available.")


def _runtime_requirements(spec: RepoTaskSpec) -> Iterable[str]:
    runtime = (spec.runtime_family or spec.language or "").lower()
    if runtime == "node":
        yield "node"
        yield "npm"
    elif runtime.startswith("python"):
        yield "python"
    else:
        if runtime:
            yield runtime


def _check_runtime_tooling(specs: Sequence[RepoTaskSpec]) -> List[PreflightCheck]:
    command_to_tasks: Dict[str, List[str]] = {}
    for spec in specs:
        for command in _runtime_requirements(spec):
            command_to_tasks.setdefault(command, []).append(spec.task_id)
    checks: List[PreflightCheck] = []
    for command, tasks in command_to_tasks.items():
        ok = _command_exists(command)
        message = f"Command '{command}' available." if ok else f"Missing required command '{command}'."
        checks.append(
            PreflightCheck(
                name=f"tool:{command}",
                ok=ok,
                message=message,
                details={"tasks": tasks[:8]},
            )
        )
    return checks


def _check_commands_are_defined(commands: Sequence[str], name: str, task_id: str, *, required: bool) -> PreflightCheck:
    if not commands:
        if not required:
            return PreflightCheck(
                name=f"{name}:{task_id}",
                ok=True,
                message=f"{name.replace('_', ' ').title()} not required.",
            )
        return PreflightCheck(
            name=f"{name}:{task_id}",
            ok=False,
            message=f"{name.replace('_', ' ').title()} missing.",
        )
    if all(isinstance(cmd, str) and cmd.strip() for cmd in commands):
        return PreflightCheck(name=f"{name}:{task_id}", ok=True, message=f"{name.replace('_', ' ').title()} OK.")
    return PreflightCheck(name=f"{name}:{task_id}", ok=False, message=f"{name.replace('_', ' ').title()} invalid entries.")


def _check_setup_plans(specs: Sequence[RepoTaskSpec]) -> List[PreflightCheck]:
    checks: List[PreflightCheck] = []
    for spec in specs:
        plan = resolve_setup_plan(spec, spec.repo_path)
        runtime = (spec.runtime_family or "").lower()
        needs_setup = bool(plan.commands) or runtime == "node"
        if not plan.commands and needs_setup:
            checks.append(
                PreflightCheck(
                    name=f"setup_plan:{spec.task_id}",
                    ok=False,
                    message="Setup plan missing commands for repo runtime.",
                    details={"strategy": plan.strategy},
                )
            )
        else:
            checks.append(
                PreflightCheck(
                    name=f"setup_plan:{spec.task_id}",
                    ok=True,
                    message="Setup plan ready.",
                    details={"strategy": plan.strategy, "commands": plan.commands},
                )
            )
        checks.append(_check_commands_are_defined(spec.test_commands, "test_commands", spec.task_id, required=True))
        checks.append(_check_commands_are_defined(spec.build_commands, "build_commands", spec.task_id, required=False))
    return checks


def run_preflight_checks(
    specs: Sequence[RepoTaskSpec],
    *,
    task_sources: Sequence[Path],
    mode: str,
    provider: str,
    model: str,
) -> PreflightReport:
    checks: List[PreflightCheck] = []
    checks.append(_check_provider(provider, mode))
    checks.append(_check_model(model, mode))
    checks.append(_check_local_provider_runtime(provider))
    checks.append(_check_provider_ping())
    checks.extend(_check_task_sources(task_sources))
    checks.append(_check_repo_paths(specs))
    checks.extend(_check_runtime_tooling(specs))
    checks.extend(_check_setup_plans(specs))
    runtime_counts = Counter((spec.runtime_family or spec.language or "unknown").lower() for spec in specs)
    requires_network = sum(1 for spec in specs if spec.requires_network)
    provider_metadata: Dict[str, object] = {"provider": provider, "model": model}
    report = PreflightReport(
        provider=provider,
        model=model,
        mode=mode,
        task_sources=[str(src) for src in task_sources],
        task_count=len(specs),
        checks=checks,
        runtime_counts=dict(runtime_counts),
        requires_network=requires_network,
        provider_metadata=provider_metadata,
    )
    for check in checks:
        if check.name == "provider_ping":
            provider_metadata["ping"] = check.details
        if check.name == "provider_runtime":
            provider_metadata["runtime"] = check.details
    return report


def write_preflight_report(report: PreflightReport, json_path: Path, md_path: Path) -> None:
    json_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    lines = [
        "# Real Repo Benchmark Preflight",
        "",
        f"- Mode: {report.mode}",
        f"- Provider: {report.provider}",
        f"- Model: {report.model}",
        f"- Task sources: {', '.join(report.task_sources) or 'n/a'}",
        f"- Tasks detected: {report.task_count}",
        f"- Runtime families: {report.runtime_counts}",
        f"- Tasks requiring network: {report.requires_network}",
        "",
        "| Check | Status | Message |",
        "| --- | --- | --- |",
    ]
    for check in report.checks:
        status = "PASS" if check.ok else "FAIL"
        lines.append(f"| {check.name} | {status} | {check.message} |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


__all__ = ["PreflightCheck", "PreflightReport", "run_preflight_checks", "write_preflight_report"]
