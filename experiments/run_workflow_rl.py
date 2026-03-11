#!/usr/bin/env python
"""End-to-end experiment runner for workflow RL control."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import asdict, replace
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Tuple
import base64
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import yaml

try:  # pragma: no cover - graceful fallback for headless environments
    import matplotlib.pyplot as plt
except Exception:  # pragma: no cover - optional dependency
    plt = None

HAS_MPL = plt is not None
PLACEHOLDER_PIXEL = base64.b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGMAAQAABQABDQottAAAAABJRU5ErkJggg=="
)

from src.config import PROJECT_ROOT
from src.rl.workflow_env import (
    WorkflowAction,
    WorkflowEnv,
    WorkflowEnvConfig,
    WorkflowEvaluationMode,
    WorkflowRewardConfig,
)
from src.rl.workflow_agents import (
    AlwaysDecomposeAgent,
    AlwaysDirectAgent,
    BanditAgentConfig,
    ContextualBanditWorkflowAgent,
    DoubleDQNWorkflowAgent,
    DQNWorkflowConfig,
    DuelingDoubleDQNWorkflowAgent,
    HeuristicThresholdAgent,
    HeuristicThresholdConfig,
    WorkflowAgentBase,
    HAS_TORCH,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Workflow RL experiment suite.")
    parser.add_argument("--episodes", type=int, default=20, help="Episodes per agent for the main run.")
    parser.add_argument("--ablation-episodes", type=int, default=10, help="Episodes per ablation scenario.")
    parser.add_argument("--budget-episodes", type=int, default=10, help="Episodes for fixed-budget evaluation.")
    parser.add_argument(
        "--figure-episodes",
        type=int,
        default=8,
        help="Episodes per evaluation mode when generating figure data.",
    )
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument(
        "--evaluation-mode",
        type=str,
        default="unconstrained",
        choices=[mode.value for mode in WorkflowEvaluationMode],
        help="Evaluation mode for the main experiments.",
    )
    parser.add_argument(
        "--ablation-agent",
        type=str,
        default="double_dqn",
        help="Agent key to use for the ablation sweeps.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "results" / "workflow_rl",
        help="Directory for machine-readable outputs.",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=PROJECT_ROOT / "reports" / "ase2026_workflow_rl",
        help="Directory for paper-ready artifacts.",
    )
    return parser.parse_args()


def ensure_dirs(*dirs: Path) -> None:
    for path in dirs:
        path.mkdir(parents=True, exist_ok=True)


def serialize_config(env_cfg: WorkflowEnvConfig, reward_cfg: WorkflowRewardConfig, args: argparse.Namespace) -> Dict:
    env_dict = asdict(env_cfg)
    env_dict["evaluation_mode"] = env_cfg.evaluation_mode.value
    env_dict["disabled_actions"] = [action.name for action in env_cfg.disabled_actions]
    reward_dict = asdict(reward_cfg)
    cli_args = {key: (str(value) if isinstance(value, Path) else value) for key, value in vars(args).items()}
    return {"env_config": env_dict, "reward_config": reward_dict, "cli_args": cli_args}


def build_agent_factories(observation_dim: int, action_dim: int) -> Dict[str, Callable[[], WorkflowAgentBase]]:
    factories: Dict[str, Callable[[], WorkflowAgentBase]] = {
        "always_direct": lambda: AlwaysDirectAgent(),
        "always_decompose": lambda: AlwaysDecomposeAgent(),
        "heuristic_threshold": lambda: HeuristicThresholdAgent(HeuristicThresholdConfig()),
        "contextual_bandit": lambda: ContextualBanditWorkflowAgent(
            observation_dim=observation_dim, action_dim=action_dim, config=BanditAgentConfig()
        ),
    }
    if HAS_TORCH:
        factories["double_dqn"] = lambda: DoubleDQNWorkflowAgent(
            observation_dim=observation_dim, action_dim=action_dim, config=DQNWorkflowConfig()
        )
        factories["dueling_double_dqn"] = lambda: DuelingDoubleDQNWorkflowAgent(
            observation_dim=observation_dim, action_dim=action_dim, config=DQNWorkflowConfig()
        )
    return factories


def run_agents(
    agent_factories: Dict[str, Callable[[], WorkflowAgentBase]],
    env_config: WorkflowEnvConfig,
    reward_config: WorkflowRewardConfig,
    episodes: int,
    seed: int,
    scenario: str,
    log_writer,
) -> Tuple[List[Dict], Dict[str, Counter]]:
    metrics: List[Dict] = []
    action_counts: Dict[str, Counter] = {}
    for agent_name, factory in agent_factories.items():
        agent = factory()
        env = WorkflowEnv(config=env_config, reward_config=reward_config)
        rng = np.random.default_rng(seed)
        agent_counter = Counter()
        for ep in range(episodes):
            obs, info = env.reset(seed=int(rng.integers(0, 1_000_000)))
            done = False
            total_reward = 0.0
            steps = 0
            while not done:
                mask = info.get("action_mask") if isinstance(info, dict) else None
                action = agent.act(obs, action_mask=mask, info=info)
                next_obs, reward, terminated, truncated, info = env.step(action)
                agent.observe((obs, action, reward, next_obs, terminated or truncated))
                obs = next_obs
                total_reward += reward
                steps += 1
                done = terminated or truncated
                agent_counter[WorkflowAction(action).name] += 1
            success = bool(env.state.success)
            episode_record = {
                "scenario": scenario,
                "agent": agent_name,
                "episode": ep,
                "success": success,
                "reward": total_reward,
                "steps": steps,
                "prompt_spent": env.budget.prompt_spent,
                "completion_spent": env.budget.completion_spent,
                "terminal_stage": env.state.stage.name,
            }
            metrics.append(episode_record)
            if log_writer is not None:
                log_writer.write(
                    json.dumps(
                        {
                            **episode_record,
                            "trace": env.episode_trace,
                            "budget": env.budget.as_dict(),
                        }
                    )
                    + "\n"
                )
        action_counts[agent_name] = agent_counter
    return metrics, action_counts


def aggregate_metrics(rows: Iterable[Dict], group_key: str = "agent") -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(
            columns=[
                group_key,
                "success_rate",
                "avg_reward",
                "avg_prompt_tokens",
                "avg_completion_tokens",
                "avg_steps",
                "avg_total_tokens",
            ]
        )
    grouped = (
        df.groupby(group_key)
        .agg(
            success_rate=("success", "mean"),
            avg_reward=("reward", "mean"),
            avg_prompt_tokens=("prompt_spent", "mean"),
            avg_completion_tokens=("completion_spent", "mean"),
            avg_steps=("steps", "mean"),
        )
        .reset_index()
    )
    grouped["avg_total_tokens"] = grouped["avg_prompt_tokens"] + grouped["avg_completion_tokens"]
    return grouped


def save_csv(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, index=False)


def _write_placeholder_png(path: Path) -> None:
    path.write_bytes(PLACEHOLDER_PIXEL)


def plot_success_vs_cost(df: pd.DataFrame, path: Path) -> None:
    if not HAS_MPL or df.empty:
        _write_placeholder_png(path)
        return
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.scatter(df["avg_total_tokens"], df["success_rate"], c="tab:blue")
    for _, row in df.iterrows():
        ax.annotate(row["agent"], (row["avg_total_tokens"], row["success_rate"]))
    ax.set_xlabel("Avg total tokens")
    ax.set_ylabel("Success rate")
    ax.set_title("Success vs. cost")
    fig.tight_layout()
    fig.savefig(path, dpi=300)
    plt.close(fig)


def plot_action_distribution(action_counts: Dict[str, Counter], path: Path) -> None:
    if not HAS_MPL:
        _write_placeholder_png(path)
        return
    total_counts = Counter()
    for counts in action_counts.values():
        total_counts.update(counts)
    labels = list(total_counts.keys())
    if not labels:
        return
    values = [total_counts[label] for label in labels]
    positions = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(positions, values, color="tab:purple")
    ax.set_xticks(positions)
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_ylabel("Count")
    ax.set_title("Action usage distribution")
    fig.tight_layout()
    fig.savefig(path, dpi=300)
    plt.close(fig)


def plot_ablation(ablations_df: pd.DataFrame, path: Path) -> None:
    if not HAS_MPL or ablations_df.empty:
        _write_placeholder_png(path)
        return
    fig, ax = plt.subplots(figsize=(6, 4))
    positions = np.arange(len(ablations_df))
    ax.bar(positions, ablations_df["success_rate"], color="tab:green")
    ax.set_xticks(positions)
    ax.set_xticklabels(ablations_df["scenario"], rotation=45, ha="right")
    ax.set_ylabel("Success rate")
    ax.set_title("Ablation study")
    fig.tight_layout()
    fig.savefig(path, dpi=300)
    plt.close(fig)


def plot_budgeted_success(mode_rows: List[Dict], path: Path) -> None:
    if not HAS_MPL or not mode_rows:
        _write_placeholder_png(path)
        return
    fig, ax = plt.subplots(figsize=(5, 4))
    modes = [row["mode"] for row in mode_rows]
    values = [row["success_rate"] for row in mode_rows]
    ax.plot(modes, values, marker="o")
    ax.set_ylabel("Success rate")
    ax.set_title("Fixed-budget success")
    fig.tight_layout()
    fig.savefig(path, dpi=300)
    plt.close(fig)


def run_ablation_suite(
    base_env_cfg: WorkflowEnvConfig,
    reward_cfg: WorkflowRewardConfig,
    agent_factory: Callable[[], WorkflowAgentBase],
    episodes: int,
    seed: int,
    log_writer,
) -> List[Dict]:
    ablation_specs = {
        "no_uncertainty_features": {"env": {"enable_uncertainty_features": False}},
        "no_verifier_action": {"env": {"disabled_actions": (WorkflowAction.ASK_VERIFIER,)}},
        "no_retrieval_action": {"env": {"disabled_actions": (WorkflowAction.RETRIEVE_CONTEXT,)}},
        "no_budget_penalty": {"reward": {"budget_violation_penalty": 0.0}},
        "no_deep_decomposition": {"env": {"disabled_actions": (WorkflowAction.DECOMPOSE_DEEP,)}},
        "no_action_masking": {"env": {"enable_action_masking": False}},
    }
    rows: List[Dict] = []
    for name, overrides in ablation_specs.items():
        env_cfg = base_env_cfg
        if "env" in overrides:
            env_cfg = replace(base_env_cfg, **overrides["env"])
        reward_override = reward_cfg
        if "reward" in overrides:
            reward_override = replace(reward_cfg, **overrides["reward"])
        agent_metrics, _ = run_agents(
            {"ablation_agent": agent_factory},
            env_cfg,
            reward_override,
            episodes,
            seed=seed,
            scenario=name,
            log_writer=log_writer,
        )
        rows.extend(agent_metrics)
    return rows


def evaluate_modes_for_best_agent(
    best_agent_factory: Callable[[], WorkflowAgentBase],
    base_env_cfg: WorkflowEnvConfig,
    reward_cfg: WorkflowRewardConfig,
    episodes: int,
    seed: int,
    log_writer,
) -> List[Dict]:
    mode_rows: List[Dict] = []
    for mode in WorkflowEvaluationMode:
        env_cfg = replace(base_env_cfg, evaluation_mode=mode)
        metrics, _ = run_agents(
            {"best_agent": best_agent_factory},
            env_cfg,
            reward_cfg,
            episodes,
            seed,
            scenario=f"mode_{mode.value}",
            log_writer=log_writer,
        )
        agg = aggregate_metrics(metrics)
        mode_rows.append({"mode": mode.value, "success_rate": float(agg["success_rate"].iloc[0])})
    return mode_rows


def summarize_failure_modes(rows: Iterable[Dict]) -> Dict[str, int]:
    counts: Dict[str, int] = defaultdict(int)
    for row in rows:
        if not row["success"]:
            counts[row["terminal_stage"]] += 1
    return counts


def write_summary_report(
    report_path: Path,
    methods: List[str],
    main_df: pd.DataFrame,
    ablation_df: pd.DataFrame,
    best_method: str,
    best_budget_method: str,
    failure_modes: Dict[str, int],
) -> None:
    ablation_section = (
        ablation_df.to_string(index=False) if not ablation_df.empty else "No ablation results generated."
    )
    lines = [
        "# Workflow RL Summary",
        "## Compared Methods",
        ", ".join(methods),
        "## Main Metrics",
        main_df.to_string(index=False),
        "## Ablation Metrics",
        ablation_section,
        f"**Best raw success:** {best_method}",
        f"**Best fixed-budget success:** {best_budget_method}",
        "## Failure Modes",
    ]
    if failure_modes:
        failure_summary = ", ".join(f"{stage}: {count}" for stage, count in failure_modes.items())
    else:
        failure_summary = "No failures recorded."
    lines.append(failure_summary)
    report_path.write_text("\n\n".join(lines))


def write_paper_notes(path: Path) -> None:
    notes = """# ASE 2026 Workflow RL Notes

