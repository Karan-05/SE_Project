from __future__ import annotations

from src.rl.workflow_env import (
    WorkflowAction,
    WorkflowEnv,
    WorkflowEnvConfig,
    WorkflowStage,
)


def test_action_mask_respects_disabled_actions() -> None:
    cfg = WorkflowEnvConfig(disabled_actions=(WorkflowAction.ASK_VERIFIER,))
    env = WorkflowEnv(config=cfg)
    env.reset(seed=0)
    mask = env.get_action_mask()
    assert mask[int(WorkflowAction.ASK_VERIFIER)] == 0


def test_reward_improves_when_tests_progress() -> None:
    cfg = WorkflowEnvConfig(enable_action_masking=False, noise_scale=0.0)
    env = WorkflowEnv(config=cfg)
    env.reset(seed=1)
    env.state.compile_status = 0.5
    env.state.test_pass_ratio = 0.2
    _, reward_progress, *_ = env.step(int(WorkflowAction.RUN_TESTS))
    prev_reward = reward_progress
    env.state.compile_status = 1.0
    env.state.test_pass_ratio = 1.0
    _, reward_no_progress, *_ = env.step(int(WorkflowAction.RUN_TESTS))
    assert prev_reward > reward_no_progress


def test_submit_transitions_to_done() -> None:
    cfg = WorkflowEnvConfig(enable_action_masking=False, noise_scale=0.0)
    env = WorkflowEnv(config=cfg)
    env.reset(seed=2)
    env.state.compile_status = 1.0
    env.state.test_pass_ratio = 0.95
    env.state.verifier_confidence = 0.95
    env.state.retrieval_insufficiency = 0.0
    env.state.stage = WorkflowStage.FINAL_REVIEW
    _, _, done, truncated, info = env.step(int(WorkflowAction.SUBMIT))
    assert done is True
    assert truncated is False
    assert env.state.stage == WorkflowStage.DONE
    assert env.state.success is True
    assert info["success"] is True
