import io
import json
from pathlib import Path

import pytest

from scripts.openai_ops import poll_batch
from src.decomposition.openai_ops import load_jsonl


class FakeFileStream:
    def __init__(self, text: str):
        self._text = text

    def read(self) -> bytes:
        return self._text.encode("utf-8")


class FakeFiles:
    def __init__(self, mapping: dict[str, str]):
        self._mapping = mapping

    def content(self, file_id: str) -> FakeFileStream:
        return FakeFileStream(self._mapping[file_id])

    def retrieve_content(self, file_id: str) -> str:
        return self._mapping[file_id]


class FakeBatches:
    def __init__(self, batch_obj):
        self._batch = batch_obj

    def retrieve(self, batch_id: str):
        return self._batch


class FakeClient:
    def __init__(self, batch_obj, files: dict[str, str]):
        self.batches = FakeBatches(batch_obj)
        self.files = FakeFiles(files)


class BatchStub:
    def __init__(self, **kwargs):
        self.status = kwargs.get("status", "completed")
        self.output_file_id = kwargs.get("output_file_id")
        self.error_file_id = kwargs.get("error_file_id")
        self.errors = kwargs.get("errors")


def _run_poll(tmp_path: Path, batch_stub, files_map: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> Path:
    client = FakeClient(batch_stub, files_map)
    monkeypatch.setattr(poll_batch, "get_openai_client", lambda: client)
    monkeypatch.setattr(poll_batch.time, "sleep", lambda *_: None)
    monkeypatch.setattr(poll_batch, "sys", __import__("sys"))
    poll_batch.sys.argv = [
        "poll_batch.py",
        "--batch-id",
        "batch_test",
        "--output-dir",
        str(tmp_path),
    ]
    poll_batch.main()
    return tmp_path


def _make_success_row(payload: dict) -> str:
    row = {
        "custom_id": "req-1",
        "metadata": {"task_id": "task_a", "split": "train", "strategy": "cgcs", "clause_id": "c1"},
        "status": "completed",
        "response": {
            "id": "resp_1",
            "status": "completed",
            "output": [
                {"content": [{"type": "output_text", "text": json.dumps(payload)}]},
            ],
            "usage": {"output_tokens": 21},
        },
    }
    return json.dumps(row)


def _make_error_row(code: str = "rate_limit") -> str:
    return json.dumps({"custom_id": "req-error", "error": {"code": code, "message": "boom"}})


def test_poll_batch_handles_success_and_error_files(tmp_path, monkeypatch):
    success_text = "\n".join([_make_success_row({"edits": [], "localized": True})])
    error_text = "\n".join([_make_error_row()])
    batch = BatchStub(output_file_id="out1", error_file_id="err1")
    _run_poll(tmp_path, batch, {"out1": success_text, "err1": error_text}, monkeypatch)
    normalized = load_jsonl(tmp_path / "batch_test.jsonl")
    assert normalized and normalized[0]["payload"]["localized"] is True
    errors = load_jsonl(tmp_path / "batch_test_errors.jsonl")
    assert errors and errors[0]["error_code"] == "rate_limit"
    summary = json.loads((tmp_path / "batch_test_summary.json").read_text(encoding="utf-8"))
    assert summary["success_count"] == 1
    assert summary["error_count"] == 1


def test_poll_batch_error_only_creates_empty_success_file(tmp_path, monkeypatch):
    error_text = "\n".join([_make_error_row("invalid_request")])
    batch = BatchStub(output_file_id=None, error_file_id="err1")
    _run_poll(tmp_path, batch, {"err1": error_text}, monkeypatch)
    normalized = load_jsonl(tmp_path / "batch_test.jsonl")
    assert normalized == []
    errors = load_jsonl(tmp_path / "batch_test_errors.jsonl")
    assert errors and errors[0]["error_code"] == "invalid_request"
    summary = json.loads((tmp_path / "batch_test_summary.json").read_text(encoding="utf-8"))
    assert summary["success_count"] == 0
    assert summary["error_count"] == 1


def test_poll_batch_records_batch_errors_without_files(tmp_path, monkeypatch):
    batch_errors = [{"error": {"code": "auth", "message": "no key"}}]
    batch = BatchStub(output_file_id=None, error_file_id=None, errors=batch_errors)
    _run_poll(tmp_path, batch, {}, monkeypatch)
    summary = json.loads((tmp_path / "batch_test_summary.json").read_text(encoding="utf-8"))
    assert summary["error_count"] == 1
    error_rows = load_jsonl(tmp_path / "batch_test_errors.jsonl")
    assert error_rows and error_rows[0]["error_code"] == "auth"


def test_poll_batch_marks_malformed_outputs(tmp_path, monkeypatch):
    # output_text not JSON => malformed flag
    row = {
        "custom_id": "req-bad",
        "metadata": {"task_id": "bad", "split": "dev", "strategy": "cgcs", "clause_id": "c2"},
        "status": "completed",
        "response": {
            "id": "resp_bad",
            "status": "completed",
            "output": [{"content": [{"type": "output_text", "text": "not-json"}]}],
            "usage": {"output_tokens": 2},
        },
    }
    batch = BatchStub(output_file_id="out2", error_file_id=None)
    _run_poll(tmp_path, batch, {"out2": json.dumps(row)}, monkeypatch)
    normalized = load_jsonl(tmp_path / "batch_test.jsonl")
    assert normalized and normalized[0]["malformed_json"] is True
    summary = json.loads((tmp_path / "batch_test_summary.json").read_text(encoding="utf-8"))
    assert summary["malformed_json_count"] == 1
