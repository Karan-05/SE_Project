"""Selective Teacher-Residual Imitation with Disagreement-aware Escalation (STRIDE)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

import numpy as np

from src.rl.aegis_env import AegisEnvConfig, AegisWorkflowEnv
from src.rl.aegis_state import AegisMacroOption
from src.rl.teacher_guided import TeacherAdvisor
from src.rl.stride_agents import (
    StrideGate,
    StrideGateConfig,
    StrideResidualPolicy,
    StrideResidualConfig,
    build_stride_features,
)
from src.rl.stride_dataset import StrideDatasetConfig, build_stride_teacher_dataset, load_stride_dataset
from src.rl.stride_metrics import StrideMetricsLogger, aggregate_stride_summary, summarize_variants, write_json_summary

VARIANTS = {
    "stride_imitation_only",
    "stride_gate_only",
    "stride_gate_plus_residual",
    "stride_gate_plus_residual_plus_curriculum",
    "stride_cost_aware",
    "stride_without_teacher_confidence",
    "stride_without_uncertainty_features",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run STRIDE experiments.")
    parser.add_argument("--variant", type=str, default="stride_gate_plus_residual", choices=sorted(VARIANTS))
    parser.add_argument("--episodes", type=int, default=32, help="Episodes per seed.")
    parser.add_argument("--dataset-episodes", type=int, default=128, help="Episodes for disagreement dataset.")
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1])
    parser.add_argument("--output-dir", type=Path, default=Path("results/aegis_rl"))
    parser.add_argument("--override-threshold", type=float, default=0.6)
    parser.add_argument("--gating-epochs", type=int, default=6)
    parser.add_argument("--residual-epochs", type=int, default=4)
    parser.add_argument("--curriculum-threshold", type=float, default=0.6)
    parser.add_argument("--full-action-space", action="store_true", help="Allow full macro action space.")
    parser.add_argument("--rebuild-dataset", action="store_true")
    parser.add_argument("--notes", type=str, default="")
    return parser.parse_args()


def _budget_ratio(budget: Dict[str, float], env: AegisWorkflowEnv) -> float:
    prompt = float(budget.get("prompt_spent", 0.0))
    completion = float(budget.get("completion_spent", 0.0))
    total = float(env.config.workflow.prompt_budget + env.config.workflow.completion_budget)
    if total <= 0:
        return 0.0
    return float(np.clip((prompt + completion) / total, 0.0, 1.0))


def _extra_features_from_sample(sample: Dict[str, object]) -> List[float]:
    return [
        float(sample.get("budget_pressure", 0.0)),
        float(sample.get("step_ratio", 0.0)),
    ]


def _extra_features_from_env(env: AegisWorkflowEnv) -> List[float]:
    budget = env.base_env.budget.as_dict()
    return [
        _budget_ratio(budget, env),
        float(budget.get("steps_taken", 0.0)) / max(1.0, float(env.config.workflow.max_steps)),
    ]


def _load_dataset(
    args: argparse.Namespace,
    env_config: AegisEnvConfig,
    output_dir: Path,
) -> List[Dict[str, object]]:
    dataset_path = output_dir / "datasets" / "stride_teacher_disagreement.jsonl"
    summary_path = output_dir / "datasets" / "stride_dataset_summary.json"
    if args.rebuild_dataset or not dataset_path.exists():
        dataset_config = StrideDatasetConfig(
            episodes=args.dataset_episodes,
            reduced_action_space=not args.full_action_space,
        )
        dataset_path, summary = build_stride_teacher_dataset(output_dir, env_config, dataset_config=dataset_config)
        summary_path.write_text(json.dumps(summary.as_dict(), indent=2), encoding="utf-8")
    if not summary_path.exists():
        summary_path.write_text(json.dumps({}, indent=2), encoding="utf-8")
    return load_stride_dataset(dataset_path)


def _sample_feature_vector(
    sample: Dict[str, object],
    action_dim: int,
    include_confidence: bool,
    include_uncertainty: bool,
) -> np.ndarray:
    observation = np.asarray(sample["observation"], dtype=np.float32)
    manager_features = sample.get("manager_features", {})
    teacher_idx = int(sample.get("teacher_index", 0))
    extra = _extra_features_from_sample(sample)
    return build_stride_features(
        observation,
        teacher_idx,
        action_dim,
        manager_features,
        include_confidence=include_confidence,
        include_uncertainty=include_uncertainty,
        extra_features=extra,
    )


def _filter_samples_curriculum(samples: Iterable[Dict[str, object]], threshold: float) -> List[Dict[str, object]]:
    selected = []
    for sample in samples:
        manager = sample.get("manager_features", {})
        if float(manager.get("uncertainty", 0.0)) >= threshold:
            selected.append(sample)
    return selected


def _train_gate(
    samples: List[Dict[str, object]],
    gate: StrideGate | None,
    action_dim: int,
    include_confidence: bool,
    include_uncertainty: bool,
    epochs: int,
) -> None:
    if gate is None:
        return
    rng = np.random.default_rng(0)
    for _ in range(epochs):
        rng.shuffle(samples)
        for sample in samples:
            features = _sample_feature_vector(sample, action_dim, include_confidence, include_uncertainty)
            label = float(sample.get("override_label", 0))
            weight = 1.0 + float(sample.get("episode_cost_ratio", 0.0))
            if sample.get("episode_success"):
                weight *= 0.75
            gate.update(features, label, weight=weight)


def _train_gate_curriculum(
    all_samples: List[Dict[str, object]],
    gate: StrideGate | None,
    action_dim: int,
    include_confidence: bool,
    include_uncertainty: bool,
    epochs: int,
    curriculum_threshold: float,
) -> None:
    if gate is None:
        return
    easy = _filter_samples_curriculum(all_samples, threshold=curriculum_threshold)
    hard = [sample for sample in all_samples if sample not in easy]
    _train_gate(easy, gate, action_dim, include_confidence, include_uncertainty, max(1, epochs // 2))
    _train_gate(hard or easy, gate, action_dim, include_confidence, include_uncertainty, epochs - max(1, epochs // 2))


def _train_residual(
    samples: List[Dict[str, object]],
    residual: StrideResidualPolicy | None,
    env_actions: Dict[str, int],
    action_dim: int,
    include_confidence: bool,
    include_uncertainty: bool,
    epochs: int,
) -> None:
    if residual is None:
        return
    rng = np.random.default_rng(42)
    focus = [s for s in samples if int(s.get("override_label", 0)) == 1]
    if not focus:
        focus = samples
    for _ in range(max(1, epochs)):
        rng.shuffle(focus)
        for sample in focus:
            features = _sample_feature_vector(sample, action_dim, include_confidence, include_uncertainty)
            alt_macro = sample.get("best_alternative", sample.get("teacher_macro"))
            action = env_actions.get(alt_macro, env_actions[next(iter(env_actions))])
            residual.imitate(features, action, weight=1.0 + float(sample.get("episode_cost_ratio", 0.0)))


def _macro_from_teacher(teacher_macro: AegisMacroOption, manager_features: Dict[str, float], env: AegisWorkflowEnv) -> AegisMacroOption:
    uncertainty = float(manager_features.get("uncertainty", 0.0))
    success_prob = float(manager_features.get("success_probability", 0.5))
    if teacher_macro == AegisMacroOption.DIRECT_SOLVE and uncertainty >= 0.55:
        return AegisMacroOption.RESEARCH_CONTEXT if AegisMacroOption.RESEARCH_CONTEXT in env.macro_actions else teacher_macro
    if teacher_macro == AegisMacroOption.RESEARCH_CONTEXT and success_prob >= 0.65:
        return AegisMacroOption.DECOMPOSE_SHALLOW if AegisMacroOption.DECOMPOSE_SHALLOW in env.macro_actions else teacher_macro
    if teacher_macro == AegisMacroOption.DECOMPOSE_SHALLOW and success_prob >= 0.7:
        return AegisMacroOption.VERIFY if AegisMacroOption.VERIFY in env.macro_actions else teacher_macro
    if teacher_macro == AegisMacroOption.VERIFY and success_prob < 0.4:
        return AegisMacroOption.REPAIR if AegisMacroOption.REPAIR in env.macro_actions else teacher_macro
    return teacher_macro


def _should_override(
    variant: str,
    gate: StrideGate | None,
    features: np.ndarray,
    threshold: float,
    budget_pressure: float,
) -> bool:
    if variant == "stride_imitation_only" or gate is None:
        return False
    prob = gate.predict(features)
    if variant == "stride_cost_aware":
        dynamic = threshold - 0.15 * (budget_pressure - 0.5)
        dynamic = float(np.clip(dynamic, 0.2, 0.85))
        return prob >= dynamic
    return prob >= threshold


def _action_entropy(hist: np.ndarray) -> float:
    counts = hist / max(1.0, np.sum(hist))
    mask = counts > 0
    if not np.any(mask):
        return 0.0
    return float(-np.sum(counts[mask] * np.log(np.clip(counts[mask], 1e-8, 1.0))))


def run_stride(args: argparse.Namespace) -> None:
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    env_config = AegisEnvConfig(
        use_reduced_action_space=not args.full_action_space,
        enable_hierarchy=False,
        reward_log_path=output_dir / f"{args.variant}_reward_diag.jsonl",
    )
    dataset = _load_dataset(args, env_config, output_dir)
    tuning_env = AegisWorkflowEnv(env_config)
    action_dim = tuning_env.action_space.n
    include_confidence = args.variant != "stride_without_teacher_confidence"
    include_uncertainty = args.variant != "stride_without_uncertainty_features"
    probe = _sample_feature_vector(dataset[0], action_dim, include_confidence, include_uncertainty) if dataset else np.zeros(tuning_env.observation_space.shape[0] + action_dim)
    gate_dim = probe.shape[0]
    gate = None if args.variant == "stride_imitation_only" else StrideGate(feature_dim=gate_dim, config=StrideGateConfig())
    residual = None
    if args.variant in {"stride_gate_plus_residual", "stride_gate_plus_residual_plus_curriculum", "stride_cost_aware"}:
        residual = StrideResidualPolicy(feature_dim=gate_dim, action_dim=action_dim, config=StrideResidualConfig())
    env_actions = {macro.value: idx for macro, idx in tuning_env.macro_indices.items()}
    if args.variant == "stride_gate_plus_residual_plus_curriculum":
        _train_gate_curriculum(dataset, gate, action_dim, include_confidence, include_uncertainty, args.gating_epochs, args.curriculum_threshold)
    else:
        _train_gate(dataset, gate, action_dim, include_confidence, include_uncertainty, args.gating_epochs)
    _train_residual(dataset, residual, env_actions, action_dim, include_confidence, include_uncertainty, args.residual_epochs)
    teacher = TeacherAdvisor(allowed=tuning_env.macro_actions)
    metrics_logger = StrideMetricsLogger(output_dir)
    method_key = args.variant
    rng = np.random.default_rng(1234)
    for seed in args.seeds:
        env = AegisWorkflowEnv(env_config)
        for episode in range(args.episodes):
            run_seed = int(rng.integers(0, 10_000) + seed * 997 + episode)
            obs, info = env.reset(seed=run_seed)
            done = False
            overrides = 0
            wins = 0
            regrets = 0
            harmful = 0
            beneficial = 0
            steps = 0
            action_hist = np.zeros(env.action_space.n, dtype=np.float32)
            episode_reward = 0.0
            while not done:
                mask = env.manager_action_mask()
                teacher_macro = teacher.propose(env.base_env.last_observation, info.get("action_mask"), info)
                teacher_idx = env.macro_indices.get(teacher_macro, 0)
                manager = env.manager_snapshot().belief_state
                manager_features = {
                    "success_probability": float(manager.success_probability),
                    "uncertainty": float(manager.uncertainty_score),
                    "expected_cost": float(manager.expected_cost_to_success),
                }
                extra = _extra_features_from_env(env)
                features = build_stride_features(
                    np.asarray(obs, dtype=np.float32),
                    teacher_idx,
                    env.action_space.n,
                    manager_features,
                    include_confidence=include_confidence,
                    include_uncertainty=include_uncertainty,
                    extra_features=extra,
                )
                budget_pressure = extra[0]
                override = _should_override(args.variant, gate, features, args.override_threshold, budget_pressure)
                reason = args.variant
                action_idx = teacher_idx
                if args.variant == "stride_gate_only":
                    candidate_macro = _macro_from_teacher(teacher_macro, manager_features, env)
                    candidate_idx = env.macro_indices.get(candidate_macro, teacher_idx)
                    if override and candidate_idx != teacher_idx:
                        action_idx = candidate_idx
                    else:
                        override = False
                elif override and residual is not None:
                    action_idx = residual.act(features, mask=mask, greedy=False)
                else:
                    action_idx = teacher_idx
                    if args.variant != "stride_gate_only":
                        override = False
                next_obs, reward, terminated, truncated, info = env.step(int(action_idx))
                done = terminated or truncated
                obs = next_obs
                action_hist[action_idx] += 1
                steps += 1
                episode_reward += float(reward)
                if override:
                    overrides += 1
                    win = reward > 0.0
                    regret = reward < -0.5
                    wins += int(win)
                    regrets += int(regret)
                    beneficial += int(win)
                    harmful += int(regret)
                    metrics_logger.record_override(
                        method_key,
                        seed,
                        episode,
                        steps,
                        teacher_macro.value,
                        env.macro_actions[action_idx].value,
                        reward,
                        True,
                        win,
                        regret,
                        reason,
                    )
            snapshot = info.get("constraint_snapshot", {})
            cost_ratio = _budget_ratio(snapshot, env)
            success = bool(info.get("success", False))
            prompt_budget = env.config.workflow.prompt_budget + env.config.workflow.completion_budget
            spent = snapshot.get("prompt_spent", 0.0) + snapshot.get("completion_spent", 0.0)
            budgeted_success = float(success and spent <= prompt_budget)
            total_steps = max(1, steps)
            override_stats = {
                "override_rate": overrides / total_steps,
                "override_win_rate": wins / overrides if overrides else 0.0,
                "override_regret_rate": regrets / overrides if overrides else 0.0,
                "harmful_fraction": harmful / overrides if overrides else 0.0,
                "beneficial_fraction": beneficial / overrides if overrides else 0.0,
            }
            entropy = _action_entropy(action_hist)
            metrics_logger.record_episode(
                method_key,
                seed,
                episode,
                reward=episode_reward,
                success=success,
                steps=steps,
                cost_ratio=cost_ratio,
                override_stats=override_stats,
                budgeted_success=budgeted_success,
                action_entropy=entropy,
            )
    metrics_logger.save()
    metrics = metrics_logger.metrics
    summary = aggregate_stride_summary(metrics)
    summary["method"] = method_key
    summary["notes"] = args.notes
    (output_dir / f"{method_key}_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    summary_table = output_dir / "stride_variant_summary.csv"
    summarize_variants({method_key: metrics}, summary_table)
    write_json_summary(metrics, output_dir / "stride_summary.json")


if __name__ == "__main__":
    run_stride(_parse_args())
