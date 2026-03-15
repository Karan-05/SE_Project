"""Workspace + execution harness for repo-backed tasks."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
from fnmatch import fnmatch

from src.decomposition.agentic.executor import ExecutionResult
from src.decomposition.interfaces import DecompositionContext
from src.decomposition.self_verify import summarize_failures
from src.decomposition.real_repo.edit_batch import (
    RepoEditBatch,
    parse_repo_edit_payload,
    parse_repo_edit_payload_with_diagnostics,
)
from src.decomposition.real_repo.lint import lint_repo_edit_payload
from src.decomposition.real_repo.task import RepoTaskSpec
from src.decomposition.real_repo.setup import resolve_setup_plan, SetupPlan
from src.decomposition.real_repo.ground_truth import load_ground_truth_files
from src.config import PROJECT_ROOT


def _as_shell_command(cmd: str | List[str]) -> List[str]:
    if isinstance(cmd, list):
        return cmd
    return ["bash", "-lc", cmd]


def _normalize_candidate_entries(*sources: Optional[List[str]]) -> List[str]:
    seen: set[str] = set()
    ordered: List[str] = []
    for source in sources:
        if not source:
            continue
        for entry in source:
            entry_str = str(entry).strip()
            if not entry_str or entry_str in seen:
                continue
            seen.add(entry_str)
            ordered.append(entry_str)
    return ordered


_REPO_FINGERPRINT_CACHE: Dict[str, str] = {}


def _fingerprint_repo(root: Path) -> str:
    root = root.resolve()
    cache_key = str(root)
    cached = _REPO_FINGERPRINT_CACHE.get(cache_key)
    if cached:
        return cached
    digests: List[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.startswith("node_modules/") or rel.startswith(".git/"):
            continue
        if rel.endswith(".pyc") or rel.endswith("~"):
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        digest = hashlib.sha256(rel.encode("utf-8") + b"\0" + data).hexdigest()
        digests.append(digest)
    fingerprint = hashlib.sha256("\n".join(digests).encode("utf-8")).hexdigest()
    _REPO_FINGERPRINT_CACHE[cache_key] = fingerprint
    return fingerprint


@dataclass
class RepoTaskHarness:
    """Manage workspace copies and test execution for repo tasks."""

    task: RepoTaskSpec
    strategy_name: str
    output_root: Path

    def __post_init__(self) -> None:
        self.run_root = (self.output_root / self.task.task_id / self.strategy_name).resolve()
        self.workspace = self.run_root / "workspace"
        self.logs_dir = self.run_root / "logs"
        if self.workspace.exists():
            shutil.rmtree(self.workspace)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.task.repo_path, self.workspace)
        self.round_counter = 0
        self._workspace_root = self.workspace.resolve()
        self.snapshot_record = self._verify_snapshot()
        self.snapshot_ok = bool(self.snapshot_record.get("snapshot_verified", True))
        self.setup_plan: SetupPlan
        self.setup_summary_path = self.logs_dir / "setup_summary.json"
        if not self.snapshot_ok:
            self.setup_plan = SetupPlan(
                commands=[],
                strategy="snapshot_blocked",
                derived=True,
                package_manager=str(self.task.package_manager or ""),
                runtime_family=str(self.task.runtime_family or ""),
                notes={"error": "repo_snapshot_mismatch"},
            )
            error = (
                "Repository snapshot hash mismatch. Expected "
                f"{self.snapshot_record.get('expected_snapshot') or 'n/a'} but saw "
                f"{self.snapshot_record.get('computed_snapshot') or 'n/a'}. "
                "Refresh the repo snapshot before running benchmarks."
            )
            summary = {
                "status": "snapshot_mismatch",
                "duration": 0.0,
                "commands": [],
                "plan": self.setup_plan.to_dict(),
                "steps": [],
                "requires_network": self.task.requires_network,
                "last_log": self.snapshot_record.get("log_path", ""),
                "error": error,
            }
            self.setup_record = summary
            self.setup_ready = False
            self.setup_summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
            return
        self.setup_plan = resolve_setup_plan(self.task, self.workspace)
        self.setup_summary_path = self.logs_dir / "setup_summary.json"
        self.setup_record = self._prepare_workspace()
        self.setup_ready = self.setup_record.get("status") in {"success", "skipped"}

    def _resolve_workspace_path(self, rel_path: Path) -> Path:
        candidate = (self.workspace / rel_path).resolve()
        try:
            candidate.relative_to(self._workspace_root)
        except ValueError as exc:  # pragma: no cover - guard
            raise ValueError(f"Attempted to edit file outside workspace: {rel_path}") from exc
        return candidate

    def _ensure_allowed_path(self, rel_path: Path) -> None:
        allowed = self.task.allowed_edit_paths
        if not allowed:
            return
        rel_str = str(rel_path).replace("\\", "/")
        for pattern in allowed:
            if pattern in {"*", "**"}:
                return
            if fnmatch(rel_str, pattern):
                return
        raise PermissionError(f"Edits to {rel_str} are not allowed for this task.")

    def _verify_snapshot(self) -> Dict[str, object]:
        metadata = self.task.metadata or {}
        expected = str(metadata.get("repo_snapshot_sha256") or "")
        record = {
            "expected_snapshot": expected,
            "computed_snapshot": "",
            "snapshot_verified": True,
        }
        log_path = self.logs_dir / "snapshot_check.json"
        try:
            computed = _fingerprint_repo(self.task.repo_path)
        except Exception as exc:  # pragma: no cover - defensive
            record["computed_snapshot"] = ""
            record["snapshot_verified"] = False
            record["error"] = f"fingerprint_failed:{exc}"
        else:
            record["computed_snapshot"] = computed
            if expected:
                record["snapshot_verified"] = computed == expected
                if not record["snapshot_verified"]:
                    record["error"] = "repo_snapshot_mismatch"
            else:
                record["snapshot_verified"] = True
        record["log_path"] = str(log_path)
        log_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return record

    def _apply_marker_block(self, rel_path: Path, code: str, markers: Optional[Dict[str, str]] = None) -> Path:
        file_path = self._resolve_workspace_path(rel_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Target file {rel_path} not found for marker replacement")
        text = file_path.read_text(encoding="utf-8")
        use_markers = markers or self.task.markers
        begin = use_markers.get("begin", "# BEGIN SOLUTION")
        end = use_markers.get("end", "# END SOLUTION")
        if begin not in text or end not in text:
            raise RuntimeError(f"Markers not found in {rel_path}")
        start_idx = text.index(begin) + len(begin)
        end_idx = text.index(end, start_idx)
        new_block = f"\n{code.strip()}\n"
        new_text = text[:start_idx] + new_block + text[end_idx:]
        file_path.write_text(new_text, encoding="utf-8")
        return rel_path

    def _apply_edit_batch(self, batch: RepoEditBatch) -> List[str]:
        edited: List[str] = []
        backups: Dict[Path, Optional[str]] = {}
        for edit in batch.edits:
            rel_path = Path(edit.path)
            self._ensure_allowed_path(rel_path)
            file_path = self._resolve_workspace_path(rel_path)
            existed = file_path.exists()
            allow_create = bool(edit.allow_create or self.task.allow_file_creation)
            if not existed and not allow_create:
                raise FileNotFoundError(
                    f"Target file {rel_path} missing; set allow_create=true to permit creation."
                )
            if existed and file_path not in backups:
                backups[file_path] = file_path.read_text(encoding="utf-8")
            elif not existed:
                backups[file_path] = None
            try:
                if edit.mode == "rewrite":
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    file_path.write_text(str(edit.content), encoding="utf-8")
                elif edit.mode == "markers":
                    self._apply_marker_block(rel_path, str(edit.content), edit.markers or self.task.markers)
                else:
                    raise ValueError(f"Unsupported edit mode '{edit.mode}' for {rel_path}")
            except Exception:
                # revert touched files
                for back_path, prior in backups.items():
                    if prior is None:
                        if back_path.exists():
                            back_path.unlink()
                    else:
                        back_path.write_text(prior, encoding="utf-8")
                raise
            edited.append(str(rel_path))
        return edited

    def _apply_code(self, code: str) -> Path:
        if not self.task.target_files:
            raise RuntimeError("Repo task missing target_files")
        rel_path = Path(self.task.target_files[0])
        self._ensure_allowed_path(rel_path)
        self._apply_marker_block(rel_path, code)
        return rel_path

    def _log_edit_attempt(
        self,
        *,
        proposed_files: List[str],
        applied_files: List[str],
        status: str,
        metadata: Dict[str, object],
        error: Optional[str] = None,
    ) -> Path:
        payload = {
            "round": self.round_counter,
            "strategy": self.strategy_name,
            "proposed_files": proposed_files,
            "applied_files": applied_files,
            "status": status,
            "metadata": metadata,
            "error": error or "",
            "proposed_file_count": len(proposed_files),
            "applied_file_count": len(applied_files),
            "multi_file_proposed": len(proposed_files) > 1,
            "multi_file_applied": len(applied_files) > 1,
        }
        target = self.logs_dir / f"edits_round{self.round_counter}.json"
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return target

    def _run_command(self, cmd: str, name: str, *, timeout: Optional[float] = None, log_suffix: Optional[str] = None) -> Dict[str, object]:
        timeout_value = timeout if timeout is not None else self.task.timeout_seconds
        env = {**self.task.env}
        env.setdefault("PYTHONPATH", ".")
        env = {str(k): str(v) for k, v in env.items()}
        base_env = os.environ.copy()
        base_env.update(env)
        start = time.perf_counter()
        try:
            proc = subprocess.run(
                _as_shell_command(cmd),
                cwd=self.workspace,
                env=base_env,
                text=True,
                capture_output=True,
                timeout=timeout_value,
            )
            duration = time.perf_counter() - start
            status = "pass" if proc.returncode == 0 else "fail"
            stdout, stderr = proc.stdout, proc.stderr
            returncode = proc.returncode
        except subprocess.TimeoutExpired as exc:  # pragma: no cover - defensive
            duration = time.perf_counter() - start
            status = "timeout"
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            returncode = -1
        suffix = log_suffix or f"round{self.round_counter}"
        log_path = self.logs_dir / f"{name}_{suffix}.log"
        log_path.write_text(
            f"CMD: {cmd}\nSTATUS: {status}\nRETURN: {returncode}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}\n",
            encoding="utf-8",
        )
        return {
            "name": name,
            "status": status,
            "returncode": returncode,
            "stdout": stdout,
            "stderr": stderr,
            "duration": duration,
            "log_path": str(log_path),
        }

    def apply_patch_file(self, patch_path: Path) -> List[str]:
        if not self.snapshot_record.get("snapshot_verified", True):
            expected = self.snapshot_record.get("expected_snapshot") or "n/a"
            computed = self.snapshot_record.get("computed_snapshot") or "n/a"
            raise RuntimeError(
                f"Cannot apply teacher patch because repository snapshot hash mismatch "
                f"(expected {expected}, computed {computed})."
            )
        path = Path(patch_path)
        if not path.is_absolute():
            path = (PROJECT_ROOT / path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Ground-truth patch {path} not found.")
        prefix = ""
        try:
            prefix = str(self.task.repo_path.relative_to(PROJECT_ROOT)).rstrip("/")
        except Exception:
            prefix = ""
        patch_text = path.read_text(encoding="utf-8")
        if prefix:
            patch_text = patch_text.replace(f"{prefix}/", "")
        temp_patch = (self.logs_dir / f"{path.name}.normalized").resolve()
        temp_patch.write_text(patch_text, encoding="utf-8")
        proc = subprocess.run(
            ["patch", "-s", "-p0", "-i", str(temp_patch)],
            cwd=self.workspace,
            text=True,
            capture_output=True,
        )
        patch_log = self.logs_dir / f"{path.stem}_teacher_patch.log"
        patch_log.write_text(
            f"CMD: patch -s -p0 -i {temp_patch}\nSTATUS: {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}\n",
            encoding="utf-8",
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"Failed to apply patch {path}: {proc.stderr or proc.stdout}. See {patch_log}"
            )
        touched: List[str] = []
        for entry in load_ground_truth_files(path):
            entry_path = Path(entry)
            rel: Optional[Path] = None
            try:
                if entry_path.is_absolute():
                    rel = entry_path.relative_to(self.task.repo_path)
                else:
                    rel = (PROJECT_ROOT / entry_path).relative_to(self.task.repo_path)
            except Exception:
                rel = entry_path
            touched.append(rel.as_posix())
        return touched

    def run_build_and_tests(self) -> Dict[str, object]:
        tests: List[Dict[str, object]] = []
        status = "passed"
        compile_failed = False
        for idx, cmd in enumerate(self.task.build_commands):
            record = self._run_command(cmd, f"build_{idx}")
            tests.append(record)
            if record["status"] != "pass":
                status = "build_failed"
                compile_failed = True
                break
        if status == "passed":
            for idx, cmd in enumerate(self.task.test_commands):
                record = self._run_command(cmd, f"tests_{idx}")
                tests.append(record)
                if record["status"] != "pass":
                    status = "tests_failed"
                    break
        pass_rate = 1.0 if status == "passed" else 0.0
        return {
            "status": status,
            "tests": tests,
            "pass_rate": pass_rate,
            "compile_failed": compile_failed,
        }

    def _prepare_workspace(self) -> Dict[str, object]:
        plan = self.setup_plan
        records: List[Dict[str, object]] = []
        status = "skipped"
        duration = 0.0
        last_error = ""
        timeout = self.task.setup_timeout_seconds or max(self.task.timeout_seconds, 300.0)
        if plan.commands:
            status = "success"
            for idx, cmd in enumerate(plan.commands):
                record = self._run_command(cmd, f"setup_{idx}", timeout=timeout, log_suffix="setup")
                records.append(record)
                duration += float(record.get("duration") or 0.0)
                if record["status"] != "pass":
                    status = "failed"
                    last_error = (record.get("stderr") or record.get("stdout") or "").strip()
                    break
        summary = {
            "status": status,
            "duration": duration,
            "commands": plan.commands,
            "plan": plan.to_dict(),
            "steps": records,
            "requires_network": self.task.requires_network,
            "last_log": records[-1]["log_path"] if records else "",
            "error": last_error,
        }
        self.setup_summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary

    def repo_metrics(self) -> Dict[str, object]:
        record = dict(self.setup_record)
        snapshot = dict(self.snapshot_record) if hasattr(self, "snapshot_record") else {}
        return {
            "setup_status": record.get("status", "unknown"),
            "setup_duration": record.get("duration", 0.0),
            "setup_commands": ";".join(record.get("commands", [])),
            "setup_requires_network": 1.0 if self.task.requires_network else 0.0,
            "setup_last_log": record.get("last_log", ""),
            "setup_plan_strategy": record.get("plan", {}).get("strategy", ""),
            "setup_summary_path": str(self.setup_summary_path),
            "repo_snapshot_expected": snapshot.get("expected_snapshot", ""),
            "repo_snapshot_computed": snapshot.get("computed_snapshot", ""),
            "repo_snapshot_ok": 1.0 if snapshot.get("snapshot_verified", True) else 0.0,
            "repo_snapshot_log": snapshot.get("log_path", ""),
        }

    def ensure_ready(self) -> None:
        if self.setup_ready:
            return
        raise RuntimeError(f"Workspace setup failed for {self.task.task_id}: {self.setup_record.get('error')}")

    def __call__(self, *, code: str, ctx: DecompositionContext, subtask_focus: Optional[str] = None) -> ExecutionResult:
        return self.evaluate_attempt(code, ctx, subtask_focus)

    def evaluate_attempt(self, code: str, ctx: DecompositionContext, subtask_focus: Optional[str]) -> ExecutionResult:
        if not self.setup_ready:
            failure = {
                "name": "workspace_setup",
                "status": "fail",
                "error": self.setup_record.get("error") or "workspace setup failed",
                "stdout": "",
                "stderr": self.setup_record.get("error") or "",
                "log_path": self.setup_record.get("last_log", ""),
            }
            summary = summarize_failures([failure])
            return ExecutionResult(
                code=code,
                tests=[failure],
                pass_rate=0.0,
                status="setup_failed",
                duration=0.0,
                summary=summary,
                compile_failed=True,
                edited_files=[],
                proposed_files=[],
                inspected_files=[],
                artifacts={
                    "workspace": str(self.workspace),
                    "logs_dir": str(self.logs_dir),
                    "setup_summary": str(self.setup_summary_path),
                },
                edit_metadata={"setup_failed": True},
            )
        self.round_counter += 1
        attempt_start = time.perf_counter()
        tests: List[Dict[str, object]] = []
        status = "passed"
        compile_failed = False
        edited_files: List[str] = []
        proposed_files: List[str] = []
        edit_log_path: Optional[Path] = None
        task_metadata = ctx.metadata if isinstance(ctx.metadata, dict) else {}
        candidate_files_raw = _normalize_candidate_entries(
            task_metadata.get("repo_candidate_files"),
            task_metadata.get("repo_target_files"),
            task_metadata.get("expected_files"),
        )
        candidate_files_filtered = _normalize_candidate_entries(
            task_metadata.get("implementation_target_files"),
            task_metadata.get("expected_files"),
            task_metadata.get("repo_target_files"),
        )
        if not candidate_files_filtered:
            candidate_files_filtered = list(candidate_files_raw)
        edit_metadata: Dict[str, object] = {
            "raw_edit_payload": code,
            "raw_payload": code,
            "payload_parse_ok": False,
            "payload_parse_error": "",
            "candidate_files_raw": candidate_files_raw,
            "candidate_files_filtered": candidate_files_filtered,
            "candidate_files": candidate_files_filtered or candidate_files_raw,
            "strategy_mode": self.strategy_name,
        }

        try:
            batch, parse_error = parse_repo_edit_payload_with_diagnostics(code)
            if batch and batch.edits:
                proposed_files = batch.proposed_files
                edit_metadata.update(
                    {
                        "edit_mode": "edit_batch",
                        "localized_requested": batch.localized,
                        "fallback_requested": batch.fallback_to_full_regen,
                        "raw_metadata_keys": list(batch.metadata.keys()),
                        "raw_payload": batch.raw_payload,
                        "raw_edit_payload": batch.raw_payload or code,
                        "payload_parse_ok": True,
                        "payload_parse_error": "",
                    }
                )
                contract_review = batch.metadata.get("contract_review")
                if contract_review:
                    edit_metadata["contract_review"] = contract_review
                skipped_targets = batch.metadata.get("skipped_targets")
                if skipped_targets:
                    edit_metadata["skipped_targets"] = skipped_targets
                lint_errors = lint_repo_edit_payload(batch, self.task, task_metadata)
                if lint_errors:
                    edit_metadata["lint_errors"] = lint_errors
                    lint_message = "; ".join(lint_errors)
                    tests.append(
                        {
                            "name": "payload_lint",
                            "status": "fail",
                            "error": lint_message,
                            "stdout": "",
                            "stderr": lint_message,
                        }
                    )
                    status = "lint_failed"
                    compile_failed = True
                    edit_log_path = self._log_edit_attempt(
                        proposed_files=proposed_files,
                        applied_files=edited_files,
                        status="lint_failed",
                        metadata=edit_metadata,
                        error=lint_message,
                    )
                    summary = summarize_failures(tests)
                    return ExecutionResult(
                        code=code,
                        tests=tests,
                        pass_rate=0.0,
                        status=status,
                        duration=time.perf_counter() - attempt_start,
                        summary=summary,
                        compile_failed=compile_failed,
                        edited_files=edited_files,
                        proposed_files=proposed_files,
                        inspected_files=self.task.file_context,
                        artifacts={
                            "workspace": str(self.workspace),
                            "logs_dir": str(self.logs_dir),
                            "edit_log": str(edit_log_path) if edit_log_path else "",
                        },
                            edit_metadata=edit_metadata,
                        )
                edited_files = self._apply_edit_batch(batch)
            else:
                edit_metadata["payload_parse_ok"] = False
                edit_metadata["payload_parse_error"] = parse_error or "no_structured_payload"
                rel_path = self._apply_code(code)
                edited_files.append(str(rel_path))
                proposed_files = [str(rel_path)]
                edit_metadata.update(
                    {
                        "edit_mode": "single_file_markers",
                    }
                )
            applied_count = len(set(edited_files))
            proposed_count = len(set(proposed_files))
            edit_metadata["applied_file_count"] = applied_count
            edit_metadata["proposed_file_count"] = proposed_count
            edit_metadata["multi_file_applied"] = applied_count > 1
            edit_metadata["subtask_focus"] = subtask_focus or "global"
            edit_log_path = self._log_edit_attempt(
                proposed_files=proposed_files,
                applied_files=edited_files,
                status="applied",
                metadata=edit_metadata,
            )
        except Exception as exc:  # pragma: no cover - defensive
            edit_log_path = self._log_edit_attempt(
                proposed_files=proposed_files,
                applied_files=edited_files,
                status="failed",
                metadata=edit_metadata or {"edit_mode": "parse_or_apply_error"},
                error=str(exc),
            )
            tests.append(
                {
                    "name": "apply_patch",
                    "status": "fail",
                    "error": str(exc),
                    "stdout": "",
                    "stderr": "",
                }
            )
            status = "edit_apply_failed"
            compile_failed = True
            summary = summarize_failures(tests)
            return ExecutionResult(
                code=code,
                tests=tests,
                pass_rate=0.0,
                status=status,
                duration=time.perf_counter() - attempt_start,
                summary=summary,
                compile_failed=compile_failed,
                edited_files=edited_files,
                proposed_files=proposed_files,
                inspected_files=self.task.file_context,
                artifacts={
                    "workspace": str(self.workspace),
                    "logs_dir": str(self.logs_dir),
                    "edit_log": str(edit_log_path) if edit_log_path else "",
                },
                edit_metadata=edit_metadata,
            )

        for idx, cmd in enumerate(self.task.build_commands):
            record = self._run_command(cmd, f"build_{idx}")
            tests.append(record)
            if record["status"] != "pass":
                status = "build_failed"
                compile_failed = True
                break

        if status == "passed":
            for idx, cmd in enumerate(self.task.test_commands):
                record = self._run_command(cmd, f"tests_{idx}")
                tests.append(record)
                if record["status"] != "pass":
                    status = "tests_failed"
                    break

        pass_rate = 1.0 if status == "passed" else 0.0
        summary = summarize_failures(tests) if pass_rate < 1.0 else None
        edit_log_path = edit_log_path or self._log_edit_attempt(
            proposed_files=proposed_files or edited_files,
            applied_files=edited_files,
            status=status,
            metadata=edit_metadata,
        )
        return ExecutionResult(
            code=code,
            tests=tests,
            pass_rate=pass_rate,
            status=status,
            duration=time.perf_counter() - attempt_start,
            summary=summary,
            compile_failed=compile_failed,
            edited_files=edited_files,
            proposed_files=proposed_files or edited_files,
            inspected_files=self.task.file_context or self.task.target_files,
            artifacts={
                "workspace": str(self.workspace),
                "logs_dir": str(self.logs_dir),
                "edit_log": str(edit_log_path) if edit_log_path else "",
            },
            edit_metadata=edit_metadata,
        )
