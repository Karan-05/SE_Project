from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.decomposition.agentic.loop import _select_active_clause_id
from src.decomposition.interfaces import DecompositionContext
from src.decomposition.real_repo.harness import RepoTaskHarness
from src.decomposition.real_repo.strict_logging import STRICT_TRACE_FILENAME, persist_strict_trace_entry
from src.decomposition.real_repo.task import RepoTaskSpec


def _write_log(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_strict_trace_written_to_logs_and_trace_file(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"
    log_path = logs_dir / "edits_round1.json"
    base_payload = {
        "round": 1,
        "strategy": "cgcs",
        "metadata": {"raw_edit_payload": "print('hello')"},
    }
    _write_log(log_path, base_payload)
    strict_payload = {
        "round": 1,
        "strategy": "cgcs",
        "task_id": "task",
        "contract_items": [{"id": "clause_a"}],
        "active_clause_id": "",
        "regression_guard_ids": [],
        "witnesses": [],
        "raw_edit_payload": "print('hello')",
        "payload_parse_ok": True,
        "candidate_files": ["foo.py"],
        "candidate_files_raw": ["foo.py"],
        "candidate_files_filtered": ["foo.py"],
        "row_quality": {
            "contract_quality": "strong",
            "active_clause_source": "manual",
            "witness_count": 0,
            "payload_present": True,
            "payload_parse_ok": True,
            "candidate_file_count": 1,
            "strategy_mode": "cgcs",
            "used_fallback": False,
        },
    }
    persist_strict_trace_entry(
        logs_dir=logs_dir,
        edit_log_path=log_path,
        strict_entry=strict_payload,
    )

    updated = json.loads(log_path.read_text(encoding="utf-8"))
    assert updated["contract_items"]
    assert updated["raw_edit_payload"] == "print('hello')"
    assert updated["row_quality"]["strategy_mode"] == "cgcs"
    strict_file = logs_dir / STRICT_TRACE_FILENAME
    contents = strict_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(contents) == 1
    recorded = json.loads(contents[0])
    assert recorded["candidate_files"] == ["foo.py"]
    assert recorded["witnesses"] == []


def test_active_clause_fallback_for_non_clause_strategy() -> None:
    items = [{"id": "clause_primary"}]
    assert _select_active_clause_id("", items, "contract_first") == "clause_primary"
    assert _select_active_clause_id("", [], "failure_mode_first") == "failure_mode_first_default_clause"


def test_raw_payload_preserved_on_parse_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    target = repo_root / "target.py"
    target.write_text("# BEGIN SOLUTION\npass\n# END SOLUTION\n", encoding="utf-8")
    output_root = tmp_path / "runs"
    task = RepoTaskSpec(
        task_id="t",
        prompt="fix",
        repo_path=repo_root,
        build_commands=[],
        test_commands=[],
        target_files=["target.py"],
        file_context=["target.py"],
        metadata={"repo_target_files": ["target.py"], "repo_candidate_files": ["target.py"]},
    )
    harness = RepoTaskHarness(task=task, strategy_name="contract_first", output_root=output_root)

    def _parse_failure(unused: str) -> tuple[None, str]:
        return None, "malformed"

    monkeypatch.setattr(
        "src.decomposition.real_repo.harness.parse_repo_edit_payload_with_diagnostics",
        _parse_failure,
    )
    ctx = DecompositionContext(
        task_id="t",
        problem_statement="fix",
        metadata={"repo_target_files": ["target.py"], "repo_candidate_files": ["target.py"]},
    )
    code = "nonsense patch payload"
    result = harness.evaluate_attempt(code=code, ctx=ctx, subtask_focus=None)
    assert result.edit_metadata["raw_edit_payload"] == code

    log_path = Path(result.artifacts.get("edit_log") or "")
    assert log_path.exists()
    logged = json.loads(log_path.read_text(encoding="utf-8"))
    assert logged["metadata"]["raw_edit_payload"] == code
