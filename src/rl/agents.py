"""Baseline and RL agents for the CompetitionEnv."""
from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim


class BaseAgent:
    def act(self, env, observation: np.ndarray) -> int:  # pragma: no cover - interface
        raise NotImplementedError

    def observe(self, *_) -> None:
        return None


class RandomAgent(BaseAgent):
    def act(self, env, observation: np.ndarray) -> int:
        return env.action_space.sample()


class GreedyPrizeAgent(BaseAgent):
    def act(self, env, observation: np.ndarray) -> int:
        prizes = [meta["prize"] for meta in env.current_slate.metadata]
        return int(np.argmax(prizes))


class SkillMatchAgent(BaseAgent):
    def act(self, env, observation: np.ndarray) -> int:
        skill = observation[: env.skill_dim]
        tasks = _task_matrix(env, observation)
        truncated_skill = skill[: tasks.shape[1]]
        sims = tasks @ truncated_skill
        return int(np.argmax(sims))


@dataclass
class BanditConfig:
    alpha: float = 0.05
    epsilon: float = 0.1


class ContextualBanditAgent(BaseAgent):
    def __init__(self, obs_dim: int, task_dim: int, config: BanditConfig | None = None) -> None:
        self.config = config or BanditConfig()
        self.weights = np.zeros(task_dim)
        self.last_observation: np.ndarray | None = None
        self.last_action: int | None = None

    def act(self, env, observation: np.ndarray) -> int:
        self.last_observation = observation.copy()
        if np.random.rand() < self.config.epsilon:
            action = env.action_space.sample()
        else:
            tasks = _task_matrix(env, observation)
            scores = tasks @ self.weights
            action = int(np.argmax(scores))
        self.last_action = action
        return action

    def observe(self, reward: float, env) -> None:
        if self.last_observation is None or self.last_action is None:
            return
        if self.last_action >= env.max_tasks:
            return
        tasks = _task_matrix(env, self.last_observation)
        x = tasks[self.last_action]
        prediction = float(self.weights @ x)
        error = reward - prediction
        self.weights += self.config.alpha * error * x


class DQN(nn.Module):
    def __init__(self, input_dim: int, output_dim: int) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 256),
            nn.ReLU(),
            nn.Linear(256, 128),
            nn.ReLU(),
            nn.Linear(128, output_dim),
        )

    def forward(self, x):  # type: ignore[override]
        return self.net(x)


@dataclass
class DQNConfig:
    gamma: float = 0.95
    lr: float = 1e-3
    epsilon_start: float = 1.0
    epsilon_min: float = 0.05
    epsilon_decay: float = 0.995
    buffer_size: int = 10_000
    batch_size: int = 64
    target_update: int = 100


class DQNAgent(BaseAgent):
    def __init__(self, obs_dim: int, action_dim: int, config: DQNConfig | None = None) -> None:
        self.config = config or DQNConfig()
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.policy_net = DQN(obs_dim, action_dim).to(self.device)
        self.target_net = DQN(obs_dim, action_dim).to(self.device)
        self.target_net.load_state_dict(self.policy_net.state_dict())
        self.optimizer = optim.Adam(self.policy_net.parameters(), lr=self.config.lr)
        self.memory: Deque[Tuple[np.ndarray, int, float, np.ndarray, bool]] = deque(
            maxlen=self.config.buffer_size
        )
        self.epsilon = self.config.epsilon_start
        self.steps = 0
        self.action_dim = action_dim

    def act(self, env, observation: np.ndarray) -> int:
        if np.random.rand() < self.epsilon:
            return env.action_space.sample()
        obs_tensor = torch.tensor(observation, dtype=torch.float32, device=self.device).unsqueeze(0)
        with torch.no_grad():
            q_values = self.policy_net(obs_tensor)
        return int(torch.argmax(q_values, dim=1).item())

    def remember(
        self,
        obs: np.ndarray,
        action: int,
        reward: float,
        next_obs: np.ndarray,
        done: bool,
    ) -> None:
        self.memory.append((obs, action, reward, next_obs, done))

    def learn(self) -> None:
        if len(self.memory) < self.config.batch_size:
            return
        batch = random.sample(self.memory, self.config.batch_size)
        states, actions, rewards, next_states, dones = map(list, zip(*batch))
        states_tensor = torch.tensor(np.stack(states), dtype=torch.float32, device=self.device)
        actions_tensor = torch.tensor(actions, dtype=torch.long, device=self.device).unsqueeze(1)
        rewards_tensor = torch.tensor(rewards, dtype=torch.float32, device=self.device).unsqueeze(1)
        next_states_tensor = torch.tensor(np.stack(next_states), dtype=torch.float32, device=self.device)
        dones_tensor = torch.tensor(dones, dtype=torch.float32, device=self.device).unsqueeze(1)

        current_q = self.policy_net(states_tensor).gather(1, actions_tensor)
        with torch.no_grad():
            max_next_q = self.target_net(next_states_tensor).max(1)[0].unsqueeze(1)
            target_q = rewards_tensor + self.config.gamma * (1 - dones_tensor) * max_next_q

        loss = nn.functional.mse_loss(current_q, target_q)
        self.optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.policy_net.parameters(), 1.0)
        self.optimizer.step()

        if self.steps % self.config.target_update == 0:
            self.target_net.load_state_dict(self.policy_net.state_dict())
        self.steps += 1
        self.epsilon = max(self.config.epsilon_min, self.epsilon * self.config.epsilon_decay)


__all__ = [
    "BaseAgent",
    "RandomAgent",
    "GreedyPrizeAgent",
    "SkillMatchAgent",
    "ContextualBanditAgent",
    "DQNAgent",
    "BanditConfig",
    "DQNConfig",
]


def _task_matrix(env, observation: np.ndarray) -> np.ndarray:
    feature_dim = len(getattr(env, "task_feature_columns", [])) or max(1, env.observation_dim)
    start = env.skill_dim
    end = start + env.max_tasks * feature_dim
    task_slice = observation[start:end]
    if task_slice.size != env.max_tasks * feature_dim:
        # Fall back to best-effort reshape (padding/truncating) to keep agents robust
        padded = np.zeros(env.max_tasks * feature_dim, dtype=observation.dtype)
        usable = min(task_slice.size, padded.size)
        padded[:usable] = task_slice[:usable]
        task_slice = padded
    return task_slice.reshape(env.max_tasks, feature_dim)
