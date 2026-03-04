from src.config import DataConfig, SupervisedConfig
from src.data.preprocess import preprocess
from src.models.supervised import SupervisedExperiment


def test_supervised_experiment_runs(tmp_path):
    processed_dir = tmp_path / "processed"
    preprocess(output_dir=processed_dir, data_config=DataConfig(num_tasks=80, num_workers=50))

    cfg = SupervisedConfig(
        use_embeddings=False,
        max_tfidf_features=128,
        classification_targets={"starved": "classification"},
        regression_targets={"num_submissions": "regression"},
        test_size=0.25,
        val_size=0.2,
    )
    exp = SupervisedExperiment(processed_dir=processed_dir, config=cfg, feature_mode="text_metadata")
    metrics = exp.run()
    assert not metrics.empty
