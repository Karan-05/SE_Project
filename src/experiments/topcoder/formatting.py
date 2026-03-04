"""Utilities for enforcing deterministic JSON formatting/repair."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from src.providers import llm

from .parsing import JsonExtractionError, extract_json_block, try_recover_balanced_json
from .task_router import TaskType

SENTINEL_BEGIN = "BEGIN_JSON"
SENTINEL_END = "END_JSON"

RepairPromptBuilder = Callable[[str], str]


class DeliverableParseError(JsonExtractionError):
    """Raised when the universal agent output cannot be parsed even after repair."""

    def __init__(
        self,
        message: str,
        *,
        raw_path: Path,
        diagnostics_path: Path,
        repair_path: Optional[Path] = None,
    ):
        super().__init__(message)
        self.raw_agent_path = raw_path
        self.diagnostics_path = diagnostics_path
        self.repaired_agent_path = repair_path


@dataclass(frozen=True)
class JsonExtractionOutcome:
    """Encoded metadata about an extracted JSON payload."""

    payload: Dict[str, Any]
    json_text: str
    source: str
    raw_text: str
    raw_path: Path
    diagnostics_path: Path
    parse_diagnostics: Dict[str, Any] = field(default_factory=dict)
    used_repair: bool = False
    repair_text: Optional[str] = None
    repair_path: Optional[Path] = None


REQUIRED_ROOT_KEYS = {
    "task_type",
    "id",
    "title",
    "summary",
    "assumptions",
    "plan",
    "artifacts",
    "validations",
    "confidence",
    "stop_reason",
    "rubric_self_check",
}
RUBRIC_KEYS = {"coverage", "specificity", "actionability", "overall_notes"}
ARTIFACT_KEY_MAP: Dict[str, tuple[str, ...]] = {
    TaskType.ALGO_CODING.value: ("solution_py", "unit_tests_py", "run_instructions"),
    TaskType.REPO_PATCH.value: ("patch_diff_unified", "file_plan", "risks", "test_plan"),
    TaskType.API_BACKEND.value: ("endpoints", "request_response_examples", "schema", "minimal_impl_plan"),
    TaskType.ARCHITECTURE_DOC.value: ("design_doc_md", "mermaid_diagram", "interfaces", "tradeoffs"),
    TaskType.DATA_ETL.value: ("pipeline_spec", "sql_snippets", "python_snippets", "data_quality_checks"),
    TaskType.NON_ACTIONABLE.value: ("reason", "what_needed"),
}
VALID_TASK_TYPES = {task.value for task in TaskType}


def _safe_task_slug(task_id: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in str(task_id))
    return safe[:120] or "task"


def _extract_between_sentinels(payload: str) -> Optional[str]:
    if not payload:
        return None
    start = payload.find(SENTINEL_BEGIN)
    if start == -1:
        return None
    start += len(SENTINEL_BEGIN)
    end = payload.find(SENTINEL_END, start)
    if end == -1:
        return None
    return payload[start:end].strip()


def _ensure_float(value: object, name: str) -> None:
    try:
        float(value)
    except (TypeError, ValueError):
        raise JsonExtractionError(f"{name} must be numeric.")


def _validate_payload_schema(data: Dict[str, Any]) -> None:
    missing = [key for key in REQUIRED_ROOT_KEYS if key not in data]
    if missing:
        raise JsonExtractionError(f"Missing required keys: {', '.join(missing)}")
    for field_name in ("id", "title", "summary", "stop_reason", "task_type"):
        if not isinstance(data.get(field_name), str):
            raise JsonExtractionError(f"{field_name} must be a string.")
    task_type = data["task_type"].strip().lower()
    if task_type not in VALID_TASK_TYPES:
        raise JsonExtractionError(f"task_type '{task_type}' unsupported.")
    assumptions = data.get("assumptions")
    plan = data.get("plan")
    validations = data.get("validations")
    if not isinstance(assumptions, list):
        raise JsonExtractionError("assumptions must be a list.")
    if not isinstance(plan, list):
        raise JsonExtractionError("plan must be a list.")
    if not isinstance(validations, list) or not validations:
        raise JsonExtractionError("validations must be a non-empty list.")
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, dict):
        raise JsonExtractionError("artifacts must be an object.")
    required_artifacts = ARTIFACT_KEY_MAP.get(task_type, ())
    missing_artifacts = [key for key in required_artifacts if key not in artifacts]
    if missing_artifacts:
        raise JsonExtractionError(f"artifacts missing keys: {', '.join(missing_artifacts)}")
    if task_type == TaskType.NON_ACTIONABLE.value and not isinstance(artifacts.get("what_needed"), list):
        raise JsonExtractionError("artifacts.what_needed must be a list for non_actionable tasks.")
    rubric = data.get("rubric_self_check")
    if not isinstance(rubric, dict):
        raise JsonExtractionError("rubric_self_check must be an object.")
    for key in RUBRIC_KEYS:
        if key not in rubric:
            raise JsonExtractionError(f"rubric_self_check missing '{key}'.")
        if key == "overall_notes":
            if not isinstance(rubric.get(key), str):
                raise JsonExtractionError("rubric_self_check.overall_notes must be a string.")
        else:
            _ensure_float(rubric.get(key), f"rubric_self_check.{key}")
    _ensure_float(data.get("confidence"), "confidence")


def _write_text(path: Path, content: str) -> None:
    payload = (content or "").strip() or "(empty response)"
    path.write_text(payload, encoding="utf-8")


def build_strict_repair_prompt(
    raw_text: str,
    *,
    schema_hint: str,
    solver_name: str,
    task_id: str,
    run_id: str,
) -> str:
    """Construct a shared repair prompt that preserves the agent's substance."""

    instructions = (
        "Return ONLY a valid JSON object wrapped exactly in BEGIN_JSON and END_JSON.\n"
        "No markdown fences. No prose. Fix formatting only; do not change substance unless required to satisfy required keys.\n"
    )
    return (
        "FORMAT REPAIR REQUEST\n"
        f"run_id={run_id} task_id={task_id} solver={solver_name}\n"
        f"{instructions}"
        "Schema reminder:\n"
        f"{schema_hint.strip()}\n\n"
        "Raw response:\n<<<\n"
        f"{(raw_text or '').strip()}\n"
        ">>>\n"
    )


