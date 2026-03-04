"""Utility helpers for decomposition strategies."""
from __future__ import annotations

import builtins
import contextlib
import io
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.decomposition.interfaces import DecompositionContext, DecompositionPlan, StrategyResult
from src.decomposition.timeline import current_timeline
from src.providers.llm import LLMResponse


def _normalize_stdout(text: str) -> str:
    lines = text.splitlines()
    return "\n".join(line.rstrip() for line in lines).strip()


def _value_signature(value: Any) -> str:
    if isinstance(value, list):
        if not value:
            return "list"
        return f"list[{_value_signature(value[0])}]"
    if isinstance(value, tuple):
        if not value:
            return "tuple"
        return f"tuple[{_value_signature(value[0])}]"
    if isinstance(value, set):
        if not value:
            return "set"
        return f"set[{_value_signature(next(iter(value)))}]"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__


def _format_signature(name: str, test: Dict[str, Any]) -> str:
    raw_inputs = test.get("input")
    if isinstance(raw_inputs, (list, tuple)):
        inputs = list(raw_inputs)
    elif raw_inputs in (None, ""):
        inputs = []
    else:
        inputs = [raw_inputs]
    kwargs = test.get("kwargs") if isinstance(test, dict) else {}
    if not isinstance(kwargs, dict):
        kwargs = {}
    parts: List[str] = []
    for idx, value in enumerate(inputs):
        parts.append(f"arg{idx + 1}:{_value_signature(value)}")
    for key, value in kwargs.items():
        parts.append(f"{key}:{_value_signature(value)}")
    joined = ", ".join(parts)
    return f"{name}({joined})" if joined else f"{name}()"


def build_implementation_contract(ctx: DecompositionContext) -> str:
    metadata = ctx.metadata if isinstance(ctx.metadata, dict) else {}
    tests = metadata.get("tests") or []
    if not isinstance(tests, list):
        tests = []
    entry_point = str(metadata.get("entry_point") or "solve")
    if not tests:
        return f"Implement function {entry_point}(*args) to solve the described problem. Do not read stdin or write stdout."
    prioritized = sorted(
        (test for test in tests if isinstance(test, dict)),
        key=lambda payload: {"method": 0, "io": 1}.get(str(payload.get("mode", "call")).lower(), 2),
    )
    if not prioritized:
        return f"Implement function {entry_point}(*args) to solve the described problem. Do not read stdin or write stdout."
    sample = prioritized[0]
    mode = str(sample.get("mode", "call")).lower()
    if mode == "io":
        return (
            f"Implement function {entry_point}() that reads all required input from stdin and writes the exact expected output to stdout. "
            "Do not return values, prompt the user, or print extra text."
        )
    if mode == "method":
        class_name = str(sample.get("class_name") or "Solution")
        method_name = str(sample.get("method") or entry_point)
        signature = _format_signature(method_name, sample)
        return_type = _value_signature(sample.get("expected"))
        return (
            f"Implement class {class_name} with method {signature} -> {return_type}. "
            "Do NOT read stdin/stdout; all parameters are provided explicitly."
        )
    signature = _format_signature(entry_point, sample)
    return_type = _value_signature(sample.get("expected"))
    return (
        f"Implement function {signature} -> {return_type}. "
        "Do NOT read from stdin or write to stdout; rely solely on the provided arguments."
    )


