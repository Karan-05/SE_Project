from __future__ import annotations

from experiments.run_aegis_rl import run_online_training, _warm_start_agent
from src.rl.aegis_env import AegisEnvConfig, AegisWorkflowEnv
from src.rl.aegis_agents import AegisAgentConfig, AegisManagerAgent
from src.rl.workflow_env import WorkflowEnvConfig


def test_run_online_training_smoke(tmp_path) -> None:
    env_cfg = AegisEnvConfig(workflow=WorkflowEnvConfig(max_steps=5, max_retries=1))
    agent_config = AegisAgentConfig(buffer_size=256, min_buffer=1, batch_size=8)
    metrics, summary = run_online_training(
        label="smoke",
        env_config=env_cfg,
        agent_config=agent_config,
        output_dir=tmp_path,
        episodes=1,
        pretrain_summary=None,
        log_traces=False,
        notes="smoke_test",
    )
    assert len(metrics) == 1
    assert summary["method"] == "smoke"
    assert 0.0 <= summary["success_rate"] <= 1.0


def test_warm_start_agent_populates_buffer() -> None:
    env = AegisWorkflowEnv(AegisEnvConfig())
    agent = AegisManagerAgent(env.observation_space.shape[0], env.action_space.n)
    before = len(agent.buffer)
    _warm_start_agent(env, agent, episodes=1)
    assert len(agent.buffer) > before