def extract_json_or_repair(
    raw_llm_text: str,
    *,
    llm_client=None,
    repair_prompt_builder: RepairPromptBuilder,
    artifact_dir: Path,
    task_id: str,
    run_id: str,
    max_repairs: int = 1,
) -> JsonExtractionOutcome:
    """Best-effort JSON extraction that tolerates chatter and triggers repair exactly once."""

    artifact_dir.mkdir(parents=True, exist_ok=True)
    safe_task = _safe_task_slug(task_id)
    raw_text = raw_llm_text or ""
    raw_path = artifact_dir / f"{safe_task}_agent_raw.txt"
    _write_text(raw_path, raw_text)
    diag_path = artifact_dir / f"{safe_task}_agent_parse_diag.json"
    diagnostics: Dict[str, Any] = {
        "task_id": str(task_id),
        "run_id": str(run_id),
        "raw_path": str(raw_path),
        "raw_length": len(raw_text),
        "sentinel_found": False,
        "attempts": [],
        "errors": [],
        "repair_attempted": False,
        "repair_used": False,
        "max_repairs": max(0, int(max_repairs)),
        "llm_provider": getattr(getattr(llm_client or llm, "CONFIG", None), "provider", ""),
    }

    def _record_attempt(mode: str, success: bool, error: Optional[str] = None, length: Optional[int] = None) -> None:
        entry: Dict[str, Any] = {"mode": mode, "success": bool(success)}
        if length is not None:
            entry["length"] = length
        if error:
            entry["error"] = error
        diagnostics["attempts"].append(entry)

    def _attempt(candidate: str, mode: str) -> tuple[str, Dict[str, Any]]:
        try:
            block = extract_json_block(candidate or "")
            data = json.loads(block)
            _validate_payload_schema(data)
            _record_attempt(mode, True, length=len(block))
            diagnostics["source"] = mode
            diagnostics["parsed_length"] = len(block)
            return block, data
        except JsonExtractionError as exc:
            _record_attempt(mode, False, str(exc))
            raise
        except json.JSONDecodeError as exc:
            message = f"JSON parsing failed ({mode}): {exc}"
            _record_attempt(mode, False, message)
            raise JsonExtractionError(message) from exc

    def _write_diag(status: str) -> None:
        diagnostics["status"] = status
        diag_path.write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")

    sentinel_candidate = _extract_between_sentinels(raw_text)
    if sentinel_candidate is None:
        _record_attempt("sentinel", False, "sentinel_block_missing")
    else:
        diagnostics["sentinel_found"] = True
        try:
            json_text, data = _attempt(sentinel_candidate, "sentinel")
            diagnostics["repair_path"] = ""
            _write_diag("success")
            return JsonExtractionOutcome(
                payload=data,
                json_text=json_text,
                source="sentinel",
                raw_text=raw_text,
                raw_path=raw_path,
                diagnostics_path=diag_path,
                parse_diagnostics=json.loads(json.dumps(diagnostics)),
            )
        except JsonExtractionError:
            diagnostics["errors"].append({"stage": "sentinel", "message": diagnostics["attempts"][-1]["error"]})

    balanced_candidate = try_recover_balanced_json(raw_text)
    if balanced_candidate is None:
        _record_attempt("balanced", False, "no_balanced_candidate")
    else:
        try:
            json_text, data = _attempt(balanced_candidate, "balanced")
            diagnostics["repair_path"] = ""
            _write_diag("success")
            return JsonExtractionOutcome(
                payload=data,
                json_text=json_text,
                source="balanced",
                raw_text=raw_text,
                raw_path=raw_path,
                diagnostics_path=diag_path,
                parse_diagnostics=json.loads(json.dumps(diagnostics)),
            )
        except JsonExtractionError:
            diagnostics["errors"].append({"stage": "balanced", "message": diagnostics["attempts"][-1]["error"]})

    llm_client = llm_client or llm
    repair_path: Optional[Path] = None
    repair_text: Optional[str] = None
    if diagnostics["max_repairs"] > 0 and llm_client is not None:
        diagnostics["repair_attempted"] = True
        attempt_input = raw_text
        for repair_index in range(diagnostics["max_repairs"]):
            prompt = repair_prompt_builder(attempt_input or "")
            response = llm_client.call(
                prompt,
                max_tokens=800,
                temperature=0.0,
                caller="universal_agent_repair",
            )
            repair_text = (response.content or "").strip()
            repair_path = artifact_dir / f"{safe_task}_agent_repair.txt"
            _write_text(repair_path, repair_text)
            diagnostics["repair_path"] = str(repair_path)
            try:
                json_text, data = _attempt(repair_text, "repair")
                diagnostics["repair_used"] = True
                _write_diag("success")
                return JsonExtractionOutcome(
                    payload=data,
                    json_text=json_text,
                    source="repair",
                    raw_text=raw_text,
                    raw_path=raw_path,
                    diagnostics_path=diag_path,
                    parse_diagnostics=json.loads(json.dumps(diagnostics)),
                    used_repair=True,
                    repair_text=repair_text,
                    repair_path=repair_path,
                )
            except JsonExtractionError:
                diagnostics["errors"].append({"stage": "repair", "message": diagnostics["attempts"][-1]["error"]})
                attempt_input = repair_text

    diagnostics["repair_path"] = str(repair_path or "")
    diagnostics["repair_used"] = False
    _write_diag("failed")
    message = (
        "Universal agent emitted invalid JSON and repair could not fix it."
        if repair_path
        else "Universal agent emitted invalid JSON and no repair was possible."
    )
    raise DeliverableParseError(
        message,
        raw_path=raw_path,
        diagnostics_path=diag_path,
        repair_path=repair_path,
    )


__all__ = [
    "DeliverableParseError",
    "JsonExtractionOutcome",
    "build_strict_repair_prompt",
    "extract_json_or_repair",
    "SENTINEL_BEGIN",
    "SENTINEL_END",
]
