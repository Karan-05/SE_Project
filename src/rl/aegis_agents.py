"""AEGIS-RL hierarchical agents and training utilities."""
from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np

try:  # pragma: no cover - optional dep
    import torch
    import torch.nn as nn
    import torch.optim as optim
except Exception:  # pragma: no cover - fallback
    torch = None
    nn = None
    optim = None

from .aegis_state import AegisMacroOption


@dataclass
class AegisAgentConfig:
    """Hyper-parameters for the manager policy."""

    gamma: float = 0.99
    lr: float = 3e-4
    batch_size: int = 64
    buffer_size: int = 50_000
    min_buffer: int = 1_000
    target_update: int = 250
    epsilon_start: float = 1.0
    epsilon_final: float = 0.1
    epsilon_decay: float = 0.998
    grads_per_step: int = 1
    device: str = "cpu"


class AegisReplayBuffer:
    """Simple replay buffer storing transitions."""

    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self.buffer: Deque[Tuple[np.ndarray, int, float, np.ndarray, bool]] = deque(maxlen=capacity)

    def push(self, transition: Tuple[np.ndarray, int, float, np.ndarray, bool]) -> None:
        self.buffer.append(transition)

    def sample(self, batch_size: int) -> List[Tuple[np.ndarray, int, float, np.ndarray, bool]]:
        size = min(batch_size, len(self.buffer))
        if size == 0:
            return []
        indices = np.random.choice(len(self.buffer), size=size, replace=False)
        return [self.buffer[idx] for idx in indices]

    def __len__(self) -> int:
        return len(self.buffer)


