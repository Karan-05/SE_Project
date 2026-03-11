"\"\"\"Regenerate valid unified diffs for repo-backed TopCoder tasks.\"\"\""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable, List, Sequence, Set

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_task_dirs(root: Path) -> List[Path]:
    return sorted(path for path in root.iterdir() if path.is_dir() and (path / "task.json").exists())


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _collect_paths(task: dict) -> Set[str]:
    metadata = task.get("metadata") or {}
    paths: Set[str] = set()
    for key in ("target_files",):
        for entry in task.get(key) or []:
            paths.add(str(entry))
    for key in ("expected_files",):
        for entry in metadata.get(key, []):
            paths.add(str(entry))
    for entry in task.get("file_context") or []:
        if str(entry).startswith("test/"):
            paths.add(str(entry))
    for entry in metadata.get("related_tests") or []:
        paths.add(str(entry))
    for command in task.get("test_commands") or []:
        for token in command.split():
            token = token.strip()
            if token.startswith("test/"):
                paths.add(token)
    return {path for path in paths if path}


def _changed_files(base_repo: Path, fixed_repo: Path) -> Set[str]:
    cmd = ["/usr/bin/diff", "-qr", str(base_repo), str(fixed_repo)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode not in {0, 1}:
        raise RuntimeError(f"diff -qr failed: {proc.stderr}")
    changed: Set[str] = set()
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line.startswith("Files "):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        left = Path(parts[1])
        rel = left.relative_to(base_repo)
        if (base_repo / rel).is_file():
            changed.add(str(rel))
    return changed


def _run_diff(old_path: Path, new_path: Path, label: str) -> str:
    cmd = [
        "/usr/bin/diff",
        "-u",
        "--label",
        label,
        "--label",
        label,
        str(old_path),
        str(new_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode not in {0, 1}:
        raise RuntimeError(f"diff failed for {label}: {proc.stderr or proc.stdout}")
    return proc.stdout.strip()


def _copy_repo(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _run_commands(commands: Sequence[str], *, cwd: Path) -> None:
    for index, command in enumerate(commands):
        proc = subprocess.run(
            ["bash", "-lc", command],
            cwd=cwd,
            text=True,
            capture_output=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"Command failed ({command}) in {cwd}:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
            )


def regenerate(task_dirs: Iterable[Path], *, base_root: Path, fixed_root: Path | None) -> None:
    summary: List[str] = []
    for task_dir in task_dirs:
        task = _read_json(task_dir / "task.json")
        repo_rel = Path(task["repo_path"])
        if fixed_root:
            candidate = fixed_root / f"{repo_rel.name}.solved"
            if not candidate.exists():
                candidate = fixed_root / repo_rel.name
            repo_fixed = candidate.resolve()
        else:
            repo_fixed = (PROJECT_ROOT / repo_rel).resolve()
        base_candidate = base_root / f"{repo_rel.name}.base"
        base_repo = base_candidate if base_candidate.exists() else (base_root / repo_rel.name)
        base_repo = base_repo.resolve()
        if not base_repo.exists():
            raise FileNotFoundError(
                f"Base snapshot not found for {task['task_id']} ({base_repo})"
            )
        changed = _changed_files(base_repo, repo_fixed)
        paths = _collect_paths(task) | changed
        patch_parts: List[str] = []
        for rel in sorted(paths):
            base_file = base_repo / rel
            fixed_file = repo_fixed / rel
            if not base_file.exists() and not fixed_file.exists():
                continue
            label = str(rel)
            diff_text = _run_diff(base_file, fixed_file, label)
            if diff_text:
                patch_parts.append(diff_text)
        if not patch_parts:
            raise RuntimeError(f"No diff generated for {task['task_id']}; nothing to patch.")
        patch_path = task_dir / "ground_truth.patch"
        patch_path.write_text("\n".join(patch_parts) + "\n", encoding="utf-8")
        summary.append(f"{task['task_id']}: generated")
        # Validation
        with tempfile.TemporaryDirectory(prefix=f"{task['task_id']}_") as tmpdir:
            tmp_repo = Path(tmpdir) / repo_rel.name
            shutil.copytree(base_repo, tmp_repo)
            proc = subprocess.run(
                ["patch", "-s", "-p0", "-i", str(patch_path.resolve())],
                cwd=tmp_repo,
                text=True,
                capture_output=True,
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    f"Patch apply failed for {task['task_id']}: {proc.stderr or proc.stdout}"
                )
            setup_cmds = task.get("setup_commands") or []
            test_cmds = task.get("test_commands") or []
            _run_commands(setup_cmds, cwd=tmp_repo)
            _run_commands(test_cmds, cwd=tmp_repo)
    print("Patch regeneration summary:")
    for line in summary:
        print(f"- {line}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate ground_truth.patch files.")
    parser.add_argument(
        "--tasks-root",
        type=Path,
        default=PROJECT_ROOT / "experiments" / "real_repo_tasks" / "topcoder",
    )
    parser.add_argument(
        "--base-root",
        type=Path,
        default=PROJECT_ROOT / "experiments" / "real_repos_snapshots",
    )
    parser.add_argument(
        "--fixed-root",
        type=Path,
        default=None,
        help="Optional directory containing solved repo snapshots.",
    )
    args = parser.parse_args()
    task_dirs = _load_task_dirs(args.tasks_root)
    regenerate(task_dirs, base_root=args.base_root, fixed_root=args.fixed_root)


if __name__ == "__main__":  # pragma: no cover
    main()
