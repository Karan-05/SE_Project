from __future__ import annotations

from pathlib import Path

from src.decomposition.topcoder.snapshot import build_snapshot


def create_js_repo(base: Path) -> Path:
    repo_path = base / "js_repo"
    repo_path.mkdir()
    (repo_path / "package.json").write_text(
        '{"scripts": {"build": "vite build", "test": "jest"}}',
        encoding="utf-8",
    )
    (repo_path / "pnpm-lock.yaml").write_text("lock", encoding="utf-8")
    src_path = repo_path / "src"
    src_path.mkdir()
    (src_path / "main.ts").write_text("const main = () => 1;", encoding="utf-8")
    tests_dir = repo_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "app.test.ts").write_text("describe('app', () => {})", encoding="utf-8")
    return repo_path


def create_python_repo(base: Path) -> Path:
    repo_path = base / "py_repo"
    repo_path.mkdir()
    (repo_path / "requirements.txt").write_text("pytest\nrequests", encoding="utf-8")
    tests_dir = repo_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_app.py").write_text("def test_ok():\n    assert True", encoding="utf-8")
    (repo_path / "project.py").write_text("print('hi')", encoding="utf-8")
    return repo_path


def test_snapshot_detects_js_signals(tmp_path: Path) -> None:
    repo_path = create_js_repo(tmp_path)
    snapshot = build_snapshot(
        repo_url="https://github.com/topcoder/js_repo",
        local_path=repo_path,
        normalized_repo_key="github.com/topcoder/js_repo",
        challenge_ids=["c1"],
        resolved_commit="abc123",
        branch="main",
    )
    assert "TypeScript" in snapshot.detected_languages
    assert "pnpm" in snapshot.detected_build_systems
    assert any(framework in snapshot.detected_test_frameworks for framework in ("jest", "tests_dir"))
    assert snapshot.likely_runnable


def test_snapshot_detects_python_signals(tmp_path: Path) -> None:
    repo_path = create_python_repo(tmp_path)
    snapshot = build_snapshot(
        repo_url="https://github.com/topcoder/py_repo",
        local_path=repo_path,
        normalized_repo_key="github.com/topcoder/py_repo",
        challenge_ids=["c2"],
        resolved_commit="def456",
        branch="main",
    )
    assert "Python" in snapshot.detected_languages
    assert "pip" in snapshot.detected_build_systems
    assert snapshot.likely_python_repo
