"""Workflow-aware reinforcement learning environment for agentic SE pipelines."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Dict, List, Tuple

import numpy as np

try:  # pragma: no cover - optional dependency shim
    import gymnasium as gym
    from gymnasium import spaces
except Exception:  # pragma: no cover - lightweight fallback
    class _BaseEnv:
        def __init__(self, *_, **__):
            return None

    class _Discrete:
        def __init__(self, n: int) -> None:
            self.n = n

        def sample(self) -> int:
            return int(np.random.randint(self.n))

        def contains(self, x: int) -> bool:
            return 0 <= int(x) < self.n

    class _Box:
        def __init__(self, low, high, shape, dtype) -> None:
            self.low = low
            self.high = high
            self.shape = shape
            self.dtype = dtype

        def sample(self) -> np.ndarray:
            return np.random.uniform(low=self.low, high=self.high, size=self.shape).astype(self.dtype)

        def contains(self, x) -> bool:
            return np.shape(x) == tuple(self.shape)

    class _SpacesNamespace:
        Box = _Box
        Discrete = _Discrete

    class _GymNamespace:
        Env = _BaseEnv

    gym = _GymNamespace()
    spaces = _SpacesNamespace()


class WorkflowAction(IntEnum):
    """Discrete workflow control actions exposed to the policy."""

    DIRECT_SOLVE = 0
    DECOMPOSE_SHALLOW = 1
    DECOMPOSE_DEEP = 2
    RETRIEVE_CONTEXT = 3
    RUN_TESTS = 4
    ASK_VERIFIER = 5
    SPAWN_ALT_SOLVER = 6
    REPAIR_CURRENT = 7
    SUBMIT = 8
    ABANDON = 9


class WorkflowStage(IntEnum):
    """Coarse workflow stages used inside the simulator."""

    PLANNING = 0
    SOLVING = 1
    VERIFYING = 2
    FINAL_REVIEW = 3
    DONE = 4
    ABANDONED = 5


class WorkflowEvaluationMode(str, Enum):
    """Modes for budget and constraint handling."""

    UNCONSTRAINED = "unconstrained"
    FIXED_TOKEN = "fixed_token_budget"
    FIXED_STEP = "fixed_step_budget"


@dataclass
class WorkflowRewardConfig:
    """Reward weights surfaced for experiment sweeps."""

    success_bonus: float = 25.0
    test_improvement: float = 4.0
    compile_bonus: float = 2.5
    token_cost: float = 0.0002
    latency_cost: float = 0.08
    invalid_action_penalty: float = 3.0
    repair_loop_penalty: float = 1.5
    budget_violation_penalty: float = 8.0
    abandon_penalty: float = 10.0
    abandon_recoverable_penalty: float = 15.0
    step_penalty: float = 0.05
    failure_penalty: float = 5.0


@dataclass
class WorkflowEnvConfig:
    """Environment hyper-parameters and deterministic knobs."""

    seed: int = 2026
    max_steps: int = 24
    prompt_budget: int = 40_000
    completion_budget: int = 26_000
    max_retries: int = 6
    retrieval_limit: int = 6
    verifier_limit: int = 4
    enable_action_masking: bool = True
    enable_uncertainty_features: bool = True
    evaluation_mode: WorkflowEvaluationMode = WorkflowEvaluationMode.UNCONSTRAINED
    track_episode_logs: bool = True
    noise_scale: float = 0.05
    max_subtasks: int = 6
    min_recoverable_ratio: float = 0.35
    disabled_actions: Tuple[WorkflowAction, ...] = field(default_factory=tuple)
    difficulty_min: float | None = None
    difficulty_max: float | None = None


@dataclass
class WorkflowTaskProfile:
    """Synthetic task metadata fed into the state."""

    difficulty: float
    scope: float
    baseline_compile: float
    baseline_tests: float
    retrieval_complexity: float
    verifier_strictness: float


@dataclass
class BudgetState:
    """Tracks agent resource consumption for both logging and masking."""

    prompt_tokens: float
    completion_tokens: float
    step_budget: int
    retries_remaining: int
    repair_count: int = 0
    verifier_calls: int = 0
    retrieval_calls: int = 0

    prompt_spent: float = 0.0
    completion_spent: float = 0.0
    steps_taken: int = 0

    def consume(self, prompt: float, completion: float, step_increment: int = 1) -> None:
        self.prompt_spent += prompt
        self.completion_spent += completion
        self.prompt_tokens -= prompt
        self.completion_tokens -= completion
        self.steps_taken += step_increment

    def as_dict(self) -> Dict[str, float]:
        return {
            "prompt_remaining": self.prompt_tokens,
            "completion_remaining": self.completion_tokens,
            "prompt_spent": self.prompt_spent,
            "completion_spent": self.completion_spent,
            "steps_taken": self.steps_taken,
            "retries_remaining": self.retries_remaining,
            "repair_count": self.repair_count,
            "verifier_calls": self.verifier_calls,
            "retrieval_calls": self.retrieval_calls,
        }

    def exhausted(self, mode: WorkflowEvaluationMode) -> bool:
        if mode == WorkflowEvaluationMode.UNCONSTRAINED:
            return False
        if mode == WorkflowEvaluationMode.FIXED_TOKEN:
            return self.prompt_tokens <= 0 or self.completion_tokens <= 0
        if mode == WorkflowEvaluationMode.FIXED_STEP:
            return self.steps_taken >= self.step_budget
        return False


@dataclass
class WorkflowSimState:
    """Internal simulator state used to build observations."""

    stage: WorkflowStage = WorkflowStage.PLANNING
    compile_status: float = 0.0
    test_pass_ratio: float = 0.0
    verifier_confidence: float = 0.2
    verifier_disagreement: float = 0.3
    retrieval_coverage: float = 0.1
    evidence_count: int = 0
    num_subtasks: int = 0
    unresolved_subtasks: int = 0
    repeated_failures: int = 0
    test_stagnation: int = 0
    retrieval_insufficiency: float = 1.0
    previous_action: int = -1
    step_count: int = 0
    success: bool | None = None
    terminated: bool = False

    def reset(self) -> None:
        self.stage = WorkflowStage.PLANNING
        self.compile_status = 0.0
        self.test_pass_ratio = 0.0
        self.verifier_confidence = 0.2
        self.verifier_disagreement = 0.3
        self.retrieval_coverage = 0.1
        self.evidence_count = 0
        self.num_subtasks = 0
        self.unresolved_subtasks = 0
        self.repeated_failures = 0
        self.test_stagnation = 0
        self.retrieval_insufficiency = 1.0
        self.previous_action = -1
        self.step_count = 0
        self.success = None
        self.terminated = False


class WorkflowEnv(gym.Env):
    """Gymnasium-compatible environment for workflow control under constraints."""

    metadata = {"render_modes": ["human"]}

    def __init__(
        self,
        config: WorkflowEnvConfig | None = None,
        reward_config: WorkflowRewardConfig | None = None,
    ) -> None:
        super().__init__()
        self.config = config or WorkflowEnvConfig()
        self.reward_config = reward_config or WorkflowRewardConfig()
        self.action_space = spaces.Discrete(len(WorkflowAction))
        self.observation_dim = 25
        self.observation_space = spaces.Box(
            low=-1.0,
            high=1.0,
            shape=(self.observation_dim,),
            dtype=np.float32,
        )
        self.rng = np.random.default_rng(self.config.seed)
        self.state = WorkflowSimState()
        self.budget = BudgetState(
            prompt_tokens=float(self.config.prompt_budget),
            completion_tokens=float(self.config.completion_budget),
            step_budget=self.config.max_steps,
            retries_remaining=self.config.max_retries,
        )
        self.task_profile = self._sample_task_profile()
        self.episode_trace: List[Dict] = []
        self.last_observation = np.zeros(self.observation_dim, dtype=np.float32)

    # ------------------------------------------------------------------ Gym API
    def reset(self, *, seed: int | None = None, options: Dict | None = None):  # type: ignore[override]
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        self.state.reset()
        self.budget = BudgetState(
            prompt_tokens=float(self.config.prompt_budget),
            completion_tokens=float(self.config.completion_budget),
            step_budget=self.config.max_steps,
            retries_remaining=self.config.max_retries,
        )
        self.task_profile = self._sample_task_profile()
        self.episode_trace = []
        self.last_observation = self._compose_observation()
        info = self._build_info()
        return self.last_observation.copy(), info

    def step(self, action: int):  # type: ignore[override]
        if not self.action_space.contains(action):
            raise ValueError(f"Action {action} outside bounds.")
        if self.state.terminated:
            raise RuntimeError("Episode already terminated. Call reset before step again.")

        mask = self.get_action_mask()
        invalid = bool(mask is not None and mask[action] == 0)

        self.state.step_count += 1
        self.budget.consume(prompt=0.0, completion=0.0, step_increment=1)
        base_reward = -self.reward_config.step_penalty
        info: Dict[str, object] = {}
        tokens_prompt, tokens_completion = self._action_cost(action)
        self.budget.consume(prompt=tokens_prompt, completion=tokens_completion, step_increment=0)
        token_penalty = (tokens_prompt + tokens_completion) * self.reward_config.token_cost

        latency_penalty = self.reward_config.latency_cost
        incremental_reward = -token_penalty - latency_penalty
        action_reward, terminated, success = self._simulate_action(int(action), invalid)
        reward = base_reward + incremental_reward + action_reward

        if invalid:
            reward -= self.reward_config.invalid_action_penalty

        if self.config.evaluation_mode == WorkflowEvaluationMode.FIXED_TOKEN and (
            self.budget.prompt_tokens < 0 or self.budget.completion_tokens < 0
        ):
            reward -= self.reward_config.budget_violation_penalty
            terminated = True

        if self.config.evaluation_mode == WorkflowEvaluationMode.FIXED_STEP and self.state.step_count >= self.config.max_steps:
            terminated = True

        if self.budget.exhausted(self.config.evaluation_mode):
            reward -= self.reward_config.budget_violation_penalty
            terminated = True

        self.state.previous_action = int(action)
        self.state.terminated = terminated

        self.last_observation = self._compose_observation()
        info.update(
            {
                "stage": WorkflowStage(self.state.stage).name,
                "success": success,
                "action_mask": mask.copy() if mask is not None else None,
                "budget": self.budget.as_dict(),
                "uncertainty_summary": self._uncertainty_vector().tolist(),
            }
        )
        terminated_flag = terminated and self.state.stage in {WorkflowStage.DONE, WorkflowStage.ABANDONED}
        truncated_flag = terminated and not terminated_flag
        if self.config.track_episode_logs:
            self.episode_trace.append(
                {
                    "step": self.state.step_count,
                    "action": WorkflowAction(action).name,
                    "reward": reward,
                    "done": terminated_flag,
                    "truncated": truncated_flag,
                    "state": self._state_snapshot(),
                }
            )
        return self.last_observation.copy(), reward, terminated_flag, truncated_flag, info

    def render_episode_summary(self) -> str:
        """Lightweight textual summary for CLI debugging."""
        if not self.episode_trace:
            return "Episode trace empty."
        success_steps = [e for e in self.episode_trace if e.get("done")]
        final_state = self._state_snapshot()
        summary = (
            f"steps={self.state.step_count} "
            f"success={self.state.success} "
            f"compile={final_state['compile_status']:.2f} "
            f"tests={final_state['test_pass_ratio']:.2f} "
            f"prompt_spent={self.budget.prompt_spent:.0f} "
            f"completion_spent={self.budget.completion_spent:.0f}"
        )
        if success_steps:
            summary += f" terminal_action={success_steps[-1]['action']}"
        return summary

    # ------------------------------------------------------------------ Helpers
    def get_action_mask(self) -> np.ndarray:
        if not self.config.enable_action_masking or self.state.terminated:
            return np.ones(self.action_space.n, dtype=np.int8)
        mask = np.ones(self.action_space.n, dtype=np.int8)
        if self.state.stage == WorkflowStage.PLANNING:
            mask[WorkflowAction.RUN_TESTS] = 0
            mask[WorkflowAction.ASK_VERIFIER] = 0
            mask[WorkflowAction.SUBMIT] = 0
            mask[WorkflowAction.REPAIR_CURRENT] = 0
        if self.state.unresolved_subtasks >= self.config.max_subtasks:
            mask[WorkflowAction.DECOMPOSE_DEEP] = 0
        if self.state.stage in {WorkflowStage.DONE, WorkflowStage.ABANDONED}:
            mask[:] = 0
        if self.budget.verifier_calls >= self.config.verifier_limit:
            mask[WorkflowAction.ASK_VERIFIER] = 0
        if self.budget.retrieval_calls >= self.config.retrieval_limit:
            mask[WorkflowAction.RETRIEVE_CONTEXT] = 0
        if self.state.compile_status < 0.2:
            mask[WorkflowAction.SUBMIT] = 0
        if self.state.test_pass_ratio < 0.1:
            mask[WorkflowAction.RUN_TESTS] = 0
        if self.budget.retries_remaining <= 0:
            mask[WorkflowAction.SPAWN_ALT_SOLVER] = 0
            mask[WorkflowAction.REPAIR_CURRENT] = 0
        for disabled in self.config.disabled_actions:
            mask[int(disabled)] = 0
        return mask

    def _state_snapshot(self) -> Dict[str, float]:
        return {
            "stage": WorkflowStage(self.state.stage).name,
            "compile_status": float(self.state.compile_status),
            "test_pass_ratio": float(self.state.test_pass_ratio),
            "verifier_confidence": float(self.state.verifier_confidence),
            "verifier_disagreement": float(self.state.verifier_disagreement),
            "retrieval_coverage": float(self.state.retrieval_coverage),
            "evidence_count": int(self.state.evidence_count),
            "num_subtasks": int(self.state.num_subtasks),
            "unresolved_subtasks": int(self.state.unresolved_subtasks),
            "budget": self.budget.as_dict(),
            "repeated_failures": int(self.state.repeated_failures),
            "test_stagnation": int(self.state.test_stagnation),
            "retrieval_insufficiency": float(self.state.retrieval_insufficiency),
        }

    def _build_info(self) -> Dict[str, object]:
        return {
            "stage": WorkflowStage(self.state.stage).name,
            "action_mask": self.get_action_mask(),
            "budget": self.budget.as_dict(),
            "uncertainty_summary": self._uncertainty_vector().tolist(),
        }

    def _compose_observation(self) -> np.ndarray:
        obs = np.zeros(self.observation_dim, dtype=np.float32)
        obs[0] = self.task_profile.difficulty * 2 - 1
        obs[1] = self.task_profile.scope * 2 - 1
        obs[2] = self.task_profile.baseline_tests * 2 - 1
        obs[3] = (float(self.state.stage) / float(max(1, WorkflowStage.FINAL_REVIEW))) * 2 - 1
        obs[4] = self.state.compile_status * 2 - 1
        obs[5] = self.state.test_pass_ratio * 2 - 1
        obs[6] = self.state.verifier_confidence * 2 - 1
        obs[7] = self.state.verifier_disagreement * 2 - 1
        obs[8] = self.state.retrieval_coverage * 2 - 1
        obs[9] = min(1.0, self.state.evidence_count / 10.0) * 2 - 1
        obs[10] = min(1.0, self.state.num_subtasks / max(1, self.config.max_subtasks)) * 2 - 1
        obs[11] = min(1.0, self.state.unresolved_subtasks / max(1, self.config.max_subtasks)) * 2 - 1
        obs[12] = (self.budget.prompt_tokens / max(1.0, self.config.prompt_budget)) * 2 - 1
        obs[13] = (self.budget.completion_tokens / max(1.0, self.config.completion_budget)) * 2 - 1
        obs[14] = (1 - self.budget.steps_taken / max(1, self.config.max_steps)) * 2 - 1
        obs[15] = (self.budget.retries_remaining / max(1, self.config.max_retries)) * 2 - 1
        if self.state.previous_action >= 0:
            norm_prev = self.state.previous_action / max(1, self.action_space.n - 1)
            obs[16] = norm_prev * 2 - 1
        else:
            obs[16] = -1.0
        obs[17] = (self.state.step_count / max(1, self.config.max_steps)) * 2 - 1
        obs[18] = min(1.0, self.state.repeated_failures / 5.0) * 2 - 1
        obs[19] = min(1.0, self.state.test_stagnation / 5.0) * 2 - 1
        obs[20] = self.state.retrieval_insufficiency * 2 - 1
        uncertainty = self._uncertainty_vector()
        start = 21
        obs[start : start + len(uncertainty)] = uncertainty * 2 - 1
        if not self.config.enable_uncertainty_features:
            obs[start : start + len(uncertainty)] = 0.0
        return obs

    def _uncertainty_vector(self) -> np.ndarray:
        return np.array(
            [
                self.state.verifier_disagreement,
                min(1.0, self.state.repeated_failures / 5.0),
                min(1.0, self.state.test_stagnation / 5.0),
                self.state.retrieval_insufficiency,
            ],
            dtype=np.float32,
        )

    def _sample_task_profile(self) -> WorkflowTaskProfile:
        low = self.config.difficulty_min if self.config.difficulty_min is not None else 0.2
        high = self.config.difficulty_max if self.config.difficulty_max is not None else 0.95
        if high <= low:
            high = min(0.99, low + 0.01)
        difficulty = float(self.rng.uniform(low, high))
        scope = float(self.rng.uniform(0.3, 0.9))
        baseline_compile = float(self.rng.uniform(0.1, 0.4))
        baseline_tests = float(self.rng.uniform(0.05, 0.35))
        retrieval_complexity = float(self.rng.uniform(0.2, 0.8))
        verifier_strictness = float(self.rng.uniform(0.3, 0.9))
        return WorkflowTaskProfile(
            difficulty=difficulty,
            scope=scope,
            baseline_compile=baseline_compile,
            baseline_tests=baseline_tests,
            retrieval_complexity=retrieval_complexity,
            verifier_strictness=verifier_strictness,
        )

    def _action_cost(self, action: int) -> Tuple[float, float]:
        prompt_costs = {
            WorkflowAction.DIRECT_SOLVE: 1200,
            WorkflowAction.DECOMPOSE_SHALLOW: 600,
            WorkflowAction.DECOMPOSE_DEEP: 900,
            WorkflowAction.RETRIEVE_CONTEXT: 700,
            WorkflowAction.RUN_TESTS: 400,
            WorkflowAction.ASK_VERIFIER: 500,
            WorkflowAction.SPAWN_ALT_SOLVER: 1500,
            WorkflowAction.REPAIR_CURRENT: 800,
            WorkflowAction.SUBMIT: 300,
            WorkflowAction.ABANDON: 200,
        }
        completion_costs = {
            WorkflowAction.DIRECT_SOLVE: 1000,
            WorkflowAction.DECOMPOSE_SHALLOW: 200,
            WorkflowAction.DECOMPOSE_DEEP: 300,
            WorkflowAction.RETRIEVE_CONTEXT: 350,
            WorkflowAction.RUN_TESTS: 500,
            WorkflowAction.ASK_VERIFIER: 450,
            WorkflowAction.SPAWN_ALT_SOLVER: 1200,
            WorkflowAction.REPAIR_CURRENT: 600,
            WorkflowAction.SUBMIT: 400,
            WorkflowAction.ABANDON: 100,
        }
        return float(prompt_costs[WorkflowAction(action)]), float(completion_costs[WorkflowAction(action)])

    def _simulate_action(self, action: int, invalid: bool) -> Tuple[float, bool, bool]:
        """Applies simulator dynamics and returns (reward, terminated, success flag)."""
        if invalid:
            return 0.0, False, False
        reward = 0.0
        success = False
        terminated = False
        prev_compile = self.state.compile_status
        prev_tests = self.state.test_pass_ratio
        prev_retrieval = self.state.retrieval_coverage

        action_enum = WorkflowAction(action)
        noise = float(self.rng.normal(0.0, self.config.noise_scale))

        if action_enum == WorkflowAction.DIRECT_SOLVE:
            gain = max(0.05, 0.25 - self.task_profile.difficulty * 0.15 + noise)
            self.state.compile_status = float(np.clip(self.state.compile_status + gain, 0.0, 1.0))
            self.state.test_pass_ratio = float(
                np.clip(self.state.test_pass_ratio + gain * (0.8 + self.state.retrieval_coverage * 0.2), 0.0, 1.0)
            )
            if self.state.unresolved_subtasks > 0:
                self.state.unresolved_subtasks -= 1
            self.state.stage = max(self.state.stage, WorkflowStage.SOLVING)

        elif action_enum == WorkflowAction.DECOMPOSE_SHALLOW:
            self.state.num_subtasks = min(self.config.max_subtasks, self.state.num_subtasks + 2)
            self.state.unresolved_subtasks = min(self.config.max_subtasks, self.state.unresolved_subtasks + 2)
            self.state.retrieval_coverage = float(
                np.clip(self.state.retrieval_coverage + 0.1 + 0.05 * noise, 0.0, 1.0)
            )
            self.state.stage = WorkflowStage.PLANNING

        elif action_enum == WorkflowAction.DECOMPOSE_DEEP:
            self.state.num_subtasks = min(self.config.max_subtasks, self.state.num_subtasks + 3)
            self.state.unresolved_subtasks = min(self.config.max_subtasks, self.state.unresolved_subtasks + 3)
            self.state.retrieval_coverage = float(np.clip(self.state.retrieval_coverage + 0.15 + noise, 0.0, 1.0))
            self.state.evidence_count += 1
            self.state.stage = WorkflowStage.PLANNING

        elif action_enum == WorkflowAction.RETRIEVE_CONTEXT:
            self.budget.retrieval_calls += 1
            coverage_boost = 0.25 - self.task_profile.retrieval_complexity * 0.15 + noise
            self.state.retrieval_coverage = float(np.clip(self.state.retrieval_coverage + coverage_boost, 0.0, 1.0))
            self.state.evidence_count += 2
            self.state.retrieval_insufficiency = float(max(0.0, 1.0 - self.state.retrieval_coverage))

        elif action_enum == WorkflowAction.RUN_TESTS:
            improvement = 0.2 + 0.1 * (self.state.compile_status - self.task_profile.baseline_compile) + noise
            improvement *= 1.0 + self.state.retrieval_coverage * 0.2
            self.state.test_pass_ratio = float(np.clip(self.state.test_pass_ratio + improvement, 0.0, 1.0))
            self.state.test_stagnation = 0 if self.state.test_pass_ratio > prev_tests else self.state.test_stagnation + 1
            self.state.stage = WorkflowStage.VERIFYING

        elif action_enum == WorkflowAction.ASK_VERIFIER:
            self.budget.verifier_calls += 1
            self.state.verifier_confidence = float(
                np.clip(
                    self.state.verifier_confidence
                    + 0.15
                    - self.task_profile.verifier_strictness * 0.05
                    + noise,
                    0.0,
                    1.0,
                )
            )
            disagreement_delta = -0.1 + noise * 0.5
            self.state.verifier_disagreement = float(np.clip(self.state.verifier_disagreement + disagreement_delta, 0.0, 1.0))
            self.state.stage = WorkflowStage.FINAL_REVIEW

        elif action_enum == WorkflowAction.SPAWN_ALT_SOLVER:
            if self.budget.retries_remaining > 0:
                self.budget.retries_remaining -= 1
            self.state.repeated_failures = max(0, self.state.repeated_failures - 1)
            self.state.compile_status = float(
                np.clip(self.state.compile_status + 0.1 + 0.05 * self.state.retrieval_coverage + noise, 0.0, 1.0)
            )
            if self.state.unresolved_subtasks > 0:
                self.state.unresolved_subtasks -= 1
            self.state.stage = WorkflowStage.SOLVING

        elif action_enum == WorkflowAction.REPAIR_CURRENT:
            self.budget.repair_count += 1
            gain = 0.12 - 0.02 * self.state.repeated_failures + noise
            self.state.compile_status = float(np.clip(self.state.compile_status + gain, 0.0, 1.0))
            if gain < 0.05:
                reward -= self.reward_config.repair_loop_penalty
            else:
                self.state.test_pass_ratio = float(np.clip(self.state.test_pass_ratio + gain * 0.6, 0.0, 1.0))

        elif action_enum == WorkflowAction.SUBMIT:
            readiness = (
                0.4 * self.state.compile_status
                + 0.3 * self.state.test_pass_ratio
                + 0.2 * self.state.verifier_confidence
                - 0.25 * self.task_profile.difficulty
            )
            readiness += -0.1 * self.state.retrieval_insufficiency + noise
            readiness = float(np.clip(readiness, 0.0, 1.0))
            success = bool(self.rng.random() < readiness)
            if success:
                reward += self.reward_config.success_bonus
                self.state.stage = WorkflowStage.DONE
                self.state.success = True
                terminated = True
            else:
                reward -= self.reward_config.failure_penalty
                self.state.repeated_failures += 1
                self.state.stage = WorkflowStage.VERIFYING

        elif action_enum == WorkflowAction.ABANDON:
            success = False
            terminated = True
            self.state.success = False
            self.state.stage = WorkflowStage.ABANDONED
            recoverable = self._is_recoverable()
            penalty = self.reward_config.abandon_penalty
            if recoverable:
                penalty = self.reward_config.abandon_recoverable_penalty
            reward -= penalty

        else:
            raise ValueError(f"Unsupported action {action_enum}")

        compile_delta = self.state.compile_status - prev_compile
        test_delta = self.state.test_pass_ratio - prev_tests
        retrieval_delta = self.state.retrieval_coverage - prev_retrieval
        if compile_delta > 0:
            reward += self.reward_config.compile_bonus * compile_delta
        if test_delta > 0:
            reward += self.reward_config.test_improvement * test_delta
        if retrieval_delta > 0 and action_enum == WorkflowAction.RETRIEVE_CONTEXT:
            reward += 0.5 * retrieval_delta

        if action_enum == WorkflowAction.REPAIR_CURRENT and test_delta <= 0 and compile_delta <= 0:
            reward -= self.reward_config.repair_loop_penalty

        if success is True:
            self.state.terminated = True
        if self.state.step_count >= self.config.max_steps:
            terminated = True
        return reward, terminated, success

    def _is_recoverable(self) -> bool:
        readiness = (
            self.state.compile_status
            + self.state.test_pass_ratio
            + self.state.verifier_confidence
            + (1 - self.state.retrieval_insufficiency)
        ) / 4.0
        return readiness >= self.config.min_recoverable_ratio and self.state.stage not in {
            WorkflowStage.DONE,
            WorkflowStage.ABANDONED,
        }


__all__ = [
    "WorkflowEnv",
    "WorkflowEnvConfig",
    "WorkflowRewardConfig",
    "WorkflowAction",
    "WorkflowStage",
    "WorkflowEvaluationMode",
]
