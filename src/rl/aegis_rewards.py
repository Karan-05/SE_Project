"""Reward shaping utilities for AEGIS-RL."""
from __future__ import annotations

from dataclasses import dataclass

from .aegis_constraints import ConstraintSnapshot
from .aegis_state import AegisMacroOption, OptionRewardFeatures


@dataclass
class AegisRewardConfig:
    """Reward coefficients for hierarchical learning."""

    option_switch_penalty: float = 0.1
    belief_uncertainty_penalty: float = 0.5
    budget_reward_scale: float = 1e-4
    calibration_bonus: float = 2.0
    constraint_scale: float = 1.0
    success_bonus: float = 20.0
    failure_penalty: float = 15.0
    escalate_penalty: float = 4.0
    escalation_bonus: float = 6.0
    verify_bonus: float = 4.0
    submit_uncertainty_penalty: float = 6.0
    progress_bonus_scale: float = 35.0
    direct_solve_streak_penalty: float = 2.0
    stagnation_penalty: float = 1.5


class AegisRewardModel:
    """Combines environment rewards with constraint and calibration signals."""

    def __init__(self, config: AegisRewardConfig | None = None) -> None:
        self.config = config or AegisRewardConfig()

    def compute(
        self,
        env_reward: float,
        snapshot: ConstraintSnapshot,
        success_probability: float,
        expected_cost: float,
        option_switches: int,
        terminated: bool,
        success: bool,
        constraint_penalty: float,
        option_features: OptionRewardFeatures,
    ) -> float:
        reward = env_reward - option_switches * self.config.option_switch_penalty
        reward -= snapshot.cvar_risk * self.config.belief_uncertainty_penalty
        reward -= constraint_penalty * self.config.constraint_scale
        reward += success_probability * self.config.calibration_bonus
        reward -= expected_cost * self.config.budget_reward_scale
        reward += option_features.progress_delta * self.config.progress_bonus_scale
        if option_features.escalation_taken() and option_features.uncertainty_before > 0.35:
            reward += self.config.escalation_bonus * option_features.uncertainty_before
        if option_features.macro_option == AegisMacroOption.DIRECT_SOLVE:
            if option_features.progress_delta <= 0.01 and option_features.direct_solve_streak > 1:
                reward -= self.config.direct_solve_streak_penalty * option_features.direct_solve_streak
        if option_features.macro_option == AegisMacroOption.VERIFY and option_features.verification_gain > 0:
            reward += self.config.verify_bonus * option_features.verification_gain
        if option_features.macro_option == AegisMacroOption.SUBMIT and option_features.uncertainty_after > 0.25:
            reward -= self.config.submit_uncertainty_penalty * option_features.uncertainty_after
        if option_features.stagnation_steps > 2:
            reward -= self.config.stagnation_penalty * option_features.stagnation_steps
        if terminated and success:
            reward += self.config.success_bonus
        if terminated and not success:
            reward -= self.config.failure_penalty
        return float(reward)
