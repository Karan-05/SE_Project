"""Counterfactual branch-rollout dataset builder for override learning."""
from __future__ import annotations

import copy
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np

from .aegis_env import AegisEnvConfig, AegisWorkflowEnv
from .aegis_state import AegisMacroOption, ManagerObservation
from .teacher_guided import TeacherAdvisor


@dataclass
class CounterfactualDatasetConfig:
    """Configuration knobs for counterfactual branch collection."""

    episodes: int = 128
    max_alternatives: int = 3
    max_branch_steps: int = 32
    reduced_action_space: bool = True
    min_uncertainty: float = 0.0
    min_budget_pressure: float = 0.0
    seed: int = 2026
    seeds: Sequence[int] | None = None


def _macro_from_index(env: AegisWorkflowEnv, index: int) -> AegisMacroOption:
    index = int(np.clip(index, 0, len(env.macro_actions) - 1))
    return env.macro_actions[index]


def _resolve_macro(
    env: AegisWorkflowEnv,
    macro: AegisMacroOption,
    mask: np.ndarray,
) -> Tuple[AegisMacroOption, int]:
    idx = env.macro_indices.get(macro)
    if idx is None or mask[idx] <= 0:
        valid = np.where(mask > 0)[0]
        idx = int(valid[0]) if valid.size else 0
        macro = _macro_from_index(env, idx)
    return macro, idx


def _budget_pressure(env: AegisWorkflowEnv) -> float:
    budget = env.base_env.budget.as_dict()
    spent = float(budget.get("prompt_spent", 0.0) + budget.get("completion_spent", 0.0))
    total = float(env.config.workflow.prompt_budget + env.config.workflow.completion_budget)
    return float(np.clip(spent / max(1.0, total), 0.0, 1.0))


def _manager_features(obs: ManagerObservation) -> Dict[str, float]:
    belief = obs.belief_state
    return {
        "success_probability": float(belief.success_probability),
        "expected_cost": float(belief.expected_cost_to_success),
        "uncertainty": float(belief.uncertainty_score),
    }


def _select_alternatives(
    env: AegisWorkflowEnv,
    teacher_macro: AegisMacroOption,
    mask: np.ndarray,
    max_alternatives: int,
    rng: np.random.Generator,
) -> List[AegisMacroOption]:
    if max_alternatives <= 0:
        return []
    candidates: List[AegisMacroOption] = []
    for idx, macro in enumerate(env.macro_actions):
        if macro == teacher_macro:
            continue
        if mask[idx] <= 0:
            continue
        candidates.append(macro)
    if not candidates:
        return []
    rng.shuffle(candidates)
    return candidates[:max_alternatives]


def _rollout_branch(
    env: AegisWorkflowEnv,
    first_macro: AegisMacroOption,
    teacher: TeacherAdvisor,
    max_steps: int,
) -> Dict[str, object]:
    macro_idx = env.macro_indices.get(first_macro, 0)
    manager_obs, reward, done, truncated, info = env.step(int(macro_idx))
    total_reward = float(reward)
    branch_actions = [first_macro.value]
    steps = 1
    last_info = info
    while not (done or truncated) and steps < max_steps:
        mask = env.manager_action_mask()
        macro = teacher.propose(env.base_env.last_observation, env.last_info.get("action_mask"), env.last_info)
        macro, macro_idx = _resolve_macro(env, macro, mask)
        manager_obs, reward, done, truncated, info = env.step(int(macro_idx))
        total_reward += float(reward)
        branch_actions.append(macro.value)
        steps += 1
        last_info = info
    final_info = last_info or {}
    snapshot = final_info.get("constraint_snapshot", {})
    prompt_spent = float(snapshot.get("prompt_spent", 0.0))
    completion_spent = float(snapshot.get("completion_spent", 0.0))
    prompt_budget = float(env.config.workflow.prompt_budget)
    completion_budget = float(env.config.workflow.completion_budget)
    total_budget = max(1.0, prompt_budget + completion_budget)
    token_spent = prompt_spent + completion_spent
    cost_ratio = float(np.clip(token_spent / total_budget, 0.0, 1.0))
    success = bool(final_info.get("success", False))
    return {
        "reward": total_reward,
        "success": success,
        "cost_ratio": cost_ratio,
        "token_spent": token_spent,
        "steps": steps,
        "actions": branch_actions,
        "budgeted_success": float(success and token_spent <= total_budget),
        "constraint_penalty": float(final_info.get("constraint_penalty", 0.0)),
        "terminated": bool(done),
        "truncated": bool(truncated or steps >= max_steps),
    }


