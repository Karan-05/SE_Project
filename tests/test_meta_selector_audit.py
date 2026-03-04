import json
from pathlib import Path

import pandas as pd

from src.decomposition.runners.run_meta_selector import (
    build_dataset,
    train_meta_selector,
    _run_loo_type,
    _write_audit,
)


def test_meta_selector_audit_and_loo(tmp_path):
    tasks = [
        {
            "id": "t1",
            "problem_statement": "Example",
            "statement": "Example",
            "type": "array",
            "difficulty": "S",
            "pitfalls": ["off_by_one"],
        },
        {
            "id": "t2",
            "problem_statement": "Example",
            "statement": "Example",
            "type": "string",
            "difficulty": "M",
            "pitfalls": ["unicode"],
        },
    ]
    tasks_file = tmp_path / "tasks.json"
    tasks_file.write_text(json.dumps(tasks), encoding="utf-8")
    comparison = pd.DataFrame(
        [
            {"strategy": "contract_first", "task_id": "t1", "pass_rate": 1.0, "decomposition_steps": 3, "contract_length": 10, "contract_completeness": 0.9},
            {"strategy": "pattern_skeleton", "task_id": "t1", "pass_rate": 0.4, "decomposition_steps": 5, "contract_length": 5, "contract_completeness": 0.5},
            {"strategy": "contract_first", "task_id": "t2", "pass_rate": 0.6, "decomposition_steps": 4, "contract_length": 7, "contract_completeness": 0.8},
            {"strategy": "pattern_skeleton", "task_id": "t2", "pass_rate": 0.9, "decomposition_steps": 4, "contract_length": 6, "contract_completeness": 0.7},
        ]
    )
    comparison_file = tmp_path / "comp.csv"
    comparison.to_csv(comparison_file, index=False)

    dataset = build_dataset(tasks_file, comparison_file)
    assert "pass_rate" not in dataset.columns
    model, feature_cols, acc = train_meta_selector(dataset)
    assert acc >= 0.5
    audit_file = tmp_path / "audit.md"
    _write_audit(model, feature_cols, audit_file)
    assert audit_file.exists()
    loo_file = tmp_path / "loo.csv"
    _run_loo_type(dataset, loo_file)
    loo_df = pd.read_csv(loo_file)
    assert set(loo_df.columns) == {"task_type", "accuracy", "num_tasks", "num_rows"}
