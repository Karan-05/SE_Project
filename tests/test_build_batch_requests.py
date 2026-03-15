import json
from pathlib import Path

import pytest

from scripts.openai_ops import build_batch_requests as builder
from src.decomposition.openai_ops import load_jsonl


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _make_eval_item(task_id: str, *, active_clause: str = "clause1") -> dict:
    return {
        "task_id": task_id,
        "split": "train",
        "strategy": "cgcs",
        "round_index": 0,
        "active_clause_id": active_clause,
        "contract_items": [{"id": "c1", "description": "desc"}],
        "witnesses": [{"test_case": "tests_0", "message": "fail"}],
        "regression_guard_ids": ["guard"],
        "candidate_files": ["src/app.js", "tests/app.spec.js"],
        "context_snippets": [],
        "raw_edit_payload": '{"edits":[]}',
        "outcome": {},
        "row_quality": {"contract_quality": "ok"},
    }


def _run_builder(tmp_path: Path, rows: list[dict], monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    eval_path = tmp_path / "eval.jsonl"
    models_path = tmp_path / "models.yaml"
    output_path = tmp_path / "batch.jsonl"
    skipped_path = tmp_path / "skipped.jsonl"
    summary_path = tmp_path / "summary.json"
    _write_jsonl(eval_path, rows)
    models_path.write_text(json.dumps({"responses": {"default_model": "unit-test-model"}}), encoding="utf-8")
    argv = [
        "build_batch_requests.py",
        "--eval-items",
        str(eval_path),
        "--models-config",
        str(models_path),
        "--output",
        str(output_path),
        "--skipped-output",
        str(skipped_path),
        "--summary-output",
        str(summary_path),
        "--seed",
        "7",
    ]
    monkeypatch.setattr(builder, "sys", __import__("sys"))
    builder.sys.argv = argv
    builder.main()
    return output_path, skipped_path, summary_path


def test_batch_requests_use_text_format_and_unique_ids(tmp_path, monkeypatch):
    rows = [_make_eval_item("task_a"), _make_eval_item("task_b")]
    output_path, skipped_path, summary_path = _run_builder(tmp_path, rows, monkeypatch)
    requests = load_jsonl(output_path)
    assert len(requests) == 2
    custom_ids = {req["custom_id"] for req in requests}
    assert len(custom_ids) == 2
    for request in requests:
        body = request["body"]
        assert "text" in body and "response_format" not in body
        assert body["text"]["format"]["schema"]["required"] == ["edits", "localized"]
    skipped = load_jsonl(skipped_path)
    assert skipped == []
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["generated_requests"] == 2
    assert summary["skipped_items"] == 0


def test_skips_rows_missing_active_clause(tmp_path, monkeypatch):
    rows = [_make_eval_item("task_missing", active_clause="")]
    output_path, skipped_path, summary_path = _run_builder(tmp_path, rows, monkeypatch)
    requests = load_jsonl(output_path)
    assert requests == []
    skipped = load_jsonl(skipped_path)
    assert skipped and skipped[0]["reason"] == "missing_active_clause_id"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["skipped_items"] == 1
    assert summary["skip_reasons"]["missing_active_clause_id"] == 1
