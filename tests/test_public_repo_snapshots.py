from __future__ import annotations

from pathlib import Path

from src.public_repos.snapshots import build_snapshots


def create_repo(tmp_path: Path) -> Path:
    repo_dir = tmp_path / "github.com/example/demo"
    (repo_dir / "tests").mkdir(parents=True)
    (repo_dir / "src" / "test" / "java").mkdir(parents=True)
    (repo_dir / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    (repo_dir / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (repo_dir / "src" / "test" / "java" / "AppTest.java").write_text("class AppTest {}\n", encoding="utf-8")
    return repo_dir


def test_build_snapshots_detects_build_and_tests(tmp_path: Path) -> None:
    repo_dir = create_repo(tmp_path)
    manifest_records = [
        {
            "repo_key": "github.com/example/demo",
            "repo_url": "https://github.com/example/demo",
            "local_path": str(repo_dir),
            "status": "cloned",
            "resolved_commit": "abc123",
            "default_branch": "main",
            "language": "python",
            "selection_rank": 1,
            "source_type": "host_search",
        }
    ]
    snapshots = build_snapshots(manifest_records, tmp_path, max_files=500)
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.has_tests
    assert snapshot.has_build_files
    assert "python" in snapshot.languages
    assert "python-pyproject" in snapshot.build_systems
    assert "junit" in snapshot.test_frameworks

