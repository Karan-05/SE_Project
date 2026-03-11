"""Agents tailored for the workflow control environment."""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np
from collections import deque

try:  # pragma: no cover - optional dependency
    import torch
    import torch.nn as nn
    import torch.optim as optim
except Exception:  # pragma: no cover - torch optional
    torch = None
    nn = None
    optim = None

HAS_TORCH = torch is not None

from .workflow_env import WorkflowAction


def decode_feature(value: float) -> float:
    """Inverse of the environment's [-1, 1] scaling."""
    return (value + 1.0) / 2.0


def masked_argmax(values: Any, mask: Optional[np.ndarray]) -> int:
    """Returns the index of the maximum value while respecting invalid actions."""
    if mask is None:
        return int(torch.argmax(values).item()) if isinstance(values, torch.Tensor) else int(np.argmax(values))
    if isinstance(mask, list):
        mask = np.array(mask, dtype=np.int8)
    if HAS_TORCH and isinstance(values, torch.Tensor):
        masked = values.clone()
        invalid = torch.tensor(mask == 0, dtype=torch.bool, device=values.device)
        masked[invalid] = -torch.inf
        return int(torch.argmax(masked).item())
    masked = np.array(values, copy=True)
    masked[mask == 0] = -np.inf
    return int(np.argmax(masked))


class WorkflowAgentBase:
    """Interface that all workflow agents follow."""

    def act(
        self,
        observation: np.ndarray,
        action_mask: Optional[np.ndarray] = None,
        info: Optional[Dict[str, float]] = None,
    ) -> int:
        raise NotImplementedError

    def observe(
        self,
        transition: Tuple[np.ndarray, int, float, np.ndarray, bool],
    ) -> None:
        return None

    def save(self, path: str | Path) -> None:  # pragma: no cover - optional hook
        return None

    def load(self, path: str | Path) -> None:  # pragma: no cover - optional hook
        return None


class AlwaysDirectAgent(WorkflowAgentBase):
    """Baseline that always attempts a direct solve."""

    def act(self, observation: np.ndarray, action_mask: Optional[np.ndarray] = None, info=None) -> int:
        action = WorkflowAction.DIRECT_SOLVE
        if action_mask is not None and action_mask[action] == 0:
            return int(np.random.choice(np.where(action_mask == 1)[0]))
        return int(action)


class AlwaysDecomposeAgent(WorkflowAgentBase):
    """Baseline that repeatedly performs shallow decomposition."""

    def act(self, observation: np.ndarray, action_mask: Optional[np.ndarray] = None, info=None) -> int:
        action = WorkflowAction.DECOMPOSE_SHALLOW
        if action_mask is not None and action_mask[action] == 0:
            return int(np.random.choice(np.where(action_mask == 1)[0]))
        return int(action)


@dataclass
class HeuristicThresholdConfig:
    compile_threshold: float = 0.75
    test_threshold: float = 0.7
    confidence_threshold: float = 0.65


class HeuristicThresholdAgent(WorkflowAgentBase):
    """Rule-based agent that mimics a planner-solver-verifier cadence."""

    def __init__(self, config: HeuristicThresholdConfig | None = None) -> None:
        self.config = config or HeuristicThresholdConfig()

    def act(self, observation: np.ndarray, action_mask: Optional[np.ndarray] = None, info=None) -> int:
        compile_ratio = decode_feature(observation[4])
        test_ratio = decode_feature(observation[5])
        verifier_conf = decode_feature(observation[6])
        retrieval_cov = decode_feature(observation[8])
        step_count = decode_feature(observation[17])

        if retrieval_cov < 0.5:
            return self._safe_action(WorkflowAction.RETRIEVE_CONTEXT, action_mask)
        if compile_ratio < self.config.compile_threshold:
            return self._safe_action(WorkflowAction.DIRECT_SOLVE, action_mask)
        if test_ratio < self.config.test_threshold:
            return self._safe_action(WorkflowAction.RUN_TESTS, action_mask)
        if verifier_conf < self.config.confidence_threshold and step_count < 0.9:
            return self._safe_action(WorkflowAction.ASK_VERIFIER, action_mask)
        if action_mask is not None and action_mask[WorkflowAction.SUBMIT] == 1:
            return int(WorkflowAction.SUBMIT)
        return self._safe_action(WorkflowAction.REPAIR_CURRENT, action_mask)

    @staticmethod
    def _safe_action(action: WorkflowAction, mask: Optional[np.ndarray]) -> int:
        if mask is not None and mask[action] == 0:
            candidates = np.where(mask == 1)[0]
            if len(candidates) == 0:
                return int(action)
            return int(np.random.choice(candidates))
        return int(action)


