from src.decomposition.interfaces import DecompositionContext
from src.decomposition.strategies.contract_first import ContractFirstStrategy
from src.providers import llm


def test_llm_budget_and_strategy_fallback(monkeypatch):
    monkeypatch.setenv("LLM_TOKEN_BUDGET", "3")
    monkeypatch.setenv("LLM_TIME_BUDGET_SECONDS", "0.006")
    first = llm.call("hello world", caller="budget-test")
    assert not first.budget_exceeded
    second = llm.call("second call", caller="budget-test")
    assert second.budget_exceeded

    ctx = DecompositionContext(
        task_id="budget",
        problem_statement="Add numbers",
        metadata={
            "inputs": "List[int]",
            "outputs": "int",
            "tests": [{"input": [[1, 2, 3]], "expected": 6}],
            "reference_solution": "def solve(nums):\n    return sum(nums)\n",
            "entry_point": "solve",
        },
    )
    strategy = ContractFirstStrategy()
    plan = strategy.decompose(ctx)
    result = strategy.solve(ctx, plan)
    assert "tokens_used" in result.metrics
    assert result.metrics["pass_rate"] == 1.0
