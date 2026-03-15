#!/usr/bin/env python3
"""Generate seeded repair tasks from validated pilot workspaces."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List

from src.decomposition.public_repo_tasks.seeding import (
    SeedMutation,
    find_mutation_candidates,
    apply_mutation,
    generate_unified_diff,
)
from src.decomposition.public_repo_tasks.contracts import generate_contracts_for_mutations, build_task_metadata


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    if not path.exists():
        return records
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _write_jsonl(path: Path, records: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def _safe_task_id(repo_key: str, index: int) -> str:
    """Turn github.com/owner/repo  →  public_pilot_owner_repo_000"""
    parts = str(repo_key).replace("https://", "").split("/")
    owner_repo = "_".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
    # sanitise
    safe = "".join(c if c.isalnum() or c == "_" else "_" for c in owner_repo)
    return f"public_pilot_{safe}_{index:03d}"


def _build_prompt(mutations: List[SeedMutation], repo_key: str, language: str) -> str:
    lines = [
        f"You are fixing a seeded bug in the repository `{repo_key}`.",
        f"Language: {language}",
        "",
        "The following mutation(s) were injected into the source code:",
    ]
    for mut in mutations:
        lines.append(f"  - [{mut.family.value}] `{mut.file_path}` line {mut.line_number}: {mut.description}")
    lines += [
        "",
        "Your task:",
        "1. Identify the injected bug(s) in the listed file(s).",
        "2. Revert each mutation to restore correct behaviour.",
        "3. Ensure the repository's test suite passes after your fix.",
    ]
    return "\n".join(lines)


def _build_test_commands(entry: Dict[str, Any]) -> List[str]:
    cmd = str(entry.get("test_command") or "")
    if cmd:
        return [cmd]
    lang = str(entry.get("language") or "").lower()
    if lang in ("python",):
        return ["pytest -q"]
    if lang in ("javascript", "typescript"):
        return ["npm test"]
    if lang == "java":
        return ["./gradlew test"]
    return []


def _build_setup_commands(entry: Dict[str, Any]) -> List[str]:
    install = str(entry.get("install_command") or "")
    build = str(entry.get("build_command") or "")
    cmds: List[str] = []
    if install:
        cmds.append(install)
    if build:
        cmds.append(build)
    return cmds


def _infer_target_tests(entry: Dict[str, Any], limit: int = 5) -> List[str]:
    tests = entry.get("detected_test_paths") or entry.get("target_tests") or []
    normalized: List[str] = []
    for path in tests:
        if not path:
            continue
        normalized.append(str(path).strip())
        if len(normalized) >= limit:
            break
    if not normalized and entry.get("test_command"):
        normalized.append(str(entry["test_command"]))
    return normalized


def generate_task_for_repo(
    entry: Dict[str, Any],
    *,
    task_index: int,
    tasks_root: Path,
    mutations_per_task: int,
    seed: int,
    dry_run: bool,
) -> Optional[Dict[str, Any]]:
    repo_key = str(entry.get("repo_key") or "")
    local_path_str = str(entry.get("local_path") or "")
    language = str(entry.get("language") or "python").lower()
    task_id = _safe_task_id(repo_key, task_index)

    if not local_path_str:
        return None
    local_path = Path(local_path_str)
    if not local_path.exists():
        return None

    # Find mutation candidates
    candidates = find_mutation_candidates(
        local_path,
        max_per_file=mutations_per_task,
        max_total=mutations_per_task,
        rng_seed=seed,
    )
    if not candidates:
        return None

    mutations = candidates[:mutations_per_task]
    contract_items = generate_contracts_for_mutations(mutations, repo_key=repo_key)
    patch_lines: List[str] = []
    for mut in mutations:
        patch_lines.append(generate_unified_diff(local_path, mut))
    patch_text = "\n".join(patch_lines)

    task_dir = tasks_root / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    if not dry_run:
        workspace = task_dir / "workspace"
        if workspace.exists():
            shutil.rmtree(workspace)
        shutil.copytree(local_path, workspace, ignore_dangling_symlinks=True)
        for mut in mutations:
            apply_mutation(workspace, mut, backup=False)
    else:
        workspace = local_path

    patch_path = task_dir / "seed.patch"
    patch_path.write_text(patch_text, encoding="utf-8")

    metadata = build_task_metadata(
        mutations,
        contract_items,
        entry,
        task_id=task_id,
        seed_patch_path=str(patch_path),
    )

    prompt = _build_prompt(mutations, repo_key, language)

    mutation_type = mutations[0].family.value if len(mutations) == 1 else "multi_mutation"
    mutation_description = "; ".join(mut.description for mut in mutations)
    target_tests = _infer_target_tests(entry)
    expected_behavior = " ".join(mut.expected_behavior for mut in mutations)
    contract_payload = contract_items
    oracle_restore_info = {
        "patch_path": str(patch_path),
        "mutation_count": len(mutations),
    }

    task_spec: Dict[str, Any] = {
        "id": task_id,
        "task_id": task_id,
        "problem_statement": prompt,
        "statement": prompt,
        "prompt": prompt,
        "type": "bugfix",
        "task_type": "bugfix",
        "difficulty": "M",
        "language": language,
        "dataset": "public_repo_pilot",
        "dataset_source": "seeded_repair",
        "repo_url": entry.get("repo_url"),
        "repo_local_path": entry.get("local_path"),
        "repo_snapshot": entry.get("workspace_id"),
        "repo_path": str(workspace),
        "target_files": [m.file_path for m in mutations],
        "file_context": [m.file_path for m in mutations],
        "allowed_edit_paths": [m.file_path for m in mutations],
        "apply_mode": "edit_batch",
        "test_commands": _build_test_commands(entry),
        # Empty setup_commands so harness uses "skipped" strategy — workspace
        # is a copy of the already-cloned repo; reinstalling deps is not needed
        # for the LLM to produce and log an edit payload.
        "setup_commands": [],
        "timeout_seconds": 60.0,
        "test_command": entry.get("test_command") or "",
        "target_tests": target_tests,
        "mutation_type": mutation_type,
        "mutation_description": mutation_description,
        "expected_behavior": expected_behavior,
        "contract_items": contract_payload,
        "oracle_restore_info": oracle_restore_info,
        # Leave runtime_family blank to prevent auto-inference of npm/pip installs
        "runtime_family": "",
        "package_manager": None,
        "allow_file_creation": False,
        "task_is_real_world": True,
        "requires_network": False,
        "metadata": metadata,
    }

    if not dry_run:
        _write_json(task_dir / "task.json", task_spec)

    return {
        "task_id": task_id,
        "repo_key": repo_key,
        "language": language,
        "task_json_path": str(task_dir / "task.json"),
        "patch_path": str(patch_path),
        "workspace_path": str(workspace),
        "mutation_count": len(mutations),
        "contract_item_count": len(contract_items),
        "dry_run": dry_run,
        "mutation_family": mutation_type,
        "pilot_rank": entry.get("pilot_rank"),
        "selection_reason": entry.get("selection_reason"),
    }


def generate_tasks(
    *,
    validated_path: Path,
    out_dir: Path,
    mutations_per_task: int,
    max_tasks: int,
    seed: int,
    dry_run: bool,
    allow_runnable_without_build: bool,
) -> Dict[str, Any]:
    validations = _load_jsonl(validated_path)
    allowed_verdicts = {"runnable"}
    if allow_runnable_without_build:
        allowed_verdicts.add("runnable_without_build")
    runnable_entries = [
        entry
        for entry in validations
        if entry.get("final_verdict") in allowed_verdicts and entry.get("is_runnable")
    ]
    runnable_entries.sort(key=lambda r: (int(r.get("pilot_rank") or 0), str(r.get("repo_key") or "")))

    if max_tasks > 0:
        runnable_entries = runnable_entries[: max_tasks]

    print(f"[seed-tasks] Generating tasks for {len(runnable_entries)} repos ...")

    out_dir.parent.mkdir(parents=True, exist_ok=True)
    if out_dir.name == "tasks":
        tasks_root = out_dir
        manifest_base = out_dir
    else:
        tasks_root = out_dir / "tasks"
        manifest_base = out_dir
    manifest: List[Dict[str, Any]] = []
    skipped = 0

    for idx, entry in enumerate(runnable_entries):
        repo_key = entry.get("repo_key", f"repo_{idx}")
        print(f"  → {repo_key}", flush=True)
        result = generate_task_for_repo(
            entry,
            task_index=idx,
            tasks_root=tasks_root,
            mutations_per_task=mutations_per_task,
            seed=seed,
            dry_run=dry_run,
        )
        if result is None:
            print(f"     SKIP (no mutation candidates or missing workspace)")
            skipped += 1
        else:
            print(f"     task_id={result['task_id']}  mutations={result['mutation_count']}")
            manifest.append(result)

    out_manifest = manifest_base / "tasks_manifest.jsonl"
    out_summary = manifest_base / "tasks_summary.json"
    _write_jsonl(out_manifest, manifest)
    family_counts: Dict[str, int] = {}
    for item in manifest:
        family = item.get("mutation_family") or "unknown"
        family_counts[family] = family_counts.get(family, 0) + 1
    summary = {
        "validated_repos": len(validations),
        "runnable_repos": len(runnable_entries),
        "tasks_generated": len(manifest),
        "skipped": skipped,
        "mutations_per_task": mutations_per_task,
        "seed": seed,
        "dry_run": dry_run,
        "mutation_families": family_counts,
    }
    _write_json(out_summary, summary)
    print(f"[seed-tasks] Task manifest → {out_manifest}")
    print(f"[seed-tasks] Summary → {out_summary}")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validated", type=Path, default=Path("data/public_repos/pilot/workspace_validation.jsonl"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/public_repos/pilot"))
    parser.add_argument("--mutations-per-task", type=int, default=1)
    parser.add_argument("--max-tasks", type=int, default=0, help="Limit number of seeded tasks (0 = use all runnable repos)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-runnable-without-build", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    generate_tasks(
        validated_path=args.validated,
        out_dir=args.out_dir,
        mutations_per_task=args.mutations_per_task,
        max_tasks=args.max_tasks,
        seed=args.seed,
        dry_run=args.dry_run,
        allow_runnable_without_build=args.allow_runnable_without_build,
    )


if __name__ == "__main__":
    main()