@dataclass
class BanditAgentConfig:
    alpha: float = 0.1
    epsilon: float = 0.1


class ContextualBanditWorkflowAgent(WorkflowAgentBase):
    """Linear contextual bandit with ε-greedy exploration."""

    def __init__(self, observation_dim: int, action_dim: int, config: BanditAgentConfig | None = None) -> None:
        self.config = config or BanditAgentConfig()
        self.weights = np.zeros((action_dim, observation_dim), dtype=np.float32)
        self.last_observation: Optional[np.ndarray] = None
        self.last_action: Optional[int] = None

    def act(self, observation: np.ndarray, action_mask: Optional[np.ndarray] = None, info=None) -> int:
        self.last_observation = observation.copy()
        if np.random.rand() < self.config.epsilon:
            if action_mask is None:
                action = np.random.randint(self.weights.shape[0])
            else:
                valid = np.where(action_mask == 1)[0]
                action = int(np.random.choice(valid))
        else:
            scores = self.weights @ observation
            action = masked_argmax(scores, action_mask)
        self.last_action = action
        return action

    def observe(self, transition: Tuple[np.ndarray, int, float, np.ndarray, bool]) -> None:
        if self.last_observation is None or self.last_action is None:
            return
        reward = transition[2]
        pred = float(self.weights[self.last_action] @ self.last_observation)
        error = reward - pred
        self.weights[self.last_action] += self.config.alpha * error * self.last_observation

    def save(self, path: str | Path) -> None:
        array = self.weights.tolist()
        Path(path).write_text(json.dumps({"weights": array}))

    def load(self, path: str | Path) -> None:
        payload = json.loads(Path(path).read_text())
        self.weights = np.array(payload["weights"], dtype=np.float32)


@dataclass
class DQNWorkflowConfig:
    gamma: float = 0.99
    lr: float = 5e-4
    batch_size: int = 64
    buffer_size: int = 50_000
    min_buffer_size: int = 2000
    target_update_interval: int = 250
    epsilon_start: float = 1.0
    epsilon_final: float = 0.05
    epsilon_decay: float = 0.995


class ReplayBuffer:
    def __init__(self, capacity: int) -> None:
        self.buffer: Deque[Tuple[np.ndarray, int, float, np.ndarray, bool]] = deque(maxlen=capacity)

    def push(self, transition: Tuple[np.ndarray, int, float, np.ndarray, bool]) -> None:
        self.buffer.append(transition)

    def sample(self, batch_size: int) -> List[Tuple[np.ndarray, int, float, np.ndarray, bool]]:
        return random.sample(self.buffer, batch_size)

    def __len__(self) -> int:
        return len(self.buffer)


if HAS_TORCH:

    class QNetwork(nn.Module):
        def __init__(self, input_dim: int, output_dim: int) -> None:
            super().__init__()
            self.model = nn.Sequential(
                nn.Linear(input_dim, 256),
                nn.ReLU(),
                nn.Linear(256, 128),
                nn.ReLU(),
                nn.Linear(128, output_dim),
            )

        def forward(self, x: torch.Tensor) -> torch.Tensor:  # type: ignore[override]
            return self.model(x)


    class DuelingQNetwork(nn.Module):
        def __init__(self, input_dim: int, output_dim: int) -> None:
            super().__init__()
            self.feature = nn.Sequential(nn.Linear(input_dim, 256), nn.ReLU())
            self.value_stream = nn.Sequential(nn.Linear(256, 128), nn.ReLU(), nn.Linear(128, 1))
            self.advantage_stream = nn.Sequential(nn.Linear(256, 128), nn.ReLU(), nn.Linear(128, output_dim))

        def forward(self, x: torch.Tensor) -> torch.Tensor:  # type: ignore[override]
            features = self.feature(x)
            value = self.value_stream(features)
            advantage = self.advantage_stream(features)
            return value + advantage - advantage.mean(dim=1, keepdim=True)


else:

    class QNetwork:
        def __init__(self, *_, **__):
            raise RuntimeError("PyTorch is required for DQN-based agents.")

    class DuelingQNetwork(QNetwork):
        pass


