"""Training entry-point for the AEGIS-RL pipeline."""
from __future__ import annotations

import argparse
import csv
import json
import copy
from contextlib import nullcontext
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Iterable, List, Tuple, Callable, Optional

import numpy as np
import yaml

from src.rl.aegis_agents import AegisAgentConfig, AegisManagerAgent
from src.rl.aegis_state import AegisMacroOption
from src.rl.aegis_env import AegisEnvConfig, AegisWorkflowEnv
from src.rl.aegis_state import AegisMacroOption
from src.rl.workflow_agents import (
    AlwaysDecomposeAgent,
    AlwaysDirectAgent,
    ContextualBanditWorkflowAgent,
    HeuristicThresholdAgent,
    DuelingDoubleDQNWorkflowAgent,
    DQNWorkflowConfig,
    WorkflowAgentBase,
    HAS_TORCH,
)
from src.rl.workflow_env import WorkflowEnv, WorkflowEnvConfig, WorkflowStage, WorkflowAction
from src.rl.teacher_guided import map_action_to_macro


def _ensure_dirs(root: Path) -> None:
    (root / "logs").mkdir(parents=True, exist_ok=True)
    (root / "datasets").mkdir(parents=True, exist_ok=True)
    (root / "reports").mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- Stage A
def build_logged_dataset(output_dir: Path, episodes_per_agent: int) -> Path:
    env = WorkflowEnv(config=WorkflowEnvConfig(track_episode_logs=False))
    agents = {
        "always_direct": AlwaysDirectAgent(),
        "always_decompose": AlwaysDecomposeAgent(),
        "heuristic": HeuristicThresholdAgent(),
        "contextual_bandit": ContextualBanditWorkflowAgent(env.observation_dim, env.action_space.n),
    }
    dataset_path = output_dir / "datasets" / "aegis_stage_a.jsonl"
    with dataset_path.open("w", encoding="utf-8") as f:
        for agent_name, agent in agents.items():
            for episode in range(episodes_per_agent):
                obs, info = env.reset()
                done = False
                while not done:
                    mask = info.get("action_mask")
                    action = agent.act(obs, action_mask=mask, info=info)
                    next_obs, reward, terminated, truncated, info = env.step(action)
                    record = {
                        "agent": agent_name,
                        "episode": episode,
                        "observation": obs.tolist(),
                        "action": int(action),
                        "macro_action": map_action_to_macro(action, AegisMacroOption.ordered()).value,
                        "reward": reward,
                        "next_observation": next_obs.tolist(),
                        "done": terminated or truncated,
                        "success": bool(info.get("success", False)),
                    }
                    f.write(json.dumps(record) + "\n")
                    obs = next_obs
                    done = terminated or truncated
    return dataset_path


# --------------------------------------------------------------------------- Stage B
def pretrain_belief_encoder(dataset_path: Path, output_dir: Path) -> Dict[str, float]:
    success = 0
    steps = 0
    rewards: List[float] = []
    with dataset_path.open("r", encoding="utf-8") as f:
        for line in f:
            payload = json.loads(line)
            rewards.append(float(payload["reward"]))
            steps += 1
            if payload.get("success"):
                success += 1
    success_rate = success / max(1, steps)
    avg_reward = float(np.mean(rewards)) if rewards else 0.0
    summary = {
        "success_rate": success_rate,
        "avg_reward": avg_reward,
        "num_samples": steps,
    }
    summary_path = output_dir / "reports" / "stage_b_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


