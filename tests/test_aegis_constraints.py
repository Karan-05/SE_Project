from __future__ import annotations

from src.rl.aegis_constraints import ConstraintConfig, ConstraintTracker


def test_constraint_tracker_penalty_increases_with_overuse() -> None:
    tracker = ConstraintTracker(ConstraintConfig(token_budget=100.0, step_budget=2, verifier_budget=1))
    tracker.observe_step(prompt=60.0, completion=5.0, verifier=True, tool=False, useless_loop=False)
    penalty_before = tracker.penalty()
    tracker.observe_step(prompt=60.0, completion=5.0, verifier=True, tool=True, useless_loop=True)
    penalty_after = tracker.penalty()
    assert penalty_after >= penalty_before
    snapshot = tracker.snapshot()
    assert snapshot.prompt_spent > 0
    updates = tracker.end_episode(success=False)
    assert isinstance(updates, dict)
