"""Teacher-guided residual learning utilities for TARL-AEGIS."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

import numpy as np

from .aegis_state import AegisMacroOption
from .workflow_agents import HeuristicThresholdAgent, HeuristicThresholdConfig
from .workflow_env import WorkflowAction


MACRO_FROM_ACTION: Dict[WorkflowAction, AegisMacroOption] = {
    WorkflowAction.DIRECT_SOLVE: AegisMacroOption.DIRECT_SOLVE,
    WorkflowAction.RETRIEVE_CONTEXT: AegisMacroOption.RESEARCH_CONTEXT,
    WorkflowAction.DECOMPOSE_SHALLOW: AegisMacroOption.DECOMPOSE_SHALLOW,
    WorkflowAction.DECOMPOSE_DEEP: AegisMacroOption.DECOMPOSE_SHALLOW,
    WorkflowAction.RUN_TESTS: AegisMacroOption.VERIFY,
    WorkflowAction.ASK_VERIFIER: AegisMacroOption.VERIFY,
    WorkflowAction.REPAIR_CURRENT: AegisMacroOption.REPAIR,
    WorkflowAction.SUBMIT: AegisMacroOption.SUBMIT,
}


def map_action_to_macro(action: int | WorkflowAction, allowed: Iterable[AegisMacroOption]) -> AegisMacroOption:
    """Maps a workflow action into the closest macro option."""
    try:
        base = WorkflowAction(action)
    except Exception:
        base = WorkflowAction.DIRECT_SOLVE
    macro = MACRO_FROM_ACTION.get(base, AegisMacroOption.DIRECT_SOLVE)
    allowed_set = set(allowed)
    if macro in allowed_set:
        return macro
    if allowed_set:
        # fall back to first allowed macro
        return next(iter(allowed_set))
    return macro


class TeacherAdvisor:
    """Wraps the heuristic baseline to propose teacher actions."""

    def __init__(self, config: HeuristicThresholdConfig | None = None, allowed: Iterable[AegisMacroOption] | None = None) -> None:
        self.agent = HeuristicThresholdAgent(config)
        self.allowed = tuple(allowed or AegisMacroOption.ordered())

    def propose(self, observation: np.ndarray, action_mask: Optional[np.ndarray], info: Dict[str, object]) -> AegisMacroOption:
        action = self.agent.act(observation, action_mask=action_mask, info=info)
        macro = map_action_to_macro(action, self.allowed)
        return macro


class OverrideClassifier:
    """Simple logistic classifier that decides whether to override the teacher."""

    def __init__(self, feature_dim: int, lr: float = 0.05) -> None:
        self.weights = np.zeros(feature_dim, dtype=np.float32)
        self.bias = 0.0
        self.lr = lr

    def predict(self, features: np.ndarray) -> float:
        z = float(np.dot(self.weights, features) + self.bias)
        return 1.0 / (1.0 + np.exp(-z))

    def update(self, features: np.ndarray, label: float) -> None:
        pred = self.predict(features)
        error = label - pred
        self.weights += self.lr * error * features
        self.bias += self.lr * error


@dataclass
class OverrideStats:
    overrides: int = 0
    follows: int = 0
    wins: int = 0
    regrets: int = 0

    def record(self, override: bool, win: bool, regret: bool) -> None:
        if override:
            self.overrides += 1
        else:
            self.follows += 1
        if win:
            self.wins += 1
        if regret:
            self.regrets += 1

    def as_dict(self) -> Dict[str, float]:
        total = self.overrides + self.follows
        return {
            "override_rate": self.overrides / total if total else 0.0,
            "override_win_rate": self.wins / self.overrides if self.overrides else 0.0,
            "override_regret_rate": self.regrets / self.overrides if self.overrides else 0.0,
        }
