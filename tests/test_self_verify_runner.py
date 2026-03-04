from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import pytest

from src.decomposition.interfaces import DecompositionContext, DecompositionPlan, StrategyResult, TaskDecompositionStrategy
from src.decomposition.self_verify import RetryConfig, execute_with_self_verification, _set_memory_adapter
from src.decomposition.strategies._utils import run_tests


@dataclass
class _StubStrategy(TaskDecompositionStrategy):
    name: str
    implementation: str

    def decompose(self, ctx: DecompositionContext) -> DecompositionPlan:
        return DecompositionPlan(strategy_name=self.name, subtasks=["plan"], diagnostics={})

    def solve(self, ctx: DecompositionContext, plan: DecompositionPlan) -> StrategyResult:
        tests_run = run_tests(self.implementation, ctx)
        return StrategyResult(plan=plan, solution_code=self.implementation, tests_run=tests_run, metrics={"pass_rate": 0.0})


class _MemoryStub:
    def __init__(self):
        self.records = []

    def store(self, task_id, reflection_text, failure_signature, metadata):
        self.records.append(
            {
                "task_id": task_id,
                "reflection": reflection_text,
                "failure_signature": failure_signature,
                "metadata": metadata,
            }
        )


def _ctx_for_tests() -> DecompositionContext:
    return DecompositionContext(
        task_id="repair",
        problem_statement="Return x + 1",
        metadata={
            "entry_point": "solve",
            "tests": [
                {"name": "small", "input": [1], "expected": 2},
                {"name": "another", "input": [3], "expected": 4},
            ],
        },
    )


def test_retry_repairs_until_pass(monkeypatch):
    ctx = _ctx_for_tests()
    failing = _StubStrategy("flaky", "def solve(x):\n    return x - 1\n")
    registry = {"flaky": failing}

    def fake_repair(strategy_name, ctx, plan, summary, code):
        assert summary.failing_tests
        return "def solve(x):\n    return x + 1\n", {"llm_tokens": "7"}

    monkeypatch.setattr("src.decomposition.self_verify.request_repair_patch", fake_repair)
    cfg = RetryConfig(max_retries_per_strategy=2, max_total_attempts=3)
    result = execute_with_self_verification(ctx, ["flaky"], cfg, registry=registry)
    assert result.metrics["final_status"] == "passed"
    assert result.metrics["attempt_count"] == 2.0
    assert float(result.metrics["pass_rate"]) == pytest.approx(1.0)


def test_stagnation_triggers_fallback(monkeypatch):
    ctx = _ctx_for_tests()
    first = _StubStrategy("primary", "def solve(x):\n    return x - 1\n")
    second = _StubStrategy("secondary", "def solve(x):\n    return x + 1\n")
    registry = {"primary": first, "secondary": second}
    calls: Dict[str, int] = {"primary": 0, "secondary": 0}

    def fake_repair(strategy_name, ctx, plan, summary, code):
        calls[strategy_name] += 1
        if strategy_name == "primary":
            return code, {"llm_tokens": "5"}
        return "def solve(x):\n    return x + 1\n", {"llm_tokens": "5"}

    monkeypatch.setattr("src.decomposition.self_verify.request_repair_patch", fake_repair)
    cfg = RetryConfig(
        max_retries_per_strategy=2,
        max_total_attempts=4,
        stagnation_patience=1,
        strategy_order=["primary", "secondary"],
        max_strategies_to_try=2,
    )
    result = execute_with_self_verification(ctx, ["primary", "secondary"], cfg, registry=registry)
    assert "primary->secondary" == result.metrics["fallback_path"]
    assert result.metrics["strategy_used"] == "secondary"
    assert result.metrics["final_status"] == "passed"
    assert calls["primary"] == 1


def test_respects_max_retries(monkeypatch):
    ctx = _ctx_for_tests()
    failing = _StubStrategy("limited", "def solve(x):\n    return x - 1\n")
    registry = {"limited": failing}
    repair_calls: List[int] = []

    def fake_repair(strategy_name, ctx, plan, summary, code):
        repair_calls.append(1)
        return "def solve(x):\n    return x + 1\n", {"llm_tokens": "5"}

    monkeypatch.setattr("src.decomposition.self_verify.request_repair_patch", fake_repair)
    cfg = RetryConfig(max_retries_per_strategy=1, max_total_attempts=1)
    result = execute_with_self_verification(ctx, ["limited"], cfg, registry=registry)
    assert result.metrics["final_status"] == "failed"
    assert result.metrics["attempt_count"] == 1.0
    assert repair_calls == []


def test_attempt_timeout_sets_metrics(monkeypatch):
    ctx = _ctx_for_tests()
    failing = _StubStrategy("slow", "def solve(x):\n    return x - 1\n")
    registry = {"slow": failing}

    class _FakePerf:
        def __init__(self, step: float):
            self.value = 0.0
            self.step = step

        def __call__(self) -> float:
            self.value += self.step
            return self.value

    fake_perf = _FakePerf(step=5.0)
    monkeypatch.setattr("src.decomposition.self_verify.time.perf_counter", fake_perf)
    cfg = RetryConfig(
        max_retries_per_strategy=1,
        max_total_attempts=1,
        attempt_timeout_seconds=1.0,
        task_timeout_seconds=100.0,
    )
    result = execute_with_self_verification(ctx, ["slow"], cfg, registry=registry)
    assert result.metrics["timed_out"] is True
    assert result.metrics["timeout_reason"] == "attempt"


def test_memory_reflection_stored_and_injected(monkeypatch):
    ctx = _ctx_for_tests()
    failing = _StubStrategy("flaky", "def solve(x):\n    return x - 1\n")
    registry = {"flaky": failing}
    memory = _MemoryStub()
    _set_memory_adapter(memory)
    cfg = RetryConfig(max_retries_per_strategy=1, max_total_attempts=1)
    result = execute_with_self_verification(ctx, ["flaky"], cfg, registry=registry)
    assert result.metrics["final_status"] == "failed"
    assert memory.records, "expected memory reflections to be stored"
    assert ctx.metadata.get("memory_hints"), "memory hints should be appended to context"
    assert "Memory Hint" in ctx.problem_statement
    _set_memory_adapter(None)
