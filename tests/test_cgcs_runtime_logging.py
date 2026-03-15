import json
from pathlib import Path

from scripts.real_repo.audit_cgcs_trace_quality import audit_trace_dir
from src.decomposition.real_repo.cgcs_logging import build_cgcs_round_trace
from src.decomposition.real_repo.witnesses import SemanticWitness


def _sample_witness() -> SemanticWitness:
    return SemanticWitness(
        test_case="tests::failure",
        message="AssertionError: expected 1 to equal 2",
        expected="2",
        actual="1",
        location="/tmp/log",
        category="assertion",
        linked_contract_ids=["clause_a"],
    )


def test_round_trace_logs_clause_guards_and_payload() -> None:
    trace = build_cgcs_round_trace(
        task_id="task_alpha",
        strategy="cgcs",
        round_index=1,
        contract_items=[{"id": "clause_a", "description": "Ensure totals match"}],
        active_clause_id="clause_a",
        regression_guard_ids=[],
        witnesses=[_sample_witness()],
        raw_edit_payload="{malformed",
        payload_parse_ok=False,
        payload_parse_error="json_error",
        candidate_files_raw=["a.js", "b.js"],
        candidate_files_filtered=["a.js"],
        clause_selection_reason="regressed_clause_priority",
        lint_errors=["lint_issue"],
        skipped_targets=["modules/foo.js"],
        outcome_metrics={"status": "tests_failed"},
        strategy_mode="cgcs",
        used_fallback=False,
    )
    payload = trace.to_dict()
    assert payload["active_clause_id"] == "clause_a"
    assert payload["regression_guard_ids"] == []
    assert payload["raw_edit_payload"] == "{malformed"
    assert payload["payload_parse_error"]
    assert payload["candidate_files_raw"] == ["a.js", "b.js"]
    assert payload["candidate_files_filtered"] == ["a.js"]
    assert payload["candidate_files"] == ["a.js"]
    assert payload["witnesses"][0]["signature"]


def test_row_quality_marks_weak_contract_and_counts_candidates() -> None:
    trace = build_cgcs_round_trace(
        task_id="task_beta",
        strategy="cgcs",
        round_index=0,
        contract_items=[{"id": "clause_b", "description": "TODO fill"}],
        active_clause_id="clause_b",
        regression_guard_ids=["clause_a"],
        witnesses=[_sample_witness()],
        raw_edit_payload="{}",
        payload_parse_ok=True,
        payload_parse_error=None,
        candidate_files_raw=["a.js", "b.js"],
        candidate_files_filtered=["a.js", "b.js"],
        clause_selection_reason="unsatisfied_clause_priority",
        lint_errors=[],
        skipped_targets=[],
        outcome_metrics={"status": "tests_failed"},
        strategy_mode="cgcs",
        used_fallback=False,
    )
    quality = trace.row_quality
    assert quality["contract_quality"] in {"weak", "missing"}
    assert quality["candidate_file_count"] == 2
    assert quality["witness_count"] == 1


def test_round_trace_serialization_deterministic() -> None:
    kwargs = dict(
        task_id="task_gamma",
        strategy="cgcs",
        round_index=2,
        contract_items=[{"id": "clause_c", "description": "Compute metadata"}],
        active_clause_id="clause_c",
        regression_guard_ids=["clause_a"],
        witnesses=[_sample_witness()],
        raw_edit_payload="{}",
        payload_parse_ok=True,
        payload_parse_error=None,
        candidate_files_raw=["x.js"],
        candidate_files_filtered=["x.js"],
        clause_selection_reason="pending_clause_priority",
        lint_errors=[],
        skipped_targets=[],
        outcome_metrics={"status": "tests_failed"},
        strategy_mode="cgcs",
        used_fallback=False,
    )
    trace_a = build_cgcs_round_trace(**kwargs)
    trace_b = build_cgcs_round_trace(**kwargs)
    assert trace_a.to_dict() == trace_b.to_dict()


def test_trace_audit_identifies_ready_rounds(tmp_path: Path) -> None:
    trace_dir = tmp_path / "traces" / "cgcs"
    trace_dir.mkdir(parents=True)
    ready_round = {
        "edit_metadata": {
            "cgcs_state": {
                "contract_items": [{"id": "clause_a"}],
                "active_clause_id": "clause_a",
                "witnesses": [{"signature": "sig"}],
            },
            "raw_edit_payload": "{\"edits\":[]}",
            "payload_parse_ok": True,
            "candidate_files": ["modules/foo.js"],
        }
    }
    failing_round = {
        "edit_metadata": {
            "cgcs_state": {
                "contract_items": [],
            },
            "raw_edit_payload": "",
            "payload_parse_ok": False,
            "candidate_files": [],
        }
    }
    payload = {"task_id": "task_delta", "strategy": "cgcs", "rounds": [ready_round, failing_round]}
    (trace_dir / "task_delta.json").write_text(json.dumps(payload), encoding="utf-8")
    summary = audit_trace_dir(tmp_path / "traces")
    assert summary["total_rounds"] == 2
    assert summary["rounds_ready_for_strict_dataset"] == 1
    assert summary["rounds_payload_parse_failed"] == 1
