"""Train/evaluate RL agents for the coding marketplace environment."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

import matplotlib.pyplot as plt
import numpy as np

from src.config import PathConfig, RLConfig
from src.rl.agents import (
    ContextualBanditAgent,
    DQNAgent,
    RandomAgent,
    SkillMatchAgent,
)
from src.rl.env import CompetitionEnv
from src.utils.metrics import save_metrics, summarize_rl_rewards


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train RL agents in the competition env")
    parser.add_argument("--processed-dir", type=Path, default=None)
    parser.add_argument("--episodes", type=int, default=50)
    parser.add_argument("--episode-length", type=int, default=30)
    return parser.parse_args()


def rollout_agent(env: CompetitionEnv, agent, episodes: int, train: bool = False):
    rewards: List[float] = []
    wins: List[int] = []
    starved: List[int] = []
    for _ in range(episodes):
        obs, _ = env.reset()
        total_reward = 0.0
        total_wins = 0
        done = False
        last_info = {}
        while not done:
            action = agent.act(env, obs)
            next_obs, reward, terminated, _, info = env.step(action)
            done = terminated
            total_reward += reward
            total_wins += int(info.get("won", False))
            last_info = info
            if hasattr(agent, "remember"):
                agent.remember(obs, action, reward, next_obs, done)
            if train and hasattr(agent, "learn"):
                agent.learn()
            if hasattr(agent, "observe"):
                agent.observe(reward, env)
            obs = next_obs
        rewards.append(total_reward)
        wins.append(total_wins / env.rl_config.episode_length)
        starved.append(last_info.get("starved_tasks", 0))
    return rewards, wins, starved


def main() -> None:
    args = parse_args()
    rl_cfg = RLConfig(num_episodes=args.episodes, episode_length=args.episode_length)
    env = CompetitionEnv(processed_dir=args.processed_dir, rl_config=rl_cfg)
    results = []

    random_agent = RandomAgent()
    rewards, wins, starved = rollout_agent(env, random_agent, episodes=10)
    results.append(summarize_rl_rewards(rewards, wins, starved, "random"))

    skill_agent = SkillMatchAgent()
    rewards, wins, starved = rollout_agent(env, skill_agent, episodes=10)
    results.append(summarize_rl_rewards(rewards, wins, starved, "skill_match"))

    bandit_agent = ContextualBanditAgent(obs_dim=env.observation_dim, task_dim=len(env.task_feature_columns))
    rewards, wins, starved = rollout_agent(env, bandit_agent, episodes=10, train=True)
    results.append(summarize_rl_rewards(rewards, wins, starved, "contextual_bandit"))

    dqn_agent = DQNAgent(env.observation_dim, env.action_space.n)
    rewards, wins, starved = rollout_agent(env, dqn_agent, episodes=env.rl_config.num_episodes, train=True)
    results.append(summarize_rl_rewards(rewards, wins, starved, "dqn"))

    tables_dir = PathConfig().tables_dir
    metrics_df = save_metrics(results, tables_dir / "rl_metrics.csv")
    print(metrics_df)

    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(metrics_df["agent"], metrics_df["avg_reward"])
    ax.set_ylabel("Average reward")
    ax.set_title("RL Agent Performance")
    fig.tight_layout()
    fig.savefig(PathConfig().figs_dir / "rl_rewards.png", dpi=200)
    plt.close(fig)


if __name__ == "__main__":
    main()
