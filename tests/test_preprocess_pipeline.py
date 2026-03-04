from pathlib import Path

from src.config import DataConfig
from src.data.preprocess import preprocess


def test_preprocess_materialises_all_tables(tmp_path):
    processed_dir = tmp_path / "processed"
    preprocess(output_dir=processed_dir, data_config=DataConfig(num_tasks=40, num_workers=30))

    for table in ["tasks", "workers", "interactions", "market"]:
        parquet_path = processed_dir / f"{table}.parquet"
        csv_path = processed_dir / f"{table}.csv"
        assert parquet_path.exists()
        assert csv_path.exists()
