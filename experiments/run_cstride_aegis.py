"""Counterfactual STRIDE (C-STRIDE) runner."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np

from src.rl.aegis_env import AegisEnvConfig, AegisWorkflowEnv
from src.rl.aegis_state import AegisMacroOption, ManagerObservation
from src.rl.teacher_guided import TeacherAdvisor
from src.rl.stride_agents import (
    StrideGate,
    StrideGateConfig,
    StrideResidualConfig,
    StrideResidualPolicy,
    build_stride_features,
)
from src.rl.stride_metrics import StrideMetricsLogger, aggregate_stride_summary
from src.rl.cstride_value import CStrideValueConfig, CStrideValueModel

VARIANT_CONFIGS: Dict[str, Dict[str, object]] = {
    "cstride_imitation_only": {"use_gate": False, "use_value_model": False, "use_residual": False},
    "cstride_gate_only": {"use_gate": True, "use_value_model": False, "use_residual": False},
    "cstride_gate_plus_value": {"use_gate": True, "use_value_model": True, "use_residual": False},
    "cstride_gate_plus_value_plus_residual": {"use_gate": True, "use_value_model": True, "use_residual": True},
    "cstride_cost_aware": {"use_gate": True, "use_value_model": True, "use_residual": False, "cost_weight": 6.0},
    "cstride_without_uncertainty": {"use_gate": True, "use_value_model": True, "use_residual": False, "include_uncertainty": False},
    "cstride_without_teacher_confidence": {"use_gate": True, "use_value_model": True, "use_residual": False, "include_confidence": False},
}


def _macro_from_teacher(
    teacher_macro: AegisMacroOption,
    manager_features: Dict[str, float],
    env: AegisWorkflowEnv,
) -> AegisMacroOption:
    uncertainty = float(manager_features.get("uncertainty", 0.0))
    success_prob = float(manager_features.get("success_probability", 0.5))
    macro = teacher_macro
    if teacher_macro == AegisMacroOption.DIRECT_SOLVE and uncertainty >= 0.55:
        macro = AegisMacroOption.RESEARCH_CONTEXT
    elif teacher_macro == AegisMacroOption.RESEARCH_CONTEXT and success_prob >= 0.65:
        macro = AegisMacroOption.DECOMPOSE_SHALLOW
    elif teacher_macro == AegisMacroOption.DECOMPOSE_SHALLOW and success_prob >= 0.7:
        macro = AegisMacroOption.VERIFY
    elif teacher_macro == AegisMacroOption.VERIFY and success_prob < 0.4:
        macro = AegisMacroOption.REPAIR
    return macro if macro in env.macro_actions else teacher_macro


def _manager_features(obs: ManagerObservation) -> Dict[str, float]:
    belief = obs.belief_state
    return {
        "success_probability": float(belief.success_probability),
        "expected_cost": float(belief.expected_cost_to_success),
        "uncertainty": float(belief.uncertainty_score),
    }


def _budget_pressure(env: AegisWorkflowEnv) -> float:
    budget = env.base_env.budget.as_dict()
    spent = float(budget.get("prompt_spent", 0.0) + budget.get("completion_spent", 0.0))
    total = float(env.config.workflow.prompt_budget + env.config.workflow.completion_budget)
    return float(np.clip(spent / max(1.0, total), 0.0, 1.0))


def _build_gate_features(
    sample: Dict[str, object],
    action_dim: int,
    include_confidence: bool,
    include_uncertainty: bool,
) -> np.ndarray:
    observation = np.asarray(sample["observation"], dtype=np.float32)
    teacher_idx = int(sample["teacher_index"])
    manager_features = sample.get("manager_features", {})
    extra = [
        float(sample.get("budget_pressure", 0.0)),
        float(sample.get("step_ratio", 0.0)),
    ]
    return build_stride_features(
        observation,
        teacher_idx,
        action_dim,
        manager_features,
        include_confidence=include_confidence,
        include_uncertainty=include_uncertainty,
        extra_features=extra,
    )


def _build_candidate_features(
    sample: Dict[str, object],
    candidate_index: int,
    action_dim: int,
    include_confidence: bool,
    include_uncertainty: bool,
) -> np.ndarray:
    base = _build_gate_features(sample, action_dim, include_confidence, include_uncertainty)
    candidate_vec = np.zeros(action_dim, dtype=np.float32)
    if 0 <= candidate_index < action_dim:
        candidate_vec[candidate_index] = 1.0
    return np.concatenate([base, candidate_vec])


def _load_counterfactual_samples(
    path: Path,
    env: AegisWorkflowEnv,
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    path = path.expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Counterfactual dataset not found: {path}")
    state_cache: Dict[str, Dict[str, object]] = {}
    candidate_rows: List[Dict[str, object]] = []
    max_steps = max(1, env.config.workflow.max_steps)
    macro_to_idx = {macro.value: idx for idx, macro in enumerate(env.macro_actions)}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            state = record["state"]
            state_id = record["state_id"]
            teacher_macro = record["teacher"]["macro"]
            teacher_idx = macro_to_idx.get(teacher_macro, 0)
            sample = state_cache.get(state_id)
            if sample is None:
                obs = np.asarray(state["observation"], dtype=np.float32)
                sample = {
                    "state_id": state_id,
                    "observation": obs,
                    "manager_features": state.get("manager_features", {}),
                    "budget_pressure": float(state.get("budget_pressure", 0.0)),
                    "step_ratio": float(state.get("step_count", 0) / max_steps),
                    "teacher_macro": teacher_macro,
                    "teacher_index": teacher_idx,
                    "episode_cost_ratio": float(record["teacher"]["outcome"].get("cost_ratio", 0.0)),
                    "episode_success": float(record["teacher"]["outcome"].get("success", False)),
                    "override_label": 0,
                    "best_alternative": teacher_macro,
                    "best_delta_reward": -1e9,
                }
                state_cache[state_id] = sample
            delta = record.get("delta", {})
            labels = record.get("labels", {})
            if labels.get("beneficial"):
                sample["override_label"] = 1
            delta_reward = float(delta.get("delta_reward", 0.0))
            if delta_reward > float(sample["best_delta_reward"]):
                sample["best_delta_reward"] = delta_reward
                sample["best_alternative"] = record["candidate"]["macro"]
            candidate_macro = record["candidate"]["macro"]
            candidate_idx = macro_to_idx.get(candidate_macro)
            if candidate_idx is None:
                continue
            candidate_rows.append(
                {
                    "observation": np.asarray(state["observation"], dtype=np.float32),
                    "manager_features": state.get("manager_features", {}),
                    "budget_pressure": float(state.get("budget_pressure", 0.0)),
                    "step_ratio": float(state.get("step_count", 0) / max_steps),
                    "teacher_index": teacher_idx,
                    "candidate_index": candidate_idx,
                    "delta_reward": delta_reward,
                    "delta_cost_ratio": float(delta.get("delta_cost_ratio", 0.0)),
                    "delta_success": float(delta.get("delta_success", 0.0)),
                    "beneficial": int(labels.get("beneficial", 0)),
                    "regret": int(labels.get("regret", 0)),
                }
            )
    return list(state_cache.values()), candidate_rows


def _train_gate(
    samples: List[Dict[str, object]],
    gate: StrideGate,
    action_dim: int,
    include_confidence: bool,
    include_uncertainty: bool,
    epochs: int,
) -> None:
    if not samples:
        return
    rng = np.random.default_rng(0)
    for _ in range(max(1, epochs)):
        rng.shuffle(samples)
        for sample in samples:
            features = _build_gate_features(sample, action_dim, include_confidence, include_uncertainty)
            label = float(sample.get("override_label", 0))
            weight = 1.0 + float(sample.get("episode_cost_ratio", 0.0))
            gate.update(features, label, weight=weight)


def _train_value_model(
    samples: List[Dict[str, object]],
    value_model: CStrideValueModel,
    action_dim: int,
    include_confidence: bool,
    include_uncertainty: bool,
    epochs: int,
    cost_weight: float,
) -> None:
    if not samples:
        return
    rng = np.random.default_rng(42)
    for _ in range(max(1, epochs)):
        rng.shuffle(samples)
        for sample in samples:
            features = _build_candidate_features(sample, int(sample["candidate_index"]), action_dim, include_confidence, include_uncertainty)
            target = float(sample["delta_reward"]) + cost_weight * float(sample["delta_cost_ratio"])
            weight = 1.0 + abs(float(sample["delta_reward"])) * 0.02
            value_model.update(features, target, weight=weight)


def _train_residual(
    samples: List[Dict[str, object]],
    residual: StrideResidualPolicy,
    action_dim: int,
    include_confidence: bool,
    include_uncertainty: bool,
    epochs: int,
    macro_to_idx: Dict[str, int],
) -> None:
    focus = [sample for sample in samples if int(sample.get("override_label", 0)) == 1]
    if not focus:
        focus = samples
    rng = np.random.default_rng(13)
    for _ in range(max(1, epochs)):
        rng.shuffle(focus)
        for sample in focus:
            features = _build_gate_features(sample, action_dim, include_confidence, include_uncertainty)
            macro = sample.get("best_alternative", sample.get("teacher_macro"))
            idx = macro_to_idx.get(str(macro), int(sample["teacher_index"]))
            residual.imitate(features, idx, weight=1.0 + max(0.0, float(sample.get("best_delta_reward", 0.0))))


def _env_sample(env: AegisWorkflowEnv, teacher_macro: AegisMacroOption) -> Dict[str, object]:
    obs = env.manager_snapshot()
    sample = {
        "observation": obs.to_vector(),
        "manager_features": _manager_features(obs),
        "budget_pressure": _budget_pressure(env),
        "step_ratio": float(env.base_env.state.step_count) / max(1, env.config.workflow.max_steps),
        "teacher_macro": teacher_macro.value,
        "teacher_index": env.macro_indices.get(teacher_macro, 0),
    }
    return sample


def _should_override(prob: float, threshold: float, budget_pressure: float) -> bool:
    adjusted = threshold
    if budget_pressure >= 0.85:
        adjusted -= 0.05
    elif budget_pressure <= 0.2:
        adjusted += 0.05
    adjusted = float(np.clip(adjusted, 0.05, 0.95))
    return prob >= adjusted


def _select_action_from_value(
    sample: Dict[str, object],
    mask: np.ndarray,
    action_dim: int,
    include_confidence: bool,
    include_uncertainty: bool,
    value_model: CStrideValueModel | None,
    residual_choice: int | None,
) -> Tuple[int, float]:
    valid = np.where(mask > 0)[0]
    if len(valid) == 0:
        return int(sample["teacher_index"]), float("-inf")
    best_idx = int(sample["teacher_index"])
    best_score = -1e9
    for idx in valid:
        score = 0.0
        if value_model is not None:
            features = _build_candidate_features(sample, int(idx), action_dim, include_confidence, include_uncertainty)
            score = value_model.predict(features)
        if residual_choice is not None and idx == residual_choice:
            score += 0.5
        if score > best_score:
            best_score = score
            best_idx = int(idx)
    return best_idx, float(best_score)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run counterfactual STRIDE variants.")
    parser.add_argument("--variant", type=str, default="cstride_gate_plus_value", choices=sorted(VARIANT_CONFIGS))
    parser.add_argument("--episodes", type=int, default=32, help="Episodes per seed.")
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1])
    parser.add_argument("--dataset", type=Path, default=Path("results/aegis_rl/counterfactual/branch_rollouts.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path("results/aegis_rl"))
    parser.add_argument("--override-threshold", type=float, default=0.6)
    parser.add_argument("--gate-epochs", type=int, default=8)
    parser.add_argument("--value-epochs", type=int, default=6)
    parser.add_argument("--residual-epochs", type=int, default=4)
    parser.add_argument("--notes", type=str, default="")
    parser.add_argument("--full-action-space", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    variant_cfg = VARIANT_CONFIGS[args.variant]
    env_config = AegisEnvConfig(
        use_reduced_action_space=not args.full_action_space,
        enable_hierarchy=False,
        reward_log_path=args.output_dir / f"{args.variant}_reward_diag.jsonl",
    )
    env = AegisWorkflowEnv(env_config)
    teacher = TeacherAdvisor(allowed=env.macro_actions)
    state_samples, candidate_samples = _load_counterfactual_samples(args.dataset, env)
    if not state_samples:
        raise RuntimeError("Counterfactual dataset is empty. Run scripts/build_counterfactual_dataset.py first.")
    macro_to_idx = {macro.value: idx for idx, macro in enumerate(env.macro_actions)}
    include_confidence = bool(variant_cfg.get("include_confidence", True))
    include_uncertainty = bool(variant_cfg.get("include_uncertainty", True))
    gate: StrideGate | None = None
    value_model: CStrideValueModel | None = None
    residual: StrideResidualPolicy | None = None
    action_dim = env.action_space.n
    if variant_cfg.get("use_gate"):
        gate_dim = len(_build_gate_features(state_samples[0], action_dim, include_confidence, include_uncertainty)) if state_samples else env.observation_space.shape[0]
        gate = StrideGate(gate_dim, config=StrideGateConfig(include_teacher_confidence=include_confidence, include_uncertainty_features=include_uncertainty))
        _train_gate(state_samples, gate, action_dim, include_confidence, include_uncertainty, args.gate_epochs)
    if variant_cfg.get("use_value_model"):
        if candidate_samples:
            candidate_dim = len(_build_candidate_features(candidate_samples[0], int(candidate_samples[0]["candidate_index"]), action_dim, include_confidence, include_uncertainty))
        else:
            base = _build_gate_features(state_samples[0], action_dim, include_confidence, include_uncertainty)
            candidate_dim = len(base) + action_dim
        value_model = CStrideValueModel(candidate_dim, CStrideValueConfig())
        _train_value_model(
            candidate_samples,
            value_model,
            action_dim,
            include_confidence,
            include_uncertainty,
            args.value_epochs,
            float(variant_cfg.get("cost_weight", 0.0)),
        )
    if variant_cfg.get("use_residual"):
        residual_dim = len(_build_gate_features(state_samples[0], action_dim, include_confidence, include_uncertainty)) if state_samples else env.observation_space.shape[0]
        residual = StrideResidualPolicy(residual_dim, action_dim, StrideResidualConfig())
        _train_residual(state_samples, residual, action_dim, include_confidence, include_uncertainty, args.residual_epochs, macro_to_idx)
    logger_root = args.output_dir / f"cstride_{args.variant}"
    metrics_logger = StrideMetricsLogger(root=logger_root)
    episode_rows: List[Dict[str, float]] = []
    for seed in args.seeds:
        for episode in range(args.episodes):
            obs, info = env.reset(seed=seed)
            done = False
            episode_reward = 0.0
            steps = 0
            mask = env.manager_action_mask()
            action_hist = np.zeros(env.action_space.n, dtype=np.int32)
            overrides = wins = regrets = beneficial = harmful = 0
            while not done:
                teacher_macro = teacher.propose(env.base_env.last_observation, info.get("action_mask"), info)
                mask = env.manager_action_mask()
                sample = _env_sample(env, teacher_macro)
                gate_features = None
                override = False
                if gate is not None:
                    gate_features = _build_gate_features(sample, action_dim, include_confidence, include_uncertainty)
                    prob = gate.predict(gate_features)
                    override = _should_override(prob, args.override_threshold, float(sample.get("budget_pressure", 0.0)))
                action_idx = sample["teacher_index"]
                reason = args.variant
                residual_choice = None
                if residual is not None and gate_features is not None:
                    residual_choice = residual.act(gate_features, mask=mask, greedy=True)
                if variant_cfg.get("use_value_model") and override:
                    candidate_idx, candidate_score = _select_action_from_value(
                        sample,
                        mask,
                        action_dim,
                        include_confidence,
                        include_uncertainty,
                        value_model,
                        residual_choice if variant_cfg.get("use_residual") else None,
                    )
                    if candidate_idx != sample["teacher_index"] and candidate_score > 0.0:
                        action_idx = candidate_idx
                    else:
                        override = False
                        action_idx = sample["teacher_index"]
                elif variant_cfg.get("use_gate") and not variant_cfg.get("use_value_model") and override:
                    candidate_macro = _macro_from_teacher(
                        teacher_macro,
                        sample.get("manager_features", {}),
                        env,
                    )
                    action_idx = env.macro_indices.get(candidate_macro, sample["teacher_index"])
                    override = action_idx != sample["teacher_index"]
                else:
                    override = False
                    action_idx = sample["teacher_index"]
                next_obs, reward, terminated, truncated, info = env.step(int(action_idx))
                done = terminated or truncated
                episode_reward += float(reward)
                steps += 1
                action_hist[int(action_idx)] += 1
                if override:
                    overrides += 1
                    win = reward > 0.0
                    regret_flag = reward < -0.5
                    wins += int(win)
                    regrets += int(regret_flag)
                    beneficial += int(win)
                    harmful += int(regret_flag)
                    metrics_logger.record_override(
                        args.variant,
                        seed,
                        episode,
                        steps,
                        teacher_macro.value,
                        env.macro_actions[int(action_idx)].value,
                        float(reward),
                        True,
                        win,
                        regret_flag,
                        reason,
                    )
                obs = next_obs
            snapshot = info.get("constraint_snapshot", {})
            prompt_budget = float(env.config.workflow.prompt_budget + env.config.workflow.completion_budget)
            spent = float(snapshot.get("prompt_spent", 0.0) + snapshot.get("completion_spent", 0.0))
            cost_ratio = float(np.clip(spent / max(1.0, prompt_budget), 0.0, 1.0))
            success = bool(info.get("success", False))
            budgeted_success = float(success and spent <= prompt_budget)
            total_steps = max(1, steps)
            override_stats = {
                "override_rate": overrides / total_steps,
                "override_win_rate": wins / overrides if overrides else 0.0,
                "override_regret_rate": regrets / overrides if overrides else 0.0,
                "harmful_fraction": harmful / overrides if overrides else 0.0,
                "beneficial_fraction": beneficial / overrides if overrides else 0.0,
            }
            entropy = 0.0
            counts = action_hist[action_hist > 0]
            if counts.size:
                probs = counts / counts.sum()
                entropy = float(-np.sum(probs * np.log(probs + 1e-8)))
            metrics_logger.record_episode(
                args.variant,
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
            episode_rows.append(metrics_logger.metrics[-1])
    metrics_logger.save()
    summary = aggregate_stride_summary(episode_rows)
    summary["method"] = args.variant
    summary_path = logger_root / f"{args.variant}_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
