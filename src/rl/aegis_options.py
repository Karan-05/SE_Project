"""Hierarchical macro-option executors for AEGIS-RL."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Tuple

import numpy as np

from .aegis_state import AegisMacroOption, AegisTermination, OptionTrace
from .workflow_env import WorkflowAction, WorkflowEnv


PolicyFn = Callable[[np.ndarray, Dict[str, object]], WorkflowAction]


@dataclass
class OptionConfig:
    """Parameterizes default option behaviour."""

    max_internal_steps: int = 3
    continue_threshold: float = 0.2


class MacroOption:
    """Base class for hierarchical options."""

    def __init__(self, config: OptionConfig | None = None) -> None:
        self.config = config or OptionConfig()

    def _single_action(self, env: WorkflowEnv, info: Dict[str, object]) -> WorkflowAction:
        raise NotImplementedError

    def run(
        self,
        env: WorkflowEnv,
        info: Dict[str, object],
        post_step: Callable[[int, np.ndarray, float, Dict[str, object]], None] | None = None,
    ) -> Tuple[OptionTrace, Dict[str, object]]:
        trace = OptionTrace(macro_option=self.macro_name)
        terminated = False
        for _ in range(self.config.max_internal_steps):
            action = self._single_action(env, info)
            obs, reward, terminated_flag, truncated_flag, info = env.step(int(action))
            if post_step:
                post_step(int(action), obs, reward, info)
            trace.add(action=int(action), reward=reward, uncertainty=float(np.mean(info.get("uncertainty_summary", [0.0]))))
            terminated = terminated_flag or truncated_flag
            if terminated or self._should_stop(obs, info):
                break
        trace.termination = AegisTermination.COMPLETED if not terminated else AegisTermination.ESCALATE
        return trace, info

    @property
    def macro_name(self) -> AegisMacroOption:
        raise NotImplementedError

    def _should_stop(self, observation: np.ndarray, info: Dict[str, object]) -> bool:
        uncertainty = info.get("uncertainty_summary", [0.0])
        if isinstance(uncertainty, (list, tuple, np.ndarray)):
            value = float(np.mean(uncertainty))
        else:
            value = float(uncertainty)
        return value < self.config.continue_threshold


class ResearchContextOption(MacroOption):
    @property
    def macro_name(self) -> AegisMacroOption:
        return AegisMacroOption.RESEARCH_CONTEXT

    def _single_action(self, env: WorkflowEnv, info: Dict[str, object]) -> WorkflowAction:
        return WorkflowAction.RETRIEVE_CONTEXT


class LocalizeOption(MacroOption):
    @property
    def macro_name(self) -> AegisMacroOption:
        return AegisMacroOption.LOCALIZE

    def _single_action(self, env: WorkflowEnv, info: Dict[str, object]) -> WorkflowAction:
        return WorkflowAction.DECOMPOSE_SHALLOW


class DirectSolveOption(MacroOption):
    @property
    def macro_name(self) -> AegisMacroOption:
        return AegisMacroOption.DIRECT_SOLVE

    def _single_action(self, env: WorkflowEnv, info: Dict[str, object]) -> WorkflowAction:
        return WorkflowAction.DIRECT_SOLVE


class DecomposeDeepOption(MacroOption):
    @property
    def macro_name(self) -> AegisMacroOption:
        return AegisMacroOption.DECOMPOSE_DEEP

    def _single_action(self, env: WorkflowEnv, info: Dict[str, object]) -> WorkflowAction:
        return WorkflowAction.DECOMPOSE_DEEP


class VerifyOption(MacroOption):
    @property
    def macro_name(self) -> AegisMacroOption:
        return AegisMacroOption.VERIFY

    def _single_action(self, env: WorkflowEnv, info: Dict[str, object]) -> WorkflowAction:
        if info.get("stage") == "FINAL_REVIEW":
            return WorkflowAction.SUBMIT
        return WorkflowAction.ASK_VERIFIER


class RepairOption(MacroOption):
    @property
    def macro_name(self) -> AegisMacroOption:
        return AegisMacroOption.REPAIR

    def _single_action(self, env: WorkflowEnv, info: Dict[str, object]) -> WorkflowAction:
        return WorkflowAction.REPAIR_CURRENT


class SubmitOption(MacroOption):
    @property
    def macro_name(self) -> AegisMacroOption:
        return AegisMacroOption.SUBMIT

    def _single_action(self, env: WorkflowEnv, info: Dict[str, object]) -> WorkflowAction:
        return WorkflowAction.SUBMIT


class AbandonOption(MacroOption):
    @property
    def macro_name(self) -> AegisMacroOption:
        return AegisMacroOption.ABANDON

    def _single_action(self, env: WorkflowEnv, info: Dict[str, object]) -> WorkflowAction:
        return WorkflowAction.ABANDON


class DecomposeShallowOption(MacroOption):
    @property
    def macro_name(self) -> AegisMacroOption:
        return AegisMacroOption.DECOMPOSE_SHALLOW

    def _single_action(self, env: WorkflowEnv, info: Dict[str, object]) -> WorkflowAction:
        return WorkflowAction.DECOMPOSE_SHALLOW


class OptionRegistry:
    """Factory/registry for macro options."""

    def __init__(self, allowed: Iterable[AegisMacroOption] | None = None) -> None:
        self._registry: Dict[AegisMacroOption, MacroOption] = {}
        self._all_options = {
            AegisMacroOption.RESEARCH_CONTEXT: ResearchContextOption(),
            AegisMacroOption.LOCALIZE: LocalizeOption(),
            AegisMacroOption.DIRECT_SOLVE: DirectSolveOption(),
            AegisMacroOption.DECOMPOSE_SHALLOW: DecomposeShallowOption(),
            AegisMacroOption.DECOMPOSE_DEEP: DecomposeDeepOption(),
            AegisMacroOption.VERIFY: VerifyOption(),
            AegisMacroOption.REPAIR: RepairOption(),
            AegisMacroOption.SUBMIT: SubmitOption(),
            AegisMacroOption.ABANDON: AbandonOption(),
        }
        use = list(allowed) if allowed else list(AegisMacroOption.ordered())
        for option in use:
            if option not in self._all_options:
                continue
            self._registry[option] = self._all_options[option]

    def get(self, macro_option: AegisMacroOption) -> MacroOption:
        if macro_option not in self._registry:
            raise KeyError(f"Option {macro_option.value} not registered.")
        return self._registry[macro_option]

    def macros(self) -> List[AegisMacroOption]:
        return list(self._registry.keys())
