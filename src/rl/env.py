"""Hardened Gymnasium environments for competitive coding marketplaces."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

import gymnasium as gym
import numpy as np
import pandas as pd
from gymnasium import spaces

from src.config import PathConfig, RLConfig


@dataclass
class EnvConfig:
    max_concurrent_tasks: int = 2
    fatigue_decay: float = 0.1
    deadline_penalty: float = 0.5
    compile_fail_prob: float = 0.05
    success_noise_std: float = 0.05
    episodes: int = 100
    horizon: int = 50
    rival_pool_size: int = 20
    rival_skill_spread: float = 0.4
    reward_scale: float = 1.0


@dataclass
class TaskSlate:
    features: np.ndarray
    metadata: List[Dict[str, float]]


@dataclass
class PendingTask:
    metadata: Dict[str, float]
    features: np.ndarray
    remaining: int
    deadline: int


@dataclass
class AgentState:
    skill: np.ndarray
    fatigue: float = 0.0
    pending: List[PendingTask] = field(default_factory=list)
    starved_tasks: int = 0
    dropped_tasks: int = 0
    deadline_misses: int = 0
    wins: int = 0


class _EnvironmentCore:
    def __init__(
        self,
        processed_dir: Path | None = None,
        rl_config: RLConfig | None = None,
        env_config: EnvConfig | None = None,
    ) -> None:
        path_cfg = PathConfig()
        self.processed_dir = processed_dir or path_cfg.processed_data
        self.rl_config = rl_config or RLConfig()
        self.env_config = env_config or EnvConfig()
        self.tasks = pd.read_parquet(self.processed_dir / "tasks.parquet")
        self.workers = pd.read_parquet(self.processed_dir / "workers.parquet")
        self.workers["skill_vector"] = self.workers["skill_vector"].apply(self._coerce_skill_vector)
        self.market = pd.read_parquet(self.processed_dir / "market.parquet")
        self.rng = np.random.default_rng(self.rl_config.seed)
        self.max_tasks = self.rl_config.max_tasks_per_step
        self.task_feature_columns = self._determine_task_features()
        self.skill_dim = len(self.workers.iloc[0]["skill_vector"])
        self.observation_dim = self.skill_dim + self.max_tasks * len(self.task_feature_columns) + 2

    # ------------------------------------------------------------------
    def _determine_task_features(self) -> List[str]:
        embedding_cols = [col for col in self.tasks.columns if str(col).startswith("dim_")]
        if embedding_cols:
            return embedding_cols
        return ["prize", "difficulty", "duration_days", "num_registrants"]

    @staticmethod
    def _coerce_skill_vector(raw) -> List[float]:
        if isinstance(raw, (list, tuple, np.ndarray)):
            return list(map(float, raw))
        return [float(val) for val in str(raw).split(";") if val]

    def _sample_skill(self) -> np.ndarray:
        worker = self.workers.sample(n=1, random_state=self.rng.integers(0, 10_000)).iloc[0]
        return np.array(worker["skill_vector"], dtype=np.float32)

    def _sample_slate(self) -> TaskSlate:
        subset = self.tasks.sample(n=self.max_tasks, replace=False, random_state=self.rng.integers(0, 10_000))
        features = subset[self.task_feature_columns].to_numpy(dtype=np.float32)
        metadata = subset[
            ["task_id", "prize", "difficulty", "num_registrants", "starved", "track", "duration_days"]
        ].to_dict(orient="records")
        return TaskSlate(features=features, metadata=metadata)

    def _new_agent_state(self) -> AgentState:
        return AgentState(skill=self._sample_skill(), fatigue=0.0)

    def _compose_observation(self, state: AgentState, slate: TaskSlate) -> np.ndarray:
        obs = np.zeros(self.observation_dim, dtype=np.float32)
        obs[: self.skill_dim] = state.skill[: self.skill_dim]
        flat = slate.features.flatten()
        obs[self.skill_dim : self.skill_dim + len(flat)] = flat
        obs[-2] = state.fatigue
        capacity_ratio = len(state.pending) / max(1, self.env_config.max_concurrent_tasks)
        obs[-1] = min(1.0, capacity_ratio)
        return obs

    def _progress_state(self, state: AgentState, current_step: int) -> Tuple[float, bool]:
        reward = 0.0
        truncated = False
        remaining: List[PendingTask] = []
        for task in state.pending:
            task.remaining -= 1
            if current_step >= task.deadline:
                state.deadline_misses += 1
                reward -= self.env_config.deadline_penalty * float(task.metadata.get("prize", 500))
                truncated = True
                continue
            if task.remaining <= 0:
                reward += self._resolve_task(state, task)
                continue
            remaining.append(task)
        state.pending = remaining
        state.fatigue = max(0.0, state.fatigue - self.env_config.fatigue_decay * 0.5)
        return reward, truncated

    def _start_task(self, state: AgentState, task_meta: Dict[str, float], features: np.ndarray, current_step: int) -> float:
        if len(state.pending) >= self.env_config.max_concurrent_tasks:
            state.dropped_tasks += 1
            return -self.env_config.deadline_penalty * float(task_meta.get("prize", 500))
        duration = int(task_meta.get("duration_days", 3) or 3)
        duration = max(1, duration // 2 or 1)
        deadline = current_step + duration + 2
        state.pending.append(PendingTask(metadata=task_meta, features=features, remaining=duration, deadline=deadline))
        state.fatigue = min(1.0, state.fatigue + self.env_config.fatigue_decay)
        return 0.0

    def _resolve_task(self, state: AgentState, pending: PendingTask) -> float:
        if self.rng.random() < self.env_config.compile_fail_prob:
            state.starved_tasks += 1
            return -self.env_config.deadline_penalty * float(pending.metadata.get("prize", 500))
        prob = self._win_probability(state, pending.features, pending.metadata)
        success = self.rng.random() < prob
        prize = float(pending.metadata.get("prize", 500)) * self.env_config.reward_scale
        if success:
            state.wins += 1
            return prize
        state.starved_tasks += 1
        return -self.env_config.deadline_penalty * float(pending.metadata.get("prize", 500))

    def _win_probability(self, state: AgentState, task_vec: np.ndarray, task_meta: Dict[str, float]) -> float:
        dims = min(len(task_vec), state.skill.shape[0])
        skill_slice = state.skill[:dims]
        task_slice = task_vec[:dims]
        dot = float(np.dot(skill_slice, task_slice))
        difficulty = float(task_meta.get("difficulty", 3) or 3)
        registrants = float(task_meta.get("num_registrants", 10) or 10)
        prize = float(task_meta.get("prize", 500) or 500)
        base_logit = 0.1 * dot + 0.002 * prize - 0.2 * difficulty - 0.05 * math.log1p(registrants)
        prob = 1 / (1 + math.exp(-base_logit))
        prob += self.rng.normal(0.0, self.env_config.success_noise_std)
        prob -= state.fatigue * self.env_config.fatigue_decay
        prob -= self._rival_penalty()
        return float(np.clip(prob, 0.01, 0.99))

    def _rival_penalty(self) -> float:
        rivals = self.rng.normal(0.6, self.env_config.rival_skill_spread, self.env_config.rival_pool_size)
        if self.rng.random() < 0.15:
            rivals = np.append(rivals, 1.0)
        return max(0.0, rivals.max() - 0.5) * 0.15


class CompetitionEnv(_EnvironmentCore, gym.Env):
    """Single-agent environment with capacity, fatigue, rivals, and deadlines."""

    metadata = {"render.modes": ["human"]}

    def __init__(
        self,
        processed_dir: Path | None = None,
        rl_config: RLConfig | None = None,
        env_config: EnvConfig | None = None,
    ) -> None:
        _EnvironmentCore.__init__(self, processed_dir=processed_dir, rl_config=rl_config, env_config=env_config)
        gym.Env.__init__(self)
        self.action_space = spaces.Discrete(self.max_tasks + 1)  # +1 for skip
        self.agent_state: AgentState | None = None
        self.current_slate: TaskSlate | None = None
        self.current_step = 0

    def reset(self, *, seed: int | None = None, options: Dict | None = None):  # type: ignore[override]
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        self.agent_state = self._new_agent_state()
        self.current_slate = self._sample_slate()
        self.current_step = 0
        observation = self._compose_observation(self.agent_state, self.current_slate)
        info = self._info(self.agent_state)
        return observation, info

    def step(self, action: int):  # type: ignore[override]
        assert self.agent_state is not None and self.current_slate is not None
        reward, deadline_truncated = self._progress_state(self.agent_state, self.current_step)
        if action == self.max_tasks:  # skip
            reward -= 1.0
            self.agent_state.starved_tasks += 1
        else:
            action = int(np.clip(action, 0, self.max_tasks - 1))
            task_meta = self.current_slate.metadata[action]
            task_vec = self.current_slate.features[action]
            reward += self._start_task(self.agent_state, task_meta, task_vec, self.current_step)
        self.current_step += 1
        time_limit = self.current_step >= self.env_config.horizon
        truncated = deadline_truncated or time_limit
        terminated = truncated
        self.current_slate = self._sample_slate()
        observation = self._compose_observation(self.agent_state, self.current_slate)
        info = self._info(self.agent_state)
        return observation, reward, terminated, truncated, info

    def _info(self, state: AgentState) -> Dict[str, float]:
        return {
            "starved_tasks": state.starved_tasks,
            "dropped_tasks": state.dropped_tasks,
            "deadline_misses": state.deadline_misses,
            "fatigue": state.fatigue,
            "pending_tasks": len(state.pending),
            "won": state.wins,
        }

    def render(self, mode: str = "human") -> None:  # pragma: no cover
        if self.current_slate is None:
            print("No slate available")
            return
        for idx, meta in enumerate(self.current_slate.metadata):
            print(f"{idx}: {meta['task_id']} prize={meta['prize']} difficulty={meta['difficulty']}")


class MultiAgentCompetitionEnv(_EnvironmentCore):
    """Wrapper that simulates multiple policies simultaneously over shared markets."""

    def __init__(
        self,
        agent_names: List[str],
        processed_dir: Path | None = None,
        rl_config: RLConfig | None = None,
        env_config: EnvConfig | None = None,
        seed: int | None = None,
    ) -> None:
        super().__init__(processed_dir=processed_dir, rl_config=rl_config, env_config=env_config)
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        self.agent_names = agent_names
        self.agent_states: Dict[str, AgentState] = {name: self._new_agent_state() for name in agent_names}
        self.current_slate = self._sample_slate()
        self.current_step = 0
        self.market_totals = {"starved": 0, "dropped": 0, "deadline": 0}
        self.action_space = spaces.Discrete(self.max_tasks + 1)

    def reset(self, seed: int | None = None):
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        self.agent_states = {name: self._new_agent_state() for name in self.agent_names}
        self.current_slate = self._sample_slate()
        self.current_step = 0
        self.market_totals = {"starved": 0, "dropped": 0, "deadline": 0}
        observations = {name: self._compose_observation(state, self.current_slate) for name, state in self.agent_states.items()}
        info = self._multi_info()
        return observations, info

    def step(self, actions: Dict[str, int]):
        rewards: Dict[str, float] = {name: 0.0 for name in self.agent_names}
        truncated = False
        for name, state in self.agent_states.items():
            reward, deadline_flag = self._progress_state(state, self.current_step)
            truncated = truncated or deadline_flag
            rewards[name] += reward
        for name in self.agent_names:
            action = actions.get(name, self.max_tasks)
            state = self.agent_states[name]
            if action == self.max_tasks:
                rewards[name] -= 1.0
                state.starved_tasks += 1
            else:
                idx = int(np.clip(action, 0, self.max_tasks - 1))
                rewards[name] += self._start_task(state, self.current_slate.metadata[idx], self.current_slate.features[idx], self.current_step)
        self.current_step += 1
        if self.current_step >= self.env_config.horizon:
            truncated = True
        self.current_slate = self._sample_slate()
        observations = {name: self._compose_observation(state, self.current_slate) for name, state in self.agent_states.items()}
        info = self._multi_info()
        terminated = truncated
        return observations, rewards, terminated, truncated, info

    def _multi_info(self) -> Dict[str, float]:
        starved = sum(state.starved_tasks for state in self.agent_states.values())
        dropped = sum(state.dropped_tasks for state in self.agent_states.values())
        deadline = sum(state.deadline_misses for state in self.agent_states.values())
        self.market_totals = {"starved": starved, "dropped": dropped, "deadline": deadline}
        return {
            "market_starved": starved,
            "market_dropped": dropped,
            "market_deadlines": deadline,
        }


__all__ = ["EnvConfig", "CompetitionEnv", "MultiAgentCompetitionEnv"]
