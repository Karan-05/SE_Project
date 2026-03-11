"""AEGIS-RL hierarchical environment wrapper."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

try:  # pragma: no cover
    import gymnasium as gym
    from gymnasium import spaces
except Exception:  # pragma: no cover
    from .workflow_env import gym, spaces  # type: ignore

from .aegis_belief import BeliefEncoder, BeliefEncoderConfig
from .aegis_constraints import ConstraintConfig, ConstraintSnapshot, ConstraintTracker
from .aegis_graph_memory import GraphMemory, GraphMemoryConfig
from .aegis_options import MacroOption, OptionConfig, OptionRegistry
from .aegis_rewards import AegisRewardConfig, AegisRewardModel
from .aegis_state import (
    AegisEpisodeLogEntry,
    AegisMacroOption,
    ManagerObservation,
    OptionRewardFeatures,
    OptionTrace,
)
from .workflow_env import WorkflowAction, WorkflowEnv, WorkflowEnvConfig, WorkflowRewardConfig, WorkflowStage

REDUCED_ACTIONS: Tuple[AegisMacroOption, ...] = (
    AegisMacroOption.RESEARCH_CONTEXT,
    AegisMacroOption.DIRECT_SOLVE,
    AegisMacroOption.DECOMPOSE_SHALLOW,
    AegisMacroOption.VERIFY,
    AegisMacroOption.REPAIR,
    AegisMacroOption.SUBMIT,
)


@dataclass
class AegisEnvConfig:
    """Top-level configuration."""

    workflow: WorkflowEnvConfig = field(default_factory=WorkflowEnvConfig)
    reward: WorkflowRewardConfig = field(default_factory=WorkflowRewardConfig)
    belief: BeliefEncoderConfig = field(default_factory=BeliefEncoderConfig)
    graph: GraphMemoryConfig = field(default_factory=GraphMemoryConfig)
    constraints: ConstraintConfig = field(default_factory=ConstraintConfig)
    option: OptionConfig = field(default_factory=OptionConfig)
    aegis_reward: AegisRewardConfig = field(default_factory=AegisRewardConfig)
    log_dir: Path = field(default_factory=lambda: Path("results/aegis_rl"))
    enable_graph: bool = True
    enable_constraints: bool = True
    enable_calibration_updates: bool = True
    enable_hierarchy: bool = True
    stagnation_threshold: float = 0.01
    stagnation_patience: int = 3
    use_reduced_action_space: bool = False
    macro_actions: Tuple[AegisMacroOption, ...] | None = None
    reward_log_path: Path = field(default_factory=lambda: Path("results/aegis_rl/metrics/reward_diagnostics.jsonl"))


class AegisWorkflowEnv(gym.Env):
    """Hierarchical manager env that wraps the base WorkflowEnv."""

    metadata = {"render_modes": ["human"]}

    def __init__(self, config: AegisEnvConfig | None = None) -> None:
        super().__init__()
        self.config = config or AegisEnvConfig()
        self.base_env = WorkflowEnv(config=self.config.workflow, reward_config=self.config.reward)
        self.graph_memory = GraphMemory(self.config.graph)
        self.belief_encoder = BeliefEncoder(self.base_env.observation_dim, config=self.config.belief)
        self.constraint_tracker = ConstraintTracker(self.config.constraints)
        self.reward_model = AegisRewardModel(self.config.aegis_reward)
        if self.config.macro_actions:
            macro_sequence = list(self.config.macro_actions)
        elif self.config.use_reduced_action_space:
            macro_sequence = list(REDUCED_ACTIONS)
        else:
            macro_sequence = AegisMacroOption.ordered()
        self.macro_actions = macro_sequence
        self.macro_indices = {macro: idx for idx, macro in enumerate(self.macro_actions)}
        self.option_registry = OptionRegistry(self.macro_actions)
        self.action_space = spaces.Discrete(len(self.macro_actions))
        manager_dim = (
            self.base_env.observation_dim
            + self.config.belief.feature_dim
            + 8
            + 6
            + len(self.macro_actions)
        )
        self.observation_space = spaces.Box(low=-1.0, high=1.0, shape=(manager_dim,), dtype=np.float32)
        self.manager_logs: List[AegisEpisodeLogEntry] = []
        self.episode_id = 0
        self.option_history: List[int] = []
        self._last_budget_snapshot: Dict[str, float] = {}
        self.last_info: Dict[str, object] = {}
        self._last_option_mask = np.ones(len(self.macro_actions), dtype=np.float32)
        self._last_manager_observation = ManagerObservation(
            base_observation=np.zeros(self.base_env.observation_dim, dtype=np.float32),
            belief_state=self.belief_encoder.encode(
                base_observation=np.zeros(self.base_env.observation_dim, dtype=np.float32),
                info={},
                graph_summary=self.graph_memory.summary(),
                budget_features=np.zeros(8, dtype=np.float32),
                option_history=[],
            ),
            budget_features=np.zeros(8, dtype=np.float32),
            graph_features=np.zeros(6, dtype=np.float32),
            option_mask=self._last_option_mask.copy(),
        )
        if not self.config.enable_hierarchy:
            self.config.option.max_internal_steps = 1
        self._stagnation_steps = 0
        self._last_progress_metric = 0.0
        self._direct_solve_streak = 0
        self._graph_enabled = self.config.enable_graph
        self._constraints_enabled = self.config.enable_constraints
        self._action_hist = np.zeros(self.action_space.n, dtype=np.int64)
        self._calibration_metrics: Dict[str, float] = {"brier": 0.0, "cost_mae": 0.0}
        self.reward_log_path = self.config.reward_log_path
        self._reward_log_enabled = self.reward_log_path is not None
        if self._reward_log_enabled:
            self.reward_log_path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ Helpers
    def _budget_features(self, budget: Dict[str, float]) -> np.ndarray:
        prompt_remaining = budget.get("prompt_remaining", self.config.workflow.prompt_budget)
        completion_remaining = budget.get("completion_remaining", self.config.workflow.completion_budget)
        prompt_spent = budget.get("prompt_spent", 0.0)
        completion_spent = budget.get("completion_spent", 0.0)
        steps_taken = budget.get("steps_taken", 0)
        retries = budget.get("retries_remaining", self.config.workflow.max_retries)
        features = np.array(
            [
                prompt_remaining / max(1.0, self.config.workflow.prompt_budget),
                completion_remaining / max(1.0, self.config.workflow.completion_budget),
                prompt_spent / max(1.0, self.config.workflow.prompt_budget),
                completion_spent / max(1.0, self.config.workflow.completion_budget),
                steps_taken / max(1.0, self.config.workflow.max_steps),
                retries / max(1.0, self.config.workflow.max_retries),
                self.constraint_tracker.risk_estimate,
                self.constraint_tracker.penalty(),
            ],
            dtype=np.float32,
        )
        return features

    def _compute_progress_metric(self) -> float:
        state = self.base_env.state
        return float(
            0.4 * state.compile_status + 0.4 * state.test_pass_ratio + 0.2 * state.retrieval_coverage
        )

    def _apply_progress_delta(self, new_metric: float) -> None:
        delta = new_metric - self._last_progress_metric
        if delta > self.config.stagnation_threshold:
            self._stagnation_steps = 0
        else:
            self._stagnation_steps += 1
        self._last_progress_metric = new_metric

    def _realized_cost(self) -> float:
        spent = self.base_env.budget.prompt_spent + self.base_env.budget.completion_spent
        total = float(self.config.workflow.prompt_budget + self.config.workflow.completion_budget)
        return float(np.clip(spent / max(1.0, total), 0.0, 1.0))

    def _maybe_update_calibration(self, success: bool) -> Dict[str, float]:
        if not self.config.enable_calibration_updates:
            return dict(self._calibration_metrics)
        belief = self._last_manager_observation.belief_state
        metrics = self.belief_encoder.update_calibration(success, self._realized_cost(), belief)
        self._calibration_metrics = metrics
        return metrics

    def _log_reward_diag(
        self,
        macro_option: AegisMacroOption,
        env_reward: float,
        shaped_reward: float,
        option_features: OptionRewardFeatures,
        constraint_penalty: float,
        success_probability: float,
    ) -> None:
        if not self._reward_log_enabled or self.reward_log_path is None:
            return
        record = {
            "episode_id": self.episode_id,
            "macro_option": macro_option.value,
            "env_reward": env_reward,
            "shaped_reward": shaped_reward,
            "constraint_penalty": constraint_penalty,
            "progress_delta": option_features.progress_delta,
            "direct_solve_streak": option_features.direct_solve_streak,
            "uncertainty_before": option_features.uncertainty_before,
            "uncertainty_after": option_features.uncertainty_after,
            "verification_gain": option_features.verification_gain,
            "success_probability": success_probability,
        }
        with self.reward_log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def _macro_to_base_action(self, macro: AegisMacroOption) -> WorkflowAction | None:
        mapping = {
            AegisMacroOption.RESEARCH_CONTEXT: WorkflowAction.RETRIEVE_CONTEXT,
            AegisMacroOption.LOCALIZE: WorkflowAction.DECOMPOSE_SHALLOW,
            AegisMacroOption.DIRECT_SOLVE: WorkflowAction.DIRECT_SOLVE,
            AegisMacroOption.DECOMPOSE_SHALLOW: WorkflowAction.DECOMPOSE_SHALLOW,
            AegisMacroOption.DECOMPOSE_DEEP: WorkflowAction.DECOMPOSE_DEEP,
            AegisMacroOption.VERIFY: WorkflowAction.ASK_VERIFIER,
            AegisMacroOption.REPAIR: WorkflowAction.REPAIR_CURRENT,
            AegisMacroOption.SUBMIT: WorkflowAction.SUBMIT,
            AegisMacroOption.ABANDON: WorkflowAction.ABANDON,
        }
        return mapping.get(macro)

    def _compute_option_mask(self, belief: "AegisBeliefState", info: Dict[str, object]) -> np.ndarray:
        mask = np.ones(self.action_space.n, dtype=np.float32)
        base_mask = info.get("action_mask")
        for idx, macro in enumerate(self.macro_actions):
            base_action = self._macro_to_base_action(macro)
            if base_mask is not None and base_action is not None:
                if base_mask[int(base_action)] == 0:
                    mask[idx] = 0.0
        if AegisMacroOption.SUBMIT in self.macro_indices:
            submit_idx = self.macro_indices[AegisMacroOption.SUBMIT]
            if belief.success_probability < 0.45:
                mask[submit_idx] = 0.0
        if AegisMacroOption.DIRECT_SOLVE in self.macro_indices:
            direct_idx = self.macro_indices[AegisMacroOption.DIRECT_SOLVE]
            if self._stagnation_steps >= self.config.stagnation_patience:
                mask[direct_idx] = 0.0
        if AegisMacroOption.VERIFY in self.macro_indices:
            verify_idx = self.macro_indices[AegisMacroOption.VERIFY]
            mask[verify_idx] = 0.0 if belief.uncertainty_score < 0.2 else 1.0
        if AegisMacroOption.RESEARCH_CONTEXT in self.macro_indices and belief.uncertainty_score < 0.15:
            mask[self.macro_indices[AegisMacroOption.RESEARCH_CONTEXT]] = 0.0
        if not np.any(mask > 0):
            mask[:] = 1.0
        return mask

    def _compose_observation(self, observation: np.ndarray, info: Dict[str, object]) -> np.ndarray:
        budget = info.get("budget", {})
        budget_features = self._budget_features(budget)
        graph_summary = self.graph_memory.summary()
        belief = self.belief_encoder.encode(
            base_observation=observation,
            info=info,
            graph_summary=graph_summary,
            budget_features=budget_features,
            option_history=self.option_history[- self.config.belief.history_length :],
        )
        mask = self._compute_option_mask(belief, info)
        manager_obs = ManagerObservation(
            base_observation=observation,
            belief_state=belief,
            budget_features=budget_features,
            graph_features=graph_summary.as_array(),
            option_mask=mask,
        )
        self._last_option_mask = mask
        normalized = manager_obs.to_vector()
        normalized = np.tanh(normalized)
        self.last_info = info
        self._last_manager_observation = manager_obs
        return normalized.astype(np.float32)

    def _update_graph(self, info: Dict[str, object]) -> None:
        if not self._graph_enabled:
            return
        stage = info.get("stage", "PLANNING")
        self.graph_memory.record_file_visit(f"stage::{stage}")
        budget = info.get("budget", {})
        unresolved = int(max(0, budget.get("retries_remaining", 0)))
        if unresolved > 0:
            parent = f"{stage}_parent"
            children = [f"{stage}_retry_{i}" for i in range(unresolved)]
            self.graph_memory.record_decomposition(parent, children)

    def _update_constraints(self, budget: Dict[str, float], action: int, info: Dict[str, object]) -> None:
        prev = self._last_budget_snapshot or {
            "prompt_spent": 0.0,
            "completion_spent": 0.0,
            "steps_taken": 0,
            "verifier_calls": 0,
        }
        prompt_delta = max(0.0, budget.get("prompt_spent", 0.0) - prev.get("prompt_spent", 0.0))
        completion_delta = max(0.0, budget.get("completion_spent", 0.0) - prev.get("completion_spent", 0.0))
        step_delta = max(0, budget.get("steps_taken", 0) - prev.get("steps_taken", 0))
        self._last_budget_snapshot = {
            "prompt_spent": budget.get("prompt_spent", 0.0),
            "completion_spent": budget.get("completion_spent", 0.0),
            "steps_taken": budget.get("steps_taken", 0),
        }
        if not self._constraints_enabled:
            return
        for _ in range(step_delta or 1):
            self.constraint_tracker.observe_step(
                prompt=prompt_delta,
                completion=completion_delta,
                verifier=info.get("stage") == "VERIFYING",
                tool=info.get("stage") in {"SOLVING", "VERIFYING"},
                useless_loop=info.get("stage") == "SOLVING" and action in {4, 6},
            )

    def _log_episode_step(
        self,
        macro_option: AegisMacroOption,
        belief: ManagerObservation,
        snapshot: ConstraintSnapshot,
        constraint_penalty: float,
        terminated: bool,
        success: bool,
    ) -> None:
        entry = AegisEpisodeLogEntry(
            episode_id=self.episode_id,
            step=len(self.manager_logs) + 1,
            macro_option=macro_option,
            belief=belief.belief_state.as_dict(),
            budget=self.base_env.budget.as_dict(),
            graph_summary=self.graph_memory.summary().as_dict(),
            success_probability=belief.belief_state.success_probability,
            expected_cost=belief.belief_state.expected_cost_to_success,
            uncertainty=belief.belief_state.uncertainty_score,
            constraint_penalty=constraint_penalty,
            terminal_failure=None if success else ("failure" if terminated else None),
        )
        self.manager_logs.append(entry)

    # ------------------------------------------------------------------ Gym API
    def reset(self, *, seed: Optional[int] = None, options: Optional[Dict] = None):  # type: ignore[override]
        self.episode_id += 1
        self.manager_logs.clear()
        self.graph_memory.reset()
        self.belief_encoder.reset()
        self.constraint_tracker.reset()
        self.option_history.clear()
        self._stagnation_steps = 0
        self._direct_solve_streak = 0
        self._action_hist[:] = 0
        obs, info = self.base_env.reset(seed=seed, options=options)
        self._last_budget_snapshot = info.get("budget", {})
        self._last_progress_metric = self._compute_progress_metric()
        manager_obs = self._compose_observation(obs, info)
        return manager_obs, info

    def step(self, action: int):  # type: ignore[override]
        if not self.action_space.contains(action):
            raise ValueError(f"Macro action {action} invalid.")
        macro_option = self.macro_actions[int(action)]
        option = self.option_registry.get(macro_option)
        env_reward = 0.0
        terminated = False
        success = False
        traces: List[OptionTrace] = []
        progress_before = self._last_progress_metric
        pre_belief = self._last_manager_observation.belief_state

        def _post_step(internal_action: int, obs: np.ndarray, reward: float, info: Dict[str, object]) -> None:
            nonlocal env_reward, terminated, success
            env_reward += reward
            terminated = bool(info.get("success") or self.base_env.state.terminated)
            success = bool(info.get("success"))
            self._update_graph(info)
            budget = info.get("budget", {})
            self._update_constraints(budget, internal_action, info)
            self._apply_progress_delta(self._compute_progress_metric())

        trace, info = option.run(self.base_env, self.last_info or {}, post_step=_post_step)
        traces.append(trace)
        self.option_history.append(int(action))
        self._action_hist[int(action)] += 1
        if macro_option == AegisMacroOption.DIRECT_SOLVE:
            self._direct_solve_streak += 1
        else:
            self._direct_solve_streak = 0
        snapshot = self.constraint_tracker.snapshot()
        constraint_penalty = self.constraint_tracker.penalty() if self._constraints_enabled else 0.0
        manager_obs = self._compose_observation(self.base_env.last_observation, info)
        observation = self._last_manager_observation
        progress_delta = self._last_progress_metric - progress_before
        graph_summary = self.graph_memory.summary()
        option_features = OptionRewardFeatures(
            macro_option=macro_option,
            uncertainty_before=pre_belief.uncertainty_score,
            uncertainty_after=observation.belief_state.uncertainty_score,
            progress_delta=progress_delta,
            direct_solve_streak=self._direct_solve_streak,
            stagnation_steps=self._stagnation_steps,
            graph_visit_ratio=graph_summary.visit_ratio,
            frontier_size=graph_summary.frontier_size,
            unresolved_dependencies=graph_summary.unresolved_dependencies,
            verification_gain=max(0.0, pre_belief.uncertainty_score - observation.belief_state.uncertainty_score),
        )
        reward = self.reward_model.compute(
            env_reward=env_reward,
            snapshot=snapshot,
            success_probability=observation.belief_state.success_probability,
            expected_cost=observation.belief_state.expected_cost_to_success,
            option_switches=len(trace.internal_actions),
            terminated=terminated,
            success=success,
            constraint_penalty=constraint_penalty,
            option_features=option_features,
        )
        self._log_reward_diag(
            macro_option,
            env_reward,
            reward,
            option_features,
            constraint_penalty,
            observation.belief_state.success_probability,
        )
        done = terminated or self.base_env.state.stage.value in (4, 5)
        truncated = bool(self.base_env.state.step_count >= self.config.workflow.max_steps)
        self._log_episode_step(macro_option, observation, snapshot, constraint_penalty, done, success)
        info = dict(info)
        info["manager_trace"] = [t.as_dict() for t in traces]
        info["constraint_snapshot"] = snapshot.as_dict()
        info["constraint_penalty"] = constraint_penalty
        info["macro_option"] = macro_option.value
        info["manager_option_mask"] = self._last_option_mask.copy()
        info["manager_option_histogram"] = self._action_hist.astype(int).tolist()
        info["option_features"] = {
            "macro_option": option_features.macro_option.value,
            "uncertainty_before": option_features.uncertainty_before,
            "uncertainty_after": option_features.uncertainty_after,
            "progress_delta": option_features.progress_delta,
            "direct_solve_streak": option_features.direct_solve_streak,
            "stagnation_steps": option_features.stagnation_steps,
            "graph_visit_ratio": option_features.graph_visit_ratio,
            "frontier_size": option_features.frontier_size,
            "unresolved_dependencies": option_features.unresolved_dependencies,
            "verification_gain": option_features.verification_gain,
        }
        if done:
            info["calibration_metrics"] = self._maybe_update_calibration(success)
        else:
            info["calibration_metrics"] = dict(self._calibration_metrics)
        return manager_obs, reward, done, truncated, info

    # ------------------------------------------------------------------ Public helpers
    def manager_action_mask(self) -> np.ndarray:
        return self._last_option_mask.copy()

    def calibration_metrics(self) -> Dict[str, float]:
        return dict(self._calibration_metrics)

    def manager_snapshot(self) -> ManagerObservation:
        """Expose the last manager observation for analytics."""
        return self._last_manager_observation
