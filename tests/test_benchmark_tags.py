import json
from pathlib import Path

from src.config import PathConfig


def test_benchmark_task_annotations():
    tasks_file = PathConfig().experiments_dir / "decomposition" / "benchmark_tasks.json"
    data = json.loads(tasks_file.read_text(encoding="utf-8"))
    assert len(data) >= 50
    hard_count = sum(1 for item in data if item.get("difficulty") == "H")
    ood_count = sum(1 for item in data if item.get("split") == "ood")
    assert hard_count >= 8
    assert ood_count >= 8
    required = {"title", "statement", "type", "difficulty", "pitfalls", "split"}
    for task in data:
        assert required.issubset(task.keys())
