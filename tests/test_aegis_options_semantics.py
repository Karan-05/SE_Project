from __future__ import annotations

from src.rl.aegis_options import DecomposeShallowOption, ResearchContextOption, VerifyOption
from src.rl.workflow_env import WorkflowEnv, WorkflowEnvConfig


def test_research_option_increases_retrieval() -> None:
    env = WorkflowEnv(WorkflowEnvConfig(seed=42, noise_scale=0.0))
    _, info = env.reset()
    base = env.state.retrieval_coverage
    option = ResearchContextOption()
    option.run(env, info)
    assert env.state.retrieval_coverage >= base


def test_decompose_option_expands_frontier() -> None:
    env = WorkflowEnv(WorkflowEnvConfig(seed=7, noise_scale=0.0))
    _, info = env.reset()
    base = env.state.num_subtasks
    option = DecomposeShallowOption()
    option.run(env, info)
    assert env.state.num_subtasks > base


def test_verify_option_boosts_confidence() -> None:
    env = WorkflowEnv(WorkflowEnvConfig(seed=99, noise_scale=0.0))
    _, info = env.reset()
    base = env.state.verifier_confidence
    option = VerifyOption()
    option.run(env, info)
    assert env.state.verifier_confidence >= base
