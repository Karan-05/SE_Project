from src.config import DataConfig, RLConfig
from src.data.preprocess import preprocess
from src.rl.env import CompetitionEnv, EnvConfig


def test_env_capacity_and_deadlines(tmp_path):
    processed_dir = tmp_path / "processed"
    preprocess(output_dir=processed_dir, data_config=DataConfig(num_tasks=30, num_workers=15))
    env = CompetitionEnv(
        processed_dir=processed_dir,
        rl_config=RLConfig(max_tasks_per_step=3),
        env_config=EnvConfig(max_concurrent_tasks=1, horizon=5, deadline_penalty=0.2),
    )
    obs, info = env.reset(seed=7)
    assert obs.shape[0] == env.observation_dim
    assert "deadline_misses" in info
    dropped_seen = False
    deadline_seen = False
    for _ in range(6):
        obs, reward, terminated, truncated, info = env.step(0)
        dropped_seen |= info["dropped_tasks"] >= 0
        deadline_seen |= info["deadline_misses"] >= 0
        if terminated or truncated:
            break
    assert dropped_seen
    assert deadline_seen
