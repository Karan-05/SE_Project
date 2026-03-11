from __future__ import annotations

from src.rl.aegis_constraints import ConstraintSnapshot
from src.rl.aegis_rewards import AegisRewardConfig, AegisRewardModel
from src.rl.aegis_state import AegisMacroOption, OptionRewardFeatures


def _snapshot() -> ConstraintSnapshot:
    return ConstraintSnapshot(
        prompt_spent=0.0,
        completion_spent=0.0,
        steps_taken=0,
        verifier_calls=0,
        tool_calls=0,
        useless_loops=0,
        cvar_risk=0.0,
    )


def _features(
    macro: AegisMacroOption,
    progress: float = 0.0,
    streak: int = 0,
    uncertainty_before: float = 0.5,
    uncertainty_after: float = 0.4,
) -> OptionRewardFeatures:
    return OptionRewardFeatures(
        macro_option=macro,
        uncertainty_before=uncertainty_before,
        uncertainty_after=uncertainty_after,
        progress_delta=progress,
        direct_solve_streak=streak,
        stagnation_steps=streak,
        graph_visit_ratio=0.2,
        frontier_size=2,
        unresolved_dependencies=1,
        verification_gain=max(0.0, uncertainty_before - uncertainty_after),
    )


def test_reward_penalizes_repeating_direct_solve_without_progress() -> None:
    model = AegisRewardModel(AegisRewardConfig())
    low = model.compute(
        env_reward=0.0,
        snapshot=_snapshot(),
        success_probability=0.4,
        expected_cost=0.2,
        option_switches=1,
        terminated=False,
        success=False,
        constraint_penalty=0.0,
        option_features=_features(AegisMacroOption.DIRECT_SOLVE, progress=0.0, streak=1),
    )
    high = model.compute(
        env_reward=0.0,
        snapshot=_snapshot(),
        success_probability=0.4,
        expected_cost=0.2,
        option_switches=1,
        terminated=False,
        success=False,
        constraint_penalty=0.0,
        option_features=_features(AegisMacroOption.DIRECT_SOLVE, progress=0.0, streak=4),
    )
    assert high < low


def test_reward_prefers_escalation_under_high_uncertainty() -> None:
    model = AegisRewardModel(AegisRewardConfig())
    research = model.compute(
        env_reward=0.0,
        snapshot=_snapshot(),
        success_probability=0.3,
        expected_cost=0.2,
        option_switches=1,
        terminated=False,
        success=False,
        constraint_penalty=0.0,
        option_features=_features(AegisMacroOption.RESEARCH_CONTEXT, progress=0.05, streak=0, uncertainty_before=0.8, uncertainty_after=0.4),
    )
    direct = model.compute(
        env_reward=0.0,
        snapshot=_snapshot(),
        success_probability=0.3,
        expected_cost=0.2,
        option_switches=1,
        terminated=False,
        success=False,
        constraint_penalty=0.0,
        option_features=_features(AegisMacroOption.DIRECT_SOLVE, progress=0.0, streak=0, uncertainty_before=0.8, uncertainty_after=0.75),
    )
    assert research > direct
