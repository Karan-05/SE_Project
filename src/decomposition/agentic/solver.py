"""LLM-backed helpers to generate and repair implementations."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Dict, List, Optional, Tuple

from src.decomposition.interfaces import DecompositionContext, DecompositionPlan
from src.decomposition.agentic.heuristics import try_generate as try_heuristic_solution
from src.decomposition.self_verify import FailureSummary
from src.decomposition.strategies._utils import BudgetTracker, build_implementation_contract
from src.decomposition.real_repo.edit_batch import parse_repo_edit_payload
from src.decomposition.agentic.executor import ExecutionResult
from src.decomposition.agentic.semantic import SemanticVariantConfig
from src.decomposition.real_repo.contracts import format_contract_summary, get_contract_items
from src.providers import llm

def _extract_code_block(payload: str) -> str:
    fence = "```"
    if fence not in payload:
        return payload.strip()
    parts = payload.split(fence)
    if len(parts) < 3:
        return payload.strip()
    code = parts[2] if parts[1].strip() else parts[1]
    return code.strip()


def _fallback_stub(ctx: DecompositionContext) -> str:
    entry_point = str(ctx.metadata.get("entry_point") or "solve")
    return f"def {entry_point}(*args, **kwargs):\n    raise NotImplementedError('generation failed')\n"


def _tests_preview(ctx: DecompositionContext, limit: int = 3) -> str:
    tests = ctx.metadata.get("tests", [])
    snippets: List[str] = []
    for test in tests[:limit]:
        name = str(test.get("name") or f"sample_{len(snippets)}")
        expected = test.get("expected", "")
        raw_input = test.get("input", "")
        snippets.append(f"- {name}: input={raw_input} -> expected={expected}")
    if not snippets:
        return "- No explicit tests provided."
    return "\n".join(snippets)


def _plan_outline(plan: DecompositionPlan, limit: int = 8) -> str:
    if not plan.subtasks:
        return "No explicit subtasks; reason end-to-end."
    return "\n".join(f"- {step}" for step in plan.subtasks[:limit])


def _diagnostics_summary(plan: DecompositionPlan) -> str:
    if not plan.diagnostics:
        return "n/a"
    highlights = []
    for key, value in plan.diagnostics.items():
        if not value:
            continue
        highlights.append(f"{key}={value}")
    return ", ".join(highlights[:8]) or "n/a"


def _is_repo_task(ctx: DecompositionContext) -> bool:
    metadata = ctx.metadata or {}
    return bool(metadata.get("repo_task") or metadata.get("repo_path"))


def _repo_expected_files(ctx: DecompositionContext, plan: DecompositionPlan) -> List[str]:
    metadata = ctx.metadata if isinstance(ctx.metadata, dict) else {}
    expected = metadata.get("implementation_target_files") or metadata.get("expected_files")
    if not expected:
        expected = metadata.get("repo_target_files") or plan.target_files or plan.candidate_files or []
    files: List[str] = []
    for entry in expected or []:
        entry_str = str(entry).strip()
        if entry_str and entry_str not in files:
            files.append(entry_str)
    return files


def _repo_requires_multi_file(ctx: DecompositionContext, plan: DecompositionPlan) -> bool:
    metadata = ctx.metadata if isinstance(ctx.metadata, dict) else {}
    if metadata.get("multi_file_localization"):
        return True
    expected = _repo_expected_files(ctx, plan)
    return len({path for path in expected if path}) > 1


def _repo_context_snippets(ctx: DecompositionContext, limit: int = 3, max_chars: int = 800) -> str:
    metadata = ctx.metadata if isinstance(ctx.metadata, dict) else {}
    snippets = metadata.get("repo_context_snippets") or []
    if not isinstance(snippets, list):
        return ""
    blocks: List[str] = []
    for entry in snippets[:limit]:
        if not isinstance(entry, dict):
            continue
        path = str(entry.get("path") or "").strip()
        preview = entry.get("preview") or entry.get("snippet") or ""
        if not path or not preview:
            continue
        text = str(preview).strip()
        if len(text) > max_chars:
            text = text[:max_chars].rstrip() + "..."
        blocks.append(f"--- {path} ---\n{text}")
    return "\n\n".join(blocks)


def _repo_edit_guidance(
    ctx: DecompositionContext,
    plan: DecompositionPlan,
    config: Optional[SemanticVariantConfig] = None,
) -> str:
    metadata = ctx.metadata or {}
    repo_path = str(metadata.get("repo_path") or "local workspace")
    target_files = metadata.get("repo_target_files") or []
    implementation_files = metadata.get("implementation_target_files") or target_files
    file_context = metadata.get("repo_file_context") or []
    expected_files = metadata.get("expected_files") or target_files
    related_tests = metadata.get("related_tests") or metadata.get("repo_related_tests") or []
    support_files = metadata.get("support_files") or file_context
    test_files = metadata.get("test_files") or related_tests
    target_lines = "\n".join(f"- {path}" for path in (implementation_files[:10] or expected_files[:10]))
    context_lines = "\n".join(f"- {path}" for path in file_context[:8]) if file_context else ""
    support_lines = "\n".join(f"- {path}" for path in support_files[:6]) if support_files else ""
    test_lines = "\n".join(f"- {path}" for path in test_files[:6]) if test_files else ""
    contract_items = get_contract_items(ctx.metadata or {})
    contract_section = ""
    if contract_items and (not config or config.emphasize_contract):
        contract_section = "Contract requirements:\n" + format_contract_summary(contract_items) + "\n"
    candidate_hint = ""
    if plan.candidate_files:
        preview = "\n".join(f"- {path}" for path in plan.candidate_files[:10])
        candidate_hint = f"\nLikely files to edit:\n{preview}\n"
    edit_policy = metadata.get("allowed_editable_files")
    policy_lines = []
    if isinstance(edit_policy, dict):
        for scope, entries in edit_policy.items():
            if not entries:
                continue
            preview = ", ".join(entries[:3])
            policy_lines.append(f"{scope}: {preview}")
    policy_note = f"Allowed edit policy -> {'; '.join(policy_lines)}\n" if policy_lines else ""
    tests_line = ", ".join(related_tests[:6]) if related_tests else "see package test suite"
    context_section = f"\nWorkspace context:\n{context_lines}\n" if context_lines else ""
    support_section = f"\nSupport files:\n{support_lines}\n" if support_lines else ""
    test_section = (
        f"\nTest files (read-only unless explicitly listed under the edit policy):\n{test_lines}\n"
        if test_lines
        else ""
    )
    expected_note = ""
    if expected_files:
        expected_note = f"Expected edited files: {', '.join(expected_files[:6])}.\n"
    expected_multi = _repo_requires_multi_file(ctx, plan)
    multi_note = ""
    if expected_multi:
        multi_note = (
            "Multi-file contract: controller/service/data files listed above must stay in sync. "
            "When tests touch both HTTP controllers and services, update each file in the same reply.\n"
        )
    schema_hints = metadata.get("schema_hints") or []
    schema_block = ""
    if schema_hints and config and config.schema_reminders:
        schema_block = "Schema hints:\n" + "\n".join(f"- {hint}" for hint in schema_hints[:6]) + "\n"
    instructions = (
        "You must return **only** a JSON payload describing multi-file edits. Format exactly as:\n"
        "```json\n"
        "{\n"
        "  \"edits\": [\n"
        "    {\n"
        "      \"path\": \"modules/Problems/services/ProblemsService.js\",\n"
        "      \"mode\": \"rewrite\",\n"
        "      \"content\": \"<full updated file contents>\"\n"
        "    }\n"
        "  ],\n"
        "  \"localized\": true\n"
        "}\n"
        "```\n"
        "Rules:\n"
        "1. Include the **entire** replacement contents for every updated file (JavaScript/JSON/etc.).\n"
        "2. Use valid JSON (double quotes, escaped newlines). No diff hunks, ellipses, or commentary.\n"
        "3. Touch only repository files listed below or inside the candidate list. Tests remain read-only unless explicitly listed under the edit policy.\n"
        "4. When multiple target files are listed, provide separate edit objects so controller/service/data stay consistent.\n"
        "5. Preserve existing exports, routing signatures, and middleware wiring; keep unrelated behavior identical.\n"
        "6. Cross-check the referenced tests when reasoning; the patch must satisfy them exactly (status codes, payload shapes, ordering, limits, tag filters, etc.).\n"
        "7. Never reference BEGIN/END markers; the repository consumes direct rewrites.\n"
        "8. Set `\"allow_create\": true` on an edit if you create a brand-new file.\n"
        "9. Controllers/services in this repo intentionally use generator functions (`function*`). Do not convert them to async/await or change module.exports signatures unless tests demand it.\n"
        "10. Guard existing behavior: outside the described contract (filters, metadata, 404 payloads) everything must remain byte-identical so existing tests continue to pass.\n"
        "11. If you decide not to edit an implementation target file, include a `\"skipped_targets\": [\"path\", ...]` field in the payload metadata explaining why.\n"
        "12. Satisfy every requirement in the prompt (filters, metadata totals, 404 handling, tag normalization, etc.), not just the first failure you observe.\n"
        "13. Emit a `\"contract_review\"` array that lists each contract clause with `{\"id\": \"CLAUSE\", \"status\": \"covered\"|\"needs-work\", \"notes\": \"how witnesses are handled\"}` so the harness can confirm CGCS state.\n"
    )
    if config and config.require_checklist:
        instructions += (
            "\nBefore listing edits, add a `\"contract_review\"` array summarizing every contract id with "
            "`\"status\": \"covered\"` or `\"status\": \"needs-work\"` plus a short plan. "
            "Only emit the `edits` array after confirming that each contract item is addressed."
        )
    if config and config.require_skip_rationale:
        instructions += "\nIf you intentionally defer a contract item, explain why inside the contract review entry."
    repo_summary = (
        f"Repository workspace: `{repo_path}`\n"
        f"Implementation target files:\n{target_lines or '  (refer to candidate files)'}\n"
        f"{context_section}"
        f"{support_section}"
        f"{test_section}"
        f"{expected_note}"
        f"{schema_block}"
        f"{contract_section}"
        f"Tests validating the change: {tests_line}\n"
        f"{policy_note}"
        f"{multi_note}"
    )
    return repo_summary + candidate_hint + instructions


def _repo_primary_path(ctx: DecompositionContext, plan: DecompositionPlan) -> str:
    metadata = ctx.metadata or {}
    for source in (
        plan.target_files or [],
        metadata.get("repo_target_files") or [],
        plan.candidate_files or [],
        metadata.get("repo_file_context") or [],
    ):
        for entry in source:
            entry_str = str(entry).strip()
            if entry_str:
                return entry_str
    return "repo_output.txt"


def _build_repo_diagnosis(
    ctx: DecompositionContext,
    plan: DecompositionPlan,
    summary: FailureSummary,
    last_result: Optional[ExecutionResult],
) -> str:
    metadata = ctx.metadata if isinstance(ctx.metadata, dict) else {}
    related_tests = metadata.get("related_tests") or metadata.get("repo_related_tests") or []
    expected_files = _repo_expected_files(ctx, plan)
    last_files = list(last_result.edited_files) if last_result and last_result.edited_files else []
    pending = [path for path in expected_files if path not in set(last_files)]
    last_mode = ""
    if last_result and last_result.edit_metadata:
        last_mode = str(last_result.edit_metadata.get("edit_mode") or "")
    diag = {
        "failing_tests": summary.failing_tests[:6],
        "assertions": summary.assertion_msgs[:4],
        "trace_excerpt": summary.brief_trace[:3],
        "error_types": summary.error_types[:4],
        "last_edit_mode": last_mode,
        "last_files_edited": last_files[:6],
        "untouched_expected_files": pending[:6],
        "expected_multi_file": _repo_requires_multi_file(ctx, plan),
        "tests_to_reference": related_tests[:6],
        "task_notes": str(metadata.get("notes") or metadata.get("repo_notes") or "")[:240],
    }
    return json.dumps(diag, indent=2)


def _format_cgcs_section(ctx: DecompositionContext, cgcs_state: Optional[Dict[str, object]]) -> str:
    if not cgcs_state:
        return ""
    items = {item.id: item for item in get_contract_items(ctx.metadata or {})}
    lines: List[str] = []
    active_clause = cgcs_state.get("active_clause") or cgcs_state.get("active_clause_id")
    if active_clause:
        desc = items.get(active_clause).description if items.get(active_clause) else ""
        detail = f"{active_clause}: {desc}" if desc else str(active_clause)
        lines.append(f"Active clause focus -> {detail}.")
    guards = cgcs_state.get("regression_guards") or []
    if guards:
        guard_lines = []
        for cid in guards[:6]:
            guard_desc = items.get(cid).description if items.get(cid) else ""
            guard_lines.append(f"{cid} ({guard_desc})" if guard_desc else cid)
        lines.append("Regression guards (keep satisfied): " + ", ".join(guard_lines))
    witness_samples = cgcs_state.get("witness_sample") or cgcs_state.get("witnesses") or []
    if witness_samples:
        preview = []
        for witness in witness_samples[:5]:
            test_case = str(witness.get("test_case") or "")
            message = str(witness.get("message") or "")[:160]
            preview.append(f"- {test_case}: {message}")
        lines.append("Linked witnesses:\n" + "\n".join(preview))
    if not lines:
        return ""
    return "CGCS state:\n" + "\n".join(lines) + "\n"


def _ensure_repo_payload(text: str, ctx: DecompositionContext, plan: DecompositionPlan) -> str:
    cleaned = text.strip()
    if not cleaned:
        path = _repo_primary_path(ctx, plan)
        payload = {"edits": [{"path": path, "mode": "rewrite", "content": ""}], "localized": True}
        return json.dumps(payload)
    parsed = parse_repo_edit_payload(cleaned)
    if parsed and parsed.edits:
        return cleaned
    path = _repo_primary_path(ctx, plan)
    payload = {
        "edits": [
            {
                "path": path,
                "mode": "rewrite",
                "content": cleaned,
            }
        ],
        "localized": True,
    }
    return json.dumps(payload)


def _build_repo_initial_prompt(
    strategy_name: str,
    ctx: DecompositionContext,
    plan: DecompositionPlan,
    semantic_config: Optional[SemanticVariantConfig] = None,
) -> str:
    contract = build_implementation_contract(ctx)
    repo_guidance = _repo_edit_guidance(ctx, plan, semantic_config)
    tests = _tests_preview(ctx)
    plan_outline = _plan_outline(plan)
    diagnostics = _diagnostics_summary(plan)
    notes = ctx.metadata.get("notes") or ctx.metadata.get("repo_notes") or ""
    notes_block = f"Important notes: {notes}\n" if notes else ""
    context_snippets = _repo_context_snippets(ctx)
    context_block = f"Repository context snippets:\n{context_snippets}\n\n" if context_snippets else ""
    return (
        f"You are executing decomposition strategy '{strategy_name}' on a real repository task.\n"
        f"{repo_guidance}\n"
        f"{context_block}"
        f"Problem statement:\n{ctx.problem_statement[:800]}\n\n"
        f"Execution plan:\n{plan_outline}\n\n"
        f"{notes_block}"
        f"Implementation contract: {contract}\n"
        f"Diagnostics: {diagnostics}\n"
        f"Sample tests:\n{tests}\n"
        "Return only the JSON edit payload described above."
    )


def build_initial_prompt(
    strategy_name: str,
    ctx: DecompositionContext,
    plan: DecompositionPlan,
    semantic_config: Optional[SemanticVariantConfig] = None,
) -> str:
    if _is_repo_task(ctx):
        return _build_repo_initial_prompt(strategy_name, ctx, plan, semantic_config)
    contract = build_implementation_contract(ctx)
    plan_outline = _plan_outline(plan)
    tests = _tests_preview(ctx)
    stats = f"depth={len(plan.subtasks)}, tests_listed={len(plan.tests)}"
    candidate_hint = ""
    if plan.candidate_files:
        preview = "\n".join(f"- {path}" for path in plan.candidate_files[:8])
        candidate_hint = f"\nLikely target files:\n{preview}\n"
    return (
        f"You are executing decomposition strategy '{strategy_name}'.\n"
        f"Problem statement:\n{ctx.problem_statement[:600]}\n\n"
        f"Implementation contract:\n{contract}\n\n"
        f"Execution plan:\n{plan_outline}\n\n"
        f"Diagnostics: { _diagnostics_summary(plan) }\n"
        f"{candidate_hint}"
        f"Sample tests:\n{tests}\n\n"
        f"Plan stats: {stats}\n"
        "Produce Python code that satisfies the contract and plan. "
        "Return only the implementation without commentary."
    )


def _build_repo_repair_prompt(
    strategy_name: str,
    ctx: DecompositionContext,
    plan: DecompositionPlan,
    summary: FailureSummary,
    current_code: str,
    subtask_focus: Optional[str],
    last_result: Optional[ExecutionResult],
    semantic_config: Optional[SemanticVariantConfig] = None,
) -> str:
    repo_guidance = _repo_edit_guidance(ctx, plan, semantic_config)
    contract = build_implementation_contract(ctx)
    failing = summary.failing_tests if summary else []
    trace = summary.brief_trace if summary else []
    assertions = summary.assertion_msgs if summary else []
    reproduction = summary.reproduction_hint if summary else ""
    plan_outline = _plan_outline(plan)
    diagnostics = _diagnostics_summary(plan)
    diagnosis_block = _build_repo_diagnosis(ctx, plan, summary, last_result) if summary else ""
    cgcs_note = ""
    lint_note = ""
    if last_result and last_result.edit_metadata:
        cgcs_note = _format_cgcs_section(ctx, last_result.edit_metadata.get("cgcs_state"))
        lint_errors = last_result.edit_metadata.get("lint_errors")
        if lint_errors:
            lint_list = lint_errors if isinstance(lint_errors, list) else [str(lint_errors)]
            lint_lines = "\n".join(f"- {err}" for err in lint_list[:4])
            lint_note = f"Payload lint errors last round:\n{lint_lines}\n"
    focus_note_parts: List[str] = []
    if isinstance(subtask_focus, str) and subtask_focus.startswith("implementation::"):
        impl_target = subtask_focus.split("implementation::", 1)[1]
        if impl_target:
            focus_note_parts.append(f"Critical implementation file requiring edits: {impl_target}.")
    if plan.subtask_file_map and subtask_focus in plan.subtask_file_map:
        files = plan.subtask_file_map[subtask_focus] or []
        if files:
            focus_note_parts.append(f"Subtask '{subtask_focus}' targets: {', '.join(files)}.")
    focus_note = f"{' '.join(focus_note_parts)}\n" if focus_note_parts else ""
    last_files = ", ".join(last_result.edited_files[:6]) if last_result and last_result.edited_files else ""
    pending_files = []
    expected_files = _repo_expected_files(ctx, plan)
    if expected_files and last_result and last_result.edited_files:
        pending_files = [path for path in expected_files if path not in set(last_result.edited_files)]
    last_files_note = f"Last patch edited: {last_files}.\n" if last_files else ""
    pending_note = ""
    if pending_files:
        pending_note = f"Target files still untouched: {', '.join(pending_files[:6])}.\n"
    context_snippets = _repo_context_snippets(ctx)
    context_block = f"Reference snippets:\n{context_snippets}\n\n" if context_snippets else ""
    coverage_note = ""
    if last_result:
        ratio = last_result.edit_metadata.get("contract_coverage")
        satisfied = last_result.edit_metadata.get("contract_satisfied") or []
        unsatisfied_ids = last_result.edit_metadata.get("contract_unsatisfied") or []
        unsatisfied_details = last_result.edit_metadata.get("contract_unsatisfied_details") or []
        if unsatisfied_details:
            bullets = "\n".join(f"- {detail}" for detail in unsatisfied_details[:6])
            coverage_note = (
                f"Contract coverage last attempt: {ratio if ratio is not None else 'n/a'} "
                f"(unsatisfied: {', '.join(unsatisfied_ids) or 'none'}).\n"
                f"Outstanding contract items:\n{bullets}\n"
            )
        elif satisfied:
            coverage_note = (
                f"Contract coverage last attempt: {ratio if ratio is not None else 'n/a'} "
                f"(all tracked items satisfied).\n"
            )
    critic_block = ""
    if semantic_config and semantic_config.enable_repair_critic:
        critic_lines = [
            f"- Failing contract categories: {last_result.edit_metadata.get('contract_failure_categories', '') if last_result else ''}",
            "- Ensure responses stay within allowed implementation files; tests remain read-only.",
            "- Verify metadata totals, sorting, filtering, and 404 contracts simultaneously.",
        ]
        critic_block = "Semantic critic focus:\n" + "\n".join(critic_lines) + "\n"
    return (
        f"You are repairing a repository-backed change produced by strategy '{strategy_name}'.\n"
        f"{repo_guidance}\n"
        f"{focus_note}"
        f"{last_files_note}"
        f"{pending_note}"
        f"{coverage_note}"
        f"{cgcs_note}"
        f"{lint_note}"
        f"{critic_block}"
        f"{context_block}"
        f"Problem statement: {ctx.problem_statement[:600]}\n"
        f"Implementation contract: {contract}\n"
        f"Plan context:\n{plan_outline}\n"
        f"Diagnostics: {diagnostics}\n"
        f"Failing tests: {failing}\n"
        f"Assertion details: {assertions}\n"
        f"Trace excerpt: {trace}\n"
        f"Reproduction hint: {reproduction}\n"
        f"Repair diagnosis summary:\n{diagnosis_block}\n"
        "Return only the JSON edit payload described above. Do not emit raw code blocks."
    )


def build_repair_prompt(
    strategy_name: str,
    ctx: DecompositionContext,
    plan: DecompositionPlan,
    summary: FailureSummary,
    current_code: str,
    subtask_focus: Optional[str],
    last_result: Optional[ExecutionResult] = None,
    semantic_config: Optional[SemanticVariantConfig] = None,
) -> str:
    if _is_repo_task(ctx):
        return _build_repo_repair_prompt(
            strategy_name,
            ctx,
            plan,
            summary,
            current_code,
            subtask_focus,
            last_result,
            semantic_config,
        )
    contract = build_implementation_contract(ctx)
    focus = subtask_focus or "global"
    focus_clause = (
        f"Focus on subtask '{focus}' and confine edits to that portion before falling back to global changes."
        if focus not in {"global", "", None}
        else "Apply a holistic repair if localisation is impossible."
    )
    failing = summary.failing_tests if summary else []
    trace = summary.brief_trace if summary else []
    assertions = summary.assertion_msgs if summary else []
    reproduction = summary.reproduction_hint if summary else ""
    candidate_hint = ""
    focus_hint = ""
    if plan.subtask_file_map and subtask_focus in plan.subtask_file_map:
        focus_files = plan.subtask_file_map[subtask_focus] or []
        if focus_files:
            focus_hint = f"Subtask '{focus}' targets files: {', '.join(focus_files)}.\n"
    if plan.candidate_files:
        preview = "\n".join(f"- {path}" for path in plan.candidate_files[:8])
        candidate_hint = f"\nFocus these files first:\n{preview}\n"
    return (
        f"You are repairing code produced by strategy '{strategy_name}'.\n"
        f"Problem statement: {ctx.problem_statement[:400]}\n"
        f"Implementation contract: {contract}\n"
        f"Plan context:\n{_plan_outline(plan)}\n"
        f"Diagnostics: { _diagnostics_summary(plan) }\n"
        f"{focus_hint}"
        f"{candidate_hint}"
        f"Current code:\n{current_code[:800]}\n"
        f"Failing tests: {failing}\n"
        f"Assertion details: {assertions}\n"
        f"Trace excerpt: {trace}\n"
        f"Reproduction hint: {reproduction}\n"
        f"{focus_clause}\n"
        "Return the full updated implementation without commentary."
    )


def generate_initial_code(
    strategy_name: str,
    ctx: DecompositionContext,
    plan: DecompositionPlan,
    tracker: BudgetTracker,
    semantic_config: Optional[SemanticVariantConfig] = None,
) -> Tuple[str, Dict[str, str]]:
    heuristic_code = try_heuristic_solution(ctx)
    if heuristic_code:
        metadata = {
            "phase": "initial",
            "source": "heuristic",
        }
        return heuristic_code, metadata

    prompt = build_initial_prompt(strategy_name, ctx, plan, semantic_config)
    response = llm.call(
        prompt,
        model="plan-runner",
        max_tokens=768,
        temperature=0.2,
        caller=f"{strategy_name}:initial",
    )
    generated = tracker.consume(response, fallback=response.content)
    if _is_repo_task(ctx):
        code = _ensure_repo_payload(generated, ctx, plan)
    else:
        code = _extract_code_block(generated) or _fallback_stub(ctx)
    metadata = {
        "prompt_excerpt": prompt[-300:],
        "llm_tokens": str(response.tokens),
        "phase": "initial",
    }
    return code, metadata


def generate_repair_code(
    strategy_name: str,
    ctx: DecompositionContext,
    plan: DecompositionPlan,
    summary: FailureSummary,
    current_code: str,
    subtask_focus: Optional[str],
    last_result: Optional[ExecutionResult],
    tracker: BudgetTracker,
    semantic_config: Optional[SemanticVariantConfig] = None,
) -> Tuple[str, Dict[str, str]]:
    heuristic_code = try_heuristic_solution(ctx)
    if heuristic_code:
        metadata = {
            "phase": "repair",
            "source": "heuristic",
            "subtask_focus": subtask_focus or "global",
        }
        return heuristic_code, metadata

    prompt = build_repair_prompt(
        strategy_name,
        ctx,
        plan,
        summary,
        current_code,
        subtask_focus,
        last_result,
        semantic_config,
    )
    response = llm.call(
        prompt,
        model="repair-loop",
        max_tokens=768,
        temperature=0.15,
        caller=f"{strategy_name}:repair",
    )
    generated = tracker.consume(response, fallback=current_code)
    if _is_repo_task(ctx):
        code = _ensure_repo_payload(generated, ctx, plan)
    else:
        code = _extract_code_block(generated) or current_code
    metadata = {
        "prompt_excerpt": prompt[-300:],
        "llm_tokens": str(response.tokens),
        "phase": "repair",
        "subtask_focus": subtask_focus or "global",
    }
    return code, metadata


__all__ = [
    "build_initial_prompt",
    "build_repair_prompt",
    "generate_initial_code",
    "generate_repair_code",
]