if torch is not None:
    class _ManagerNetwork(nn.Module):  # type: ignore[misc]
        """Dueling Double DQN with calibration heads."""

        def __init__(self, obs_dim: int, action_dim: int) -> None:  # pragma: no cover - simple nn wiring
            super().__init__()
            hidden = 256
            self.feature = nn.Sequential(nn.Linear(obs_dim, hidden), nn.ReLU(), nn.Linear(hidden, hidden), nn.ReLU())
            self.value = nn.Sequential(nn.Linear(hidden, hidden), nn.ReLU(), nn.Linear(hidden, 1))
            self.advantage = nn.Sequential(nn.Linear(hidden, hidden), nn.ReLU(), nn.Linear(hidden, action_dim))
            self.calibration = nn.Sequential(nn.Linear(hidden, 32), nn.ReLU(), nn.Linear(32, 2))

        def forward(self, obs: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:  # pragma: no cover
            base = self.feature(obs)
            value = self.value(base)
            advantage = self.advantage(base)
            q_values = value + advantage - advantage.mean(dim=1, keepdim=True)
            calib = torch.sigmoid(self.calibration(base))
            success = calib[:, :1]
            cost = calib[:, 1:]
            return q_values, success, cost
else:  # pragma: no cover - fallback
    _ManagerNetwork = None  # type: ignore[assignment]


class AegisManagerAgent:
    """Dueling Double DQN-style manager with calibration heads and option masking."""

    def __init__(self, observation_dim: int, action_dim: int, config: AegisAgentConfig | None = None) -> None:
        self.config = config or AegisAgentConfig()
        self.obs_dim = observation_dim
        self.action_dim = action_dim
        self.buffer = AegisReplayBuffer(self.config.buffer_size)
        self.device = torch.device(self.config.device) if torch else None
        self.step_count = 0
        self.epsilon = self.config.epsilon_start
        self.use_torch = torch is not None
        self.option_visit_counts = np.zeros(self.action_dim, dtype=np.int64)
        if self.use_torch:
            self.policy_net = _ManagerNetwork(self.obs_dim, self.action_dim).to(self.device)
            self.target_net = _ManagerNetwork(self.obs_dim, self.action_dim).to(self.device)
            self.target_net.load_state_dict(self.policy_net.state_dict())
            self.optimizer = optim.Adam(self.policy_net.parameters(), lr=self.config.lr)
        else:
            self.weights = np.zeros((self.action_dim, self.obs_dim), dtype=np.float32)
            self.bias = np.zeros(self.action_dim, dtype=np.float32)
            self.calibration_weights = np.zeros((2, self.obs_dim), dtype=np.float32)

    def act(self, observation: np.ndarray, option_mask: Optional[np.ndarray] = None) -> int:
        self.step_count += 1
        if np.random.rand() < self.epsilon:
            action = self._random_action(option_mask)
            self.option_visit_counts[action] += 1
            return action
        if self.use_torch:
            obs_tensor = torch.tensor(observation, dtype=torch.float32, device=self.device).unsqueeze(0)
            with torch.no_grad():
                q_values, _, _ = self.policy_net(obs_tensor)
            q = q_values.squeeze(0).cpu().numpy()
        else:
            q = observation @ self.weights.T + self.bias
        if option_mask is not None:
            masked = np.where(option_mask > 0)[0]
            if len(masked) == 0:
                return int(np.argmax(q))
            mask_array = np.full_like(q, -np.inf)
            mask_array[masked] = q[masked]
            action = int(np.argmax(mask_array))
        else:
            action = int(np.argmax(q))
        self.option_visit_counts[action] += 1
        return action

    def _random_action(self, option_mask: Optional[np.ndarray]) -> int:
        if option_mask is None:
            probs = self._exploration_probs(np.arange(self.action_dim))
            return int(np.random.choice(self.action_dim, p=probs))
        valid = np.where(option_mask > 0)[0]
        if len(valid) == 0:
            return int(np.random.randint(self.action_dim))
        probs = self._exploration_probs(valid)
        return int(np.random.choice(valid, p=probs))

    def _exploration_probs(self, indices: np.ndarray) -> np.ndarray:
        counts = self.option_visit_counts[indices]
        weights = 1.0 / (counts + 1.0)
        weights_sum = np.sum(weights)
        if weights_sum <= 0:
            return np.ones_like(weights) / len(weights)
        return weights / weights_sum

    def observe(self, transition: Tuple[np.ndarray, int, float, np.ndarray, bool]) -> None:
        self.buffer.push(transition)
        if len(self.buffer) >= self.config.min_buffer:
            for _ in range(self.config.grads_per_step):
                self._train_step()
        self.epsilon = max(self.config.epsilon_final, self.epsilon * self.config.epsilon_decay)

    def _train_step(self) -> None:
        batch = self.buffer.sample(self.config.batch_size)
        if not batch:
            return
        obs = np.stack([item[0] for item in batch])
        actions = np.array([item[1] for item in batch], dtype=np.int64)
        rewards = np.array([item[2] for item in batch], dtype=np.float32)
        next_obs = np.stack([item[3] for item in batch])
        dones = np.array([item[4] for item in batch], dtype=np.float32)
        if self.use_torch:
            obs_t = torch.tensor(obs, dtype=torch.float32, device=self.device)
            actions_t = torch.tensor(actions, dtype=torch.int64, device=self.device).unsqueeze(1)
            rewards_t = torch.tensor(rewards, dtype=torch.float32, device=self.device).unsqueeze(1)
            next_obs_t = torch.tensor(next_obs, dtype=torch.float32, device=self.device)
            dones_t = torch.tensor(dones, dtype=torch.float32, device=self.device).unsqueeze(1)
            q_values, _, _ = self.policy_net(obs_t)
            q_selected = q_values.gather(1, actions_t)
            with torch.no_grad():
                next_q_values, _, _ = self.policy_net(next_obs_t)
                next_actions = torch.argmax(next_q_values, dim=1, keepdim=True)
                target_q, _, _ = self.target_net(next_obs_t)
                next_q = target_q.gather(1, next_actions)
                target = rewards_t + self.config.gamma * (1 - dones_t) * next_q
            loss = nn.functional.mse_loss(q_selected, target)
            self.optimizer.zero_grad()
            loss.backward()
            self.optimizer.step()
            if self.step_count % self.config.target_update == 0:
                self.target_net.load_state_dict(self.policy_net.state_dict())
        else:
            for i in range(obs.shape[0]):
                target = rewards[i]
                if not dones[i]:
                    target += self.config.gamma * np.max(next_obs[i] @ self.weights.T + self.bias)
                pred = obs[i] @ self.weights[actions[i]] + self.bias[actions[i]]
                grad = (target - pred) * obs[i]
                self.weights[actions[i]] += self.config.lr * grad
                self.bias[actions[i]] += self.config.lr * (target - pred)

    def save(self, path: str | Path) -> None:
        if self.use_torch:
            payload = {
                "policy": self.policy_net.state_dict(),
                "target": self.target_net.state_dict(),
                "config": self.config.__dict__,
            }
            torch.save(payload, path)
        else:
            payload = {
                "weights": self.weights.tolist(),
                "bias": self.bias.tolist(),
                "config": self.config.__dict__,
            }
            Path(path).write_text(json.dumps(payload))

    def load(self, path: str | Path) -> None:
        if self.use_torch:
            checkpoint = torch.load(path, map_location=self.device)
            self.policy_net.load_state_dict(checkpoint["policy"])
            self.target_net.load_state_dict(checkpoint["target"])
        else:
            payload = json.loads(Path(path).read_text())
            self.weights = np.array(payload["weights"], dtype=np.float32)
            self.bias = np.array(payload["bias"], dtype=np.float32)

    def calibration_head(self, observation: np.ndarray) -> Tuple[float, float]:
        if self.use_torch:
            obs_tensor = torch.tensor(observation, dtype=torch.float32, device=self.device).unsqueeze(0)
            with torch.no_grad():
                _, success, cost = self.policy_net(obs_tensor)
            return float(success.item()), float(cost.item())
        logits = self.calibration_weights @ observation
        success = 1 / (1 + np.exp(-logits[0]))
        cost = np.clip(logits[1], 0.0, 1.0)
        return float(success), float(cost)
