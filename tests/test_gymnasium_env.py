from src.config import DataConfig, RLConfig
from src.data.preprocess import preprocess
from src.rl.env import CompetitionEnv


def test_gymnasium_reset_and_step(tmp_path):
    processed_dir = tmp_path / "processed"
    preprocess(output_dir=processed_dir, data_config=DataConfig(num_tasks=30, num_workers=20))

    env = CompetitionEnv(processed_dir=processed_dir, rl_config=RLConfig(episode_length=4, max_tasks_per_step=3))
    obs, info = env.reset(seed=99)
    assert obs.shape[0] == env.observation_dim
    assert info["starved_tasks"] == 0

    done = False
    steps = 0
    while not done:
        action = env.action_space.sample()
        obs, reward, terminated, truncated, step_info = env.step(action)
        done = bool(terminated or truncated)
        steps += 1
        assert obs.shape == (env.observation_dim,)
        assert isinstance(reward, float)
        assert "starved_tasks" in step_info
    assert steps <= env.rl_config.episode_length
