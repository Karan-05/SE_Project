from __future__ import annotations

from pathlib import Path

from src.public_repos.pilot.workspace_bootstrap import plan_workspace_normalization


def _base_snapshot(local_path: Path) -> dict[str, object]:
    return {
        "repo_key": "example/repo",
        "repo_url": "https://example/repo",
        "local_path": str(local_path),
        "detected_build_files": [],
        "test_frameworks": [],
        "build_systems": [],
        "has_tests": True,
        "has_build_files": True,
    }


def test_package_manager_field_selects_yarn_with_corepack(tmp_path: Path) -> None:
    repo = tmp_path / "repo_yarn"
    repo.mkdir()
    package_json = repo / "package.json"
    package_json.write_text(
        '{"name": "pkg", "packageManager": "yarn@3.6.0", "scripts": {"build": "echo hi"}}',
        encoding="utf-8",
    )
    (repo / "yarn.lock").write_text("", encoding="utf-8")
    snapshot = _base_snapshot(repo)
    snapshot["detected_build_files"] = ["package.json", "yarn.lock"]
    plan = plan_workspace_normalization(snapshot)
    assert plan.package_manager == "yarn"
    assert plan.package_manager_spec == "3.6.0"
    assert plan.install_command == "yarn install"
    assert plan.bootstrap.required
    assert any("corepack" in cmd for cmd in plan.bootstrap.commands)


def test_workspace_protocol_forces_yarn_install(tmp_path: Path) -> None:
    repo = tmp_path / "repo_workspace"
    repo.mkdir()
    package_json = repo / "package.json"
    package_json.write_text(
        '{"name": "pkg", "dependencies": {"lib": "workspace:*"}}',
        encoding="utf-8",
    )
    snapshot = _base_snapshot(repo)
    snapshot["detected_build_files"] = ["package.json"]
    plan = plan_workspace_normalization(snapshot)
    assert plan.package_manager == "yarn"
    assert plan.install_command == "yarn install"


def test_package_manager_field_selects_pnpm(tmp_path: Path) -> None:
    repo = tmp_path / "repo_pnpm"
    repo.mkdir()
    (repo / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    package_json = repo / "package.json"
    package_json.write_text(
        '{"name": "pkg", "packageManager": "pnpm@8.7.0"}',
        encoding="utf-8",
    )
    snapshot = _base_snapshot(repo)
    snapshot["detected_build_files"] = ["package.json", "pnpm-lock.yaml"]
    plan = plan_workspace_normalization(snapshot)
    assert plan.package_manager == "pnpm"
    assert plan.install_command == "pnpm install"
