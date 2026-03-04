import json
from pathlib import Path

import pandas as pd

from src.decomposition.runners.run_meta_selector import (
    build_dataset,
    predict_best_strategies,
    train_meta_selector,
)


def test_meta_selector_workflow(tmp_path):
    tasks = [
        {
            "id": "task_a",
            "problem_statement": "Add two numbers",
            "type": "array",
            "difficulty": "S",
            "tags": ["math"],
            "pitfalls": ["overflow"],
        },
        {
            "id": "task_b",
            "problem_statement": "Find path",
            "type": "graph",
            "difficulty": "M",
            "tags": ["graph"],
            "pitfalls": ["cycle"],
        },
    ]
    tasks_file = tmp_path / "tasks.json"
    tasks_file.write_text(json.dumps(tasks), encoding="utf-8")

    comparison = pd.DataFrame(
        [
            {"strategy": "contract_first", "task_id": "task_a", "pass_rate": 1.0, "decomposition_steps": 3, "tokens_used": 10},
            {"strategy": "pattern_skeleton", "task_id": "task_a", "pass_rate": 0.5, "decomposition_steps": 2, "tokens_used": 5},
            {"strategy": "contract_first", "task_id": "task_b", "pass_rate": 0.4, "decomposition_steps": 4, "tokens_used": 12},
            {"strategy": "pattern_skeleton", "task_id": "task_b", "pass_rate": 0.9, "decomposition_steps": 3, "tokens_used": 8},
        ]
    )
    comp_file = tmp_path / "comp.csv"
    comparison.to_csv(comp_file, index=False)

    dataset = build_dataset(tasks_file, comp_file)
    model, feature_cols, accuracy = train_meta_selector(dataset)
    assert accuracy >= 0.5
    predictions = predict_best_strategies(model, feature_cols, dataset)
    assert set(predictions.columns) == {"task_id", "predicted_strategy", "probability", "true_best_strategy"}
    assert set(predictions["task_id"]) == {"task_a", "task_b"}
    assert (predictions["predicted_strategy"] == predictions["true_best_strategy"]).any()
