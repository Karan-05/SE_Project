"""Single source of truth for the UniversalTopcoderAgent prompt."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

from ..parsing import JsonExtractionError, extract_json_object
from ..task_router import TaskType

PROMPT_PATH = Path(__file__).with_name("universal_agent.md")
UNIVERSAL_AGENT_PROMPT = PROMPT_PATH.read_text(encoding="utf-8").strip()
STRICT_JSON_CONTRACT = (
    "Emit EXACTLY one JSON object wrapped by literal BEGIN_JSON/END_JSON sentinels. "
    "Required keys: task_type, id, title, summary, assumptions[], plan[], artifacts{}, "
    "validations[], confidence, stop_reason, rubric_self_check{coverage,specificity,actionability,overall_notes}. "
    "Artifacts must contain the per-task-type payloads described above (e.g., "
    "repo_patch -> patch_diff_unified/file_plan/risks/test_plan; data_etl -> "
    "pipeline_spec/sql_snippets/python_snippets/data_quality_checks; architecture_doc -> "
    "design_doc_md/mermaid_diagram/interfaces/tradeoffs; algo_coding -> "
    "solution_py/unit_tests_py/run_instructions; api_backend -> endpoints/request_response_examples/schema/minimal_impl_plan). "
    "If non_actionable, provide artifacts.reason + artifacts.what_needed[]. "
    "If blocked, set stop_reason accordingly but still emit valid JSON between the sentinels."
)
VALID_TASK_TYPES = {task.value for task in TaskType}


@dataclass(frozen=True)
class ArtifactRequest:
    """Describe the artifacts expected from the universal agent."""

    name: str
    format: str
    description: str = ""


def _format_list(items: Iterable[str], prefix: str = "- ") -> str:
    values = [item for item in items if item]
    if not values:
        return f"{prefix}n/a"
    return "\n".join(f"{prefix}{item}" for item in values)


def _memory_hints(metadata: Dict[str, Any]) -> List[str]:
    hints = metadata.get("memory_hints") or []
    if isinstance(hints, list):
        return [str(hint) for hint in hints if hint]
    return []


def build_universal_agent_prompt(
    *,
    task: Dict[str, Any],
    solver_name: str,
    task_type_hint: Optional[str] = None,
    instructions: str,
    artifacts: Iterable[ArtifactRequest] = (),
    verification_expectations: Optional[Iterable[str]] = None,
    additional_inputs: Optional[Dict[str, str]] = None,
    extra_context: Optional[str] = None,
) -> str:
    """Render the canonical prompt string for downstream solvers."""

    metadata = task.get("metadata") or {}
    title = str(task.get("title") or task.get("name") or "").strip()
    description = str(task.get("problem_statement") or task.get("statement") or "").strip()
    tags_value = task.get("tags") or task.get("challengeTags") or []
    if isinstance(tags_value, list):
        tags = ", ".join(str(tag) for tag in tags_value if tag)
    else:
        tags = str(tags_value)
    context_lines = [
        f"task_id: {task.get('id')}",
        f"title: {title or 'n/a'}",
        f"tags: {tags or 'n/a'}",
        f"description:\n{description or 'n/a'}",
    ]
    if additional_inputs:
        for key, value in additional_inputs.items():
            context_lines.append(f"{key}: {value}")
    hints = _memory_hints(metadata)
    if hints:
        context_lines.append("memory_hints:\n" + _format_list(hints))
    if extra_context:
        context_lines.append(f"extra_context:\n{extra_context}")
    artifact_lines = [
        f"- {artifact.name} ({artifact.format}): {artifact.description or 'required'}"
        for artifact in artifacts
    ]
    if not artifact_lines:
        artifact_lines = ["- (none specified — still provide useful diagnostics)"]
    verify_lines = list(verification_expectations or [])
    if not verify_lines:
        verify_lines = [
            "- Provide deterministic verification notes summarizing checks performed.",
        ]
    task_type_hint_line = f"Task type hint: {task_type_hint}" if task_type_hint else "Task type hint: (auto-select)"
    prompt_sections = [
        UNIVERSAL_AGENT_PROMPT,
        "",
        f"CURRENT SOLVER: {solver_name}",
        task_type_hint_line,
        "TASK INPUTS:",
        "\n".join(context_lines),
        "",
        "ARTIFACT EXPECTATIONS:",
        "\n".join(artifact_lines),
        "",
        "VERIFICATION EXPECTATIONS:",
        _format_list(verify_lines),
        "",
        "ADDITIONAL INSTRUCTIONS:",
        instructions.strip(),
        "",
        "FORMAT REQUIREMENT:",
        STRICT_JSON_CONTRACT,
    ]
    return "\n".join(section for section in prompt_sections if section is not None)


def _as_list(value: object) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def parse_universal_agent_response(response: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Parse the structured JSON response from the universal agent."""

    data = response if isinstance(response, dict) else extract_json_object(response or "")
    raw_task_type = str(data.get("task_type") or "").strip()
    normalized_type = raw_task_type.replace("-", "_").lower()
    if normalized_type not in VALID_TASK_TYPES:
        raise JsonExtractionError(f"task_type '{raw_task_type}' missing or unsupported")
    task_id = str(data.get("id") or "").strip()
    title = str(data.get("title") or "").strip()
    summary = str(data.get("summary") or "").strip()
    artifacts = data.get("artifacts") or {}
    if not isinstance(artifacts, dict):
        artifacts = {}
    artifacts = {str(k): v for k, v in artifacts.items()}
    rubric_blob = data.get("rubric_self_check") or {}
    if not isinstance(rubric_blob, dict):
        rubric_blob = {}
    try:
        coverage = float(rubric_blob.get("coverage", 0.0))
    except (TypeError, ValueError):
        coverage = 0.0
    try:
        specificity = float(rubric_blob.get("specificity", 0.0))
    except (TypeError, ValueError):
        specificity = 0.0
    try:
        actionability = float(rubric_blob.get("actionability", 0.0))
    except (TypeError, ValueError):
        actionability = 0.0
    overall_notes = str(rubric_blob.get("overall_notes") or "").strip()
    assumptions = _as_list(data.get("assumptions"))
    plan = _as_list(data.get("plan"))
    validations = _as_list(data.get("validations"))
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    stop_reason = str(data.get("stop_reason") or "").strip()
    return {
        "task_type": normalized_type,
        "id": task_id,
        "title": title,
        "summary": summary,
        "artifacts": artifacts,
        "assumptions": assumptions,
        "plan": plan,
        "validations": validations,
        "confidence": confidence,
        "stop_reason": stop_reason,
        "rubric_self_check": {
            "coverage": coverage,
            "specificity": specificity,
            "actionability": actionability,
            "overall_notes": overall_notes,
        },
        "raw": data,
    }


__all__ = [
    "ArtifactRequest",
    "UNIVERSAL_AGENT_PROMPT",
    "build_universal_agent_prompt",
    "parse_universal_agent_response",
    "STRICT_JSON_CONTRACT",
]
