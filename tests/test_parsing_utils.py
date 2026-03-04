from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.experiments.topcoder.formatting import build_strict_repair_prompt, extract_json_or_repair
from src.experiments.topcoder.parsing import extract_json_object, repair_output_to_json
from src.experiments.topcoder.prompts import STRICT_JSON_CONTRACT


def test_extract_json_object_handles_fenced_json() -> None:
    payload = "```json\n{\"task_type\":\"repo_patch\",\"summary\":\"fix\"}\n```"
    data = extract_json_object(payload)
    assert data["task_type"] == "repo_patch"


def test_extract_json_object_handles_prose_and_fence() -> None:
    payload = "Plan below:\n```json\n{\"summary\":\"done\",\"task_type\":\"architecture_doc\"}\n```\nThanks!"
    data = extract_json_object(payload)
    assert data["task_type"] == "architecture_doc"


def test_extract_json_object_handles_raw_with_trailing_prose() -> None:
    payload = "Result: {\"task_type\":\"data_etl\",\"summary\":\"build pipeline\"} -- done"
    data = extract_json_object(payload)
    assert data["summary"] == "build pipeline"


def test_repair_output_to_json_round_trip(monkeypatch) -> None:
    class _DummyResp:
        def __init__(self, content: str):
            self.content = content

    def fake_call(prompt, **kwargs):
        return _DummyResp(
            json.dumps(
                {
                    "task_type": "repo_patch",
                    "id": "demo",
                    "title": "Repair",
                    "summary": "repair",
                    "assumptions": [],
                    "plan": ["step"],
                    "artifacts": {
                        "patch_diff_unified": "diff",
                        "file_plan": ["a.py - adjust"],
                        "risks": ["rollback"],
                        "test_plan": ["pytest"],
                    },
                    "validations": ["SELF_CHECK"],
                    "confidence": 0.8,
                    "stop_reason": "completed",
                    "rubric_self_check": {
                        "coverage": 80,
                        "specificity": 80,
                        "actionability": 80,
                        "overall_notes": "ok",
                    },
                }
            )
        )

    from src.experiments.topcoder import parsing as parsing_module

    monkeypatch.setattr(parsing_module.llm, "call", fake_call)
    repaired = repair_output_to_json("n/a", contract_hint="contract", caller="test")
    data = extract_json_object(repaired)
    assert data["task_type"] == "repo_patch"


def _sample_payload(task_type: str = "repo_patch") -> dict:
    base = {
        "task_type": task_type,
        "id": "demo",
        "title": "Demo",
        "summary": "Summary",
        "assumptions": ["context"],
        "plan": ["step one"],
        "validations": ["SELF_CHECK"],
        "confidence": 0.9,
        "stop_reason": "completed",
        "rubric_self_check": {
            "coverage": 90,
            "specificity": 88,
            "actionability": 87,
            "overall_notes": "ok",
        },
    }
    if task_type == "repo_patch":
        base["artifacts"] = {
            "patch_diff_unified": "diff --git",
            "file_plan": ["service.py"],
            "risks": ["regression"],
            "test_plan": ["pytest"],
        }
    elif task_type == "architecture_doc":
        base["artifacts"] = {
            "design_doc_md": "# Doc\ncontent",
            "mermaid_diagram": "graph TD;A-->B;",
            "interfaces": ["Service A -> Service B"],
            "tradeoffs": ["Latency vs cost"],
        }
    else:
        base["artifacts"] = {
            "pipeline_spec": "Extract -> Transform -> Load",
            "python_snippets": ["def run():\n    return True"],
            "sql_snippets": ["select 1;"],
            "data_quality_checks": ["Row count parity"],
            "test_plan": ["dbt test"],
        }
    return base


def _sentinel_blob(payload: dict) -> str:
    return f"BEGIN_JSON\n{json.dumps(payload)}\nEND_JSON"


def _repair_builder(run_id: str, task_id: str) -> callable:
    return lambda raw: build_strict_repair_prompt(
        raw,
        schema_hint=STRICT_JSON_CONTRACT,
        solver_name="test",
        task_id=task_id,
        run_id=run_id,
    )


def test_extract_json_or_repair_parses_sentinel_noise(tmp_path: Path) -> None:
    builder = _repair_builder("run", "task")
    payload = _sentinel_blob(_sample_payload())
    noisy = f"preface\n{payload}\npost"
    outcome = extract_json_or_repair(
        noisy,
        llm_client=None,
        repair_prompt_builder=builder,
        artifact_dir=tmp_path,
        task_id="task",
        run_id="run",
        max_repairs=0,
    )
    assert outcome.payload["task_type"] == "repo_patch"
    assert outcome.used_repair is False
    assert outcome.raw_path == tmp_path / "task_agent_raw.txt"
    assert outcome.diagnostics_path.exists()


def test_extract_json_or_repair_finds_balanced_json(tmp_path: Path) -> None:
    builder = _repair_builder("run2", "task2")
    payload = json.dumps(_sample_payload("data_etl"))
    blob = f"prefix >>> {payload} <<< suffix"
    outcome = extract_json_or_repair(
        blob,
        llm_client=None,
        repair_prompt_builder=builder,
        artifact_dir=tmp_path,
        task_id="task2",
        run_id="run2",
        max_repairs=0,
    )
    assert outcome.payload["task_type"] == "data_etl"
    assert outcome.source == "balanced"


def test_extract_json_or_repair_triggers_repair(tmp_path: Path) -> None:
    class _DummyResp:
        def __init__(self, content: str):
            self.content = content

    class _StubLLM:
        def __init__(self, content: str):
            self.content = content
            self.calls = 0

        def call(self, prompt, **kwargs):
            self.calls += 1
            return _DummyResp(self.content)

    repaired_text = _sentinel_blob(_sample_payload("architecture_doc"))
    stub = _StubLLM(repaired_text)
    outcome = extract_json_or_repair(
        "BEGIN_JSON\n{bad json}\nEND_JSON",
        llm_client=stub,
        repair_prompt_builder=_repair_builder("run3", "task3"),
        artifact_dir=tmp_path,
        task_id="task3",
        run_id="run3",
    )
    assert outcome.used_repair is True
    assert outcome.repair_path == tmp_path / "task3_agent_repair.txt"
    assert outcome.payload["task_type"] == "architecture_doc"
    assert stub.calls == 1


def test_extract_json_or_repair_raises_when_no_repair(tmp_path: Path) -> None:
    with pytest.raises(Exception) as excinfo:
        extract_json_or_repair(
            "BEGIN_JSON\ninvalid\nEND_JSON",
            llm_client=None,
            repair_prompt_builder=_repair_builder("run4", "task4"),
            artifact_dir=tmp_path,
            task_id="task4",
            run_id="run4",
            max_repairs=0,
        )
    error = excinfo.value
    diag_path = getattr(error, "diagnostics_path", None)
    assert diag_path and Path(diag_path).exists()