def _state_features(env: AegisWorkflowEnv, obs: ManagerObservation, mask: np.ndarray) -> Dict[str, object]:
    return {
        "observation": obs.to_vector().astype(float).tolist(),
        "manager_features": _manager_features(obs),
        "budget": env.base_env.budget.as_dict(),
        "graph_features": env.graph_memory.summary().as_dict(),
        "stage": env.base_env.state.stage.name,
        "action_mask": mask.astype(float).tolist(),
        "macro_actions": [macro.value for macro in env.macro_actions],
        "budget_pressure": _budget_pressure(env),
        "step_count": env.base_env.state.step_count,
    }


def _delta_labels(teacher: Dict[str, object], candidate: Dict[str, object]) -> Tuple[Dict[str, float], Dict[str, int]]:
    delta_reward = float(candidate["reward"]) - float(teacher["reward"])
    delta_cost = float(teacher["cost_ratio"]) - float(candidate["cost_ratio"])
    success_diff = int(candidate["success"]) - int(teacher["success"])
    beneficial = int(success_diff > 0 or (success_diff == 0 and delta_reward > 0.5) or (success_diff == 0 and abs(delta_reward) <= 0.5 and delta_cost > 0))
    regret = int(success_diff < 0 or (success_diff == 0 and delta_reward < -0.5) or (success_diff == 0 and abs(delta_reward) <= 0.5 and delta_cost < 0))
    delta = {
        "delta_reward": delta_reward,
        "delta_cost_ratio": delta_cost,
        "delta_success": float(success_diff),
    }
    labels = {
        "beneficial": beneficial,
        "regret": regret,
    }
    return delta, labels


