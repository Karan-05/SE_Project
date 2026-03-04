from __future__ import annotations

import json
from pathlib import Path
import csv

from tools.summarize_topcoder_run import compute_metrics, render_markdown, RunArtifacts, _load_records, _load_manifest


def _build_run(tmp_path: Path) -> RunArtifacts:
    reports_dir = tmp_path / "reports" / "experiments" / "run_test"
    reports_dir.mkdir(parents=True)
    per_problem = reports_dir / "per_problem.csv"
    rows = [
        {
            "task_id": "a",
            "status": "passed",
            "pass_rate": 1.0,
            "pass_at_final": True,
            "unit_test_success": True,
            "resolved_task_type": "algo_coding",
            "attempt_count": 2,
            "fallback_path": "contract->multi",
            "stagnation_events": 0,
            "tests_source": "extracted",
            "start_time": "2025-01-01T00:00:00",
            "end_time": "2025-01-01T00:00:30",
            "duration_seconds": 30,
            "dataset_id": "ds1",
        },
        {
            "task_id": "b",
            "status": "failed",
            "pass_rate": 0.0,
            "pass_at_final": False,
            "unit_test_success": False,
            "resolved_task_type": "algo_coding",
            "attempt_count": 10,
            "fallback_path": "contract",
            "stagnation_events": 1,
            "tests_source": "synthesized",
            "start_time": "2025-01-01T00:01:00",
            "end_time": "2025-01-01T00:01:40",
            "duration_seconds": 40,
            "dataset_id": "ds1",
        },
        {
            "task_id": "b",
            "status": "skipped_missing_tests",
            "pass_rate": 0.0,
            "pass_at_final": False,
            "unit_test_success": False,
            "resolved_task_type": "algo_coding",
            "attempt_count": 0,
            "fallback_path": "",
            "stagnation_events": 0,
            "tests_source": "",
            "dataset_id": "ds1",
        },
    ]
    with per_problem.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "run_id": "run_test",
        "total_problems": 4,
        "runtime": {
            "start_time": "2025-01-01T00:00:00",
            "end_time": "2025-01-01T00:02:00",
            "total_wall_time_seconds": 120,
            "avg_time_per_task": 60,
        },
        "llm_calls_total": 0,
        "llm_available": False,
    }
    (reports_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    manifest = {
        "tasks": [
            {"id": "a", "dataset_id": "ds1"},
            {"id": "b", "dataset_id": "ds1"},
            {"id": "c", "dataset_id": "ds2"},
            {"id": "b", "dataset_id": "ds1"},
        ],
        "task_count": 4,
    }
    (reports_dir / "tasks_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    checkpoint = reports_dir / "checkpoint.jsonl"
    checkpoint.write_text("", encoding="utf-8")
    deliverables = reports_dir / "deliverables"
    deliverables.mkdir(parents=True, exist_ok=True)
    (deliverables / "task_a.md").write_text("# Deliverable\ncontent", encoding="utf-8")
    return RunArtifacts(
        run_id="run_test",
        run_dir=reports_dir,
        per_problem=per_problem,
        checkpoint=checkpoint,
        summary=reports_dir / "summary.json",
        manifest=reports_dir / "tasks_manifest.json",
        deliverables=deliverables,
    )


def test_compute_metrics_and_render(tmp_path: Path) -> None:
    artifacts = _build_run(tmp_path)
    df = _load_records(artifacts)
    summary = json.loads(artifacts.summary.read_text())
    manifest = _load_manifest(artifacts.manifest)
    metrics = compute_metrics(df, summary, manifest, deliverables_dir=artifacts.deliverables)
    assert metrics["attempted"] == 2
    assert metrics["solved_pass_final"] == 1
    assert metrics["attempted_with_synthesized_tests"] == 1
    assert metrics["attempted_with_extracted_tests"] == 1
    assert metrics["self_check_attempted"] == 0
    assert metrics["self_check_pass_rate"] == 0
    assert metrics["retries_exhausted_count"] == 1
    assert metrics["deliverable_artifacts"] == 1
    md = render_markdown(metrics, artifacts)
    assert "TopCoder Experiment Final Results" in md
    assert "Extracted: attempted 1" in md
    assert "INVALID_NO_LLM" in md
    assert "Evaluation Coverage" in md