class DoubleDQNWorkflowAgent(WorkflowAgentBase):
    """Double DQN with action masking."""

    def __init__(
        self,
        observation_dim: int,
        action_dim: int,
        config: DQNWorkflowConfig | None = None,
        dueling: bool = False,
    ) -> None:
        if not HAS_TORCH:
            raise RuntimeError("PyTorch is required for DoubleDQNWorkflowAgent.")
        self.config = config or DQNWorkflowConfig()
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        network_cls = DuelingQNetwork if dueling else QNetwork
        self.policy_net = network_cls(observation_dim, action_dim).to(self.device)
        self.target_net = network_cls(observation_dim, action_dim).to(self.device)
        self.target_net.load_state_dict(self.policy_net.state_dict())
        self.policy_net.train()
        self.target_net.eval()
        self.optimizer = optim.Adam(self.policy_net.parameters(), lr=self.config.lr)
        self.replay = ReplayBuffer(self.config.buffer_size)
        self.steps = 0
        self.epsilon = self.config.epsilon_start
        self.action_dim = action_dim

    def act(self, observation: np.ndarray, action_mask: Optional[np.ndarray] = None, info=None) -> int:
        if np.random.rand() < self.epsilon:
            if action_mask is None:
                return int(np.random.randint(self.action_dim))
            valid = np.where(action_mask == 1)[0]
            if len(valid) == 0:
                return int(np.random.randint(self.action_dim))
            return int(np.random.choice(valid))
        obs_tensor = torch.tensor(observation, dtype=torch.float32, device=self.device).unsqueeze(0)
        with torch.no_grad():
            q_values = self.policy_net(obs_tensor)[0]
        action = masked_argmax(q_values, action_mask)
        return action

    def observe(self, transition: Tuple[np.ndarray, int, float, np.ndarray, bool]) -> None:
        self.replay.push(transition)
        self.learn()

    def learn(self) -> None:
        if len(self.replay) < self.config.min_buffer_size:
            return
        batch = self.replay.sample(self.config.batch_size)
        states, actions, rewards, next_states, dones = map(np.array, zip(*batch))
        states_tensor = torch.tensor(states, dtype=torch.float32, device=self.device)
        actions_tensor = torch.tensor(actions, dtype=torch.long, device=self.device).unsqueeze(1)
        rewards_tensor = torch.tensor(rewards, dtype=torch.float32, device=self.device).unsqueeze(1)
        next_states_tensor = torch.tensor(next_states, dtype=torch.float32, device=self.device)
        dones_tensor = torch.tensor(dones, dtype=torch.float32, device=self.device).unsqueeze(1)

        current_q = self.policy_net(states_tensor).gather(1, actions_tensor)
        with torch.no_grad():
            next_actions = torch.argmax(self.policy_net(next_states_tensor), dim=1, keepdim=True)
            next_q = self.target_net(next_states_tensor).gather(1, next_actions)
            target_q = rewards_tensor + self.config.gamma * (1 - dones_tensor) * next_q

        loss = nn.functional.mse_loss(current_q, target_q)
        self.optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.policy_net.parameters(), 1.0)
        self.optimizer.step()

        self.steps += 1
        if self.steps % self.config.target_update_interval == 0:
            self.target_net.load_state_dict(self.policy_net.state_dict())
        self.epsilon = max(self.config.epsilon_final, self.epsilon * self.config.epsilon_decay)

    def save(self, path: str | Path) -> None:
        payload = {
            "policy_state": self.policy_net.state_dict(),
            "target_state": self.target_net.state_dict(),
            "optimizer_state": self.optimizer.state_dict(),
            "epsilon": self.epsilon,
        }
        torch.save(payload, path)

    def load(self, path: str | Path) -> None:
        payload = torch.load(path, map_location=self.device)
        self.policy_net.load_state_dict(payload["policy_state"])
        self.target_net.load_state_dict(payload["target_state"])
        self.optimizer.load_state_dict(payload["optimizer_state"])
        self.epsilon = payload.get("epsilon", self.config.epsilon_start)


class DuelingDoubleDQNWorkflowAgent(DoubleDQNWorkflowAgent):
    """Thin wrapper that enables the dueling architecture."""

    def __init__(self, observation_dim: int, action_dim: int, config: DQNWorkflowConfig | None = None) -> None:
        super().__init__(observation_dim, action_dim, config=config, dueling=True)


__all__ = [
    "WorkflowAgentBase",
    "AlwaysDirectAgent",
    "AlwaysDecomposeAgent",
    "HeuristicThresholdAgent",
    "HeuristicThresholdConfig",
    "ContextualBanditWorkflowAgent",
    "BanditAgentConfig",
    "DoubleDQNWorkflowAgent",
    "DuelingDoubleDQNWorkflowAgent",
    "DQNWorkflowConfig",
    "HAS_TORCH",
]
