from src.config import DataConfig, RLConfig
from src.data.preprocess import preprocess
from src.rl.env import EnvConfig, MultiAgentCompetitionEnv


def test_multiagent_step_returns_metrics(tmp_path):
    processed_dir = tmp_path / "processed"
    preprocess(output_dir=processed_dir, data_config=DataConfig(num_tasks=25, num_workers=10))
    env = MultiAgentCompetitionEnv(
        agent_names=["agent_a", "agent_b"],
        processed_dir=processed_dir,
        rl_config=RLConfig(max_tasks_per_step=3),
        env_config=EnvConfig(max_concurrent_tasks=1, horizon=4),
        seed=3,
    )
    obs, market_info = env.reset(seed=11)
    assert set(obs.keys()) == {"agent_a", "agent_b"}
    actions = {name: env.max_tasks for name in env.agent_states}
    obs, rewards, terminated, truncated, info = env.step(actions)
    assert set(rewards.keys()) == {"agent_a", "agent_b"}
    assert "market_starved" in info and "market_dropped" in info
    assert obs["agent_a"].shape == (env.observation_dim,)
