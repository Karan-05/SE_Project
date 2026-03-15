from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts.public_repos.debug_workspace_failures import main as debug_main


def write_records(path: Path, records: list[dict[str, object]]) -> None:
    lines = "\n".join(json.dumps(record) for record in records)
    path.write_text(lines + "\n", encoding="utf-8")


def test_failure_debug_summary(tmp_path: Path, monkeypatch) -> None:
    input_path = tmp_path / "workspace_validation.jsonl"
    records = [
        {
            "repo_key": "github.com/demo/py",
            "failure_category": "missing_python_build_module",
            "final_verdict": "blocked_by_environment",
            "language": "python",
            "package_manager": "pip",
            "build_system": "pyproject",
            "stderr_snippet": "error: build module missing",
        },
        {
            "repo_key": "github.com/demo/node",
            "failure_category": "missing_build_command",
            "final_verdict": "blocked_by_command_inference",
            "language": "node",
            "package_manager": "npm",
            "build_system": "nodejs",
            "stderr_snippet": "",
        },
        {
            "repo_key": "github.com/demo/ok",
            "failure_category": "",
            "final_verdict": "runnable",
            "language": "python",
            "package_manager": "pip",
            "build_system": "pyproject",
            "stderr_snippet": "",
        },
    ]
    write_records(input_path, records)
    out_dir = tmp_path / "out"
    report_dir = tmp_path / "reports"
    monkeypatch.setattr(sys, "argv", [
        "debug_workspace_failures",
        "--input", str(input_path),
        "--out-dir", str(out_dir),
        "--report-dir", str(report_dir),
    ])
    debug_main()
    payload = json.loads((out_dir / "workspace_failure_debug.json").read_text(encoding="utf-8"))
    assert payload["failure_counts"]["missing_python_build_module"] == 1
    assert payload["verdict_counts"]["runnable"] == 1
    assert payload["safe_bootstrap_candidates"][0]["repo_key"] == "github.com/demo/py"
    assert payload["command_inference_candidates"][0]["repo_key"] == "github.com/demo/node"
    markdown = (report_dir / "workspace_failure_debug.md").read_text(encoding="utf-8")
    assert "Safe bootstrap candidates" in markdown