## Proposed Title
Trace-Aware Workflow Reinforcement Learning for Agentic Software Engineering

## Novelty Statement
We shift RL control from task selection to budget-aware decision making over Planner–Solver–Verifier workflows with explicit uncertainty and trace supervision.

## Research Questions
1. Can a single policy learn to navigate decomposition, retrieval, solving, verification, and repair under strict budgets?
2. How do uncertainty signals (verifier disagreement, failure counters) influence control effectiveness?
3. What is the marginal utility of verifier, retrieval, and deep decomposition actions when budgets are constrained?

## Code ↔ Paper Mapping
- `src/rl/workflow_env.py` → Environment and methodology section describing simulator assumptions and reward design.
- `src/rl/workflow_agents.py` → Agent architecture section.
- `experiments/run_workflow_rl.py` → Experimental setup and evaluation protocol.
- `reports/ase2026_workflow_rl/summary.md` → Empirical findings.
- `reports/ase2026_workflow_rl/figure_*.png` → Quantitative results figures.
- `reports/ase2026_workflow_rl/table_*.csv` → Tabulated metrics for main and ablation studies.

## Figures/Tables for Paper
- `figure_success_vs_cost.png`, `figure_budgeted_success.png`, `figure_action_distribution.png`, `figure_ablation.png`
- `table_main.csv`, `table_ablation.csv`

