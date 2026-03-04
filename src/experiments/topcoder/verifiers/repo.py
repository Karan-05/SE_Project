"""Run lightweight repo checks (tests/lint) for patch tasks."""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ..solvers.base import sanitize_task_id


@dataclass
class RepoVerificationResult:
    success: bool
    commands: List[List[str]]
    log_path: Path
    details: List[Dict[str, Any]]


class RepoVerifier:
    """Rudimentary command detector that runs repo tests/linting."""

    def __init__(self, logs_dir: Path, timeout_seconds: int = 180):
        self.logs_dir = logs_dir
        self.timeout_seconds = timeout_seconds
        logs_dir.mkdir(parents=True, exist_ok=True)

    def detect_commands(self, repo_path: Path) -> List[List[str]]:
        commands: List[List[str]] = []
        if (repo_path / "package.json").exists():
            commands.append(["npm", "test", "--", "--runInBand"])
        if (repo_path / "pnpm-lock.yaml").exists():
            commands.append(["pnpm", "test"])
        if (repo_path / "yarn.lock").exists():
            commands.append(["yarn", "test"])
        if (repo_path / "pytest.ini").exists() or (repo_path / "pyproject.toml").exists():
            commands.append(["pytest", "-q"])
        if (repo_path / "manage.py").exists():
            commands.append(["python", "manage.py", "test"])
        if (repo_path / "go.mod").exists():
            commands.append(["go", "test", "./..."])
        return commands

    def run(self, task_id: str, repo_path: Path, commands: Optional[Sequence[Sequence[str]]] = None) -> RepoVerificationResult:
        commands_list: List[List[str]] = [list(cmd) for cmd in (commands or self.detect_commands(repo_path))]
        if not commands_list:
            return self._write_log(task_id, success=True, commands=[], details=[{"info": "no commands detected"}])
        results: List[Dict[str, Any]] = []
        success = True
        for cmd in commands_list:
            start = time.perf_counter()
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
                duration = time.perf_counter() - start
                entry = {
                    "command": cmd,
                    "returncode": proc.returncode,
                    "stdout": proc.stdout[-6000:],
                    "stderr": proc.stderr[-6000:],
                    "duration_seconds": duration,
                }
                results.append(entry)
                if proc.returncode != 0:
                    success = False
            except subprocess.TimeoutExpired as exc:
                success = False
                results.append(
                    {
                        "command": cmd,
                        "error": "timeout",
                        "duration_seconds": exc.timeout or self.timeout_seconds,
                    }
                )
            except FileNotFoundError as exc:
                success = False
                results.append(
                    {
                        "command": cmd,
                        "error": f"command_not_found:{exc.filename}",
                    }
                )
        return self._write_log(task_id, success=success, commands=commands_list, details=results)

    def _write_log(
        self,
        task_id: str,
        *,
        success: bool,
        commands: List[List[str]],
        details: List[Dict[str, Any]],
    ) -> RepoVerificationResult:
        payload = {
            "task_id": task_id,
            "success": success,
            "commands": commands,
            "details": details,
        }
        safe = sanitize_task_id(task_id)
        path = self.logs_dir / f"{safe}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return RepoVerificationResult(success=success, commands=commands, log_path=path, details=details)

