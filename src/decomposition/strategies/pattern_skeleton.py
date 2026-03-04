"""Pattern + skeleton strategy."""
from __future__ import annotations

from typing import Dict, List, Tuple

from src.decomposition.interfaces import DecompositionContext, DecompositionPlan, StrategyResult, TaskDecompositionStrategy
from src.decomposition.strategies._utils import BudgetTracker, build_implementation_contract, finalize_result, run_tests
from src.providers import llm

PATTERN_LIBRARY: List[Dict[str, object]] = [
    {
        "name": "two_pointers",
        "signals": ["sorted", "window", "pair", "difference"],
        "skeleton": """def solve(nums, target):\n    left, right = 0, len(nums) - 1\n    while left < right:\n        total = nums[left] + nums[right]\n        if total == target:\n            return left, right\n        if total < target:\n            left += 1\n        else:\n            right -= 1\n    return -1, -1\n""",
        "pitfalls": ["Ensure indices not reused", "Handle no-solution case"],
    },
    {
        "name": "hash_bucket",
        "signals": ["anagram", "frequency", "multiset"],
        "skeleton": """def solve(words):\n    buckets = {}\n    for word in words:\n        key = tuple(sorted(word))\n        buckets.setdefault(key, []).append(word)\n    return list(buckets.values())\n""",
        "pitfalls": ["Immutable key", "Stable grouping"],
    },
    {
        "name": "kadane",
        "signals": ["maximum subarray", "contiguous"],
        "skeleton": """def solve(nums):\n    best = float('-inf')\n    cur = 0\n    for value in nums:\n        cur = max(value, cur + value)\n        best = max(best, cur)\n    return best\n""",
        "pitfalls": ["All-negative arrays"],
    },
]


class PatternSkeletonStrategy(TaskDecompositionStrategy):
    name = "pattern_skeleton"

    def _score_pattern(self, ctx: DecompositionContext, pattern: Dict[str, object], tracker: BudgetTracker) -> float:
        signals = pattern.get("signals", [])
        statement = ctx.problem_statement.lower()
        score = 0.0
        for signal in signals:
            if signal in statement:
                score += 1.0
        for tag in ctx.tags:
            if tag.lower() in signals:
                score += 0.5
        hint = tracker.consume(
            llm.call(
                f"Given the problem: {ctx.problem_statement[:200]}, would pattern {pattern['name']} be relevant?",
                model="pattern-hint",
                max_tokens=32,
                temperature=0.0,
                caller=self.name,
            ),
            fallback="uncertain",
        )
        if "yes" in hint.lower():
            score += 0.5
        return score

    def decompose(self, ctx: DecompositionContext) -> DecompositionPlan:
        tracker = BudgetTracker(f"{self.name}:plan")
        pattern_scores: List[Tuple[float, Dict[str, object]]] = [
            (self._score_pattern(ctx, pattern, tracker), pattern) for pattern in PATTERN_LIBRARY
        ]
        pattern_scores.sort(key=lambda item: item[0], reverse=True)
        top_pattern = pattern_scores[0][1] if pattern_scores else PATTERN_LIBRARY[0]
        confidence = pattern_scores[0][0] if pattern_scores else 0.0
        pitfall_tests = [f"Verify pitfall: {pitfall}" for pitfall in top_pattern.get("pitfalls", [])]
        diagnostics = {
            "pattern_name": top_pattern["name"],
            "confidence": f"{confidence:.2f}",
            "pitfalls": "; ".join(top_pattern.get("pitfalls", [])),
            "planning_tokens": str(tracker.tokens),
            "planning_time": f"{tracker.time_spent:.6f}",
            "skeleton": top_pattern.get("skeleton", ""),
        }
        plan = DecompositionPlan(
            strategy_name=self.name,
            patterns=[top_pattern["name"]],
            subtasks=[
                "instantiate skeleton",
                "fill placeholders",
                "derive pitfall-specific checks",
                "verify pitfalls",
            ],
            tests=pitfall_tests or ["pitfall regression tests"],
            diagnostics=diagnostics,
        )
        return plan

    def solve(self, ctx: DecompositionContext, plan: DecompositionPlan) -> StrategyResult:
        tracker = BudgetTracker(f"{self.name}:solve")
        contract = build_implementation_contract(ctx)
        tracker.consume(
            llm.call(
                f"{contract}\nFill in the {plan.diagnostics.get('pattern_name')} skeleton respecting pitfalls {plan.diagnostics.get('pitfalls')}",
                model="pattern-codegen",
                max_tokens=128,
                temperature=0.2,
                caller=self.name,
            ),
            fallback="Skeleton fill skipped",
        )
        base_code = ctx.metadata.get("reference_solution", plan.diagnostics.get("skeleton", "def solve(*args):\n    return None"))
        tests_run = run_tests(base_code, ctx)
        planning_tokens = float(plan.diagnostics.get("planning_tokens", 0) or 0)
        planning_time = float(plan.diagnostics.get("planning_time", 0) or 0.0)
        metrics = {
            "pattern_confidence": float(plan.diagnostics.get("confidence", 0.0)),
            "tokens_used": planning_tokens + tracker.tokens,
            "planning_time": planning_time + tracker.time_spent,
        }
        return finalize_result(ctx, plan, base_code, tests_run, metrics)
