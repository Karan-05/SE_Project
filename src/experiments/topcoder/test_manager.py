"""Manage extraction and synthesis of tests per task."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .test_parsing import parse_examples_from_statement, has_io_markers
from .test_synthesis import synthesize_tests
from .llm_utils import llm_available


def _sanitize_task_id(task_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", task_id)
    return safe[:120] or "task"


@dataclass
class TestPolicy:
    require_tests: bool = False
    use_samples_as_tests: bool = True
    synthesize_tests: bool = True
    max_synthesized_tests_per_task: int = 8
    max_tasks_needing_synthesis: int = 200
    allow_no_llm: bool = False
    __test__ = False


class TestManager:
    __test__ = False
    def __init__(self, policy: TestPolicy, run_dir: Path):
        self.policy = policy
        self.run_dir = run_dir
        self.extracted_dir = run_dir / "extracted_tests"
        self.generated_dir = run_dir / "generated_tests"
        self.extracted_dir.mkdir(parents=True, exist_ok=True)
        self.generated_dir.mkdir(parents=True, exist_ok=True)
        avail, reason = llm_available()
        self._llm_available = avail
        self._llm_reason = reason
        if not self._llm_available and not self.policy.allow_no_llm:
            raise RuntimeError(
                "LLM provider not configured. Enable an LLM or re-run with --allow-no-llm."
            )
        self._synthesis_used = 0

    @property
    def llm_available(self) -> bool:
        return self._llm_available

    @property
    def llm_reason(self) -> str:
        return getattr(self, "_llm_reason", "unknown")

    def ensure_tests(self, task: Dict[str, Any]) -> Optional[Dict[str, str]]:
        metadata = task.setdefault("metadata", {})
        tests: List[Dict[str, object]] = list(metadata.get("tests") or [])
        source = metadata.get("tests_source", "")
        statement_text = str(task.get("problem_statement") or "")
        parse_hint = has_io_markers(statement_text)
        if tests and not self.policy.use_samples_as_tests and source in {"samples", "statement"}:
            tests = []
            metadata.pop("tests_source", None)
            metadata.pop("tests_path", None)
            metadata["tests"] = []
        if tests:
            metadata["tests"] = tests
            metadata["tests_source"] = source or "provided"
            metadata["tests_path"] = self._persist_tests(task["id"], tests, metadata["tests_source"])
            metadata["tests_path_kind"] = metadata["tests_source"]
            metadata.pop("parse_failure_hint", None)
            return None

        extracted = []
        if self.policy.use_samples_as_tests:
            extracted = parse_examples_from_statement(statement_text)
        if extracted:
            tests = [spec.to_metadata_dict() for spec in extracted]
            metadata["tests"] = tests
            metadata["tests_source"] = "statement"
            metadata["tests_path"] = self._persist_tests(task["id"], tests, "statement")
            metadata["tests_path_kind"] = "statement"
            metadata.pop("parse_failure_hint", None)
            return None

        if parse_hint:
            metadata["parse_failure_hint"] = True

        if not self.policy.synthesize_tests:
            return self._skip_response(metadata, "skipped_missing_tests", "missing_tests")

        if not self._llm_available:
            return self._skip_response(metadata, "skipped_no_llm_config", "missing_dependency")

        if self._synthesis_used >= self.policy.max_tasks_needing_synthesis:
            return self._skip_response(metadata, "skipped_synthesis_limit", "synthesis_limited")

        self._synthesis_used += 1
        synthesized, meta = synthesize_tests(task, max_tests=self.policy.max_synthesized_tests_per_task)
        if not synthesized:
            return self._skip_response(metadata, "skipped_failed_synthesis", "synthesis_failure")
        tests = [spec.to_metadata_dict() for spec in synthesized]
        metadata["tests"] = tests
        metadata["tests_source"] = "self_check"
        metadata["synthesis_meta"] = meta
        metadata["self_check_only"] = True
        metadata["tests_path"] = self._persist_tests(task["id"], tests, "synthesized")
        metadata["tests_path_kind"] = "self_check"
        metadata.pop("parse_failure_hint", None)
        return None

    def _persist_tests(self, task_id: str, tests: List[Dict[str, object]], kind: str) -> str:
        directory = self.generated_dir if kind == "synthesized" else self.extracted_dir
        safe_name = _sanitize_task_id(task_id)
        target = directory / f"{safe_name}.json"
        with target.open("w", encoding="utf-8") as fp:
            json.dump(tests, fp, indent=2)
        return str(target)

    def _skip_response(self, metadata: Dict[str, Any], status: str, error_type: str) -> Dict[str, str]:
        payload = {"status": status, "error_type": error_type}
        if metadata.get("parse_failure_hint"):
            payload["parse_failure"] = True
        return payload
