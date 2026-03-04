"""LLM helper to synthesize test cases when datasets lack samples."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from src.providers import llm

from .test_parsing import TestSpec

PROMPT_TEMPLATE = """You are a diligent Topcoder judge. Given the problem description below, produce JSON describing up to {max_tests} deterministic tests that validate solutions.

Problem title: {title}
Statement:
{statement}

The JSON schema must be:
{{
  "mode": "io" | "method",
  "tests": [
    {{
      "name": "short_identifier",
      "input": "stdin payload or JSON array (for method mode)",
      "output": "expected stdout or expected return value",
      "args": optional JSON array when mode == "method",
      "kwargs": optional object,
      "notes": optional string describing why the test matters
    }}
  ],
  "assumptions": "critical constraints or notes",
  "notes": "any additional hints"
}}

Constraints:
- Always include at least two edge or adversarial cases.
- Prefer parsing-friendly data (JSON arrays/objects) whenever possible.
- Keep outputs short and exact.
- Respond with JSON only. Do not wrap it in markdown fences or prose.
"""


def _coerce_to_spec(payload: Dict[str, Any], default_mode: str) -> TestSpec | None:
    mode = payload.get("mode") or default_mode
    name = payload.get("name") or payload.get("id") or payload.get("label") or "synthetic"
    if mode == "io":
        stdin = payload.get("input") or payload.get("stdin") or ""
        stdout = payload.get("output") or payload.get("expected") or payload.get("expected_stdout") or ""
        if not stdin or not stdout:
            return None
        return TestSpec(name=name, mode="io", stdin=str(stdin), stdout=str(stdout), expected=str(stdout))
    args = payload.get("args") or payload.get("input") or payload.get("inputs")
    if args is None:
        return None
    if not isinstance(args, (list, tuple)):
        args = [args]
    expected = payload.get("output") or payload.get("expected")
    return TestSpec(name=name, mode="call", inputs=list(args), expected=expected)


def synthesize_tests(task: Dict[str, Any], *, max_tests: int = 8) -> Tuple[List[TestSpec], Dict[str, Any]]:
    statement = task.get("problem_statement") or task.get("statement") or ""
    title = task.get("title") or task.get("id")
    prompt = PROMPT_TEMPLATE.format(title=title, statement=statement[:2000], max_tests=max_tests)
    response = llm.call(prompt, model="test-synthesizer", max_tokens=800, temperature=0.2, caller="test_synthesis")
    raw = response.content.strip()
    data: Dict[str, Any]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {"mode": "io", "tests": [], "assumptions": f"unparsed response: {raw[:120]}"}
    tests: List[TestSpec] = []
    tests_payload = data.get("tests") if isinstance(data, dict) else []
    mode = data.get("mode", "io") if isinstance(data, dict) else "io"
    if isinstance(tests_payload, list):
        for idx, spec_payload in enumerate(tests_payload[:max_tests]):
            if isinstance(spec_payload, dict):
                spec = _coerce_to_spec(spec_payload, mode)
                if spec:
                    spec.name = spec.name or f"synth_{idx}"
                    tests.append(spec)
    return tests, {
        "assumptions": data.get("assumptions", ""),
        "notes": data.get("notes", ""),
        "raw_response": raw[:500],
        "mode": data.get("mode", "io"),
    }
