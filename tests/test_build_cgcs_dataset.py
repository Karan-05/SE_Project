import json
from pathlib import Path

from scripts.build_cgcs_dataset import DatasetBuildOptions, build_dataset
from src.decomposition.openai_ops import load_jsonl


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _setup_run(tmp_path, *, placeholder_contract: bool = False, empty_payload: bool = False) -> tuple[Path, Path, Path]:
    run_root = tmp_path / "runs"
    trace_root = tmp_path / "traces"
    output_dir = tmp_path / "output"

    task_dir = run_root / "task_alpha"
    logs_dir = task_dir / "strategy_one" / "logs"
    trace_dir = trace_root / "strategy_one"
    logs_dir.mkdir(parents=True, exist_ok=True)
    trace_dir.mkdir(parents=True, exist_ok=True)

    cgcs_contract_items = None if placeholder_contract else [{"id": "limits", "description": "Limit results"}]
    contract_payload = (
        {"inputs": "Underspecified", "outputs": "Underspecified", "constraints": "", "edge_cases": "None"}
        if placeholder_contract
        else [{"id": "limits", "description": "Respect pagination limits"}]
    )
    trace_payload = {
        "task_id": "task_alpha",
        "strategy": "strategy_one",
        "plan": {
            "contract": contract_payload,
            "candidate_files": ["src/app.js", "node_modules/pkg/index.js", "tests/app.spec.js"],
            "diagnostics": {"repo_context_snippets": ["snippet"]},
        },
        "rounds": [
            {
                "round": 0,
                "status": "tests_failed",
                "edit_metadata": {
                    "cgcs_state": {
                        "witness_sample": [
                            {"test_case": "tests_0", "message": "fail", "linked_contract_ids": ["clause_from_witness"]}
                        ],
                        "contract_items": cgcs_contract_items,
                        "regression_guards": ["limits"],
                    }
                },
            }
        ],
    }
    _write_json(trace_dir / "task_alpha.json", trace_payload)
    _write_json(logs_dir / "snapshot_check.json", {"computed_snapshot": "abc123"})
    payload_text = "" if empty_payload else '{"edits": [{"path":"src/app.js","mode":"rewrite","content":"x"}]}'
    _write_json(
        logs_dir / "edits_round1.json",
        {"round": 0, "metadata": {"raw_payload": payload_text}},
    )
    return run_root, trace_root, output_dir


def test_build_dataset_filters_candidates_and_inferrs_clause(tmp_path):
    run_root, trace_root, output_dir = _setup_run(tmp_path)
    options = DatasetBuildOptions()
    build_dataset(run_root, trace_root, output_dir, options)
    all_rows = load_jsonl(output_dir / "all_rows.jsonl")
    assert len(all_rows) == 1
    row = all_rows[0]
    assert row["active_clause_id"] == "clause_from_witness"
    assert row["candidate_files"] == ["src/app.js"]
    assert row["row_quality"]["candidate_files_kept"] == 1
    assert row["row_quality"]["contract_quality"] == "ok"


def test_placeholder_contracts_rejected_without_flag(tmp_path):
    run_root, trace_root, output_dir = _setup_run(tmp_path, placeholder_contract=True, empty_payload=False)
    options = DatasetBuildOptions()
    build_dataset(run_root, trace_root, output_dir, options)
    rejected_rows = load_jsonl(output_dir / "rejected.jsonl")
    assert rejected_rows, "Expected rejected rows when placeholder contracts are present."
    rejection = rejected_rows[0]
    assert "placeholder_contract" in rejection.get("row_errors", [])
    assert rejection.get("row_quality", {}).get("contract_quality") == "weak"
