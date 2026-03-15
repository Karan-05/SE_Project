"""Rescue + expansion orchestration for the public-repo pilot."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence

from scripts.public_repos.validate_cgcs_workspaces import (
    ValidationSettings,
    build_summary as build_validation_summary,
    validate_workspace,
)

from . import bootstrap, expansion, selection

SUCCESS_VERDICTS = {"runnable", "runnable_without_build"}
PYTHON_RESCUE_FAILURES = {
    "missing_python_packaging_tool",
    "missing_python_build_module",
    "missing_python_packaging_stack",
}
NODE_RESCUE_FAILURES = {"missing_node_package_manager"}


def _compact_result(record: Mapping[str, object]) -> dict[str, object]:
    return {
        "final_verdict": record.get("final_verdict"),
        "failure_category": record.get("failure_category"),
        "install_status": record.get("install_status"),
        "build_status": record.get("build_status"),
        "test_status": record.get("test_status"),
    }


@dataclass(slots=True)
class RescueAction:
    repo_key: str
    action_type: str
    package_manager: str | None = None
    reason: str | None = None


@dataclass(slots=True)
class RescueOutcome:
    repo_key: str
    success: bool
    validation_before: dict[str, object]
    validation_after: Optional[dict[str, object]]
    action: Optional[RescueAction]
    commands: list[str] = field(default_factory=list)
    failure_reason: str | None = None


@dataclass(slots=True)
class PilotRescueResult:
    validation_results: list[dict[str, object]]
    validation_summary: dict[str, object]
    attempt_log: list[dict[str, object]]
    expansion_log: list[dict[str, object]]
    rescue_summary: dict[str, object]
    expansion_summary: dict[str, object]
    current_subset: list[dict[str, object]]
    hard_blocked_repos: list[str]


class PilotRescueOrchestrator:
    """Coordinates validation, rescue, and backfill for the pilot subset."""

    def __init__(
        self,
        *,
        seed_pool: Sequence[Mapping[str, object]],
        manifest_entries: Sequence[Mapping[str, object]],
        initial_subset: Sequence[Mapping[str, object]],
        initial_size: int,
        target_validated: int,
        max_pilot_size: int,
        max_rounds: int,
        rng_seed: int,
        validation_settings: ValidationSettings,
        validator: Callable[[Mapping[str, object], ValidationSettings], dict[str, object]] = validate_workspace,
    ) -> None:
        self.seed_pool = [dict(entry) for entry in seed_pool]
        self.manifest_by_repo = {
            str(entry.get("repo_key") or ""): dict(entry) for entry in manifest_entries
        }
        self.initial_subset = [dict(entry) for entry in initial_subset]
        self.initial_size = max(1, initial_size)
        self.target_validated = max(1, target_validated)
        self.max_pilot_size = max(self.initial_size, max_pilot_size)
        self.max_rounds = max_rounds
        self.rng_seed = rng_seed
        self.validation_settings = validation_settings
        self.validator = validator

        self.current_entries: list[dict[str, object]] = []
        self.results_by_repo: dict[str, dict[str, object]] = {}
        self.attempt_log: list[dict[str, object]] = []
        self.expansion_log: list[dict[str, object]] = []
        self.rescue_counts: dict[str, int] = {}
        self.original_repo_keys: set[str] = set()
        self.hard_blocked: set[str] = set()
        self.attempted_keys: set[str] = set()
        self.replacement_origin: dict[str, str] = {}
        self.round_initial_successes = 0
        self._init_selection()

    def _init_selection(self) -> None:
        merged: list[dict[str, object]] = []
        for entry in self.initial_subset[: self.initial_size]:
            repo_key = str(entry.get("repo_key") or "")
            manifest = self.manifest_by_repo.get(repo_key, {})
            merged_entry = selection.merge_manifest_entry(manifest, entry)
            merged.append(merged_entry)
            self.original_repo_keys.add(repo_key)
        if len(merged) < self.initial_size:
            needed = self.initial_size - len(merged)
            replacements = expansion.select_replacements(
                self.seed_pool,
                current_entries=merged,
                attempted_keys=set(),
                hard_blocked=set(),
                max_new=needed,
                rng_seed=self.rng_seed,
            )
            for decision in replacements:
                self.replacement_origin[decision.repo_key] = ""
                merged.append(decision.entry)
        selection.normalize_pilot_rank(merged)
        self.current_entries = merged

    def _record_attempt(
        self,
        *,
        entry: Mapping[str, object],
        round_idx: int,
        before_result: dict[str, object],
        after_result: Optional[dict[str, object]],
        action: Optional[RescueAction],
        hard_blocked: bool,
    ) -> None:
        repo_key = str(entry.get("repo_key") or "")
        self.attempt_log.append(
            {
                "repo_key": repo_key,
                "repo_url": entry.get("repo_url"),
                "pilot_round": round_idx,
                "was_original_subset": repo_key in self.original_repo_keys,
                "replacement_for": self.replacement_origin.get(repo_key),
                "validation_result_before": before_result,
                "validation_result_after": after_result,
                "rescue_actions": [action.action_type] if action else [],
                "hard_blocked": hard_blocked,
            }
        )

    def _validate_entry(self, entry: Mapping[str, object]) -> dict[str, object]:
        repo_key = str(entry.get("repo_key") or "")
        result = self.validator(entry, self.validation_settings)
        self.results_by_repo[repo_key] = result
        return result

    def _plan_rescue(self, result: Mapping[str, object], entry: Mapping[str, object]) -> Optional[RescueAction]:
        repo_key = str(entry.get("repo_key") or "")
        failure_category = str(result.get("failure_category") or "")
        if failure_category in PYTHON_RESCUE_FAILURES:
            return RescueAction(
                repo_key=repo_key,
                action_type="python_bootstrap",
                reason=failure_category,
            )
        if failure_category in NODE_RESCUE_FAILURES:
            manifest_pkg = str(entry.get("package_manager") or "") or None
            return RescueAction(
                repo_key=repo_key,
                action_type="node_package_manager",
                reason=failure_category,
                package_manager=manifest_pkg,
            )
        return None

    def _execute_rescue(self, action: RescueAction, entry: Mapping[str, object]) -> RescueOutcome:
        repo_key = action.repo_key
        before = _compact_result(self.results_by_repo.get(repo_key, {}))
        local_path = Path(str(entry.get("local_path") or ""))
        if action.action_type == "python_bootstrap":
            report = bootstrap.ensure_python_packaging_stack(local_path)
            if not report.success:
                return RescueOutcome(
                    repo_key=repo_key,
                    success=False,
                    validation_before=before,
                    validation_after=None,
                    action=action,
                    commands=report.commands_run,
                    failure_reason=report.failure_reason,
                )
        elif action.action_type == "node_package_manager":
            report = bootstrap.ensure_node_package_manager(local_path, action.package_manager)
            if not report.success:
                return RescueOutcome(
                    repo_key=repo_key,
                    success=False,
                    validation_before=before,
                    validation_after=None,
                    action=action,
                    commands=report.commands_run,
                    failure_reason=report.failure_reason,
                )
        else:
            return RescueOutcome(
                repo_key=repo_key,
                success=False,
                validation_before=before,
                validation_after=None,
                action=action,
                failure_reason="unknown_action",
            )

        refreshed = self._validate_entry(entry)
        after = _compact_result(refreshed)
        return RescueOutcome(
            repo_key=repo_key,
            success=refreshed.get("final_verdict") in SUCCESS_VERDICTS,
            validation_before=before,
            validation_after=after,
            action=action,
            commands=[],
        )

    def _validated_repo_keys(self) -> set[str]:
        return {
            repo_key
            for repo_key, result in self.results_by_repo.items()
            if result.get("final_verdict") in SUCCESS_VERDICTS
        }

    def _drop_hard_blocked(self) -> None:
        self.current_entries = [entry for entry in self.current_entries if entry.get("repo_key") not in self.hard_blocked]

    def _expand_if_needed(self, round_idx: int) -> None:
        desired_size = min(self.max_pilot_size, max(self.initial_size, self.target_validated * 2))
        needed = desired_size - len(self.current_entries)
        if needed <= 0:
            return
        replacements = expansion.select_replacements(
            self.seed_pool,
            current_entries=self.current_entries,
            attempted_keys=self.attempted_keys,
            hard_blocked=self.hard_blocked,
            max_new=needed,
            rng_seed=self.rng_seed + round_idx,
        )
        for decision in replacements:
            repo_key = decision.repo_key
            manifest = self.manifest_by_repo.get(repo_key, {})
            merged_entry = selection.merge_manifest_entry(manifest, decision.entry)
            self.current_entries.append(merged_entry)
            self.replacement_origin[repo_key] = decision.replacement_for or ""
            self.expansion_log.append(
                {
                    "pilot_round": round_idx,
                    "repo_key": repo_key,
                    "reason": decision.reason,
                }
            )
        if replacements:
            selection.normalize_pilot_rank(self.current_entries)

    def run(self) -> PilotRescueResult:
        round_idx = 1
        initial_success_logged = False
        while round_idx <= self.max_rounds:
            processed_this_round: set[str] = set()
            for entry in list(self.current_entries):
                repo_key = str(entry.get("repo_key") or "")
                if not repo_key or repo_key in processed_this_round:
                    continue
                self.attempted_keys.add(repo_key)
                result = self._validate_entry(entry)
                before = _compact_result(result)

                if result.get("final_verdict") in SUCCESS_VERDICTS:
                    if not initial_success_logged:
                        self.round_initial_successes += 1
                    self._record_attempt(
                        entry=entry,
                        round_idx=round_idx,
                        before_result=before,
                        after_result=before,
                        action=None,
                        hard_blocked=False,
                    )
                    processed_this_round.add(repo_key)
                    continue

                action = self._plan_rescue(result, entry)
                if action:
                    outcome = self._execute_rescue(action, entry)
                    if outcome.success:
                        self.rescue_counts[action.action_type] = self.rescue_counts.get(action.action_type, 0) + 1
                        self._record_attempt(
                            entry=entry,
                            round_idx=round_idx,
                            before_result=before,
                            after_result=outcome.validation_after,
                            action=action,
                            hard_blocked=False,
                        )
                    else:
                        self.hard_blocked.add(repo_key)
                        self._record_attempt(
                            entry=entry,
                            round_idx=round_idx,
                            before_result=before,
                            after_result=outcome.validation_after,
                            action=action,
                            hard_blocked=True,
                        )
                else:
                    self.hard_blocked.add(repo_key)
                    self._record_attempt(
                        entry=entry,
                        round_idx=round_idx,
                        before_result=before,
                        after_result=None,
                        action=None,
                        hard_blocked=True,
                    )
                processed_this_round.add(repo_key)

            validated = self._validated_repo_keys()
            if len(validated) >= self.target_validated:
                break
            self._drop_hard_blocked()
            self._expand_if_needed(round_idx)
            if not self.current_entries:
                break
            round_idx += 1
            initial_success_logged = True

        final_results = [
            self.results_by_repo[str(entry.get("repo_key") or "")]
            for entry in self.current_entries
            if str(entry.get("repo_key") or "") in self.results_by_repo
        ]
        validation_summary = build_validation_summary(final_results)

        rescue_summary = {
            "initial_validated": self.round_initial_successes,
            "final_validated": len(self._validated_repo_keys()),
            "rescue_counts": dict(self.rescue_counts),
            "hard_blocked": len(self.hard_blocked),
        }
        expansion_summary = {
            "replacements_added": len(self.expansion_log),
            "current_subset_size": len(self.current_entries),
            "attempted_repos": len(self.attempted_keys),
        }
        return PilotRescueResult(
            validation_results=final_results,
            validation_summary=validation_summary,
            attempt_log=self.attempt_log,
            expansion_log=self.expansion_log,
            rescue_summary=rescue_summary,
            expansion_summary=expansion_summary,
            current_subset=self.current_entries,
            hard_blocked_repos=sorted(self.hard_blocked),
        )
