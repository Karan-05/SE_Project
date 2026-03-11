"""Budget and risk constraint utilities for AEGIS-RL."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

import numpy as np


@dataclass
class ConstraintConfig:
    """Constraint hyper-parameters."""

    token_budget: float = 60_000.0
    step_budget: int = 32
    verifier_budget: int = 6
    tool_budget: int = 32
    useless_loop_limit: int = 5
    risk_beta: float = 0.1
    dual_learning_rate: float = 0.05
    cvar_alpha: float = 0.2


@dataclass
class ConstraintSnapshot:
    prompt_spent: float
    completion_spent: float
    steps_taken: int
    verifier_calls: int
    tool_calls: int
    useless_loops: int
    cvar_risk: float

    def as_array(self) -> np.ndarray:
        return np.array(
            [
                self.prompt_spent,
                self.completion_spent,
                self.steps_taken,
                self.verifier_calls,
                self.tool_calls,
                self.useless_loops,
                self.cvar_risk,
            ],
            dtype=np.float32,
        )

    def as_dict(self) -> Dict[str, float]:
        return {
            "prompt_spent": self.prompt_spent,
            "completion_spent": self.completion_spent,
            "steps_taken": float(self.steps_taken),
            "verifier_calls": float(self.verifier_calls),
            "tool_calls": float(self.tool_calls),
            "useless_loops": float(self.useless_loops),
            "cvar_risk": float(self.cvar_risk),
        }


class ConstraintTracker:
    """Tracks resource usage and computes constraint penalties."""

    def __init__(self, config: ConstraintConfig | None = None) -> None:
        self.config = config or ConstraintConfig()
        self.prompt_spent = 0.0
        self.completion_spent = 0.0
        self.steps_taken = 0
        self.verifier_calls = 0
        self.tool_calls = 0
        self.useless_loops = 0
        self.dual_prompt = 0.0
        self.dual_steps = 0.0
        self.dual_verifier = 0.0
        self.dual_tool = 0.0
        self.risk_estimate = 0.0

    def reset(self) -> None:
        self.prompt_spent = 0.0
        self.completion_spent = 0.0
        self.steps_taken = 0
        self.verifier_calls = 0
        self.tool_calls = 0
        self.useless_loops = 0
        self.dual_prompt = 0.0
        self.dual_steps = 0.0
        self.dual_verifier = 0.0
        self.dual_tool = 0.0
        self.risk_estimate = 0.0

    def observe_step(self, prompt: float, completion: float, verifier: bool, tool: bool, useless_loop: bool) -> None:
        self.prompt_spent += prompt
        self.completion_spent += completion
        self.steps_taken += 1
        if verifier:
            self.verifier_calls += 1
        if tool:
            self.tool_calls += 1
        if useless_loop:
            self.useless_loops += 1
        # simple CVaR proxy: penalize tail usage
        over_budget = max(0.0, self.prompt_spent - self.config.token_budget)
        tail_prob = np.exp(-over_budget / max(1.0, self.config.token_budget))
        self.risk_estimate = (1 - self.config.risk_beta) * self.risk_estimate + self.config.risk_beta * tail_prob

    def penalty(self) -> float:
        prompt_over = max(0.0, self.prompt_spent - self.config.token_budget)
        completion_over = max(0.0, self.completion_spent - self.config.token_budget)
        step_over = max(0, self.steps_taken - self.config.step_budget)
        verifier_over = max(0, self.verifier_calls - self.config.verifier_budget)
        tool_over = max(0, self.tool_calls - self.config.tool_budget)
        loop_over = max(0, self.useless_loops - self.config.useless_loop_limit)
        penalty = (
            self.dual_prompt * prompt_over
            + self.dual_prompt * completion_over * 0.5
            + self.dual_steps * step_over
            + self.dual_verifier * verifier_over
            + self.dual_tool * tool_over
            + loop_over * 0.5
        )
        penalty += self.config.risk_beta * self.risk_estimate
        return float(penalty)

    def snapshot(self) -> ConstraintSnapshot:
        return ConstraintSnapshot(
            prompt_spent=self.prompt_spent,
            completion_spent=self.completion_spent,
            steps_taken=self.steps_taken,
            verifier_calls=self.verifier_calls,
            tool_calls=self.tool_calls,
            useless_loops=self.useless_loops,
            cvar_risk=self.risk_estimate,
        )

    def end_episode(self, success: bool) -> Dict[str, float]:
        prompt_over = max(0.0, self.prompt_spent - self.config.token_budget)
        step_over = max(0, self.steps_taken - self.config.step_budget)
        verifier_over = max(0, self.verifier_calls - self.config.verifier_budget)
        updates = {
            "dual_prompt": prompt_over > 0,
            "dual_steps": step_over > 0,
            "dual_verifier": verifier_over > 0,
        }
        self.dual_prompt = max(0.0, self.dual_prompt + self.config.dual_learning_rate * prompt_over)
        self.dual_steps = max(0.0, self.dual_steps + self.config.dual_learning_rate * step_over)
        self.dual_verifier = max(0.0, self.dual_verifier + self.config.dual_learning_rate * verifier_over)
        self.dual_tool = max(0.0, self.dual_tool + self.config.dual_learning_rate * max(0, self.tool_calls - self.config.tool_budget))
        self.risk_estimate = (1 - self.config.cvar_alpha) * self.risk_estimate + self.config.cvar_alpha * (0.0 if success else 1.0)
        return updates