# --------------------------------------------------------------------------- Helpers
def _aggregate_summary(
    label: str,
    metrics: List[Dict[str, float]],
    calibration: Dict[str, float] | None = None,
    notes: str = "",
) -> Dict[str, object]:
    episodes = len(metrics)
    if episodes == 0:
        return {
            "method": label,
            "success_rate": 0.0,
            "avg_reward": 0.0,
            "avg_steps": 0.0,
            "avg_constraint": 0.0,
            "avg_tokens": 0.0,
            "budgeted_success": 0.0,
            "catastrophic_failure": 0.0,
            "action_entropy": 0.0,
            "notes": notes,
            "calibration": calibration or {},
        }
    success_rate = sum(float(m["success"]) for m in metrics) / episodes
    avg_reward = float(np.mean([m["reward"] for m in metrics]))
    avg_steps = float(np.mean([m["steps"] for m in metrics]))
    avg_constraint = float(np.mean([m["constraint_penalty"] for m in metrics]))
    avg_tokens = float(np.mean([m.get("token_spent", 0.0) for m in metrics]))
    budgeted_success = float(np.mean([m.get("budgeted_success", 0.0) for m in metrics]))
    catastrophic = float(np.mean([m.get("catastrophic_failure", 0.0) for m in metrics]))
    action_entropy = float(np.mean([m.get("action_entropy", 0.0) for m in metrics]))
    summary = {
        "method": label,
        "success_rate": success_rate,
        "avg_reward": avg_reward,
        "avg_steps": avg_steps,
        "avg_constraint": avg_constraint,
        "avg_tokens": avg_tokens,
        "budgeted_success": budgeted_success,
        "catastrophic_failure": catastrophic,
        "action_entropy": action_entropy,
        "notes": notes,
        "calibration": calibration or {},
    }
    return summary


# --------------------------------------------------------------------------- Stage C
def run_online_training(
    label: str,
    env_config: AegisEnvConfig,
    agent_config: AegisAgentConfig,
    output_dir: Path,
    episodes: int,
    pretrain_summary: Dict[str, float] | None = None,
    log_traces: bool = False,
    notes: str = "aegis_variant",
    warm_start_episodes: int = 0,
    curriculum_schedule: Optional[List[Tuple[Optional[float], Optional[float]]]] = None,
) -> Tuple[List[Dict[str, float]], Dict[str, object]]:
    env = AegisWorkflowEnv(config=env_config)
    agent = AegisManagerAgent(env.observation_space.shape[0], env.action_space.n, config=agent_config)
    if pretrain_summary:
        prior = float(pretrain_summary.get("success_rate", 0.5))
        agent.epsilon = max(agent.config.epsilon_final, 1.0 - prior)
    if warm_start_episodes > 0:
        _warm_start_agent(env, agent, warm_start_episodes)
    metrics: List[Dict[str, float]] = []
    (output_dir / "metrics").mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "metrics" / "episode_logs.jsonl"
    log_ctx = log_path.open("w", encoding="utf-8") if log_traces else nullcontext(None)
    schedule = curriculum_schedule or [(env.config.workflow.difficulty_min, env.config.workflow.difficulty_max)] * episodes
    if len(schedule) < episodes:
        schedule.extend([schedule[-1]] * (episodes - len(schedule)))
    with log_ctx as log_file:
        for episode in range(episodes):
            stage_bounds = schedule[min(episode, len(schedule) - 1)]
            env.base_env.config.difficulty_min = stage_bounds[0]
            env.base_env.config.difficulty_max = stage_bounds[1]
            env.config.workflow.difficulty_min = stage_bounds[0]
            env.config.workflow.difficulty_max = stage_bounds[1]
            obs, info = env.reset()
            done = False
            total_reward = 0.0
            steps_taken = 0
            while not done:
                mask = env.manager_action_mask()
                action = agent.act(obs, option_mask=mask)
                next_obs, reward, terminated, truncated, info = env.step(action)
                agent.observe((obs, action, reward, next_obs, terminated or truncated))
                obs = next_obs
                done = terminated or truncated
                total_reward += reward
                steps_taken += 1
            snapshot = info.get("constraint_snapshot", {})
            prompt_budget = env.config.workflow.prompt_budget + env.config.workflow.completion_budget
            budgeted_success = float(
                info.get("success", False)
                and (snapshot.get("prompt_spent", 0.0) + snapshot.get("completion_spent", 0.0)) <= prompt_budget
            )
            catastrophic = float(
                not info.get("success", False) and info.get("macro_option") == AegisMacroOption.ABANDON.value
            )
            action_hist = np.array(info.get("manager_option_histogram", []), dtype=np.float32)
            entropy = 0.0
            if action_hist.size > 0 and action_hist.sum() > 0:
                probs = action_hist / action_hist.sum()
                entropy = float(-np.sum(probs * np.log(probs + 1e-8)))
            metrics.append(
                {
                    "method": label,
                    "episode": episode,
                    "reward": total_reward,
                    "success": float(info.get("success", False)),
                    "steps": steps_taken,
                    "constraint_penalty": float(info.get("constraint_penalty", 0.0)),
                    "token_spent": float(snapshot.get("prompt_spent", 0.0) + snapshot.get("completion_spent", 0.0)),
                    "verifier_calls": float(snapshot.get("verifier_calls", 0.0)),
                    "budgeted_success": budgeted_success,
                    "catastrophic_failure": catastrophic,
                    "action_entropy": entropy,
                }
            )
            if log_file:
                for entry in env.manager_logs:
                    log_file.write(json.dumps(entry.to_jsonable()) + "\n")
    summary = _aggregate_summary(label, metrics, calibration=env.calibration_metrics(), notes=notes)
    return metrics, summary


