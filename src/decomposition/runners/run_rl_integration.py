"""Integrate decomposition strategies with hardened RL environments."""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

from src.config import PathConfig, RLConfig
from src.decomposition.interfaces import DecompositionContext
from src.decomposition.registry import STRATEGIES
from src.decomposition.runners.run_on_task import _build_context
from src.rl.agents import BaseAgent, RandomAgent, SkillMatchAgent
from src.rl.env import CompetitionEnv, EnvConfig
from src.rl.utils import set_global_seeds

REPORTS_DIR = PathConfig().reports_root / "decomposition"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
REPORT_STEM = REPORTS_DIR / "rl_decomposition_metrics"


@dataclass
class StrategyAwareAgent(BaseAgent):
    strategy_name: str

    def act(self, env: CompetitionEnv, observation):  # type: ignore[override]
        strategy = STRATEGIES[self.strategy_name]
        best_idx = env.action_space.sample()
        best_score = float("-inf")
        for idx, meta in enumerate(env.current_slate.metadata):
            ctx = self._ctx_from_meta(meta)
            plan = strategy.decompose(ctx)
            reliability = len(plan.subtasks) + len(plan.tests) * 0.5
            score = reliability + float(meta.get("prize", 0)) * 0.001
            if score > best_score:
                best_idx = idx
                best_score = score
        return best_idx

    def _ctx_from_meta(self, meta: Dict[str, object]) -> DecompositionContext:
        task = {
            "id": meta.get("task_id", "sim"),
            "problem_statement": f"Simulated task {meta.get('task_id')}",
            "tags": [meta.get("track", "track")],
            "difficulty": str(meta.get("difficulty", "unknown")),
            "constraints": "Simulated",
            "examples": [{"input": "", "output": ""}],
            "tests": [{"input": [], "expected": True}],
            "reference_solution": "def solve():\n    return True\n",
        }
        return _build_context(task)


class MetaStrategyAgent(BaseAgent):
    def __init__(self, strategy_weights: Dict[str, float]) -> None:
        self.strategy_weights = strategy_weights

    def act(self, env: CompetitionEnv, observation):  # type: ignore[override]
        best_idx = env.action_space.sample()
        best_score = float("-inf")
        for idx, meta in enumerate(env.current_slate.metadata):
            score = 0.0
            for strategy_name, weight in self.strategy_weights.items():
                ctx = StrategyAwareAgent(strategy_name)._ctx_from_meta(meta)
                plan = STRATEGIES[strategy_name].decompose(ctx)
                reliability = len(plan.subtasks) + len(plan.tests) * 0.5
                score += weight * reliability
            score += float(meta.get("prize", 0)) * 0.0005
            if score > best_score:
                best_idx = idx
                best_score = score
        return best_idx


def _load_env_config(config_path: Path | None, horizon: int) -> EnvConfig:
    cfg = EnvConfig(horizon=horizon)
    if config_path and config_path.exists():
        data = json.loads(config_path.read_text(encoding="utf-8"))
        for key, value in data.items():
            if hasattr(cfg, key):
                setattr(cfg, key, value)
    return cfg


def rollout_agent(env: CompetitionEnv, agent: BaseAgent, episodes: int, base_seed: int) -> Dict[str, float]:
    rewards: List[float] = []
    win_rates: List[float] = []
    starved: List[float] = []
    deadlines: List[float] = []
    horizon = env.env_config.horizon
    for episode in range(episodes):
        obs, _ = env.reset(seed=base_seed + episode)
        done = False
        total_reward = 0.0
        wins_before = env.agent_state.wins if env.agent_state else 0
        starved_before = env.agent_state.starved_tasks if env.agent_state else 0
        deadline_before = env.agent_state.deadline_misses if env.agent_state else 0
        last_info: Dict[str, float] = {}
        while not done:
            action = agent.act(env, obs)
            obs, reward, terminated, truncated, info = env.step(action)
            done = bool(terminated or truncated)
            total_reward += reward
            last_info = info
        rewards.append(total_reward)
        wins_after = last_info.get("won", wins_before)
        starved_after = last_info.get("starved_tasks", starved_before)
        deadline_after = last_info.get("deadline_misses", deadline_before)
        win_rates.append((wins_after - wins_before) / max(1, horizon))
        starved.append(starved_after - starved_before)
        deadlines.append(deadline_after - deadline_before)
    return {
        "avg_reward": float(np.mean(rewards)),
        "std_reward": float(np.std(rewards)),
        "win_rate": float(np.mean(win_rates)),
        "starved_tasks": float(np.mean(starved)),
        "deadline_misses": float(np.mean(deadlines)),
    }


def load_strategy_weights(report: Path) -> Dict[str, float]:
    if not report.exists():
        return {name: 1.0 for name in STRATEGIES}
    df = pd.read_csv(report)
    weights = {row["strategy"]: row["avg_pass_rate"] for _, row in df.iterrows()}
    total = sum(weights.values()) or 1.0
    return {k: v / total for k, v in weights.items()}


def run_rl_decomposition(seed: int = 42, episodes: int = 5, horizon: int = 50, config_path: Path | None = None) -> pd.DataFrame:
    set_global_seeds(seed)
    env_config = _load_env_config(config_path, horizon=horizon)
    rl_cfg = RLConfig(episode_length=horizon, num_episodes=episodes, seed=seed)
    env = CompetitionEnv(rl_config=rl_cfg, env_config=env_config)

    results = []
    agents = [
        ("random", RandomAgent()),
        ("skill_match", SkillMatchAgent()),
        ("contract_first", StrategyAwareAgent("contract_first")),
        ("pattern_skeleton", StrategyAwareAgent("pattern_skeleton")),
    ]
    weights = load_strategy_weights(REPORTS_DIR / "cost_vs_quality.csv")
    agents.append(("meta_strategy", MetaStrategyAgent(weights)))

    for label, agent in agents:
        metrics = rollout_agent(env, agent, episodes, base_seed=seed)
        metrics.update({"agent": label, "seed": seed, "episodes": episodes})
        results.append(metrics)

    df = pd.DataFrame(results)
    seed_path = REPORT_STEM.with_name(f"{REPORT_STEM.name}_seed_{seed}.csv")
    df.to_csv(seed_path, index=False)
    df.to_csv(REPORT_STEM.with_suffix(".csv"), index=False)
    return df


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run RL decomposition rollouts with Gymnasium seeds")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for the rollout")
    parser.add_argument("--episodes", type=int, default=5, help="Episodes per agent evaluation")
    parser.add_argument("--horizon", type=int, default=50, help="Maximum steps per episode")
    parser.add_argument("--config", type=Path, help="Optional JSON file overriding EnvConfig fields")
    return parser.parse_args()


def main() -> None:  # pragma: no cover
    args = parse_args()
    df = run_rl_decomposition(seed=args.seed, episodes=args.episodes, horizon=args.horizon, config_path=args.config)
    print(df)


if __name__ == "__main__":  # pragma: no cover
    main()