## Limitations and Threats to Validity
- Environment relies on stylized dynamics rather than live coding tasks.
- Token costs approximate LLM usage; real deployment may have different scaling.
- Policies trained with few episodes in quick sweeps may require longer training for stable convergence.
- Ablation toggles are deterministic and may not capture partial degradations observed in practice.
"""
    path.write_text(notes.strip() + "\n")


def main() -> None:
    args = parse_args()
    ensure_dirs(args.output_dir, args.report_dir)
    # Prepare configs and snapshot
    env_cfg = WorkflowEnvConfig(
        seed=args.seed,
        evaluation_mode=WorkflowEvaluationMode(args.evaluation_mode),
    )
    reward_cfg = WorkflowRewardConfig()
    snapshot_path = args.output_dir / "config_snapshot.yaml"
    snapshot_path.write_text(yaml.safe_dump(serialize_config(env_cfg, reward_cfg, args)))

    env_probe = WorkflowEnv(config=env_cfg, reward_config=reward_cfg)
    observation_dim = env_probe.observation_space.shape[0]
    action_dim = env_probe.action_space.n
    agent_factories = build_agent_factories(observation_dim, action_dim)
    if args.ablation_agent not in agent_factories:
        fallback_agent = "heuristic_threshold"
        print(
            f"[workflow_rl] Requested ablation agent '{args.ablation_agent}' unavailable. "
            f"Falling back to '{fallback_agent}'."
        )
        args.ablation_agent = fallback_agent

    episode_log_path = args.output_dir / "episode_logs.jsonl"
    if episode_log_path.exists():
        episode_log_path.unlink()
    with episode_log_path.open("w") as log_writer:
        main_rows, action_counts = run_agents(
            agent_factories,
            env_cfg,
            reward_cfg,
            episodes=args.episodes,
            seed=args.seed,
            scenario="main",
            log_writer=log_writer,
        )
        main_df = aggregate_metrics(main_rows)
        save_csv(main_df, args.output_dir / "metrics.csv")
        save_csv(main_df, args.report_dir / "table_main.csv")

        best_method = main_df.sort_values("success_rate", ascending=False)["agent"].iloc[0]

        ablation_agent_factory = agent_factories[args.ablation_agent]
        ablation_rows = run_ablation_suite(
            env_cfg,
            reward_cfg,
            ablation_agent_factory,
            episodes=args.ablation_episodes,
            seed=args.seed + 7,
            log_writer=log_writer,
        )
        if ablation_rows:
            ablation_df = aggregate_metrics(ablation_rows, group_key="scenario")
            save_csv(ablation_df, args.output_dir / "ablations.csv")
            save_csv(ablation_df, args.report_dir / "table_ablation.csv")
        else:
            ablation_df = pd.DataFrame(
                columns=[
                    "scenario",
                    "success_rate",
                    "avg_reward",
                    "avg_prompt_tokens",
                    "avg_completion_tokens",
                    "avg_steps",
                    "avg_total_tokens",
                ]
            )

        budget_env_cfg = replace(env_cfg, evaluation_mode=WorkflowEvaluationMode.FIXED_TOKEN)
        budget_rows, _ = run_agents(
            agent_factories,
            budget_env_cfg,
            reward_cfg,
            episodes=args.budget_episodes,
            seed=args.seed + 99,
            scenario="fixed_token",
            log_writer=log_writer,
        )
        budget_df = aggregate_metrics(budget_rows)
        best_budget_method = budget_df.sort_values("success_rate", ascending=False)["agent"].iloc[0]

        mode_rows = evaluate_modes_for_best_agent(
            agent_factories[best_method],
            env_cfg,
            reward_cfg,
            episodes=args.figure_episodes,
            seed=args.seed + 123,
            log_writer=log_writer,
        )

    # Figures
    plot_success_vs_cost(main_df, args.report_dir / "figure_success_vs_cost.png")
    plot_action_distribution(action_counts, args.report_dir / "figure_action_distribution.png")
    if not ablation_df.empty:
        plot_ablation(ablation_df[["scenario", "success_rate"]], args.report_dir / "figure_ablation.png")
    plot_budgeted_success(mode_rows, args.report_dir / "figure_budgeted_success.png")

    failure_modes = summarize_failure_modes(main_rows)
    write_summary_report(
        args.report_dir / "summary.md",
        methods=list(agent_factories.keys()),
        main_df=main_df,
        ablation_df=ablation_df,
        best_method=best_method,
        best_budget_method=best_budget_method,
        failure_modes=failure_modes,
    )
    write_paper_notes(args.report_dir / "paper_notes.md")


if __name__ == "__main__":
    main()
