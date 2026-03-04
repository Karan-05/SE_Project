"""Run multi-agent competitions with simultaneous policies."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

from src.config import PathConfig, RLConfig
from src.decomposition.runners.run_rl_integration import MetaStrategyAgent, StrategyAwareAgent
from src.rl.agents import RandomAgent, SkillMatchAgent
from src.rl.env import EnvConfig, MultiAgentCompetitionEnv
from src.rl.utils import set_global_seeds

REPORTS_DIR = PathConfig().reports_root / "decomposition"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
MULTIAGENT_STEM = REPORTS_DIR / "rl_multiagent_metrics"


def _load_env_config(config_path: Path | None, horizon: int) -> EnvConfig:
    cfg = EnvConfig(horizon=horizon)
    if config_path and config_path.exists():
        data = json.loads(config_path.read_text(encoding="utf-8"))
        for key, value in data.items():
            if hasattr(cfg, key):
                setattr(cfg, key, value)
    return cfg


def _agent_policies(weights: Dict[str, float]) -> Dict[str, object]:
    return {
        "random": RandomAgent(),
        "skill_match": SkillMatchAgent(),
        "contract_first": StrategyAwareAgent("contract_first"),
        "pattern_skeleton": StrategyAwareAgent("pattern_skeleton"),
        "meta_strategy": MetaStrategyAgent(weights),
    }


def _load_weights(report: Path) -> Dict[str, float]:
    if not report.exists():
        return {name: 1.0 for name in ["contract_first", "pattern_skeleton"]}
    df = pd.read_csv(report)
    weights = {row["strategy"]: row["avg_pass_rate"] for _, row in df.iterrows()}
    total = sum(weights.values()) or 1.0
    return {k: v / total for k, v in weights.items()}


def run_multiagent(seed: int, episodes: int, horizon: int, config_path: Path | None = None) -> pd.DataFrame:
    set_global_seeds(seed)
    env_config = _load_env_config(config_path, horizon=horizon)
    rl_cfg = RLConfig(episode_length=horizon, num_episodes=episodes, seed=seed)
    weight_file = REPORTS_DIR / "cost_vs_quality.csv"
    policies = _agent_policies(_load_weights(weight_file))
    env = MultiAgentCompetitionEnv(list(policies.keys()), rl_config=rl_cfg, env_config=env_config, seed=seed)

    history: Dict[str, Dict[str, List[float]]] = {
        name: {"reward": [], "win_rate": [], "starved": [], "dropped": [], "deadline": []}
        for name in policies
    }
    market_history: List[Dict[str, float]] = []

    for episode in range(episodes):
        obs, _ = env.reset(seed=seed + episode)
        baselines = {
            name: {
                "wins": env.agent_states[name].wins,
                "starved": env.agent_states[name].starved_tasks,
                "dropped": env.agent_states[name].dropped_tasks,
                "deadline": env.agent_states[name].deadline_misses,
            }
            for name in policies
        }
        totals = {name: 0.0 for name in policies}
        done = False
        while not done:
            actions = {name: agent.act(env, obs[name]) for name, agent in policies.items()}
            obs, rewards, terminated, truncated, info = env.step(actions)
            for name, reward in rewards.items():
                totals[name] += reward
            done = bool(terminated or truncated)
        for name in policies:
            state = env.agent_states[name]
            base = baselines[name]
            history[name]["reward"].append(totals[name])
            history[name]["win_rate"].append((state.wins - base["wins"]) / max(1, horizon))
            history[name]["starved"].append(state.starved_tasks - base["starved"])
            history[name]["dropped"].append(state.dropped_tasks - base["dropped"])
            history[name]["deadline"].append(state.deadline_misses - base["deadline"])
        market_history.append(env.market_totals.copy())

    rows = []
    market_starved_avg = float(np.mean([m["starved"] for m in market_history]))
    market_dropped_avg = float(np.mean([m["dropped"] for m in market_history]))
    for name in policies:
        stats = history[name]
        rows.append(
            {
                "seed": seed,
                "policy": name,
                "avg_reward": float(np.mean(stats["reward"])),
                "std_reward": float(np.std(stats["reward"])),
                "win_rate": float(np.mean(stats["win_rate"])),
                "starved_tasks": float(np.mean(stats["starved"])),
                "dropped_tasks": float(np.mean(stats["dropped"])),
                "deadline_misses": float(np.mean(stats["deadline"])),
                "market_starved": market_starved_avg,
                "market_dropped": market_dropped_avg,
            }
        )
    df = pd.DataFrame(rows)
    out_path = MULTIAGENT_STEM.with_name(f"{MULTIAGENT_STEM.name}_seed_{seed}.csv")
    df.to_csv(out_path, index=False)
    return df


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run multi-agent decomposition rollouts")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--episodes", type=int, default=5)
    parser.add_argument("--horizon", type=int, default=50)
    parser.add_argument("--config", type=Path)
    return parser.parse_args()


def main() -> None:  # pragma: no cover
    args = parse_args()
    df = run_multiagent(seed=args.seed, episodes=args.episodes, horizon=args.horizon, config_path=args.config)
    print(df)


if __name__ == "__main__":  # pragma: no cover
    main()
