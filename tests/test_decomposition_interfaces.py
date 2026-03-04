from src.decomposition.interfaces import DecompositionContext
from src.decomposition.strategies.contract_first import ContractFirstStrategy


def test_contract_first_creates_contract():
    ctx = DecompositionContext(
        task_id="demo",
        problem_statement="Add numbers",
        metadata={
            "inputs": "List[int]",
            "outputs": "int",
            "reference_solution": "def solve(nums):\n    return sum(nums)\n",
            "tests": [{"input": [[1, 2, 3]], "expected": 6}],
            "entry_point": "solve",
        },
    )
    strat = ContractFirstStrategy()
    plan = strat.decompose(ctx)
    assert plan.contract["inputs"] == "List[int]"
    result = strat.solve(ctx, plan)
    assert result.metrics["pass_rate"] == 1.0
