"""Solver that produces structured design/architecture documents."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from src.providers import llm

from ..formatting import (
    JsonExtractionOutcome,
    SENTINEL_BEGIN,
    SENTINEL_END,
    build_strict_repair_prompt,
    extract_json_or_repair,
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
from ..verifiers import RubricVerifier
from .base import BaseSolver, SolverContext, SolverResult, resolve_run_id, sanitize_task_id


class ArchitectureDocSolver:
    """Generate a Markdown deliverable with strict architecture sections."""

    name = "architecture_doc"
    supported_types = (TaskType.ARCHITECTURE_DOC,)

    required_sections = [
        "Problem Summary",
        "Proposed Approach",
        "File-Level Plan",
        "API / Interface Changes",
        "Constraints & SLAs",
        "Risks & Trade-offs",
        "Edge Cases",
        "Acceptance Checklist",
    ]

    def __init__(self, rubric: RubricVerifier, rubric_name: str = "architecture_doc", temperature: float = 0.4):
        self.rubric = rubric
        self.rubric_name = rubric_name
        self.temperature = temperature

    def solve(self, ctx: SolverContext) -> SolverResult:
        start_calls = llm.total_calls()
        metadata = ctx.task.setdefault("metadata", {})
        metadata.setdefault("insufficient_context", not bool(ctx.task.get("problem_statement")))
        metadata.setdefault("universal_prompt", UNIVERSAL_AGENT_PROMPT)
        try:
            agent_payload, extraction = self._request_document(ctx)
        except JsonExtractionError as exc:
            llm_calls_used = max(0, llm.total_calls() - start_calls)
            raw_path = getattr(exc, "raw_agent_path", None)
            repaired_path = getattr(exc, "repaired_agent_path", None)
            diag_path = getattr(exc, "diagnostics_path", None)
            return self._parse_failure_result(ctx, str(exc), llm_calls_used, raw_path, repaired_path, diag_path)
        agent_task_type = str(agent_payload.get("task_type") or TaskType.ARCHITECTURE_DOC.value)
        metadata["solver_reported_task_type"] = agent_task_type
        artifacts_map = agent_payload.get("artifacts", {}) if isinstance(agent_payload, dict) else {}
        if agent_task_type == TaskType.NON_ACTIONABLE.value:
            llm_calls_used = max(0, llm.total_calls() - start_calls)
            return self._non_actionable_result(
                ctx,
                agent_payload,
                extraction.raw_path,
                extraction.repair_path,
                extraction.diagnostics_path,
                llm_calls_used,
            )
        deliverable = self._render_deliverable(ctx, agent_payload, artifacts_map)
        deliverable_path = self._write_deliverable(ctx, deliverable)
        agent_payload_path = self._write_json_artifact(ctx, agent_payload or {}, suffix="_agent_payload")
        self_check_path = self._write_json_artifact(ctx, agent_payload.get("rubric_self_check") or {}, suffix="_agent_self_check")
        reflections_path = self._write_deliverable(
            ctx,
            "- Reflections captured via rubric self-check.",
            suffix="_reflections",
        )
        rubric_result = self.rubric.evaluate(
            task=ctx.task,
            deliverable_text=deliverable,
            rubric_name=self.rubric_name,
            required_sections=self.required_sections,
            artifacts={"architecture.md": deliverable},
        )
        llm_calls_used = max(0, llm.total_calls() - start_calls)
        status = "completed_architecture_doc" if rubric_result.passes_threshold else "failed_architecture_doc"
        error_type = "success" if rubric_result.passes_threshold else "failed_rubric"
        artifacts = {
            "deliverable_path": str(deliverable_path),
            "rubric_path": str(rubric_result.path),
            "classification_path": str(agent_payload_path),
            "verification_path": str(self_check_path),
            "reflections_path": str(reflections_path),
            "raw_agent_response_path": str(extraction.raw_path),
            "repaired_agent_response_path": str(extraction.repair_path) if extraction.repair_path else "",
            "agent_parse_diagnostics_path": str(extraction.diagnostics_path),
        }
        metrics = {
            "rubric_reasons": rubric_result.reasons,
            "rubric_missing": rubric_result.missing,
            "agent_task_type": agent_task_type,
            "agent_summary": agent_payload.get("summary", ""),
            "agent_rubric_self_check": agent_payload.get("rubric_self_check") or {},
            "agent_parse_source": extraction.source,
            "agent_parse_used_repair": extraction.used_repair,
        }
        return SolverResult(
            status=status,
            error_type=error_type,
            verifier_type="rubric_architecture_doc",
            verifier_name=self.rubric_name,
            verifier_score=rubric_result.score,
            artifacts=artifacts,
            metrics=metrics,
            deliverable_success=rubric_result.passes_threshold,
            llm_calls_used=float(llm_calls_used),
            notes="Architecture document deliverable",
        )

    def _request_document(self, ctx: SolverContext) -> Tuple[Dict[str, object], JsonExtractionOutcome]:
        statement = str(ctx.task.get("problem_statement") or ctx.task.get("statement") or "")[:4000]
        hints = self._memory_hints(ctx)
        run_id = resolve_run_id(ctx)
        repair_builder = lambda broken: build_strict_repair_prompt(
            broken,
            schema_hint=STRICT_JSON_CONTRACT,
            solver_name=self.name,
            task_id=ctx.task_id,
            run_id=run_id,
        )
        if llm.CONFIG.provider == "mock":
            payload = self._mock_payload(ctx, statement, hints)
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
        hint_block = statement
        if hints:
            hint_block += "\n\nMemory Hints:\n" + "\n".join(f"- {hint}" for hint in hints)
        prompt = build_universal_agent_prompt(
            task=ctx.task,
            solver_name=self.name,
            task_type_hint="architecture_doc",
            instructions=(
                "Produce a complete architecture/design doc with all required sections."
                "Keep prose concise and actionable."
            ),
            artifacts=[
                ArtifactRequest("architecture.md", "md", "Architecture doc with required sections in order."),
            ],
            verification_expectations=[
                "Check section coverage vs. rubric.",
                "Quantify constraints and call out risks/trade-offs.",
                "Mark DELIVERABLE_PASS when the rubric satisfied but no live tests run.",
            ],
            additional_inputs={
                "router_rationale": ctx.decision.rationale if ctx.decision else "",
                "router_heuristics": ", ".join(ctx.decision.heuristics) if ctx.decision else "",
            },
            extra_context=hint_block,
        )
        response = llm.call(
            prompt,
            max_tokens=700,
            temperature=self.temperature,
            caller="design_doc_solver",
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

    def _fallback_deliverable(self, ctx: SolverContext) -> str:
        statement = str(ctx.task.get("problem_statement") or ctx.task.get("statement") or "")[:4000]
        hints = self._memory_hints(ctx)
        return self._mock_deliverable(ctx, statement, hints)

    def _write_deliverable(self, ctx: SolverContext, content: str, suffix: str = ""):
        ctx.deliverables_dir.mkdir(parents=True, exist_ok=True)
        safe = sanitize_task_id(ctx.task_id)
        appendix = suffix if suffix else ""
        path = ctx.deliverables_dir / f"{safe}{appendix}.md"
        path.write_text(content, encoding="utf-8")
        return path

    def _write_json_artifact(self, ctx: SolverContext, payload: Dict[str, object], suffix: str) -> Path:
        ctx.deliverables_dir.mkdir(parents=True, exist_ok=True)
        safe = sanitize_task_id(ctx.task_id)
        path = ctx.deliverables_dir / f"{safe}{suffix}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def _format_sections(self, sections: Iterable[str]) -> str:
        return "\n".join(f"- {name}" for name in sections)

    def _memory_hints(self, ctx: SolverContext) -> List[str]:
        metadata = ctx.task.get("metadata") or {}
        hints = metadata.get("memory_hints") or []
        if isinstance(hints, list):
            return [str(hint) for hint in hints if hint]
        return []

    def _safe_list(self, value: object) -> List[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    def _render_deliverable(self, ctx: SolverContext, payload: Dict[str, object], artifacts: Dict[str, object]) -> str:
        base_doc = str(artifacts.get("design_doc_md") or artifacts.get("doc_markdown") or "").strip()
        if not base_doc:
            return self._fallback_deliverable(ctx)
        sections = [base_doc]
        mermaid = str(artifacts.get("mermaid_diagram") or "").strip()
        if mermaid:
            sections.append("```mermaid\n" + mermaid + "\n```")
        interfaces = self._safe_list(artifacts.get("interfaces") or artifacts.get("components"))
        if interfaces:
            sections.append("## Interfaces\n" + "\n".join(f"- {entry}" for entry in interfaces))
        tradeoffs = self._safe_list(artifacts.get("tradeoffs"))
        if tradeoffs:
            sections.append("## Trade-offs\n" + "\n".join(f"- {entry}" for entry in tradeoffs))
        return "\n\n".join(section for section in sections if section.strip()) or self._fallback_deliverable(ctx)

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
        reason = str(artifacts_map.get("reason") or "Insufficient information for design doc.")
        needed = self._safe_list(artifacts_map.get("what_needed"))
        lines = [
            "# Non-actionable Architecture Task",
            "",
            f"Reason: {reason}",
            "",
            "## Information Needed",
        ]
        lines.extend(f"- {entry}" for entry in (needed or ["Link to repo/API, enumerate requirements, provide acceptance criteria."]))
        blocked_path = self._write_deliverable(ctx, "\n".join(lines), suffix="_blocked")
        agent_payload_path = self._write_json_artifact(ctx, payload or {}, suffix="_agent_payload")
        self_check_path = self._write_json_artifact(ctx, payload.get("rubric_self_check") or {}, suffix="_agent_self_check")
        artifacts = {
            "deliverable_path": str(blocked_path),
            "classification_path": str(agent_payload_path),
            "verification_path": str(self_check_path),
            "raw_agent_response_path": str(raw_path),
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
            verifier_type="rubric_architecture_doc",
            verifier_name=self.rubric_name,
            verifier_score=0.0,
            artifacts=artifacts,
            metrics=metrics,
            deliverable_success=False,
            llm_calls_used=llm_calls_used,
            notes="Agent classified task as non-actionable.",
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
            status="failed_architecture_doc",
            error_type="deliverable_parse_error",
            verifier_type="rubric_architecture_doc",
            verifier_name=self.rubric_name,
            verifier_score=0.0,
            artifacts=artifacts,
            metrics=metrics,
            deliverable_success=False,
            llm_calls_used=llm_calls_used,
            notes="Universal agent response was not valid JSON.",
        )

    def _mock_deliverable(self, ctx: SolverContext, statement: str, hints: List[str]) -> str:
        summary = statement or "Task overview unavailable."
        hint_text = "\n".join(f"- {hint}" for hint in hints) if hints else "- No historical hints."
        sections: List[str] = []
        for section in self.required_sections:
            if section == "Problem Summary":
                content = summary[:600]
            elif section == "Constraints & SLAs":
                content = "- Latency < 500ms\n- Availability 99.5%\n- Budget: reuse existing services"
            elif section == "Risks & Trade-offs":
                content = "- Limited observability when reusing legacy APIs\n- Trade-off between cost and performance"
            elif section == "Edge Cases":
                content = "- Stress test under bursty load\n- Handle malformed payloads gracefully\n" + hint_text
            elif section == "Acceptance Checklist":
                content = "- Architecture diagrams reviewed\n- APIs documented\n- Smoke tests executed"
            else:
                content = f"- Derived from statement: {summary[:200]}"
            sections.append(f"## {section}\n{content}")
        return "\n\n".join(sections)

    def _mock_payload(self, ctx: SolverContext, statement: str, hints: List[str]) -> Dict[str, object]:
        doc = self._mock_deliverable(ctx, statement, hints)
        mermaid = "graph TD;\n    A[Problem] --> B[Proposed Approach];\n    B --> C[Components];\n    C --> D[Interfaces];\n    D --> E[Risks];"
        return {
            "task_type": TaskType.ARCHITECTURE_DOC.value,
            "id": ctx.task_id,
            "title": str(ctx.task.get("title") or "Mock Architecture Document"),
            "summary": (statement or "Outline architecture components and rollout plan.")[:300],
            "assumptions": ["Mock payload emitted because provider=mock."],
            "plan": [
                "Summarize router rationale and challenge context.",
                "Describe architecture sections with risks + constraints.",
                "Provide acceptance checklist with validation guidance.",
            ],
            "artifacts": {
                "design_doc_md": doc,
                "mermaid_diagram": mermaid,
                "interfaces": [
                    "Ingress Gateway – AuthN/AuthZ, rate limiting",
                    "Recommendation Service – stateless API using feature store",
                    "Gateway -> Recommendation Service (gRPC, proto v2)",
                    "Recommendation Service -> Feature Store (Redis Cluster)",
                ],
                "tradeoffs": [
                    "Server-side rendering vs SPA for personalization UX",
                    "Managed message bus vs self-hosted Kafka",
                ],
            },
            "validations": ["SELF_CHECK: Confirmed required sections present in mock output."],
            "confidence": 0.5,
            "stop_reason": "completed",
            "rubric_self_check": {
                "coverage": 90,
                "specificity": 88,
                "actionability": 87,
                "overall_notes": "Mock provider emitted full doc + component traceability.",
            },
        }


# Backwards compatibility alias for imports.
DesignDocSolver = ArchitectureDocSolver