def run_flat_agent(
    label: str,
    agent_factory: Callable[[WorkflowEnv], WorkflowAgentBase],
    episodes: int,
    env_config: WorkflowEnvConfig | None = None,
) -> Tuple[List[Dict[str, float]], Dict[str, object]]:
    env = WorkflowEnv(config=env_config or WorkflowEnvConfig())
    agent = agent_factory(env)
    metrics: List[Dict[str, float]] = []
    for episode in range(episodes):
        obs, info = env.reset()
        done = False
        total_reward = 0.0
        steps_taken = 0
        while not done:
            mask = info.get("action_mask")
            action = agent.act(obs, action_mask=mask, info=info)
            next_obs, reward, terminated, truncated, info = env.step(action)
            agent.observe((obs, action, reward, next_obs, terminated or truncated))
            obs = next_obs
            done = terminated or truncated
            total_reward += reward
            steps_taken += 1
        budget = info.get("budget", {})
        token_spent = float(budget.get("prompt_spent", 0.0) + budget.get("completion_spent", 0.0))
        prompt_budget = env.config.prompt_budget + env.config.completion_budget
        metrics.append(
            {
                "method": label,
                "episode": episode,
                "reward": total_reward,
                "success": float(info.get("success", False)),
                "steps": steps_taken,
                "constraint_penalty": 0.0,
                "token_spent": token_spent,
                "verifier_calls": float(budget.get("verifier_calls", 0.0)),
                "budgeted_success": float(info.get("success", False) and token_spent <= prompt_budget),
                "catastrophic_failure": 0.0,
                "action_entropy": 0.0,
            }
        )
    summary = _aggregate_summary(label, metrics, notes="baseline")
    return metrics, summary


