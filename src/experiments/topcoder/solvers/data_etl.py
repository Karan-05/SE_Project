"""Solver focused on data/ETL specifications."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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


class DataETLSolver:
    """Produce ETL blueprints with schema + validation guidance."""

    name = "data_etl"
    supported_types = (TaskType.DATA_ETL,)

    sections = [
        "Problem Summary",
        "Source Data and Schemas",
        "Pipeline Skeleton (Python)",
        "Transformation Steps",
        "Test Strategy & Validation Queries",
        "Sample Outputs",
        "Acceptance Checklist",
    ]

    def __init__(self, rubric: RubricVerifier, rubric_name: str = "data_etl"):
        self.rubric = rubric
        self.rubric_name = rubric_name

    def solve(self, ctx: SolverContext) -> SolverResult:
        start_calls = llm.total_calls()
        metadata = ctx.task.setdefault("metadata", {})
        metadata.setdefault("insufficient_context", not bool(ctx.task.get("problem_statement")))
        metadata.setdefault("universal_prompt", UNIVERSAL_AGENT_PROMPT)
        try:
            agent_payload, extraction = self._request_plan(ctx)
        except JsonExtractionError as exc:
            llm_calls_used = max(0, llm.total_calls() - start_calls)
            raw_path = getattr(exc, "raw_agent_path", None)
            repaired_path = getattr(exc, "repaired_agent_path", None)
            diag_path = getattr(exc, "diagnostics_path", None)
            return self._parse_failure_result(ctx, str(exc), llm_calls_used, raw_path, repaired_path, diag_path)
        agent_task_type = str(agent_payload.get("task_type") or TaskType.DATA_ETL.value)
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
        content = self._render_plan(ctx, agent_payload, artifacts_map)
        deliverable_path = self._write_deliverable(ctx, content)
        agent_payload_path = self._write_json_artifact(ctx, agent_payload or {}, suffix="_agent_payload")
        self_check_path = self._write_json_artifact(ctx, agent_payload.get("rubric_self_check") or {}, suffix="_agent_self_check")
        reflections_path = self._write_deliverable(
            ctx,
            "- Reflections captured via rubric self-check.",
            suffix="_reflections",
        )
        rubric_result = self.rubric.evaluate(
            task=ctx.task,
            deliverable_text=content,
            rubric_name=self.rubric_name,
            required_sections=self.sections,
            artifacts={"data_etl.md": content},
        )
        llm_calls_used = max(0, llm.total_calls() - start_calls)
        status = "completed_data_etl" if rubric_result.passes_threshold else "failed_data_etl"
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
            verifier_type="rubric_data_etl",
            verifier_name=self.rubric_name,
            verifier_score=rubric_result.score,
            artifacts=artifacts,
            metrics=metrics,
            deliverable_success=rubric_result.passes_threshold,
            llm_calls_used=float(llm_calls_used),
            notes="ETL blueprint deliverable",
        )

    def _request_plan(self, ctx: SolverContext) -> Tuple[Dict[str, object], JsonExtractionOutcome]:
        statement = str(ctx.task.get("problem_statement") or ctx.task.get("statement") or "")[:4000]
        title = str(ctx.task.get("title") or "")
        hints = (ctx.task.get("metadata") or {}).get("memory_hints") or []
        run_id = resolve_run_id(ctx)
        repair_builder = lambda broken: build_strict_repair_prompt(
            broken,
            schema_hint=STRICT_JSON_CONTRACT,
            solver_name=self.name,
            task_id=ctx.task_id,
            run_id=run_id,
        )
        if llm.CONFIG.provider == "mock":
            payload = self._mock_payload(ctx, statement, title, hints)
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
            hint_block += "\nMemory hints:\n" + "\n".join(f"- {hint}" for hint in hints)
        prompt = build_universal_agent_prompt(
            task=ctx.task,
            solver_name=self.name,
            task_type_hint="data_etl",
            instructions=(
                "Produce an end-to-end ETL blueprint with runnable pseudo-code "
                "and explicit validation queries. Include all required sections."
            ),
            artifacts=[
                ArtifactRequest("data_etl.md", "md", "Sections covering schema, pipeline, tests, samples, checklist."),
            ],
            verification_expectations=[
                "List data quality checks and how to validate them.",
                "Note assumptions when source context missing.",
            ],
            additional_inputs={
                "task_title": title,
            },
            extra_context=hint_block,
        )
        response = llm.call(prompt, max_tokens=700, temperature=0.35, caller="data_etl_solver")
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

    def _write_deliverable(self, ctx: SolverContext, content: str, suffix: str = "_etl"):
        ctx.deliverables_dir.mkdir(parents=True, exist_ok=True)
        safe = sanitize_task_id(ctx.task_id)
        appendix = suffix or "_etl"
        path = ctx.deliverables_dir / f"{safe}{appendix}.md"
        path.write_text(content or "Pending ETL plan.", encoding="utf-8")
        return path

    def _write_json_artifact(self, ctx: SolverContext, payload: Dict[str, object], suffix: str) -> Path:
        ctx.deliverables_dir.mkdir(parents=True, exist_ok=True)
        safe = sanitize_task_id(ctx.task_id)
        path = ctx.deliverables_dir / f"{safe}{suffix}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def _format_sections(self) -> str:
        return "\n".join(f"- {section}" for section in self.sections)

    def _safe_list(self, value: object) -> List[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    def _render_plan(self, ctx: SolverContext, payload: Dict[str, object], artifacts: Dict[str, object]) -> str:
        summary = payload.get("summary") or str(ctx.task.get("problem_statement") or "")
        pipeline_overview = str(artifacts.get("pipeline_spec") or artifacts.get("pipeline_overview") or "").strip()
        sql_entries = artifacts.get("sql_snippets") or artifacts.get("sql_or_pseudocode") or ""
        python_entries = artifacts.get("python_snippets") or ""
        dq_checks = self._safe_list(artifacts.get("data_quality_checks") or artifacts.get("dq_checks"))
        tests = self._safe_list(artifacts.get("test_plan") or artifacts.get("tests"))
        tables = self._safe_list(artifacts.get("tables"))
        sql_blocks = self._safe_list(sql_entries)
        python_blocks = self._safe_list(python_entries)
        lines = [
            "## Problem Summary",
            summary[:800] or "Pending summary from challenge statement.",
            "## Source Data and Schemas",
        ]
        lines.extend(f"- {entry}" for entry in (tables or ["Define staging + warehouse schemas."]))
        lines.append("## Pipeline Skeleton (Python)")
        if python_blocks:
            for snippet in python_blocks:
                lines.append(f"```python\n{snippet}\n```")
        else:
            lines.append("```python\nclass Pipeline:\n    def run(self):\n        raise NotImplementedError('fill with extraction/transform/load steps')\n```")
        lines.append("## Transformation Steps")
        lines.append(pipeline_overview or "- Outline extraction, normalization, load cadence.")
        lines.append("## SQL / Validation Snippets")
        if sql_blocks:
            for snippet in sql_blocks:
                lines.append(f"```sql\n{snippet}\n```")
        else:
            lines.append("- Provide CTEs/queries validating row counts and invariants.")
        lines.append("## Test Strategy & Validation Queries")
        lines.extend(f"- {check}" for check in (dq_checks or ["Pending DQ checks."]))
        lines.extend(f"- Test: {cmd}" for cmd in tests)
        lines.append("## Sample Outputs")
        lines.append("- Provide sample before/after rows or aggregates.")
        lines.append("## Acceptance Checklist")
        lines.append("- Pipeline scheduled\n- DQ alerts configured\n- Backfill validated")
        return "\n".join(lines)

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
        reason = str(artifacts_map.get("reason") or "Insufficient data sources/requirements for ETL.")
        needed = self._safe_list(artifacts_map.get("what_needed"))
        lines = [
            "# Non-actionable ETL Task",
            "",
            f"Reason: {reason}",
            "",
            "## Information Needed",
        ]
        lines.extend(f"- {entry}" for entry in (needed or ["Provide source schema, cadence, success metrics."]))
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
            verifier_type="rubric_data_etl",
            verifier_name=self.rubric_name,
            verifier_score=0.0,
            artifacts=artifacts,
            metrics=metrics,
            deliverable_success=False,
            llm_calls_used=llm_calls_used,
            notes="Agent classified ETL task as non-actionable.",
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
            status="failed_data_etl",
            error_type="deliverable_parse_error",
            verifier_type="rubric_data_etl",
            verifier_name=self.rubric_name,
            verifier_score=0.0,
            artifacts=artifacts,
            metrics=metrics,
            deliverable_success=False,
            llm_calls_used=llm_calls_used,
            notes="Universal agent response was not valid JSON.",
        )

    def _mock_deliverable(self, statement: str, title: str) -> str:
        base = statement or f"Design ETL pipeline for {title}."
        return "\n\n".join(
            [
                "## Problem Summary\n" + base[:400],
                "## Source Data and Schemas\n- Source: operational DB\n- Fields: id, user_id, status, updated_at",
                "## Pipeline Skeleton (Python)\n```python\nclass DailyPipeline:\n    def extract(self):\n        # TODO: wire up source connector\n        return []\n    def transform(self, rows):\n        # TODO: implement business logic\n        return rows\n    def load(self, rows):\n        # TODO: push to warehouse\n        pass\n```\n",
                "## Transformation Steps\n1. Ingest via CDC\n2. Normalize enums\n3. Aggregate daily metrics",
                "## Test Strategy & Validation Queries\n- Assert row counts match\n- Spot check null ratios\n```sql\nSELECT user_id, COUNT(*) AS events FROM staging.events GROUP BY 1;\n```",
                "## Sample Outputs\n| user_id | events |\n| --- | --- |\n| 42 | 15 |\n",
                "## Acceptance Checklist\n- Schema versioned\n- Data quality alerts configured\n- Backfill validated\n- Pytest suite green",
            ]
        )

    def _mock_payload(self, ctx: SolverContext, statement: str, title: str, hints) -> Dict[str, object]:
        doc = self._mock_deliverable(statement, title)
        return {
            "task_type": TaskType.DATA_ETL.value,
            "id": ctx.task_id,
            "title": title or "Mock Data ETL Plan",
            "summary": (statement or f"Design ETL pipeline for {title}.")[:300],
            "assumptions": ["Mock payload emitted because provider=mock.", f"Hints: {', '.join(hints) or 'n/a'}"],
            "plan": [
                "Describe upstream sources and schemas.",
                "Provide python/sql snippets to orchestrate extraction + transformation.",
                "List validation queries and data quality gates before go-live.",
            ],
            "artifacts": {
                "pipeline_spec": doc,
                "python_snippets": [
                    "class DailyPipeline:\n    def run(self):\n        df = extract('staging.orders')\n        modeled = transform(df)\n        load(modeled, 'warehouse.fact_orders')\n",
                ],
                "sql_snippets": [
                    "with source as (\n    select * from staging.orders\n)\nselect status, count(*) as orders from source group by 1;",
                ],
                "data_quality_checks": [
                    "Row count parity between staging.orders and fact_orders within 1%",
                    "No NULL user_id in fact_orders",
                ],
                "tables": [
                    "staging.orders(order_id STRING, status STRING, updated_at TIMESTAMP)",
                    "warehouse.fact_orders(order_id STRING PK, user_id STRING, gross_amount DECIMAL)",
                ],
                "test_plan": [
                    "dbt test --select fact_orders*",
                    "python scripts/check_freshness.py --lookback 2h",
                ],
            },
            "validations": ["SELF_CHECK: Verified ETL sections populated (pipeline/spec/tests)."],
            "confidence": 0.5,
            "stop_reason": "completed",
            "rubric_self_check": {
                "coverage": 90,
                "specificity": 88,
                "actionability": 87,
                "overall_notes": "Mock provider produced schema, DQ checks, and validation commands.",
            },
        }
