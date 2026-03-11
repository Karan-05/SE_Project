"""Typed containers for AEGIS-RL hierarchical workflow control."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Sequence, Tuple

import numpy as np


class AegisMacroOption(str, Enum):
    """High-level workflow handles surfaced to the manager policy."""

    RESEARCH_CONTEXT = "research_context"
    LOCALIZE = "localize"
    DIRECT_SOLVE = "direct_solve"
    DECOMPOSE_SHALLOW = "decompose_shallow"
    DECOMPOSE_DEEP = "decompose_deep"
    VERIFY = "verify"
    REPAIR = "repair"
    SUBMIT = "submit"
    ABANDON = "abandon"

    @classmethod
    def ordered(cls) -> List["AegisMacroOption"]:
        return [
            cls.RESEARCH_CONTEXT,
            cls.LOCALIZE,
            cls.DIRECT_SOLVE,
            cls.DECOMPOSE_SHALLOW,
            cls.DECOMPOSE_DEEP,
            cls.VERIFY,
            cls.REPAIR,
            cls.SUBMIT,
            cls.ABANDON,
        ]


class AegisTermination(Enum):
    """Option termination codes tracked for reporting."""

    CONTINUE = auto()
    COMPLETED = auto()
    FAILED = auto()
    ESCALATE = auto()
    BUDGET_HIT = auto()


@dataclass
class AegisBeliefState:
    """Compact belief vector surfaced to agents and analytics."""

    features: np.ndarray
    success_probability: float
    expected_cost_to_success: float
    uncertainty_score: float
    history_window: Tuple[int, ...] = field(default_factory=tuple)

    def as_array(self) -> np.ndarray:
        return np.asarray(self.features, dtype=np.float32)

    def as_dict(self) -> Dict[str, float]:
        vector = self.as_array()
        payload = {f"f_{idx}": float(value) for idx, value in enumerate(vector)}
        payload.update(
            {
                "success_probability": float(self.success_probability),
                "expected_cost_to_success": float(self.expected_cost_to_success),
                "uncertainty_score": float(self.uncertainty_score),
            }
        )
        return payload


@dataclass
class ManagerObservation:
    """Observation presented to the hierarchical manager."""

    base_observation: np.ndarray
    belief_state: AegisBeliefState
    budget_features: np.ndarray
    graph_features: np.ndarray
    option_mask: np.ndarray

    def to_vector(self) -> np.ndarray:
        sections: Sequence[np.ndarray] = (
            np.asarray(self.base_observation, dtype=np.float32),
            self.belief_state.as_array(),
            np.asarray(self.budget_features, dtype=np.float32),
            np.asarray(self.graph_features, dtype=np.float32),
            np.asarray(self.option_mask, dtype=np.float32),
        )
        return np.concatenate(sections, axis=0)


@dataclass
class OptionTrace:
    """Fine-grained trace for option rollouts."""

    macro_option: AegisMacroOption
    internal_actions: List[int] = field(default_factory=list)
    rewards: List[float] = field(default_factory=list)
    termination: AegisTermination = AegisTermination.CONTINUE
    duration_steps: int = 0
    uncertainty: List[float] = field(default_factory=list)

    def add(self, action: int, reward: float, uncertainty: float) -> None:
        self.internal_actions.append(action)
        self.rewards.append(reward)
        self.duration_steps += 1
        self.uncertainty.append(uncertainty)

    def as_dict(self) -> Dict:
        return {
            "option": self.macro_option.value,
            "actions": self.internal_actions,
            "rewards": self.rewards,
            "termination": self.termination.name,
            "duration": self.duration_steps,
            "uncertainty": self.uncertainty,
        }


@dataclass
class AegisEpisodeLogEntry:
    """Structured log entry for downstream analytics."""

    episode_id: int
    step: int
    macro_option: AegisMacroOption
    belief: Dict[str, float]
    budget: Dict[str, float]
    graph_summary: Dict[str, float]
    success_probability: float
    expected_cost: float
    uncertainty: float
    constraint_penalty: float
    terminal_failure: str | None = None

    def to_jsonable(self) -> Dict[str, object]:
        payload = {
            "episode_id": self.episode_id,
            "step": self.step,
            "macro_option": self.macro_option.value,
            "belief": self.belief,
            "budget": self.budget,
            "graph": self.graph_summary,
            "success_probability": self.success_probability,
            "expected_cost": self.expected_cost,
            "uncertainty": self.uncertainty,
            "constraint_penalty": self.constraint_penalty,
        }
        if self.terminal_failure:
            payload["terminal_failure"] = self.terminal_failure
        return payload


@dataclass
class OptionRewardFeatures:
    """Per-macro-option context exposing progress/uncertainty deltas."""

    macro_option: AegisMacroOption
    uncertainty_before: float
    uncertainty_after: float
    progress_delta: float
    direct_solve_streak: int
    stagnation_steps: int
    graph_visit_ratio: float
    frontier_size: int
    unresolved_dependencies: int
    verification_gain: float

    def escalation_taken(self) -> bool:
        return self.macro_option in {
            AegisMacroOption.RESEARCH_CONTEXT,
            AegisMacroOption.LOCALIZE,
            AegisMacroOption.DECOMPOSE_SHALLOW,
            AegisMacroOption.DECOMPOSE_DEEP,
            AegisMacroOption.VERIFY,
        }