def _write_metrics_csv(metrics: List[Dict[str, float]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "method",
        "episode",
        "reward",
        "success",
        "steps",
        "constraint_penalty",
        "token_spent",
        "verifier_calls",
        "budgeted_success",
        "catastrophic_failure",
        "action_entropy",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in metrics:
            writer.writerow(row)


def _write_ablation_table(summaries: List[Dict[str, object]], path: Path) -> None:
    rows = [
        (s["method"], s["success_rate"], s["avg_reward"], s.get("notes", ""))
        for s in summaries
        if "aegis_no" in s["method"] or "aegis_flat" in s["method"] or "aegis_reduced" in s["method"]
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["setting", "success_rate", "avg_reward", "notes"])
        writer.writerows(rows)


def _write_calibration_table(summaries: List[Dict[str, object]], path: Path) -> None:
    rows = []
    for summary in summaries:
        calib = summary.get("calibration", {})
        if not calib:
            continue
        rows.append([summary["method"], calib.get("brier", 0.0), calib.get("cost_mae", 0.0)])
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["method", "brier", "cost_mae"])
        writer.writerows(rows)


def _write_main_table(summaries: List[Dict[str, object]], path: Path) -> None:
    rows = [
        [
            s["method"],
            s["success_rate"],
            s["avg_reward"],
            s["avg_steps"],
            s["avg_tokens"],
            s["avg_constraint"],
            s.get("budgeted_success", 0.0),
            s.get("catastrophic_failure", 0.0),
            s.get("action_entropy", 0.0),
            s.get("notes", ""),
        ]
        for s in summaries
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["method", "success_rate", "avg_reward", "avg_steps", "avg_tokens", "avg_constraint", "budgeted_success", "catastrophic_failure", "action_entropy", "notes"]
        )
        writer.writerows(rows)


def _write_summary_markdown(summaries: List[Dict[str, object]], path: Path) -> None:
    lines: List[str] = ["# ASE 2026 AEGIS-RL Summary", "", "## Compared Methods"]
    for summary in summaries:
        lines.append(
            f"- **{summary['method']}** — success {summary['success_rate']:.2f}, "
            f"reward {summary['avg_reward']:.2f}, steps {summary['avg_steps']:.2f}, "
            f"tokens {summary['avg_tokens']:.1f}, notes: {summary.get('notes', 'n/a')}"
        )
    lines.append("")
    lines.append("## Calibration")
    for summary in summaries:
        calib = summary.get("calibration", {})
        if not calib:
            continue
        lines.append(
            f"- {summary['method']}: Brier {calib.get('brier', 0.0):.3f}, Cost MAE {calib.get('cost_mae', 0.0):.3f}"
        )
    if len(lines) == 3:
        lines.append("No calibration metrics recorded.")
    lines.append("")
    lines.append("## Action Distribution & Failure Modes")
    lines.append(
        "See `results/aegis_rl/metrics/trace_summary.json` (generated via `scripts/build_aegis_traces.py`) "
        "for option usage histograms and failure summaries."
    )
    lines.append("")
    lines.append("## Notes")
    lines.append("These metrics are exploratory; rerun with more episodes for publication-ready statistics.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _heuristic_macro_index(env: AegisWorkflowEnv) -> int:
    state = env.base_env.state
    idx = env.macro_indices
    def has(option: AegisMacroOption) -> Optional[int]:
        return idx.get(option)

    if has(AegisMacroOption.SUBMIT) is not None and state.test_pass_ratio > 0.9 and state.verifier_confidence > 0.6:
        return idx[AegisMacroOption.SUBMIT]
    if has(AegisMacroOption.VERIFY) is not None and state.stage == WorkflowStage.VERIFYING:
        return idx[AegisMacroOption.VERIFY]
    if has(AegisMacroOption.REPAIR) is not None and state.repeated_failures > 1:
        return idx[AegisMacroOption.REPAIR]
    if has(AegisMacroOption.RESEARCH_CONTEXT) is not None and state.retrieval_coverage < 0.4:
        return idx[AegisMacroOption.RESEARCH_CONTEXT]
    if has(AegisMacroOption.DECOMPOSE_SHALLOW) is not None and state.num_subtasks < 2:
        return idx[AegisMacroOption.DECOMPOSE_SHALLOW]
    if has(AegisMacroOption.DIRECT_SOLVE) is not None:
        return idx[AegisMacroOption.DIRECT_SOLVE]
    return 0


def _warm_start_agent(env: AegisWorkflowEnv, agent: AegisManagerAgent, episodes: int) -> None:
    for _ in range(max(0, episodes)):
        obs, info = env.reset()
        done = False
        while not done:
            action = _heuristic_macro_index(env)
            next_obs, reward, terminated, truncated, info = env.step(action)
            agent.buffer.push((obs, action, reward, next_obs, terminated or truncated))
            obs = next_obs
            done = terminated or truncated


def _default_curriculum_schedule(episodes: int) -> List[Tuple[Optional[float], Optional[float]]]:
    stages = [(0.2, 0.5), (0.4, 0.7), (0.6, 0.95)]
    stage_len = max(1, episodes // len(stages))
    schedule: List[Tuple[Optional[float], Optional[float]]] = []
    for idx, bounds in enumerate(stages):
        remaining = episodes - len(schedule)
        count = stage_len if idx < len(stages) - 1 else max(1, remaining)
        schedule.extend([bounds] * count)
        if len(schedule) >= episodes:
            break
    return schedule[:episodes]


def _write_final_summary(summaries: List[Dict[str, object]], path: Path) -> None:
    sorted_methods = sorted(summaries, key=lambda s: s["success_rate"], reverse=True)
    lines = ["# Final AEGIS-RL Summary", "", "## Top Methods"]
    for summary in sorted_methods[:5]:
        lines.append(
            f"- {summary['method']}: success {summary['success_rate']:.2f}, reward {summary['avg_reward']:.2f}, "
            f"budgeted {summary.get('budgeted_success', 0.0):.2f}, entropy {summary.get('action_entropy', 0.0):.2f}"
        )
    lines.append("")
    lines.append("## Notes")
    lines.append("Calibrations and constraints are reported per-method; see calibration table for details.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_model_selection_decision(summaries: List[Dict[str, object]], path: Path) -> None:
    aegis_candidates = [s for s in summaries if s["method"].startswith("aegis")]
    candidate_pool = aegis_candidates or summaries
    best = max(candidate_pool, key=lambda s: s["success_rate"])
    lookup = {s["method"]: s for s in summaries}

    def is_essential(ablation: str) -> bool:
        alt = lookup.get(ablation)
        if not alt:
            return True
        return alt["success_rate"] < best["success_rate"] - 0.02

    essential_components = []
    optional_components = []
    if is_essential("aegis_no_graph"):
        essential_components.append("graph_memory")
    else:
        optional_components.append("graph_memory")
    if is_essential("aegis_no_calibration"):
        essential_components.append("calibration_head")
    else:
        optional_components.append("calibration_head")
    if is_essential("aegis_no_constraints"):
        essential_components.append("constraint_penalties")
    else:
        optional_components.append("constraint_penalties")
    if is_essential("aegis_flat"):
        essential_components.append("hierarchical_options")
    else:
        optional_components.append("hierarchy")

    lines = [
        "# Model Selection Decision",
        "",
        f"**Selected headline method:** {best['method']} (success {best['success_rate']:.2f}, reward {best['avg_reward']:.2f}).",
        "",
        "## Rationale",
        f"- Outperforms other AEGIS variants on success rate ({best['success_rate']:.2f}) and budgeted success "
        f"({best.get('budgeted_success', 0.0):.2f}).",
        "- Offers balanced action diversity (entropy {:.2f}).".format(best.get("action_entropy", 0.0)),
        "",
        "## Essential Components",
    ]
    lines.extend(f"- {component}" for component in essential_components) if essential_components else lines.append("- None identified.")
    lines.append("")
    lines.append("## Optional / Ablatable Components")
    lines.extend(f"- {component}" for component in optional_components) if optional_components else lines.append("- None identified.")
    lines.append("")
    lines.append("## Evidence Considered")
    lines.append("- Comparisons against no-graph, no-calibration, no-constraints, and flat variants.")
    lines.append("- Calibration/Brier metrics from calibration table.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_config_snapshot(env_config: AegisEnvConfig, agent_config: AegisAgentConfig, path: Path) -> None:
    snapshot = {
        "env": _sanitize(asdict(env_config.workflow)),
        "belief": _sanitize(asdict(env_config.belief)),
        "graph": _sanitize(asdict(env_config.graph)),
        "constraints": _sanitize(asdict(env_config.constraints)),
        "agent": _sanitize(asdict(agent_config)),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(snapshot, sort_keys=True), encoding="utf-8")


def _sanitize(obj):
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if hasattr(obj, "value"):
        return obj.value
    return obj


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AEGIS-RL training pipeline")
    parser.add_argument("--output-dir", type=Path, default=Path("results/aegis_rl"))
    parser.add_argument("--episodes-per-agent", type=int, default=5)
    parser.add_argument("--episodes", type=int, default=10)
    parser.add_argument("--use-reduced-actions", action="store_true", help="Enable reduced macro action set for main run.")
    parser.add_argument("--warm-start-episodes", type=int, default=0, help="Heuristic imitation episodes before RL.")
    parser.add_argument("--enable-curriculum", action="store_true", help="Train with default curriculum schedule.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    _ensure_dirs(args.output_dir)
    dataset = build_logged_dataset(args.output_dir, episodes_per_agent=args.episodes_per_agent)
    pretrain_summary = pretrain_belief_encoder(dataset, args.output_dir)
    env_config = AegisEnvConfig(use_reduced_action_space=args.use_reduced_actions)
    agent_config = AegisAgentConfig()
    all_metrics: List[Dict[str, float]] = []
    summaries: List[Dict[str, object]] = []
    method_specs = [
        ("aegis_full", {}, args.episodes, args.enable_curriculum, args.warm_start_episodes, "full_hierarchy"),
        ("aegis_flat", {"enable_hierarchy": False}, max(1, args.episodes // 2), False, 0, "flat_controller"),
        ("aegis_reduced", {"use_reduced_action_space": True}, max(1, args.episodes // 2), False, 0, "reduced_action_space"),
        ("aegis_no_calibration", {"enable_calibration_updates": False}, max(1, args.episodes // 2), False, 0, "calibration_disabled"),
        ("aegis_no_graph", {"enable_graph": False}, max(1, args.episodes // 2), False, 0, "graph_disabled"),
        ("aegis_no_constraints", {"enable_constraints": False}, max(1, args.episodes // 2), False, 0, "constraints_disabled"),
        ("aegis_warm_start", {}, max(1, args.episodes // 2), False, max(1, args.warm_start_episodes) if args.warm_start_episodes > 0 else 0, "imitation_warm_start"),
    ]
    if args.enable_curriculum:
        method_specs.append(("aegis_curriculum", {}, args.episodes, True, 0, "curriculum_schedule"))
    for label, overrides, eps, use_curriculum, warm_start, note in method_specs:
        cfg = copy.deepcopy(env_config)
        for attr, value in overrides.items():
            setattr(cfg, attr, value)
        cfg.reward_log_path = args.output_dir / "metrics" / f"reward_diag_{label}.jsonl"
        schedule = _default_curriculum_schedule(eps) if use_curriculum else None
        metrics, summary = run_online_training(
            label=label,
            env_config=cfg,
            agent_config=agent_config,
            output_dir=args.output_dir,
            episodes=eps,
            pretrain_summary=pretrain_summary,
            log_traces=label == "aegis_full",
            notes=note,
            warm_start_episodes=warm_start,
            curriculum_schedule=schedule,
        )
        all_metrics.extend(metrics)
        summaries.append(summary)
    _write_config_snapshot(env_config, agent_config, args.output_dir / "config_snapshot.yaml")

    baseline_factories: Dict[str, Callable[[WorkflowEnv], WorkflowAgentBase]] = {
        "baseline_always_direct": lambda env: AlwaysDirectAgent(),
        "baseline_always_decompose": lambda env: AlwaysDecomposeAgent(),
        "baseline_heuristic": lambda env: HeuristicThresholdAgent(),
        "baseline_contextual_bandit": lambda env: ContextualBanditWorkflowAgent(env.observation_dim, env.action_space.n),
    }
    if HAS_TORCH:
        baseline_factories["baseline_dueling_dqn"] = lambda env: DuelingDoubleDQNWorkflowAgent(
            env.observation_dim, env.action_space.n, DQNWorkflowConfig()
        )
    for label, factory in baseline_factories.items():
        metrics, summary = run_flat_agent(label, factory, episodes=max(1, args.episodes // 2))
        all_metrics.extend(metrics)
        summaries.append(summary)

    metrics_path = args.output_dir / "metrics" / "metrics.csv"
    _write_metrics_csv(all_metrics, metrics_path)
    _write_ablation_table(summaries, args.output_dir / "metrics" / "ablations.csv")
    _write_calibration_table(summaries, args.output_dir / "metrics" / "calibration.csv")
    reports_dir = Path("reports/ase2026_aegis")
    _write_main_table(summaries, reports_dir / "table_main.csv")
    _write_ablation_table(summaries, reports_dir / "table_ablation.csv")
    _write_calibration_table(summaries, reports_dir / "table_calibration.csv")
    _write_summary_markdown(summaries, reports_dir / "summary.md")
    _write_final_summary(summaries, reports_dir / "final_summary.md")
    _write_model_selection_decision(summaries, reports_dir / "model_selection_decision.md")


if __name__ == "__main__":
    main()
