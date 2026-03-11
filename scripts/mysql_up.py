#!/usr/bin/env python3
"""Bootstrap helper for the local MySQL container."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence


def _run(cmd: Sequence[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=check)


def _has_docker_cli() -> bool:
    return shutil.which("docker") is not None


def _detect_compose_command() -> list[str]:
    if shutil.which("docker") and shutil.which("docker-compose"):
        return ["docker-compose"]
    if shutil.which("docker"):
        return ["docker", "compose"]
    raise RuntimeError("Neither docker-compose nor docker compose is available in PATH.")


def _check_docker_access() -> None:
    if not _has_docker_cli():
        raise RuntimeError("docker CLI not found. Install Docker Desktop or Colima + docker first.")
    info = subprocess.run(["docker", "info"], text=True, capture_output=True)
    if info.returncode != 0:
        hint = info.stderr.strip() or info.stdout.strip()
        raise RuntimeError(
            "Failed to talk to the Docker daemon. "
            "If you're on macOS with Colima, run `colima start` from a shell that can write "
            "to ~/.colima, then re-run this script.\n"
            f"docker info output:\n{hint}"
        )


def _wait_for_mysql(compose_cmd: list[str], compose_file: Path, service: str, password: str, timeout: int) -> None:
    ping_cmd = [
        *compose_cmd,
        "-f",
        str(compose_file),
        "exec",
        "-T",
        service,
        "mysqladmin",
        "ping",
        "-h",
        "127.0.0.1",
        f"-p{password}",
    ]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        proc = subprocess.run(ping_cmd, text=True, capture_output=True)
        if proc.returncode == 0:
            print("MySQL is accepting connections.")
            return
        time.sleep(2)
    raise TimeoutError(f"MySQL did not become ready within {timeout} seconds. Last output: {proc.stderr.strip()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the local MySQL container via docker compose/Colima.")
    parser.add_argument("--compose-file", type=Path, default=Path("docker-compose.mysql.yml"))
    parser.add_argument("--service", default="mysql")
    parser.add_argument("--wait", action="store_true", help="Wait for MySQL to accept connections after boot.")
    parser.add_argument("--root-password", default=os.environ.get("MYSQL_ROOT_PASSWORD", "change_me"))
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()

    try:
        _check_docker_access()
    except RuntimeError as exc:
        print(f"[mysql_up] {exc}", file=sys.stderr)
        print(
            "\nIf Colima is installed, run:\n"
            "  colima start --cpu 2 --memory 4\n"
            "  docker context use colima\n"
            "  python scripts/mysql_up.py\n",
            file=sys.stderr,
        )
        sys.exit(1)

    compose_cmd = _detect_compose_command()
    up_cmd = [*compose_cmd, "-f", str(args.compose_file), "up", "-d", args.service]
    print(">>", " ".join(up_cmd))
    proc = _run(up_cmd)
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        sys.exit(proc.returncode)
    if args.wait:
        try:
            _wait_for_mysql(compose_cmd, args.compose_file, args.service, args.root_password, args.timeout)
        except TimeoutError as exc:
            print(f"[mysql_up] {exc}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
