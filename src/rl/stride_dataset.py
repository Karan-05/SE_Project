"""Teacher disagreement dataset utilities for STRIDE."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np

from .aegis_env import AegisEnvConfig, AegisWorkflowEnv
from .aegis_state import AegisMacroOption, ManagerObservation
from .teacher_guided import TeacherAdvisor


@dataclass
class StrideDatasetConfig:
    """Configuration for disagreement data mining."""

    episodes: int = 128
    expensive_threshold: float = 0.85
    stagnation_override: int = 3
    uncertainty_threshold: float = 0.6
    budget_pressure_threshold: float = 0.8
    reward_regret_threshold: float = -0.25
    reduced_action_space: bool = True


@dataclass
class StrideDatasetSummary:
    """Aggregate summary statistics for dataset generation."""

    total_steps: int
    override_positive: int
    override_negative: int
    failure_fraction: float
    expensive_fraction: float

    def as_dict(self) -> Dict[str, float]:
        return {
            "total_steps": float(self.total_steps),
            "override_positive": float(self.override_positive),
            "override_negative": float(self.override_negative),
            "failure_fraction": float(self.failure_fraction),
            "expensive_fraction": float(self.expensive_fraction),
        }


def _budget_ratio(budget: Dict[str, float], env: AegisWorkflowEnv) -> float:
    prompt = float(budget.get("prompt_spent", 0.0))
    completion = float(budget.get("completion_spent", 0.0))
    total_budget = float(env.config.workflow.prompt_budget + env.config.workflow.completion_budget)
    if total_budget <= 0:
        return 0.0
    return float(np.clip((prompt + completion) / total_budget, 0.0, 1.0))


def _manager_features(obs: ManagerObservation) -> Dict[str, float]:
    belief = obs.belief_state
    features = {
        "success_probability": float(belief.success_probability),
        "uncertainty": float(belief.uncertainty_score),
        "expected_cost": float(belief.expected_cost_to_success),
    }
    return features


def _reason_labels(
    option_features: Dict[str, float],
    episode_success: bool,
    cost_ratio: float,
    config: StrideDatasetConfig,
    reward: float,
) -> Tuple[int, List[str]]:
    reasons: List[str] = []
    local_reasons: List[str] = []
    if not episode_success:
        reasons.append("teacher_failed_episode")
    if cost_ratio >= config.expensive_threshold:
        reasons.append("teacher_expensive")
    stagnation = int(option_features.get("stagnation_steps", 0))
    progress = float(option_features.get("progress_delta", 0.0))
    uncertainty = float(option_features.get("uncertainty_before", 0.0))
    macro = option_features.get("macro_option", "")
    if stagnation >= config.stagnation_override and progress <= 0.0:
        local_reasons.append("stagnation")
        reasons.append("stagnation")
    if macro == AegisMacroOption.DIRECT_SOLVE.value and uncertainty >= config.uncertainty_threshold:
        local_reasons.append("high_uncertainty_direct_solve")
        reasons.append("high_uncertainty_direct_solve")
    if macro == AegisMacroOption.RESEARCH_CONTEXT.value and progress <= 0:
        local_reasons.append("no_graph_gain")
        reasons.append("no_graph_gain")
    if reward <= config.reward_regret_threshold:
        local_reasons.append("negative_reward")
        reasons.append("negative_reward")
    label = 1 if local_reasons or (not episode_success and cost_ratio >= config.expensive_threshold) else 0
    return label, reasons


def _recommend_alternative(
    teacher_macro: AegisMacroOption,
    option_features: Dict[str, float],
    allowed: Sequence[AegisMacroOption],
) -> AegisMacroOption:
    allowed_set = set(allowed)
    if teacher_macro not in allowed_set:
        teacher_macro = allowed[0]
    uncertainty = float(option_features.get("uncertainty_before", 0.0))
    stagnation = int(option_features.get("stagnation_steps", 0))
    progress = float(option_features.get("progress_delta", 0.0))
    verification_gain = float(option_features.get("verification_gain", 0.0))
    if teacher_macro == AegisMacroOption.DIRECT_SOLVE:
        if uncertainty >= 0.55 and AegisMacroOption.RESEARCH_CONTEXT in allowed_set:
            return AegisMacroOption.RESEARCH_CONTEXT
        if stagnation >= 2 and AegisMacroOption.DECOMPOSE_SHALLOW in allowed_set:
            return AegisMacroOption.DECOMPOSE_SHALLOW
    if teacher_macro == AegisMacroOption.RESEARCH_CONTEXT and progress <= 0 and AegisMacroOption.DECOMPOSE_SHALLOW in allowed_set:
        return AegisMacroOption.DECOMPOSE_SHALLOW
    if teacher_macro == AegisMacroOption.DECOMPOSE_SHALLOW and verification_gain <= 0 and AegisMacroOption.VERIFY in allowed_set:
        return AegisMacroOption.VERIFY
    if teacher_macro == AegisMacroOption.VERIFY and verification_gain <= 0 and AegisMacroOption.REPAIR in allowed_set:
        return AegisMacroOption.REPAIR
    if teacher_macro == AegisMacroOption.REPAIR and uncertainty >= 0.6 and AegisMacroOption.RESEARCH_CONTEXT in allowed_set:
        return AegisMacroOption.RESEARCH_CONTEXT
    return teacher_macro


def build_stride_teacher_dataset(
    output_dir: Path,
    env_config: AegisEnvConfig | None = None,
    dataset_config: StrideDatasetConfig | None = None,
    seeds: Sequence[int] | None = None,
) -> Tuple[Path, StrideDatasetSummary]:
    """Collects trajectories where the heuristic teacher struggles."""

    env = AegisWorkflowEnv(env_config or AegisEnvConfig(use_reduced_action_space=True, enable_hierarchy=False))
    teacher = TeacherAdvisor(allowed=env.macro_actions)
    config = dataset_config or StrideDatasetConfig(episodes=128, reduced_action_space=True)
    dataset_path = output_dir / "datasets" / "stride_teacher_disagreement.jsonl"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    total_steps = 0
    positive = 0
    negative = 0
    failures = 0
    expensive = 0
    with dataset_path.open("w", encoding="utf-8") as f:
        for episode in range(config.episodes):
            seed = None
            if seeds:
                seed = int(seeds[episode % len(seeds)])
            obs, info = env.reset(seed=seed)
            done = False
            buffer: List[Dict[str, object]] = []
            step_idx = 0
            while not done:
                mask = env.manager_action_mask()
                teacher_macro = teacher.propose(env.base_env.last_observation, info.get("action_mask"), info)
                teacher_idx = env.macro_indices.get(teacher_macro, 0)
                manager_obs = env.manager_snapshot()
                manager_feats = _manager_features(manager_obs)
                snapshot = env.base_env.budget.as_dict()
                max_steps = float(max(1, env.config.workflow.max_steps))
                record: Dict[str, object] = {
                    "episode": episode,
                    "seed": seed if seed is not None else episode,
                    "step": step_idx,
                    "observation": obs.tolist(),
                    "teacher_macro": teacher_macro.value,
                    "teacher_index": teacher_idx,
                    "manager_features": manager_feats,
                    "budget_pressure": _budget_ratio(snapshot, env),
                    "step_ratio": float(snapshot.get("steps_taken", 0.0)) / max_steps,
                }
                next_obs, reward, terminated, truncated, info = env.step(int(teacher_idx))
                done = terminated or truncated
                step_idx += 1
                record["reward"] = float(reward)
                record["constraint_penalty"] = float(info.get("constraint_penalty", 0.0))
                record["option_features"] = info.get("option_features", {})
                record["stage"] = info.get("stage", "UNKNOWN")
                buffer.append(record)
                obs = next_obs
            success = bool(info.get("success", False))
            if not success:
                failures += 1
            episode_cost = _budget_ratio(info.get("constraint_snapshot", {}), env)
            if episode_cost >= config.expensive_threshold:
                expensive += 1
            for record in buffer:
                label, reasons = _reason_labels(
                    record.get("option_features", {}),
                    success,
                    episode_cost,
                    config,
                    float(record.get("reward", 0.0)),
                )
                record["episode_success"] = success
                record["episode_cost_ratio"] = episode_cost
                record["override_label"] = label
                record["reasons"] = reasons
                alt = _recommend_alternative(
                    AegisMacroOption(record["teacher_macro"]),
                    record.get("option_features", {}),
                    env.macro_actions,
                )
                record["best_alternative"] = alt.value
                f.write(json.dumps(record) + "\n")
                total_steps += 1
                if label:
                    positive += 1
                else:
                    negative += 1
    summary = StrideDatasetSummary(
        total_steps=total_steps,
        override_positive=positive,
        override_negative=negative,
        failure_fraction=(failures / max(1, config.episodes)),
        expensive_fraction=(expensive / max(1, config.episodes)),
    )
    summary_path = output_dir / "datasets" / "stride_dataset_summary.json"
    summary_path.write_text(json.dumps(summary.as_dict(), indent=2), encoding="utf-8")
    return dataset_path, summary


def load_stride_dataset(path: Path) -> List[Dict[str, object]]:
    """Load disagreement samples for model training."""

    rows: List[Dict[str, object]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rows.append(json.loads(line))
    return rows
