from src.config import DataConfig, RLConfig
from src.data.preprocess import preprocess
from src.rl.env import CompetitionEnv


def test_competition_env_step(tmp_path):
    processed_dir = tmp_path / "processed"
    preprocess(output_dir=processed_dir, data_config=DataConfig(num_tasks=50, num_workers=30))

    env = CompetitionEnv(processed_dir=processed_dir, rl_config=RLConfig(episode_length=5, num_episodes=2, max_tasks_per_step=3))
    obs, info = env.reset()
    assert obs.shape[0] == env.observation_dim
    assert "starved_tasks" in info
    action = env.action_space.sample()
    next_obs, reward, terminated, truncated, info = env.step(action)
    assert next_obs.shape == obs.shape
    assert isinstance(reward, float)
    assert isinstance(terminated, bool)
    assert isinstance(truncated, bool)
