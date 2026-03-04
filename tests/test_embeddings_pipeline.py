from src.config import DataConfig, EmbeddingConfig
from src.data.preprocess import preprocess
from src.models.self_supervised import EmbeddingPipeline


def test_embedding_pipeline(tmp_path):
    processed_dir = tmp_path / "processed"
    preprocess(output_dir=processed_dir, data_config=DataConfig(num_tasks=60, num_workers=40))

    pipeline = EmbeddingPipeline(
        processed_dir=processed_dir,
        embedding_dir=tmp_path / "embeddings",
        embedding_config=EmbeddingConfig(dimensions=8, walk_length=10, num_walks=5),
    )
    pipeline.train()
    assert (tmp_path / "embeddings" / "tasks.npy").exists()
    assert (tmp_path / "embeddings" / "workers.npy").exists()