def run_tests(solution_code: str, ctx: DecompositionContext, *, timeout_seconds: Optional[float] = None) -> List[Dict[str, str | float]]:
    tests = ctx.metadata.get("tests", [])
    entry_point = ctx.metadata.get("entry_point", "solve")
    effective_timeout = timeout_seconds
    if effective_timeout is None:
        try:
            effective_timeout = float(ctx.metadata.get("test_timeout_seconds", 30.0))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            effective_timeout = 30.0
    results: List[Dict[str, str | float]] = []
    namespace: Dict[str, object] = {}
    try:
        exec(solution_code, namespace)
    except Exception as exc:  # pragma: no cover - codegen failure
        return [
            {
                "status": "compile_error",
                "error": str(exc),
            }
        ]

    func = namespace.get(entry_point)
    if not callable(func):  # pragma: no cover
        return [{"status": "missing_entry_point", "error": entry_point}]

    timeline = current_timeline()
    tests_phase_started = False
    tests_phase_start = 0.0
    for idx, test in enumerate(tests):
        name = test.get("name") if isinstance(test, dict) else None
        if not name:
            name = f"test_{idx}"
        mode = str(test.get("mode", "call")).lower()
        if timeline and not tests_phase_started:
            tests_phase_started = True
            tests_phase_start = time.perf_counter()
            timeline.start("tests")
        start = time.perf_counter()
        if mode == "io":
            record = _run_io_test(func, name, test)
        else:
            record = _run_call_test(func, name, test)
        record["duration"] = time.perf_counter() - start
        if effective_timeout and record["duration"] >= effective_timeout:
            record["status"] = "timeout"
            record["error"] = f"test_timeout_exceeded>{record['duration']:.2f}s>{effective_timeout:.2f}s"
            results.append(record)
            break
        results.append(record)
    if timeline and tests_phase_started:
        timeline.end("tests", time.perf_counter() - tests_phase_start)
    return results


def _run_call_test(func, name: str, test: Dict[str, object]) -> Dict[str, str | float]:
    args = test.get("input", [])
    if not isinstance(args, (list, tuple)):
        args = [args]
    kwargs = test.get("kwargs", {}) if isinstance(test, dict) else {}
    expected = test.get("expected")
    try:
        output = func(*args, **kwargs)
        passed = output == expected
        error = ""
    except Exception as exc:  # pragma: no cover
        output = None
        passed = False
        error = str(exc)
    return {
        "name": name,
        "mode": "call",
        "status": "pass" if passed else "fail",
        "expected": repr(expected),
        "output": repr(output),
        "error": error,
        "input": repr(args),
        "kwargs": repr(kwargs),
    }


def _run_io_test(func, name: str, test: Dict[str, object]) -> Dict[str, str | float]:
    stdin = str(test.get("stdin") or test.get("input") or "")
    expected = str(test.get("expected_stdout") or test.get("expected") or "")
    args = test.get("args", [])
    if not isinstance(args, (list, tuple)):
        args = [] if args is None else [args]
    buffer_in = io.StringIO(stdin)
    buffer_out = io.StringIO()

    def _fake_input(prompt: str = "") -> str:
        line = buffer_in.readline()
        if not line:
            return ""
        return line.rstrip("\n")

    old_input = builtins.input
    try:
        builtins.input = _fake_input
        with contextlib.redirect_stdout(buffer_out):
            func(*args)
    except Exception as exc:  # pragma: no cover
        output = ""
        passed = False
        error = str(exc)
    else:
        output = buffer_out.getvalue()
        passed = _normalize_stdout(output) == _normalize_stdout(expected)
        error = ""
    finally:
        builtins.input = old_input
    return {
        "name": name,
        "mode": "io",
        "status": "pass" if passed else "fail",
        "expected": expected,
        "output": output,
        "error": error,
        "stdin": stdin,
        "args": repr(args),
    }


def finalize_result(
    ctx: DecompositionContext,
    plan: DecompositionPlan,
    solution_code: str,
    tests_run: List[Dict[str, str | float]],
    extra_metrics: Dict[str, float | str] | None = None,
) -> StrategyResult:
    pass_count = sum(1 for tr in tests_run if tr["status"] == "pass")
    total = len(tests_run)
    metrics: Dict[str, float | str] = {
        "pass_rate": pass_count / total if total else 0.0,
        "num_tests": total,
        "decomposition_steps": float(len(plan.subtasks) or len(plan.contract) or 1),
    }
    if extra_metrics:
        metrics.update(extra_metrics)
    return StrategyResult(
        plan=plan,
        solution_code=solution_code,
        tests_run=tests_run,
        metrics=metrics,
    )


@dataclass
class BudgetTracker:
    """Track tokens/time consumed when calling the LLM provider."""

    strategy: str
    tokens: int = 0
    time_spent: float = 0.0
    responses: List[LLMResponse] = field(default_factory=list)

    def consume(self, response: LLMResponse, fallback: str) -> str:
        """Record a response and return usable content or the fallback if budgeted out."""

        self.responses.append(response)
        if response.budget_exceeded:
            return fallback
        self.tokens += response.tokens
        self.time_spent += response.elapsed
        return response.content
