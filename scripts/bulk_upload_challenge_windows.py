#!/usr/bin/env python3
"""Bulk upload helper for challenge_data/challengeData_* windows."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

if __package__ in {None, ""}:
    REPO_ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(REPO_ROOT))

from uploader import Uploader

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s | %(message)s"


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format=LOG_FORMAT)


def _resolve_directories(root: Path, inputs: Sequence[str]) -> List[Path]:
    if inputs:
        directories: List[Path] = []
        missing: List[Path] = []
        for entry in inputs:
            path = Path(entry).expanduser().resolve()
            if path.is_dir():
                directories.append(path)
            else:
                missing.append(path)
        if missing:
            missing_list = "\n".join(str(path) for path in missing)
            raise FileNotFoundError(f"The following directories do not exist:\n{missing_list}")
        return directories
    pattern = "challengeData_*"
    directories = sorted(
        path for path in root.glob(pattern) if path.is_dir()
    )
    return directories


def _summarize(results: Iterable[Tuple[Path, bool, str]]) -> None:
    print("\nBulk upload summary")
    print("-------------------")
    for directory, ok, message in results:
        status = "OK" if ok else "FAILED"
        print(f"{status:7} | {directory} | {message}")


def run_bulk_upload(directories: Sequence[Path]) -> Tuple[int, List[Tuple[Path, bool, str]]]:
    results: List[Tuple[Path, bool, str]] = []
    skip_members = os.environ.get("TOPCODER_SKIP_MEMBER_FETCH", "").lower() in {"1", "true", "yes"}
    logger = logging.getLogger("bulk_upload")
    logger.info(
        "Starting bulk upload for %s window(s). TOPCODER_SKIP_MEMBER_FETCH=%s",
        len(directories),
        skip_members,
    )

    for directory in directories:
        logger.info("Processing %s", directory)
        try:
            Uploader(str(directory))
        except KeyboardInterrupt:
            logger.warning("Interrupted while uploading %s", directory)
            results.append((directory, False, "interrupted by user"))
            break
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Failed while uploading %s", directory)
            results.append((directory, False, str(exc)))
        else:
            results.append((directory, True, "completed"))

    failures = [entry for entry in results if not entry[1]]
    return (1 if failures else 0, results)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the uploader across all challengeData_* directories."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("challenge_data"),
        help="Directory containing challengeData_* folders (default: challenge_data)",
    )
    parser.add_argument(
        "directories",
        nargs="*",
        help="Optional explicit directories to upload. "
        "If omitted, all challengeData_* directories under --root are processed.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging for troubleshooting.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    _configure_logging(args.verbose)

    root = args.root.expanduser().resolve()
    if not args.directories and not root.is_dir():
        logging.getLogger("bulk_upload").error("%s is not a directory.", root)
        return 1

    try:
        directories = _resolve_directories(root, args.directories)
    except FileNotFoundError as exc:
        logging.getLogger("bulk_upload").error("%s", exc)
        return 1

    if not directories:
        logger = logging.getLogger("bulk_upload")
        if args.directories:
            logger.error("No valid directories were provided.")
        else:
            logger.error("No challengeData_* directories found under %s", root)
        return 1

    exit_code, results = run_bulk_upload(directories)
    _summarize(results)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
