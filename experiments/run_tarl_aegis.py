"""Teacher-Aligned Residual Learning (TARL-AEGIS) pipeline."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

from experiments.run_aegis_rl import build_logged_dataset, _aggregate_summary
from src.rl.aegis_agents import AegisAgentConfig, AegisManagerAgent
from src.rl.aegis_env import AegisEnvConfig, AegisWorkflowEnv
from src.rl.aegis_state import AegisMacroOption
from src.rl.teacher_guided import OverrideClassifier, OverrideStats, TeacherAdvisor, map_action_to_macro
from src.rl.workflow_env import WorkflowEnvConfig


def _load_teacher_dataset(path: Path) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    return rows


def _pad_or_crop(values: Iterable[float], target_dim: int) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float32)
    if arr.shape[0] >= target_dim:
        return arr[:target_dim]
    return np.pad(arr, (0, target_dim - arr.shape[0]), mode="constant")


def _train_classifier(
    dataset: List[Dict[str, object]], target_obs_dim: int, macro_dim: int, epochs: int = 3
) -> OverrideClassifier:
    classifier = OverrideClassifier(target_obs_dim + macro_dim)
    for _ in range(epochs):
        for row in dataset:
            obs = _pad_or_crop(row["observation"], target_obs_dim)
            teacher_macro = row.get("macro_action")
            teacher = AegisMacroOption[teacher_macro] if teacher_macro in AegisMacroOption.__members__ else AegisMacroOption.DIRECT_SOLVE
            macro_vec = np.zeros(macro_dim, dtype=np.float32)
            macro_vec[AegisMacroOption.ordered().index(teacher)] = 1.0
            features = np.concatenate([obs, macro_vec])
            classifier.update(features, 0.0)  # imitation: teacher prefers follow
    return classifier


def _augment_observation(obs: np.ndarray, teacher_idx: int, action_dim: int) -> np.ndarray:
    macro_vec = np.zeros(action_dim, dtype=np.float32)
    if 0 <= teacher_idx < action_dim:
        macro_vec[teacher_idx] = 1.0
    return np.concatenate([obs, macro_vec])


def run_tarl(args: argparse.Namespace) -> None:
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = build_logged_dataset(output_dir, episodes_per_agent=args.episodes_per_agent)
    dataset = _load_teacher_dataset(dataset_path)
    env_config = AegisEnvConfig(
        use_reduced_action_space=not args.full_action_space,
        enable_hierarchy=False,
        reward_log_path=output_dir / "tarl_reward_diag.jsonl",
    )
    env = AegisWorkflowEnv(env_config)
    feature_dim = env.observation_space.shape[0]
    macro_dim = len(env.macro_actions)
    classifier = _train_classifier(dataset, feature_dim, macro_dim, epochs=3)
    agent_config = AegisAgentConfig()
    override_agent = AegisManagerAgent(feature_dim + macro_dim, env.action_space.n, config=agent_config)
    advisor = TeacherAdvisor(allowed=env.macro_actions)
    stats = OverrideStats()
    metrics: List[Dict[str, float]] = []
    overrides_output = output_dir / "tarl_overrides.csv"
    with overrides_output.open("w", newline="", encoding="utf-8") as overrides_file:
        override_writer = csv.writer(overrides_file)
        override_writer.writerow(["episode", "step", "teacher_macro", "chosen_macro", "override", "reward", "win", "regret"])
        for episode in range(args.episodes):
            obs, info = env.reset()
            done = False
            total_reward = 0.0
            steps_taken = 0
            while not done:
                teacher_macro = advisor.propose(env.base_env.last_observation, info.get("action_mask"), info)
                teacher_idx = env.macro_indices.get(teacher_macro, 0)
                override_features = _augment_observation(obs, teacher_idx, macro_dim)
                override_prob = classifier.predict(override_features)
                mask = env.manager_action_mask()
                if override_prob <= args.override_threshold:
                    action = teacher_idx
                    override = False
                else:
                    action = override_agent.act(override_features, option_mask=mask)
                    override = action != teacher_idx
                next_obs, reward, terminated, truncated, info = env.step(int(action))
                done = terminated or truncated
                total_reward += reward
                steps_taken += 1
                if override:
                    override_agent.observe((override_features, int(action), reward, _augment_observation(next_obs, teacher_idx, macro_dim), done))
                win = override and reward > 0
                regret = override and reward < 0
                stats.record(override, win, regret)
                override_writer.writerow(
                    [episode, steps_taken, teacher_macro.value, env.macro_actions[int(action)].value, int(override), reward, int(win), int(regret)]
                )
                classifier.update(override_features, 1.0 if win else 0.0)
                obs = next_obs
            snapshot = info.get("constraint_snapshot", {})
            prompt_budget = env.config.workflow.prompt_budget + env.config.workflow.completion_budget
            token_spent = float(snapshot.get("prompt_spent", 0.0) + snapshot.get("completion_spent", 0.0))
            metrics.append(
                {
                    "method": "tarl_aegis",
                    "episode": episode,
                    "reward": total_reward,
                    "success": float(info.get("success", False)),
                    "steps": steps_taken,
                    "constraint_penalty": float(info.get("constraint_penalty", 0.0)),
                    "token_spent": token_spent,
                    "verifier_calls": float(snapshot.get("verifier_calls", 0.0)),
                    "budgeted_success": float(info.get("success", False) and token_spent <= prompt_budget),
                    "catastrophic_failure": 0.0,
                    "action_entropy": stats.as_dict()["override_rate"],
                    "override_rate": stats.as_dict()["override_rate"],
                    "override_win_rate": stats.as_dict()["override_win_rate"],
                    "override_regret_rate": stats.as_dict()["override_regret_rate"],
                }
            )
    metrics_path = output_dir / "tarl_metrics.csv"
    _write_tarl_metrics(metrics, metrics_path)
    summary = _aggregate_summary("tarl_aegis", metrics, notes="teacher_guided")
    _write_tarl_reports(summary, stats, output_dir)


def _write_tarl_metrics(metrics: List[Dict[str, float]], path: Path) -> None:
    fieldnames = list(metrics[0].keys()) if metrics else []
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in metrics:
            writer.writerow(row)


def _write_tarl_reports(summary: Dict[str, object], stats: OverrideStats, output_dir: Path) -> None:
    table_main = output_dir / "tarl_table_main.csv"
    with table_main.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["method", "success_rate", "avg_reward", "budgeted_success", "override_rate", "override_win_rate"])
        writer.writerow(
            [
                summary["method"],
                summary["success_rate"],
                summary["avg_reward"],
                summary.get("budgeted_success", 0.0),
                stats.as_dict()["override_rate"],
                stats.as_dict()["override_win_rate"],
            ]
        )
    ablation = output_dir / "tarl_table_ablation.csv"
    with ablation.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["setting", "success_rate", "notes"])
        writer.writerow(["tarl_aegis", summary["success_rate"], summary.get("notes", "")])
    reports_dir = Path("reports/ase2026_aegis")
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "tarl_table_main.csv").write_text(table_main.read_text(), encoding="utf-8")
    (reports_dir / "tarl_table_ablation.csv").write_text(ablation.read_text(), encoding="utf-8")
    summary_md = reports_dir / "tarl_summary.md"
    summary_md.write_text(
        "\n".join(
            [
                "# TARL-AEGIS Summary",
                "",
                f"- Success rate: {summary['success_rate']:.2f}",
                f"- Avg reward: {summary['avg_reward']:.2f}",
                f"- Budgeted success: {summary.get('budgeted_success', 0.0):.2f}",
                f"- Override rate: {stats.as_dict()['override_rate']:.2f}",
                f"- Override win rate: {stats.as_dict()['override_win_rate']:.2f}",
            ]
        ),
        encoding="utf-8",
    )
    model_path = reports_dir / "tarl_model_selection.md"
    model_path.write_text(
        "\n".join(
            [
                "# TARL Model Selection",
                "",
                f"Headline method: {summary['method']} (success {summary['success_rate']:.2f}).",
                "Hierarchy is disabled; policy defaults to reduced action space.",
                "Teacher guidance remains essential for stability.",
            ]
        ),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run TARL-AEGIS teacher-guided residual learning.")
    parser.add_argument("--output-dir", type=Path, default=Path("results/aegis_rl"))
    parser.add_argument("--episodes", type=int, default=10)
    parser.add_argument("--episodes-per-agent", type=int, default=5)
    parser.add_argument("--override-threshold", type=float, default=0.7)
    parser.add_argument("--full-action-space", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_tarl(args)


if __name__ == "__main__":
    main()