def build_counterfactual_dataset(
    output_dir: Path,
    env_config: AegisEnvConfig | None = None,
    dataset_config: CounterfactualDatasetConfig | None = None,
) -> Dict[str, float]:
    config = dataset_config or CounterfactualDatasetConfig()
    env_cfg = env_config or AegisEnvConfig(use_reduced_action_space=config.reduced_action_space, enable_hierarchy=False)
    env = AegisWorkflowEnv(env_cfg)
    teacher = TeacherAdvisor(allowed=env.macro_actions)
    rng = np.random.default_rng(config.seed)
    output_dir.mkdir(parents=True, exist_ok=True)
    branch_rollouts = output_dir / "branch_rollouts.jsonl"
    override_csv = output_dir / "override_labels.csv"
    state_csv = output_dir / "state_summary.csv"
    summary_path = output_dir / "summary.json"
    total_states = 0
    total_eval = 0
    beneficial = 0
    regret = 0
    teacher_rewards: List[float] = []
    teacher_success: List[float] = []
    teacher_costs: List[float] = []
    state_rows: List[Dict[str, object]] = []
    seeds = list(config.seeds) if config.seeds else None
    branch_rollouts.unlink(missing_ok=True)
    with branch_rollouts.open("w", encoding="utf-8") as branch_file, override_csv.open("w", newline="", encoding="utf-8") as override_file:
        override_writer = csv.writer(override_file)
        override_writer.writerow(
            [
                "state_id",
                "episode",
                "seed",
                "step",
                "teacher_macro",
                "candidate_macro",
                "delta_reward",
                "delta_cost_ratio",
                "delta_success",
                "beneficial",
                "regret",
            ]
        )
        for episode in range(config.episodes):
            seed_value = None
            if seeds:
                seed_value = int(seeds[episode % len(seeds)])
            obs_vec, info = env.reset(seed=seed_value)
            done = False
            step = 0
            while not done:
                manager_obs = env.manager_snapshot()
                mask = env.manager_action_mask()
                teacher_macro = teacher.propose(env.base_env.last_observation, info.get("action_mask"), info)
                teacher_macro, teacher_idx = _resolve_macro(env, teacher_macro, mask)
                budget_pressure = _budget_pressure(env)
                if mask.sum() > 1 and (
                    manager_obs.belief_state.uncertainty_score >= config.min_uncertainty
                    or budget_pressure >= config.min_budget_pressure
                ):
                    alt_macros = _select_alternatives(env, teacher_macro, mask, config.max_alternatives, rng)
                else:
                    alt_macros = []
                if alt_macros:
                    state_id = f"ep{episode}_step{step}_seed{seed_value if seed_value is not None else episode}"
                    teacher_clone = copy.deepcopy(env)
                    teacher_outcome = _rollout_branch(teacher_clone, teacher_macro, teacher, config.max_branch_steps)
                    state_payload = _state_features(env, manager_obs, mask)
                    teacher_entry = {
                        "macro": teacher_macro.value,
                        "outcome": teacher_outcome,
                    }
                    teacher_rewards.append(float(teacher_outcome["reward"]))
                    teacher_success.append(float(teacher_outcome["success"]))
                    teacher_costs.append(float(teacher_outcome["cost_ratio"]))
                    state_result = {
                        "state_id": state_id,
                        "episode": episode,
                        "seed": seed_value if seed_value is not None else "",
                        "step": step,
                        "teacher_macro": teacher_macro.value,
                        "num_candidates": len(alt_macros),
                        "beneficial_candidates": 0,
                        "regret_candidates": 0,
                        "teacher_reward": teacher_outcome["reward"],
                        "teacher_success": teacher_outcome["success"],
                        "teacher_cost_ratio": teacher_outcome["cost_ratio"],
                    }
                    for alt_macro in alt_macros:
                        alt_clone = copy.deepcopy(env)
                        candidate_outcome = _rollout_branch(alt_clone, alt_macro, teacher, config.max_branch_steps)
                        delta, labels = _delta_labels(teacher_outcome, candidate_outcome)
                        record = {
                            "state_id": state_id,
                            "episode": episode,
                            "seed": seed_value,
                            "step": step,
                            "teacher": teacher_entry,
                            "candidate": {
                                "macro": alt_macro.value,
                                "outcome": candidate_outcome,
                            },
                            "delta": delta,
                            "labels": labels,
                            "state": state_payload,
                        }
                        branch_file.write(json.dumps(record) + "\n")
                        override_writer.writerow(
                            [
                                state_id,
                                episode,
                                seed_value,
                                step,
                                teacher_macro.value,
                                alt_macro.value,
                                delta["delta_reward"],
                                delta["delta_cost_ratio"],
                                delta["delta_success"],
                                labels["beneficial"],
                                labels["regret"],
                            ]
                        )
                        total_eval += 1
                        beneficial += labels["beneficial"]
                        regret += labels["regret"]
                        state_result["beneficial_candidates"] += labels["beneficial"]  # type: ignore[index]
                        state_result["regret_candidates"] += labels["regret"]  # type: ignore[index]
                    state_rows.append(state_result)
                    total_states += 1
                next_obs, reward, terminated, truncated, info = env.step(int(teacher_idx))
                done = terminated or truncated
                step += 1
    if state_rows:
        with state_csv.open("w", newline="", encoding="utf-8") as state_file:
            writer = csv.DictWriter(state_file, fieldnames=list(state_rows[0].keys()))
            writer.writeheader()
            writer.writerows(state_rows)
    summary = {
        "episodes": config.episodes,
        "states_evaluated": total_states,
        "candidate_evaluations": total_eval,
        "beneficial_fraction": beneficial / max(1, total_eval),
        "regret_fraction": regret / max(1, total_eval),
        "mean_teacher_reward": float(np.mean(teacher_rewards)) if teacher_rewards else 0.0,
        "mean_teacher_success": float(np.mean(teacher_success)) if teacher_success else 0.0,
        "mean_teacher_cost_ratio": float(np.mean(teacher_costs)) if teacher_costs else 0.0,
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


__all__ = [
    "CounterfactualDatasetConfig",
    "build_counterfactual_dataset",
]
