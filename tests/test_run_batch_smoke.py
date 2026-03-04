from pathlib import Path

import pandas as pd

from src.decomposition.runners.run_batch import run_benchmark


def test_run_benchmark_outputs(tmp_path, monkeypatch):
    df = run_benchmark()
    assert not df.empty
    assert {"strategy", "task_id", "pass_rate", "task_type", "pitfalls", "split"}.issubset(df.columns)
    csv_path = Path("reports/decomposition/strategy_comparison.csv")
    assert csv_path.exists()
    out_df = pd.read_csv(csv_path)
    assert not out_df.empty
    assert {"task_difficulty", "tag_count"}.issubset(out_df.columns)
