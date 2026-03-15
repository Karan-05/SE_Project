#!/usr/bin/env python3
"""Upload CGCS artifacts to OpenAI storage."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from src.decomposition.openai_ops import ArtifactManifest, ensure_dir, get_openai_client

DATASETS = [
    Path("data/cgcs/train.jsonl"),
    Path("data/cgcs/dev.jsonl"),
    Path("data/cgcs/test.jsonl"),
]

REPORT_GLOBS = [
    "reports/ase2026_aegis/*.csv",
    "reports/ase2026_aegis/*.png",
]


def _collect_files(include_traces: bool) -> List[Path]:
    files: List[Path] = []
    for dataset in DATASETS:
        if dataset.exists():
            files.append(dataset)
    for pattern in REPORT_GLOBS:
        for path in Path(".").glob(pattern):
            if path.is_file():
                files.append(path)
    if include_traces:
        for trace in Path("reports/decomposition/traces").rglob("*.json"):
            files.append(trace)
    return files


def upload_file(path: Path, purpose: str, use_upload_api: bool):
    client = get_openai_client()
    if client is None:
        return None, "no_client"
    try:
        if use_upload_api:
            result = client.uploads.create(
                file=path.open("rb"),
                purpose=purpose,
            )
            file_id = result.id
            status = result.status
        else:
            result = client.files.create(file=path.open("rb"), purpose=purpose)
            file_id = result.id
            status = getattr(result, "status", "uploaded")
        return file_id, status
    except Exception as exc:  # pragma: no cover - network side effect
        print(f"[warn] Failed to upload {path}: {exc}", file=sys.stderr)
        return None, "error"


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload OpenAI artifacts for CGCS.")
    parser.add_argument("--manifest", type=Path, default=Path("openai_artifacts/manifest.json"))
    parser.add_argument("--include-traces", action="store_true")
    parser.add_argument("--trace-archive", type=Path, help="Optional zipped trace bundle.")
    parser.add_argument("--purpose", type=str, default="assistants")
    args = parser.parse_args()

    ensure_dir(args.manifest.parent)
    files = _collect_files(include_traces=args.include_traces)
    if args.trace_archive and args.trace_archive.exists():
        files.append(args.trace_archive)
    manifest = ArtifactManifest()
    for path in files:
        size_mb = path.stat().st_size / (1024 * 1024)
        use_upload_api = size_mb > 20
        file_id, status = upload_file(path, args.purpose, use_upload_api)
        manifest.add_record(
            path=str(path),
            file_id=file_id,
            purpose=args.purpose,
            status=status,
        )
    args.manifest.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    print(f"Stored manifest for {len(files)} artifacts at {args.manifest}")


if __name__ == "__main__":
    main()
