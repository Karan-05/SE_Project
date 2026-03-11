"""Solver that drafts repository patches or patch plans."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.providers import llm

from ..formatting import (
    JsonExtractionOutcome,
    SENTINEL_BEGIN,
    SENTINEL_END,
    extract_json_or_repair,
    build_strict_repair_prompt,
)
from ..parsing import JsonExtractionError
from ..prompts import (
    ArtifactRequest,
    STRICT_JSON_CONTRACT,
    UNIVERSAL_AGENT_PROMPT,
    build_universal_agent_prompt,
    parse_universal_agent_response,
)
from ..task_router import TaskType
from ..verifiers import RepoVerifier, RubricVerifier
from .base import BaseSolver, SolverContext, SolverResult, resolve_run_id, sanitize_task_id


class RepoPatchSolver:
    """Generate diffs + plans for repository maintenance tasks."""

    name = "repo_patch"
    supported_types = (TaskType.REPO_PATCH, TaskType.API_BACKEND)

    def __init__(self, rubric: RubricVerifier, repo_verifier: RepoVerifier):
        self.rubric = rubric
        self.repo_verifier = repo_verifier

    def solve(self, ctx: SolverContext) -> SolverResult:
        start_calls = llm.total_calls()
        repo_path = self._locate_repo(ctx)
        metadata = ctx.task.setdefault("metadata", {})
        repo_unavailable = repo_path is None
        metadata["repo_unavailable"] = repo_unavailable
        if not metadata.get("insufficient_context"):
            metadata["insufficient_context"] = not bool(ctx.task.get("problem_statement"))
        metadata.setdefault("universal_prompt", UNIVERSAL_AGENT_PROMPT)
        try:
            payload, extraction = self._request_patch(ctx, repo_path)
        except JsonExtractionError as exc:
            llm_calls_used = max(0, llm.total_calls() - start_calls)
            raw_path = getattr(exc, "raw_agent_path", None)
            repaired_path = getattr(exc, "repaired_agent_path", None)
            diag_path = getattr(exc, "diagnostics_path", None)
            return self._parse_failure_result(ctx, str(exc), llm_calls_used, raw_path, repaired_path, diag_path)
        agent_task_type = str(payload.get("task_type") or TaskType.REPO_PATCH.value)
        metadata["solver_reported_task_type"] = agent_task_type
        summary_text = str(payload.get("summary") or "").strip()
        artifact_bundle: Dict[str, object] = payload.get("artifacts", {}) if isinstance(payload.get("artifacts"), dict) else {}
        if agent_task_type == TaskType.NON_ACTIONABLE.value:
            llm_calls_used = max(0, llm.total_calls() - start_calls)
            return self._non_actionable_result(
                ctx,
                payload,
                extraction.raw_path,
                extraction.repair_path,
                extraction.diagnostics_path,
                llm_calls_used,
            )
        plan_text, test_plan_text, risks_text = self._compose_plan(summary_text, artifact_bundle)
        diff_text = self._extract_diff_text(artifact_bundle)
        if not diff_text:
            diff_text = self._build_diff_stub(ctx, plan_text)
        patch_path = self._write_patch(ctx, diff_text or plan_text)
        summary_path = self._write_summary(ctx, plan_text, suffix="_patch")
        test_plan_path = self._write_summary(ctx, test_plan_text or "- Tests pending", suffix="_test_plan")
        risks_path = self._write_summary(ctx, risks_text or "- Risks pending", suffix="_risks")
        agent_payload_path = self._write_json_artifact(ctx, payload or {}, suffix="_agent_payload")
        self_check_path = self._write_json_artifact(ctx, payload.get("rubric_self_check") or {}, suffix="_agent_self_check")
        reflections_path = self._write_summary(
            ctx,
            "- Reflections captured via rubric self-check.",
            suffix="_reflections",
        )
        repo_log_path, repo_success = self._run_repo_checks(ctx, repo_path)
        rubric_name = "api_backend" if agent_task_type == TaskType.API_BACKEND.value else "repo_patch"
        rubric_result = self.rubric.evaluate(
            task=ctx.task,
            deliverable_text=plan_text,
            rubric_name=rubric_name,
            required_sections=["Problem Summary", "Plan", "Risks", "Validation"],
            artifacts={
                "patch_plan.md": plan_text,
                "proposed_patch.diff": diff_text,
                "test_plan.md": test_plan_text,
                "risks.md": risks_text,
            },
        )
        llm_calls_used = max(0, llm.total_calls() - start_calls)
        status = "completed_patch" if rubric_result.passes_threshold and repo_success else "failed_patch"
        error_type = "success" if status == "completed_patch" else ("repo_checks_failed" if not repo_success else "failed_rubric")
        artifacts = {
            "patch_path": str(patch_path),
            "deliverable_path": str(summary_path),
            "test_plan_path": str(test_plan_path),
            "risks_path": str(risks_path),
            "repo_log_path": str(repo_log_path),
            "rubric_path": str(rubric_result.path),
            "classification_path": str(agent_payload_path),
            "verification_path": str(self_check_path),
            "reflections_path": str(reflections_path),
            "raw_agent_response_path": str(extraction.raw_path),
            "repaired_agent_response_path": str(extraction.repair_path) if extraction.repair_path else "",
            "agent_parse_diagnostics_path": str(extraction.diagnostics_path),
        }
        notes = "Repo unavailable; produced patch plan only." if repo_path is None else ""
        metrics = {
            "rubric_reasons": rubric_result.reasons,
            "rubric_missing": rubric_result.missing,
            "repo_checks_passed": repo_success,
            "repo_unavailable": repo_unavailable,
            "insufficient_context": bool(metadata.get("insufficient_context")),
            "agent_task_type": agent_task_type,
            "agent_summary": summary_text,
            "agent_rubric_self_check": payload.get("rubric_self_check") or {},
            "agent_parse_source": extraction.source,
            "agent_parse_used_repair": extraction.used_repair,
        }
        return SolverResult(
            status=status,
            error_type=error_type,
            verifier_type="rubric_repo_patch",
            verifier_name=rubric_name,
            verifier_score=rubric_result.score,
            artifacts=artifacts,
            metrics=metrics,
            deliverable_success=rubric_result.passes_threshold,
            llm_calls_used=float(llm_calls_used),
            notes=notes,
        )

    def _request_patch(self, ctx: SolverContext, repo_path: Optional[Path]) -> Tuple[Dict[str, object], JsonExtractionOutcome]:
        statement = str(ctx.task.get("problem_statement") or ctx.task.get("statement") or "")[:4000]
        repo_info = f"Local repo available at {repo_path}" if repo_path else "No local repo provided"
        run_id = resolve_run_id(ctx)
        repair_builder = lambda broken: build_strict_repair_prompt(
            broken,
            schema_hint=STRICT_JSON_CONTRACT,
            solver_name=self.name,
            task_id=ctx.task_id,
            run_id=run_id,
        )
        if llm.CONFIG.provider == "mock":
            payload = self._mock_patch_payload(ctx, statement)
            mock_text = f"{SENTINEL_BEGIN}\n{json.dumps(payload)}\n{SENTINEL_END}"
            extraction = extract_json_or_repair(
                mock_text,
                llm_client=None,
                repair_prompt_builder=repair_builder,
                artifact_dir=ctx.deliverables_dir,
                task_id=ctx.task_id,
                run_id=run_id,
                max_repairs=0,
            )
            parsed = parse_universal_agent_response(extraction.payload)
            return parsed, extraction
        prompt = build_universal_agent_prompt(
            task=ctx.task,
            solver_name=self.name,
            task_type_hint="repo_patch",
            instructions=(
                "Follow the router rationale and craft a concrete repository plan. "
                "Explicitly call out file/module impacts and acceptance criteria."
            ),
            artifacts=[
                ArtifactRequest("patch_plan.md", "md", "Must include Problem Summary, Plan, Test Plan, Risks, Validation."),
                ArtifactRequest("proposed_patch.diff", "diff", "Unified diff with ```diff fences or precise pseudo-diff."),
                ArtifactRequest("test_plan.md", "md", "Commands/tests + expected results."),
                ArtifactRequest("risks.md", "md", "Risks, mitigations, rollback."),
            ],
            verification_expectations=[
                "State whether repo context present or missing.",
                "Explain how to validate the diff/plan.",
                "Emit PASS_FINAL only when repo context + commands succeed; otherwise DELIVERABLE_PASS.",
            ],
            additional_inputs={
                "router_rationale": ctx.decision.rationale if ctx.decision else "",
                "repo_context": repo_info,
            },
            extra_context=statement,
        )
        response = llm.call(
            prompt,
            max_tokens=900,
            temperature=0.35,
            caller="repo_patch_solver",
        )
        raw_text = response.content or ""
        extraction = extract_json_or_repair(
            raw_text,
            llm_client=llm,
            repair_prompt_builder=repair_builder,
            artifact_dir=ctx.deliverables_dir,
            task_id=ctx.task_id,
            run_id=run_id,
        )
        payload = parse_universal_agent_response(extraction.payload)
        return payload, extraction

    def _write_patch(self, ctx: SolverContext, diff_text: str) -> Path:
        ctx.patches_dir.mkdir(parents=True, exist_ok=True)
        safe = sanitize_task_id(ctx.task_id)
        path = ctx.patches_dir / f"{safe}.diff"
        message = diff_text.strip() or "# Patch plan unavailable"
        path.write_text(message, encoding="utf-8")
        return path

    def _build_diff_stub(self, ctx: SolverContext, plan_text: str) -> str:
        note = "Proposed diff (synthetic stub — repository unavailable)"
        plan_lines = [line.strip() for line in plan_text.splitlines() if line.strip().startswith("- ")]
        summary = plan_lines[:2] or ["- Refer to step-by-step plan above."]
        stub = [
            f"# {note}",
            "```diff",
            "--- a/placeholder.txt",
            "+++ b/placeholder.txt",
        ]
        for line in summary:
            stub.append(f"+{line.lstrip('- ').strip()}")
        stub.append("```")
        return "\n".join(stub)

    def _write_summary(self, ctx: SolverContext, text: str, suffix: str = "") -> Path:
        ctx.deliverables_dir.mkdir(parents=True, exist_ok=True)
        safe = sanitize_task_id(ctx.task_id)
        appendix = f"{suffix}" if suffix else ""
        path = ctx.deliverables_dir / f"{safe}{appendix}.md"
        message = text.strip()
        if not message:
            message = (
                "## Problem Summary\nPending details.\n\n"
                "## Step-by-step Plan\n- Identify impacted modules\n- Draft update per requirements\n\n"
                "## Test Plan\n- List unit/integration tests to run\n\n"
                "## Risks\n- Pending analysis\n\n"
                "## Validation\n- Pending tests\n"
            )
        path.write_text(message, encoding="utf-8")
        return path

    def _write_json_artifact(self, ctx: SolverContext, payload: Dict[str, object], suffix: str) -> Path:
        ctx.deliverables_dir.mkdir(parents=True, exist_ok=True)
        safe = sanitize_task_id(ctx.task_id)
        path = ctx.deliverables_dir / f"{safe}{suffix}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def _safe_list(self, value: object) -> List[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    def _extract_diff_text(self, artifacts: Dict[str, object]) -> str:
        for key in ("patch_diff_unified", "patch_unified_diff", "patch_diff", "diff_unified"):
            value = artifacts.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _compose_plan(self, summary: str, artifacts: Dict[str, object]) -> Tuple[str, str, str]:
        file_plan_entries = self._extract_entries(
            artifacts,
            primary_keys=("file_plan",),
            fallback_keys=("files_touched", "files_impacted"),
        )
        files = self._derive_file_names(file_plan_entries) or file_plan_entries
        tests = self._extract_entries(
            artifacts,
            primary_keys=("test_plan",),
            fallback_keys=("tests_to_run", "validation_commands"),
        )
        risks = self._extract_entries(
            artifacts,
            primary_keys=("risks",),
            fallback_keys=("risk_notes",),
        )
        plan_entries = file_plan_entries or files
        plan_lines = [
            "## Problem Summary",
            summary or "Pending summary based on router context.",
            "## Files / Modules",
        ]
        plan_lines.extend(f"- {entry}" for entry in (files or ["Pending file map."]))
        plan_lines.append("## Plan")
        plan_lines.extend(f"- {entry}" for entry in (plan_entries or ["Pending repository plan."]))
        plan_lines.append("## Risks")
        plan_lines.extend(f"- {note}" for note in (risks or ["Pending risk assessment."]))
        plan_lines.append("## Validation")
        plan_lines.extend(f"- {cmd}" for cmd in (tests or ["Pending validation commands."]))
        plan_text = "\n".join(plan_lines)
        test_plan_lines = ["## Test Plan"]
        test_plan_lines.extend(f"- {cmd}" for cmd in (tests or ["Pending tests."]))
        risks_lines = ["## Risks"]
        risks_lines.extend(f"- {note}" for note in (risks or ["Pending risk assessment."]))
        return plan_text, "\n".join(test_plan_lines), "\n".join(risks_lines)

    def _extract_entries(
        self,
        artifacts: Dict[str, object],
        *,
        primary_keys: Tuple[str, ...],
        fallback_keys: Tuple[str, ...] = (),
    ) -> List[str]:
        keys = primary_keys + fallback_keys
        for key in keys:
            if key not in artifacts:
                continue
            entries = self._normalize_entries(artifacts.get(key))
            if entries:
                return entries
        return []

    def _normalize_entries(self, value: object) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            entries = []
            for item in value:
                text = str(item).strip()
                if text:
                    entries.extend(self._normalize_entries(text))
            return [entry for entry in entries if entry]
        if isinstance(value, str):
            parts = [segment.strip(" -*•") for segment in value.splitlines() if segment.strip()]
            if parts:
                return parts
            text = value.strip()
            return [text] if text else []
        text = str(value).strip()
        return [text] if text else []

    def _derive_file_names(self, plan_entries: List[str]) -> List[str]:
        files: List[str] = []
        for entry in plan_entries:
            candidate = entry
            for separator in ("–", "-", "—", ":"):
                if separator in entry:
                    candidate = entry.split(separator, 1)[0].strip()
                    break
            candidate = candidate.strip()
            if candidate and candidate not in files:
                files.append(candidate)
        return files

    def _non_actionable_result(
        self,
        ctx: SolverContext,
        payload: Dict[str, object],
        raw_path: Path,
        repaired_path: Optional[Path],
        diag_path: Optional[Path],
        llm_calls_used: float,
    ) -> SolverResult:
        artifacts_map = payload.get("artifacts") or {}
        reason = str(artifacts_map.get("reason") or "Router-classified as non-actionable.")
        needed = self._safe_list(artifacts_map.get("what_needed"))
        content_lines = [
            "# Non-actionable Task",
            "",
            f"Reason: {reason}",
            "",
            "## Information Needed to Proceed",
        ]
        content_lines.extend(f"- {item}" for item in (needed or ["Provide repo/API/data references and acceptance criteria."]))
        blocked_path = self._write_summary(ctx, "\n".join(content_lines), suffix="_blocked")
        agent_payload_path = self._write_json_artifact(ctx, payload or {}, suffix="_agent_payload")
        self_check_path = self._write_json_artifact(ctx, payload.get("rubric_self_check") or {}, suffix="_agent_self_check")
        artifacts = {
            "deliverable_path": str(blocked_path),
            "classification_path": str(agent_payload_path),
            "verification_path": str(self_check_path),
            "raw_agent_response_path": str(raw_path) if raw_path else "",
            "repaired_agent_response_path": str(repaired_path) if repaired_path else "",
            "agent_parse_diagnostics_path": str(diag_path) if diag_path else "",
        }
        metrics = {
            "agent_task_type": payload.get("task_type", ""),
            "agent_summary": payload.get("summary", ""),
            "agent_rubric_self_check": payload.get("rubric_self_check") or {},
            "non_actionable_reason": reason,
        }
        return SolverResult(
            status="skipped_non_actionable",
            error_type="non_actionable",
            verifier_type="rubric_repo_patch",
            verifier_name="repo_patch",
            verifier_score=0.0,
            artifacts=artifacts,
            metrics=metrics,
            deliverable_success=False,
            llm_calls_used=llm_calls_used,
            notes="Agent flagged task as non-actionable.",
        )

    def _parse_failure_result(
        self,
        ctx: SolverContext,
        message: str,
        llm_calls_used: float,
        raw_path: Optional[Path],
        repaired_path: Optional[Path],
        diag_path: Optional[Path],
    ) -> SolverResult:
        artifacts = {
            "raw_agent_response_path": str(raw_path) if raw_path else "",
            "repaired_agent_response_path": str(repaired_path) if repaired_path else "",
            "agent_parse_diagnostics_path": str(diag_path) if diag_path else "",
        }
        metrics = {"parse_error": message}
        return SolverResult(
            status="failed_patch",
            error_type="deliverable_parse_error",
            verifier_type="rubric_repo_patch",
            verifier_name="repo_patch",
            verifier_score=0.0,
            artifacts=artifacts,
            metrics=metrics,
            deliverable_success=False,
            llm_calls_used=llm_calls_used,
            notes="Universal agent response was not valid JSON.",
        )

    def _run_repo_checks(self, ctx: SolverContext, repo_path: Optional[Path]):
        if repo_path and repo_path.exists():
            result = self.repo_verifier.run(ctx.task_id, repo_path)
            return result.log_path, result.success
        ctx.repo_logs_dir.mkdir(parents=True, exist_ok=True)
        safe = sanitize_task_id(ctx.task_id)
        path = ctx.repo_logs_dir / f"{safe}.json"
        path.write_text(
            json.dumps(
                {
                    "task_id": ctx.task_id,
                    "success": True,
                    "commands": [],
                    "details": [{"info": "repo path unavailable; only produced plan"}],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return path, True

    def _locate_repo(self, ctx: SolverContext) -> Optional[Path]:
        metadata = ctx.task.get("metadata", {}) or {}
        for key in ("repo_path", "repository_path", "repo_dir", "repo"):
            candidate = metadata.get(key)
            if not candidate:
                continue
            path = Path(candidate)
            if path.exists():
                return path
        return None

    def _mock_patch_payload(self, ctx: SolverContext, statement: str) -> Dict[str, object]:
        summary = (statement or "Fix regression described in challenge statement.").strip()
        diff = (
            "diff --git a/service/handler.py b/service/handler.py\n"
            "--- a/service/handler.py\n"
            "+++ b/service/handler.py\n"
            "@@\n"
            "-    result = legacy_api(payload)\n"
            "+    result = modern_api(payload)\n"
        )
        title = str(ctx.task.get("title") or "Mock Repo Patch")
        return {
            "task_type": TaskType.REPO_PATCH.value,
            "id": ctx.task_id,
            "title": title,
            "summary": summary[:400],
            "assumptions": ["Mock payload emitted because provider=mock."],
            "plan": [
                "Review router rationale + repo availability.",
                "Draft diff touching affected files with validation commands.",
                "Enumerate risks and rollback guidance.",
            ],
            "artifacts": {
                "patch_diff_unified": diff,
                "file_plan": [
                    "service/handler.py – swap legacy_api for modern_api",
                    "tests/test_handler.py – cover regression scenario",
                ],
                "test_plan": [
                    "pytest tests/test_handler.py",
                    "npm run lint",
                ],
                "risks": [
                    "Monitor modern_api latency before fully cutting over",
                    "Rollback by redeploying previous tag if error rate increases",
                ],
            },
            "validations": ["SELF_CHECK: Mock diff/test plan generated for demonstration."],
            "confidence": 0.5,
            "stop_reason": "completed",
            "rubric_self_check": {
                "coverage": 50,
                "specificity": 50,
                "actionability": 50,
                "overall_notes": "Mock provider synthesized diff/tests/risks.",
            },
        }
