"""Helpers for extracting structured tests from Topcoder datasets."""
from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple


@dataclass
class TestSpec:
    """Canonical test specification understood by the experiment runner."""

    __test__ = False
    name: str
    mode: str = "call"
    inputs: List[Any] = field(default_factory=list)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    expected: Any = None
    stdin: Optional[str] = None
    stdout: Optional[str] = None

    def to_metadata_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "name": self.name,
            "mode": self.mode,
            "expected": self.expected,
        }
        if self.inputs:
            payload["input"] = self.inputs
        if self.kwargs:
            payload["kwargs"] = self.kwargs
        if self.stdin is not None:
            payload["stdin"] = self.stdin
        if self.stdout is not None:
            payload["expected_stdout"] = self.stdout
        return payload


def _normalize_column(name: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in name.strip().lower())


def _jsonish(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return value
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            return ast.literal_eval(text)
        except Exception:
            return text


def _build_call_spec(index: int, inputs: Any, expected: Any) -> Optional[TestSpec]:
    if inputs is None or expected is None:
        return None
    if not isinstance(inputs, (list, tuple)):
        inputs = [inputs]
    inputs_list = list(inputs)
    return TestSpec(name=f"sample_{index}", mode="call", inputs=inputs_list, expected=expected)


def _build_io_spec(index: int, stdin: str, stdout: str) -> Optional[TestSpec]:
    stdin = (stdin or "").strip()
    stdout = (stdout or "").strip()
    if not stdin or not stdout:
        return None
    return TestSpec(name=f"io_sample_{index}", mode="io", stdin=stdin, stdout=stdout, expected=stdout)


def _extract_structured_examples(row: Dict[str, Any], normalized: Dict[str, str]) -> Tuple[List[TestSpec], str]:
    specs: List[TestSpec] = []
    # Direct tests column with JSON/records.
    for candidate in ("tests", "test_cases", "samples", "example_tests"):
        column = normalized.get(candidate)
        if not column:
            continue
        parsed = _jsonish(row[column])
        if isinstance(parsed, list):
            for idx, payload in enumerate(parsed):
                if isinstance(payload, TestSpec):
                    specs.append(payload)
                    continue
                if isinstance(payload, dict):
                    inputs = payload.get("input") or payload.get("inputs")
                    expected = payload.get("expected") or payload.get("output")
                    mode = payload.get("mode") or payload.get("type") or "call"
                    if mode == "io":
                        stdin = payload.get("stdin") or payload.get("input_text") or payload.get("input")
                        stdout = payload.get("expected_stdout") or payload.get("output_text") or payload.get("expected")
                        spec = _build_io_spec(idx, stdin or "", stdout or "")
                    else:
                        spec = _build_call_spec(idx, inputs, expected)
                    if spec:
                        specs.append(spec)
    if specs:
        return specs, "provided"

    # Columns like sample_input_1/sample_output_1
    sample_pairs: Dict[str, Dict[str, Any]] = {}
    for column_name in row:
        normalized_name = _normalize_column(column_name)
        match = re.match(r"(example|sample)_(input|output)_?(\d+)?", normalized_name)
        if not match:
            continue
        _, kind, suffix = match.groups()
        suffix = suffix or "1"
        pair = sample_pairs.setdefault(suffix, {})
        pair[kind] = row[column_name]
    if sample_pairs:
        for idx, suffix in enumerate(sorted(sample_pairs), start=1):
            pair = sample_pairs[suffix]
            stdin = pair.get("input")
            stdout = pair.get("output")
            spec = _build_io_spec(idx, stdin or "", stdout or "")
            if spec:
                specs.append(spec)
        if specs:
            return specs, "samples"

    # Columns with aggregated inputs/outputs lists
    input_column = None
    output_column = None
    for key in ("sample_inputs", "example_inputs"):
        column = normalized.get(key)
        if column:
            input_column = column
            break
    for key in ("sample_outputs", "example_outputs"):
        column = normalized.get(key)
        if column:
            output_column = column
            break
    if input_column and output_column:
        inputs_payload = _jsonish(row[input_column]) or []
        outputs_payload = _jsonish(row[output_column]) or []
        if isinstance(inputs_payload, list) and isinstance(outputs_payload, list):
            for idx, (inputs, expected) in enumerate(zip(inputs_payload, outputs_payload), start=1):
                spec = _build_call_spec(idx, inputs, expected)
                if spec:
                    specs.append(spec)
        if specs:
            return specs, "samples"

    return [], ""


EXAMPLE_BLOCK = re.compile(
    r"(?:Example|Sample)\s*\d*[:\s]*([\s\S]*?)(?=(?:\n\s*(?:Example|Sample)\s*\d*[:\s]*|$))",
    flags=re.IGNORECASE,
)
IO_PATTERN = re.compile(
    r"Input[^:]*:\s*([\s\S]*?)(?:Output|Expected)[^:]*:\s*([\s\S]*?)($|\n\s*\n)",
    flags=re.IGNORECASE,
)


def parse_examples_from_statement(text: Optional[str]) -> List[TestSpec]:
    if not text:
        return []
    specs: List[TestSpec] = []
    cleaned = text.strip()
    if not cleaned:
        return []
    matches = EXAMPLE_BLOCK.findall(cleaned)
    search_space = matches or [cleaned]
    index = 1
    for block in search_space:
        for io_match in IO_PATTERN.findall(block):
            stdin, stdout, _ = io_match
            spec = _build_io_spec(index, stdin, stdout)
            if spec:
                specs.append(spec)
                index += 1
    return specs


def extract_tests_from_row(row: Dict[str, Any], statement: Optional[str]) -> Tuple[List[TestSpec], str]:
    normalized = {_normalize_column(k): k for k in row.keys()}
    specs, source = _extract_structured_examples(row, normalized)
    if specs:
        return specs, source
    statement_specs = parse_examples_from_statement(statement)
    if statement_specs:
        return statement_specs, "statement"
    return [], ""


def has_io_markers(text: Optional[str]) -> bool:
    """Detect whether a statement advertises explicit input/output structure."""

    if not text:
        return False
    snippet = text.strip()
    if not snippet:
        return False
    if IO_PATTERN.search(snippet):
        return True
    if EXAMPLE_BLOCK.search(snippet):
        return True
    lowered = snippet.lower()
    if "input:" in lowered and "output:" in lowered:
        return True
    if "stdin" in lowered and "stdout" in lowered:
        return True
    return False
