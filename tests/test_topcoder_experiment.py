from __future__ import annotations

import csv
import json
import importlib
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.experiments.topcoder.dataset_scanner import discover_topcoder_datasets, load_tasks_from_dataset
from src.experiments.topcoder.reporting import generate_reports
from src.experiments.topcoder.test_parsing import parse_examples_from_statement, TestSpec
from src.experiments.topcoder.test_manager import TestManager, TestPolicy
from src.experiments.topcoder.llm_utils import llm_available
from src.experiments.topcoder.task_router import TaskType, route_task, RoutingDecision
from src.experiments.topcoder.experiment_runner import ExperimentConfig, _TopcoderExperiment
from src.experiments.topcoder.solvers.design_doc import DesignDocSolver
from src.experiments.topcoder.solvers.repo_patch import RepoPatchSolver
from src.experiments.topcoder.solvers.base import SolverContext
from src.experiments.topcoder.verifiers import RubricVerifier, RepoVerifier
from src.experiments.topcoder.parsing import JsonExtractionError
from src.providers.llm import LLMResponse
from tools.run_topcoder_experiment import apply_presentation_defaults


def _write_sample_csv(path: Path, *, with_tests: bool = True) -> None:
    tests_payload = json.dumps(
        [
            {"name": "sample", "input": [1], "expected": 2},
        ]
    )
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=["challengeId", "name", "description", "tests"])
        writer.writeheader()
        writer.writerow(
            {
                "challengeId": "abc123",
                "name": "Increment",
                "description": "Return x + 1",
                "tests": tests_payload if with_tests else "",
            }
        )


def _write_sample_xlsx(path: Path) -> None:
    pd = pytest.importorskip("pandas")
    pytest.importorskip("openpyxl")
    df = pd.DataFrame(
        [
            {
                "challengeId": "xyz789",
                "name": "Double",
                "description": "Return x * 2",
                "tests": json.dumps([{"input": [2], "expected": 4}]),
            }
        ]
    )
    df.to_excel(path, index=False)  # type: ignore[attr-defined]


def test_dataset_discovery_handles_csv_and_xlsx(tmp_path: Path) -> None:
    csv_path = tmp_path / "toy.csv"
    xlsx_path = tmp_path / "toy.xlsx"
    _write_sample_csv(csv_path)
    _write_sample_xlsx(xlsx_path)

    descriptors = discover_topcoder_datasets(search_paths=[tmp_path])
    assert len(descriptors) >= 1
    tasks = []
    for descriptor in descriptors:
        tasks.extend(load_tasks_from_dataset(descriptor))
    assert tasks
    assert any(task.get("metadata", {}).get("tests") for task in tasks)


