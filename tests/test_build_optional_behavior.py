from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.public_repos.generate_seeded_repair_tasks import generate_tasks


def validation_record(repo_key: str, verdict: str) -> dict[str, object]:
    return {
        "repo_key": repo_key,
        "workspace_id": repo_key + "@abc123",
        "local_path": ".",
        "language": "python",
        "pilot_rank": 1,
        "final_verdict": verdict,
        "is_runnable": True,
        "task_command": "pytest",
    }


def test_generate_tasks_accepts_runnable_without_build(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    validated_path = tmp_path / "validation.jsonl"
    records = [
        validation_record("github.com/demo/a", "runnable"),
        validation_record("github.com/demo/b", "runnable_without_build"),
    ]
    with validated_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")

    stub_tasks: list[dict[str, object]] = []

    def fake_generate_task(entry, **kwargs):
        task_id = f"{entry['repo_key'].replace('/', '_')}_task"
        stub_tasks.append({"task_id": task_id})
        return {"task_id": task_id, "mutation_count": 1}

    monkeypatch.setattr(
        "scripts.public_repos.generate_seeded_repair_tasks.generate_task_for_repo",
        fake_generate_task,
    )
    summary = generate_tasks(
        validated_path=validated_path,
        out_dir=tmp_path,
        mutations_per_task=1,
        max_tasks=0,
        seed=0,
        dry_run=True,
        allow_runnable_without_build=True,
    )
    assert summary["tasks_generated"] == 2