def test_report_generation() -> None:
    workspace = Path("tmp/tests_report_generation")
    if workspace.exists():
        shutil.rmtree(workspace)
    run_dir = workspace / "run"
    artifact_dir = workspace / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)
    start = datetime.utcnow()
    records = [
        {
            "task_id": "task_a",
            "dataset_id": "ds",
            "dataset_path": "ds.csv",
            "title": "Task A",
            "status": "passed",
            "error_type": "none",
            "pass_rate": 1.0,
            "attempt_count": 1,
            "strategy_used": "primary",
            "fallback_path": "primary",
            "stagnation_events": 0,
            "start_time": start.isoformat(),
            "end_time": (start + timedelta(seconds=2)).isoformat(),
            "duration_seconds": 2.0,
            "tests_provided": True,
            "tests_source": "provided",
            "artifact_path": str(artifact_dir),
            "failure_signature": "",
            "failing_tests": "",
            "last_error": "",
            "pass_at_final": True,
            "resolved_task_type": "algo_coding",
            "unit_test_success": True,
            "verifier_type": "unit_tests",
            "verifier_score": 100.0,
        },
        {
            "task_id": "task_b",
            "dataset_id": "ds",
            "dataset_path": "ds.csv",
            "title": "Task B",
            "status": "failed",
            "error_type": "test_failure",
            "pass_rate": 0.0,
            "attempt_count": 2,
            "strategy_used": "secondary",
            "fallback_path": "primary->secondary",
            "stagnation_events": 1,
            "start_time": start.isoformat(),
            "end_time": (start + timedelta(seconds=3)).isoformat(),
            "duration_seconds": 3.0,
            "tests_provided": True,
            "tests_source": "provided",
            "artifact_path": str(artifact_dir),
            "failure_signature": "sig123",
            "failing_tests": "test_a",
            "last_error": "boom",
            "pass_at_final": False,
            "resolved_task_type": "algo_coding",
            "unit_test_success": False,
            "verifier_type": "unit_tests",
            "verifier_score": 0.0,
        },
        {
            "task_id": "task_c",
            "dataset_id": "ds",
            "dataset_path": "ds.csv",
            "title": "Task C",
            "status": "completed_architecture_doc",
            "error_type": "success",
            "pass_rate": 0.0,
            "attempt_count": 0,
            "strategy_used": "",
            "fallback_path": "",
            "stagnation_events": 0,
            "start_time": start.isoformat(),
            "end_time": (start + timedelta(seconds=4)).isoformat(),
            "duration_seconds": 4.0,
            "tests_provided": False,
            "artifact_path": str(artifact_dir),
            "failure_signature": "",
            "failing_tests": "",
            "last_error": "",
            "pass_at_final": False,
            "resolved_task_type": "architecture_doc",
            "deliverable_success": True,
            "verifier_type": "rubric_architecture_doc",
            "verifier_score": 85.0,
        },
    ]

    try:
        report_paths = generate_reports("testrun", run_dir, records, artifact_dir=artifact_dir)
        summary = json.loads((run_dir / "summary.json").read_text())
        assert summary["total_problems"] == 3
        assert summary["total_unique_tasks"] == 3
        assert summary["completed_successfully"] == 2
        assert summary["actionable_attempted_total"] == 3
        assert summary["attempted_success_total"] == 2
        assert summary["attempted_failed_total"] == 1
        assert summary["fallback_count"] == 1
        assert summary["fallback_rate"] == pytest.approx(1 / 3)
        assert summary["stagnation_count"] == 1
        assert summary["non_actionable_total"] == 0
        assert summary["run_validity"] == "INVALID_NO_LLM"
        assert summary["llm_calls_per_attempted"] == pytest.approx(0.0)
        assert summary["evaluation_coverage"] == pytest.approx(1.0)
        assert summary["parse_failures_total"] == 0
        assert summary["attempted_algo"] == 2
        assert summary["solved_algo"] == 1
        assert summary["attempted_non_coding"] == 1
        assert summary["completed_deliverables"] == 1
        assert summary["task_type_breakdown"]["algo_coding"]["attempted"] == 2
        assert summary["pass_at_final_extracted_only"] == pytest.approx(0.5)
        assert summary["deliverable_success_rate"] == pytest.approx(1.0)
        assert summary["self_check_attempted"] == 0
        assert summary["self_check_pass_rate"] == pytest.approx(0.0)
        assert report_paths["per_problem"].exists()
        assert report_paths["per_task_metrics"].exists()
        failures = (run_dir / "failures.csv").read_text().strip().splitlines()
        assert len(failures) == 2  # header + one failure
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


@pytest.mark.parametrize("provider", ["openai", "azure_openai", "anthropic"])
def test_apply_presentation_defaults_force_no_cache(provider: str) -> None:
    args = SimpleNamespace(
        presentation=True,
        cache_ok=True,
        no_cache=False,
        min_llm_calls_per_attempted=None,
        min_llm_calls_per_attempted_mock=0.0,
    )
    apply_presentation_defaults(args, provider)
    assert args.no_cache is True
    assert args.cache_ok is False
    assert args.min_llm_calls_per_attempted == pytest.approx(1.0)


def test_apply_presentation_defaults_mock_provider() -> None:
    args = SimpleNamespace(
        presentation=True,
        cache_ok=False,
        no_cache=False,
        min_llm_calls_per_attempted=None,
        min_llm_calls_per_attempted_mock=0.25,
    )
    apply_presentation_defaults(args, "mock")
    assert args.no_cache is False
    assert args.min_llm_calls_per_attempted == pytest.approx(0.25)


def test_parse_examples_from_statement() -> None:
    statement = """
Examples:
Input:
1 2
Output:
3

Sample 2:
Input:4
Output:8
"""
    specs = parse_examples_from_statement(statement)
    assert len(specs) == 2
    assert all(spec.mode == "io" for spec in specs)
    assert "1 2" in specs[0].stdin


def test_test_manager_synthesizes_when_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DECOMP_MOCK_MODE", "1")
    policy = TestPolicy(
        require_tests=False,
        use_samples_as_tests=False,
        synthesize_tests=True,
        max_tasks_needing_synthesis=5,
        allow_no_llm=True,
    )
    manager = TestManager(policy, tmp_path)

    def fake_synth(task, max_tests=8):
        return [TestSpec(name="case", mode="call", inputs=[1], expected=2)], {"assumptions": "mock"}

    monkeypatch.setattr("src.experiments.topcoder.test_manager.synthesize_tests", fake_synth)
    task = {"id": "task_synth", "problem_statement": "Return x + 1", "metadata": {}}
    skip = manager.ensure_tests(task)
    assert skip is None
    metadata = task["metadata"]
    assert metadata["tests_source"] == "self_check"
    assert metadata["self_check_only"] is True
    assert metadata["tests"]
    assert metadata["tests_path"]


def test_test_manager_skips_without_llm(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DECOMP_MOCK_MODE", "0")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    policy = TestPolicy(allow_no_llm=True, synthesize_tests=True)
    manager = TestManager(policy, tmp_path)
    task = {"id": "noop", "problem_statement": "", "metadata": {}}
    skip = manager.ensure_tests(task)
    assert skip["status"] == "skipped_no_llm_config"


def test_test_manager_marks_parse_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DECOMP_MOCK_MODE", "1")
    policy = TestPolicy(allow_no_llm=True, use_samples_as_tests=True, synthesize_tests=False, require_tests=True)
    manager = TestManager(policy, tmp_path)

    def fake_parse(_text):
        return []

    monkeypatch.setattr("src.experiments.topcoder.test_manager.parse_examples_from_statement", fake_parse)
    task = {
        "id": "task_pf",
        "problem_statement": "Input:\n1 2\nOutput:\n3\n",
        "metadata": {},
    }
    skip = manager.ensure_tests(task)
    assert skip["status"] == "skipped_missing_tests"
    assert skip.get("parse_failure") is True


def test_test_manager_raises_when_llm_required(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DECOMP_MOCK_MODE", "0")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    policy = TestPolicy(allow_no_llm=False, synthesize_tests=True)
    with pytest.raises(RuntimeError):
        TestManager(policy, tmp_path)


def test_mock_provider_must_be_explicit(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("DECOMP_LLM_PROVIDER", "mock")
    monkeypatch.setenv("DECOMP_LLM_EXPLICIT", "0")
    monkeypatch.setenv("DECOMP_MOCK_MODE", "0")
    avail, reason = llm_available()
    assert not avail
    assert reason == "missing_config"


def test_task_router_detects_repo_patch() -> None:
    task = {
        "title": "Topcoder Community App - Support LaTex formulas in Markdown rendering",
        "problem_statement": "Fix Markdown rendering bug in the community web app.",
    }
    decision = route_task(task)
    assert decision.task_type == TaskType.REPO_PATCH


def test_task_router_detects_api_backend() -> None:
    task = {
        "title": "GraphQL Inventory API",
        "problem_statement": "Expose inventory CRUD via REST/GraphQL endpoints, add authentication middleware.",
        "tags": ["API", "backend", "express"],
    }
    decision = route_task(task)
    assert decision.task_type == TaskType.API_BACKEND


def test_task_router_detects_algo_when_examples_present() -> None:
    task = {
        "title": "Sum numbers",
        "problem_statement": "Given input: 1 2\nOutput: 3\nPlease implement.",
    }
    decision = route_task(task)
    assert decision.task_type == TaskType.ALGO_CODING


def test_design_doc_solver_produces_required_sections(monkeypatch, tmp_path: Path) -> None:
    def fake_call(prompt, **kwargs):
        caller = kwargs.get("caller")
        if caller == "design_doc_solver":
            content = "\n".join(f"## {section}\ncontent" for section in DesignDocSolver.required_sections)
            return LLMResponse(content=content, tokens=10, elapsed=0.1)
        raise AssertionError(f"unexpected caller {caller}")

    monkeypatch.setattr("src.providers.llm.call", fake_call)
    rubric = RubricVerifier(tmp_path / "rubric")
    solver = DesignDocSolver(rubric)
    ctx = SolverContext(
        task={"id": "doc1", "title": "API overhaul", "problem_statement": "Design a new API."},
        decision=RoutingDecision(TaskType.ARCHITECTURE_DOC, "design doc", ["design"]),
        config=SimpleNamespace(test_timeout_seconds=30.0),
        retry_config=SimpleNamespace(),
        test_manager=None,
        run_dir=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        deliverables_dir=tmp_path / "deliverables",
        patches_dir=tmp_path / "patches",
        rubric_dir=tmp_path / "rubric_out",
        test_results_dir=tmp_path / "tests",
        repo_logs_dir=tmp_path / "repo_logs",
        repo_search_root=tmp_path,
        llm_available=True,
    )
    result = solver.solve(ctx)
    assert result.status == "completed_architecture_doc"
    assert result.deliverable_success
    deliverable_path = Path(result.artifacts["deliverable_path"])
    assert deliverable_path.exists()
    content = deliverable_path.read_text()
    for section in DesignDocSolver.required_sections:
        assert f"## {section}" in content
    monkeypatch.setenv("DECOMP_LLM_EXPLICIT", "1")
    avail, reason = llm_available()
    assert avail
    assert reason == "mock"


def test_memory_retrieval_injects_hints(monkeypatch) -> None:
    memory_path = Path("reports") / "tests_memory" / "mem.jsonl"
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    if memory_path.exists():
        memory_path.unlink()
    monkeypatch.setenv("TOPCODER_MEMORY_PATH", str(memory_path))
    from src.experiments.topcoder import memory as memory_module

    importlib.reload(memory_module)
    memory_module.store("t_prev", "Remember to handle zero-sum arrays explicitly.", "sig-prev", {"task_text": "Zero Sum Problem"})
    import src.experiments.topcoder.experiment_runner as runner_mod

    monkeypatch.setattr(runner_mod, "memory_store", memory_module)
    runner = object.__new__(_TopcoderExperiment)
    task = {"id": "t_new", "title": "Zero Sum", "problem_statement": "Find pairs that sum to zero", "metadata": {}}
    injected = runner._inject_memory_hints(task)
    assert injected == 1
    hints = task["metadata"]["memory_hints"]
    assert any("zero-sum" in hint.lower() for hint in hints)


def test_repo_solver_reports_parse_failure(monkeypatch, tmp_path: Path) -> None:
    rubric = RubricVerifier(tmp_path / "rubric_dir")
    repo_verifier = RepoVerifier(tmp_path / "repo_logs")
    solver = RepoPatchSolver(rubric, repo_verifier)
    for directory in ["deliverables", "patches", "rubric_out", "tests", "repo_logs", "artifacts"]:
        (tmp_path / directory).mkdir(parents=True, exist_ok=True)
    ctx = SolverContext(
        task={"id": "demo", "problem_statement": "Fix bug", "metadata": {}},
        decision=RoutingDecision(TaskType.REPO_PATCH, "route", []),
        config=SimpleNamespace(run_id="test_run"),
        retry_config=SimpleNamespace(run_id="test_run"),
        test_manager=None,
        run_dir=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        deliverables_dir=tmp_path / "deliverables",
        patches_dir=tmp_path / "patches",
        rubric_dir=tmp_path / "rubric_out",
        test_results_dir=tmp_path / "tests",
        repo_logs_dir=tmp_path / "repo_logs",
        repo_search_root=tmp_path,
        llm_available=True,
    )
    raw_path = tmp_path / "raw_agent.txt"
    raw_path.write_text("raw", encoding="utf-8")
    diag_path = tmp_path / "diag.json"
    diag_path.write_text("{}", encoding="utf-8")

    def _boom(*_args, **_kwargs):
        exc = JsonExtractionError("broken")
        setattr(exc, "raw_agent_path", raw_path)
        setattr(exc, "repaired_agent_path", None)
        setattr(exc, "diagnostics_path", diag_path)
        raise exc

    monkeypatch.setattr(solver, "_request_patch", _boom)
    result = solver.solve(ctx)
    assert result.error_type == "deliverable_parse_error"
    assert result.metrics["parse_error"] == "broken"
    assert result.artifacts["agent_parse_diagnostics_path"] == str(diag_path)


def test_route_task_identifies_repo_patch() -> None:
    task = {
        "id": "repo123",
        "title": "Fix React bug in dashboard",
        "problem_statement": "Update the dashboard React component to resolve rendering bugs.",
    }
    decision = route_task(task)
    assert decision.task_type == TaskType.REPO_PATCH


def test_route_task_identifies_algo_with_io() -> None:
    task = {
        "id": "algo123",
        "problem_statement": "Given N numbers, print their sum.\nInput: N followed by numbers\nOutput: integer sum",
        "examples": [{"input": "3 1 2 3", "output": "6"}],
    }
    decision = route_task(task)
    assert decision.task_type == TaskType.ALGO_CODING


def test_router_detects_hiring_non_actionable() -> None:
    task = {"title": "Opportunity for React Engineers", "problem_statement": "We are hiring specialists for a new role."}
    decision = route_task(task)
    assert decision.task_type == TaskType.NON_ACTIONABLE
    assert "hiring_signal" in decision.heuristics


def test_router_detects_test_challenge_stub() -> None:
    task = {"title": "QA Test Challenge", "problem_statement": "This is a short test challenge for screening hires."}
    decision = route_task(task)
    assert decision.task_type == TaskType.NON_ACTIONABLE
    assert "test_challenge_stub" in decision.heuristics


def test_router_detects_api_backend_task() -> None:
    task = {
        "title": "API Integration for Payment Webhook",
        "problem_statement": "Build REST endpoints, document Swagger, and secure OAuth callback for partner API.",
    }
    decision = route_task(task)
    assert decision.task_type == TaskType.API_BACKEND
    assert "api_keywords" in decision.heuristics


def test_router_detects_data_etl_task() -> None:
    task = {
        "title": "ETL Pipeline Refresh",
        "problem_statement": "Create Airflow/dbt pipeline to ingest CSV into Snowflake and add DQ checks.",
    }
    decision = route_task(task)
    assert decision.task_type == TaskType.DATA_ETL
    assert "data_etl_keywords" in decision.heuristics


def test_resolve_task_type_falls_back_when_no_io(tmp_path: Path) -> None:
    runner = _TopcoderExperiment(ExperimentConfig(run_id="router_guard", allow_no_llm=True))
    bland_task = {"id": "spec", "problem_statement": "Write an API design for the payments module."}
    decision = RoutingDecision(task_type=TaskType.ALGO_CODING, rationale="forced", heuristics=[])
    resolved = runner._resolve_task_type(bland_task, decision)
    assert resolved == TaskType.ARCHITECTURE_DOC


def test_parse_failure_records_artifact(tmp_path: Path) -> None:
    runner = _TopcoderExperiment(ExperimentConfig(run_id="parse_guard", allow_no_llm=True))
    def _always_fail(task):
        return {"status": "skipped_missing_tests", "error_type": "missing_tests", "parse_failure": True}
    runner.test_manager = SimpleNamespace(ensure_tests=_always_fail)  # type: ignore[assignment]
    task = {"id": "no_parse", "problem_statement": "Describe onboarding process", "metadata": {}}
    skip = runner._prepare_algo_task(task)
    assert skip and "artifact_path" in skip
    artifact_path = Path(skip["artifact_path"])
    assert artifact_path.exists()
    text = artifact_path.read_text()
    assert "Parse failure" in text


def test_generate_reports_marks_mock_runs(tmp_path: Path) -> None:
    run_dir = tmp_path / "mock_run"
    artifact_dir = tmp_path / "artifacts"
    run_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    records = [
        {
            "task_id": "mock-task",
            "dataset_id": "ds",
            "status": "completed_architecture_doc",
            "error_type": "success",
            "pass_rate": 0.0,
            "attempt_count": 0,
            "start_time": datetime.utcnow().isoformat(),
            "end_time": datetime.utcnow().isoformat(),
            "duration_seconds": 0.0,
            "resolved_task_type": "architecture_doc",
            "deliverable_success": True,
        }
    ]
    generate_reports("mock_run", run_dir, records, artifact_dir=artifact_dir, metadata={"mock_provider": True, "llm_provider": "mock"})
    summary = json.loads((run_dir / "summary.json").read_text())
    assert summary["run_validity"] == "DEMO_ONLY_MOCK"
