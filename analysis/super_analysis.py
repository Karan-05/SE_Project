"""Generate an enriched AI delivery roadmap from existing report outputs.

Reads the AI feasibility CSV produced by `analysis/report.py` and emits a
`ai_super_analysis.csv` file with deeper delivery planning, including AI-ready
components, human-led checkpoints, milestone sequencing, and risk insight.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from analysis.report import _clean_problem_statement


BLUEPRINTS: Dict[str, Dict[str, str]] = {
    "data science & modeling": {
        "solution_blueprint": (
            "Stage curated datasets, run AutoML/LLM-assisted experiments, evaluate fairness, "
            "and package a governed inference service."
        ),
        "ai_independent": (
            "Dataset profiling scripts; baseline feature extraction; AutoML training sweeps; "
            "evaluation report generation; experiment tracking automation."
        ),
        "human_led": (
            "Define business KPIs; vet data sourcing and ethics; interpret edge-case behaviour; "
            "approve deployment thresholds and monitoring strategy."
        ),
        "solution_phases": (
            "1) Data audit & gap analysis → 2) Baseline AutoML modelling → "
            "3) Feature iteration & bias review → 4) SME validation & sign-off → "
            "5) Deployment packaging & monitoring hooks."
        ),
        "critical_risks": (
            "Data drift, label leakage, regulatory exposure, and compute budget overruns."
        ),
        "oversight": (
            "Weekly model review with domain experts; enforce human-in-loop on deployment approvals."
        ),
        "workflow": (
            "AI assists via notebooks/AutoML and summarises metrics; humans challenge findings and "
            "integrate with downstream consumers."
        ),
        "notes": "Pair AutoML acceleration with rigorous human validation to avoid spurious correlations.",
    },
    "integration & automation": {
        "solution_blueprint": (
            "Design interface contracts, scaffold services, wire authentication, and validate end-to-end flows."
        ),
        "ai_independent": (
            "Generate API clients; draft integration tests; scaffold middleware; synthesise infrastructure-as-code."
        ),
        "human_led": (
            "Define non-functional requirements; negotiate upstream/downstream changes; "
            "perform security reviews and deployment sign-off."
        ),
        "solution_phases": (
            "1) Sequence system contracts → 2) Generate integration scaffolds → "
            "3) Implement business rules & retries → 4) Run cross-system tests → "
            "5) Harden logging & observability."
        ),
        "critical_risks": (
            "Hidden API constraints, idempotency gaps, auth/secret handling, and sandbox vs prod parity."
        ),
        "oversight": (
            "Pair AI-generated glue code with manual inspection; schedule exploratory testing sessions."
        ),
        "workflow": (
            "Co-pilot drafts integration modules; humans iteratively validate against live APIs and compliance."
        ),
        "notes": "Maintain updated sequence diagrams so generated code stays aligned with architecture decisions.",
    },
    "ui/ux & creative design": {
        "solution_blueprint": (
            "Rapidly ideate design directions, synthesise component libraries, and translate selections into implementable specs."
        ),
        "ai_independent": (
            "Produce design mood boards; draft layout variations; generate accessibility checks; "
            "export design tokens for implementation."
        ),
        "human_led": (
            "Curate final visual language; validate brand alignment; run user testing; "
            "author nuanced content and micro-interactions."
        ),
        "solution_phases": (
            "1) Gather references & goals → 2) AI-assisted concept generation → "
            "3) Designer refinement & stakeholder review → 4) Prototype testing → "
            "5) Handoff specs with annotated tokens."
        ),
        "critical_risks": (
            "Brand misalignment, accessibility regressions, and stakeholder buy-in delays."
        ),
        "oversight": (
            "Creative director sign-off on each iteration; ensure human review of AI-generated assets before release."
        ),
        "workflow": (
            "Generative tools provide variations while designers retain curation and narrative control."
        ),
        "notes": "Use AI for breadth of options, but final experience should be directed by human context keepers.",
    },
    "documentation & research": {
        "solution_blueprint": (
            "Synthesize source materials, extract key findings, structure narratives, and prepare publication-ready collateral."
        ),
        "ai_independent": (
            "Aggregate references; draft outline; summarise interviews; highlight contradictions; "
            "generate first-pass prose and visuals."
        ),
        "human_led": (
            "Verify factual integrity; align messaging with stakeholders; secure approvals; "
            "tailor tone and compliance-sensitive language."
        ),
        "solution_phases": (
            "1) Curate source corpus → 2) AI-assisted synthesis & outline → "
            "3) Human editing & validation → 4) Review cycles with SMEs → "
            "5) Final formatting and dissemination."
        ),
        "critical_risks": (
            "Hallucinated details, outdated references, confidentiality breaches."
        ),
        "oversight": (
            "Embed fact-check checkpoints; require SME approval before publication."
        ),
        "workflow": (
            "AI drafts and maintains living documents; humans enforce accuracy and stakeholder alignment."
        ),
        "notes": "Ensure citation metadata is tracked so reviewers can audit AI summarisation paths.",
    },
    "testing & quality": {
        "solution_blueprint": (
            "Expand automated coverage, instrument observability, and implement regression safeguards."
        ),
        "ai_independent": (
            "Generate unit/integration test skeletons; propose edge cases; synthesise test data; "
            "triage log anomalies."
        ),
        "human_led": (
            "Prioritise critical scenarios; approve gating criteria; investigate nuanced production bugs; "
            "maintain test strategy."
        ),
        "solution_phases": (
            "1) Map risk hotspots → 2) AI-generate baseline tests → 3) Hardening & flakiness fixes → "
            "4) CI integration & observability → 5) Release-readiness review."
        ),
        "critical_risks": (
            "False confidence from brittle tests, environment drift, insufficient staging data."
        ),
        "oversight": (
            "Human QA reviews AI-generated tests and ensures meaningful assertions."
        ),
        "workflow": (
            "AI accelerates test authoring while QA engineers curate suites and interpret failures."
        ),
        "notes": "Invest in feedback loops so AI learns from flaky or low-signal tests.",
    },
    "algorithmic optimization": {
        "solution_blueprint": (
            "Prototype heuristic and exact approaches, benchmark alternatives, and stabilise production-grade implementations."
        ),
        "ai_independent": (
            "Draft algorithm skeletons; generate comparative benchmarks; visualise complexity; "
            "suggest optimisation strategies."
        ),
        "human_led": (
            "Prove correctness; tailor heuristics to domain constraints; perform performance profiling under real workloads."
        ),
        "solution_phases": (
            "1) Requirement formalisation → 2) Algorithm exploration → 3) Prototype benchmarking → "
            "4) Optimisation & refactoring → 5) Validation and deployment."
        ),
        "critical_risks": (
            "Edge-case failures, non-deterministic behaviour, and hardware-specific characteristics."
        ),
        "oversight": (
            "Code reviews with algorithm specialists; enforce exhaustive scenario testing."
        ),
        "workflow": (
            "AI provides candidate implementations; experts iterate to ensure efficiency and correctness."
        ),
        "notes": "Capture benchmark baselines so improvements are measurable and reproducible.",
    },
    "devops & deployment": {
        "solution_blueprint": (
            "Codify infrastructure, automate pipelines, bake in observability, and orchestrate safe rollouts."
        ),
        "ai_independent": (
            "Generate IaC templates; scaffold CI/CD workflows; draft monitoring dashboards; "
            "produce deployment runbooks."
        ),
        "human_led": (
            "Define SLOs; enforce security & compliance; run chaos drills; execute go/no-go decisions."
        ),
        "solution_phases": (
            "1) Environment assessment → 2) IaC & pipeline scaffolding → 3) Policy & security hardening → "
            "4) Observability instrumentation → 5) Controlled rollout & post-mortem readiness."
        ),
        "critical_risks": (
            "Misconfigured secrets, insufficient rollback paths, environment drift."
        ),
        "oversight": (
            "Ops lead validates AI-generated configs; require peer review before merges."
        ),
        "workflow": (
            "AI drafts automation while operators refine for compliance and resilience."
        ),
        "notes": "Preserve manual runbooks for emergency response even when automation increases.",
    },
}


DEFAULT_BLUEPRINT = {
    "solution_blueprint": (
        "Progress requirements clarification, establish technical spike, iterate on increments, and review outcomes with stakeholders."
    ),
    "ai_independent": (
        "Draft boilerplate code/tests; summarise requirements; generate documentation scaffolds; "
        "maintain task boards."
    ),
    "human_led": (
        "Elicit precise acceptance criteria; resolve ambiguities; perform final QA; coordinate releases."
    ),
    "solution_phases": (
        "1) Requirement clarification → 2) Spike & prototype → 3) Incremental build → "
        "4) Review & QA → 5) Deployment & retrospective."
    ),
    "critical_risks": (
        "Ambiguous scope, shifting priorities, and integration surprises."
    ),
    "oversight": (
        "Frequent stakeholder check-ins and code reviews to steer AI-generated output."
    ),
    "workflow": (
        "AI accelerates boilerplate work while humans guard correctness and context."
    ),
    "notes": "Invest in backlog refinement so AI assistance stays aligned with latest priorities.",
}


INDependence_SPEEDUP = {
    "Yes": "AI-led delivery can compress build effort by ~60-70% when paired with automated QA.",
    "Partial": "Expect ~35-50% cycle acceleration with AI copilots plus human integration oversight.",
    "No": "AI provides supporting automation (est. 15-30% faster) but humans must steer critical paths.",
}

LLM_SYSTEM_PROMPT = (
    "You are an expert AI delivery strategist. Summarise findings in valid JSON with keys: "
    "'ai_solution_plan', 'ai_independent_work', 'human_collaboration', 'references'. "
    "Keep values concise (<=6 sentences each)."
)

LLM_FALLBACK = {
    "ai_solution_plan": "",
    "ai_independent_work": "",
    "human_collaboration": "",
    "references": "",
}


def load_llm_cache(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def save_llm_cache(path: Path, cache: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(cache, fh, indent=2, sort_keys=True)


def build_llm_prompt(record: Dict[str, Any]) -> str:
    return (
        "Analyse the following Topcoder challenge and provide AI solution insights.\n"
        f"Name: {record.get('name')}\n"
        f"Problem statement: {record.get('problem_statement')}\n"
        f"Root cause: {record.get('problem_root_cause')}\n"
        f"AI blockers: {record.get('ai_blockers')}\n"
        f"Existing rationale: {record.get('rationale')}\n"
        f"AI acceleration ideas: {record.get('ai_acceleration')}\n"
        "Respond in JSON with keys ai_solution_plan, ai_independent_work, human_collaboration, references."
    )


def call_openai_chat(
    prompt: str,
    *,
    model: str,
    api_key: str,
    timeout: int,
    max_tokens: int,
    temperature: float = 0.2,
) -> str:
    """Invoke the OpenAI chat completions API and return the response text."""
    url = "https://api.openai.com/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": LLM_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    parsed = json.loads(body)
    return parsed["choices"][0]["message"]["content"]


def run_llm_research(
    prompt: str,
    *,
    model: str,
    api_key: str,
    timeout: int,
    max_tokens: int,
) -> Dict[str, Any]:
    """Call an LLM for deeper research; gracefully degrade if unavailable."""
    try:
        content = call_openai_chat(
            prompt,
            model=model,
            api_key=api_key,
            timeout=timeout,
            max_tokens=max_tokens,
        )
        parsed_content = json.loads(content)
        merged = {**LLM_FALLBACK, **parsed_content}
        return {"status": "ok", **merged}
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, KeyError, ValueError) as exc:
        return {
            "status": f"error: {exc}",
            **LLM_FALLBACK,
        }


def write_markdown_report(rows: list[Dict[str, Any]], output_path: Path) -> None:
    if not rows:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# AI Delivery Super Analysis",
        "",
        f"Total challenges analysed: {len(rows)}",
        "",
    ]
    for row in rows:
        lines.extend(
            [
                f"## {row['name']} (`{row['challengeId']}`)",
                "",
                f"- **Delivery mode:** {row['ai_delivery_mode']} (independence: {row['ai_independence']}, confidence: {row['confidence']})",
                f"- **Estimated AI hours:** {row['estimated_ai_hours']} (speedup: {row['ai_speedup_estimate']})",
                f"- **Problem root cause:** {row['problem_root_cause']}",
                f"- **Solution blueprint:** {row['solution_blueprint']}",
                f"- **AI-ready components:** {row['ai_independent_components']}",
                f"- **Human-led components:** {row['human_led_components']}",
                f"- **Critical risks:** {row['critical_risks']}",
                f"- **Oversight requirements:** {row['oversight_requirements']}",
            ]
        )
        if row.get("llm_status") and row["llm_status"] != "not_requested":
            lines.append(f"- **LLM status:** {row['llm_status']}")
            if row.get("llm_solution_plan"):
                lines.append(f"- **LLM solution plan:** {row['llm_solution_plan']}")
            if row.get("llm_ai_independent_work"):
                lines.append(f"- **LLM AI work:** {row['llm_ai_independent_work']}")
            if row.get("llm_human_collaboration"):
                lines.append(f"- **LLM human collaboration:** {row['llm_human_collaboration']}")
            if row.get("llm_references"):
                lines.append(f"- **References:** {row['llm_references']}")
        lines.extend(
            [
                f"- **AI blockers:** {row['ai_blockers']}",
                f"- **Analysis notes:** {row['analysis_notes']}",
                "",
            ]
        )
    with output_path.open("w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def write_html_report(rows: list[Dict[str, Any]], output_path: Path) -> None:
    if not rows:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    parts = [
        "<!DOCTYPE html>",
        "<html>",
        "<head>",
        '<meta charset="utf-8"/>',
        "<title>AI Delivery Super Analysis</title>",
        "<style>body{font-family:Arial,Helvetica,sans-serif;margin:2rem;}h1{color:#1f2933;}section{margin-bottom:2rem;}h2{color:#334155;}ul{line-height:1.5;}</style>",
        "</head>",
        "<body>",
        "<h1>AI Delivery Super Analysis</h1>",
        f"<p>Total challenges analysed: {len(rows)}</p>",
    ]
    for row in rows:
        parts.append("<section>")
        parts.append(f"<h2>{row['name']} (<code>{row['challengeId']}</code>)</h2>")
        parts.append("<ul>")
        parts.append(
            f"<li><strong>Delivery mode:</strong> {row['ai_delivery_mode']} "
            f"(independence: {row['ai_independence']}, confidence: {row['confidence']})</li>"
        )
        parts.append(
            f"<li><strong>Estimated AI hours:</strong> {row['estimated_ai_hours']} "
            f"(speedup: {row['ai_speedup_estimate']})</li>"
        )
        parts.append(f"<li><strong>Problem root cause:</strong> {row['problem_root_cause']}</li>")
        parts.append(f"<li><strong>Solution blueprint:</strong> {row['solution_blueprint']}</li>")
        parts.append(f"<li><strong>AI-ready components:</strong> {row['ai_independent_components']}</li>")
        parts.append(f"<li><strong>Human-led components:</strong> {row['human_led_components']}</li>")
        parts.append(f"<li><strong>Critical risks:</strong> {row['critical_risks']}</li>")
        parts.append(f"<li><strong>Oversight requirements:</strong> {row['oversight_requirements']}</li>")
        if row.get("llm_status") and row["llm_status"] != "not_requested":
            parts.append(f"<li><strong>LLM status:</strong> {row['llm_status']}</li>")
            if row.get("llm_solution_plan"):
                parts.append(f"<li><strong>LLM solution plan:</strong> {row['llm_solution_plan']}</li>")
            if row.get("llm_ai_independent_work"):
                parts.append(
                    f"<li><strong>LLM AI work:</strong> {row['llm_ai_independent_work']}</li>"
                )
            if row.get("llm_human_collaboration"):
                parts.append(
                    f"<li><strong>LLM human collaboration:</strong> {row['llm_human_collaboration']}</li>"
                )
            if row.get("llm_references"):
                parts.append(f"<li><strong>References:</strong> {row['llm_references']}</li>")
        parts.append(f"<li><strong>AI blockers:</strong> {row['ai_blockers']}</li>")
        parts.append(f"<li><strong>Analysis notes:</strong> {row['analysis_notes']}</li>")
        parts.append("</ul>")
        parts.append("</section>")
    parts.extend(["</body>", "</html>"])
    with output_path.open("w", encoding="utf-8") as fh:
        fh.write("\n".join(parts))


def resolve_blueprint(problem_root_cause: str) -> Dict[str, str]:
    text = (problem_root_cause or "").lower()
    for key, blueprint in BLUEPRINTS.items():
        if key in text:
            return blueprint
    return DEFAULT_BLUEPRINT


def build_super_row(row: Dict[str, str], llm_insights: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    problem_statement = _clean_problem_statement(row.get("problem_statement", ""))
    root_cause = row.get("problem_root_cause", "")
    blueprint = resolve_blueprint(root_cause)
    independence = row.get("ai_independence", "")
    delivery_mode = row.get("ai_delivery_mode", "")

    speedup = INDependence_SPEEDUP.get(independence, "AI acceleration depends on clarified scope and guardrails.")
    oversight = blueprint["oversight"]
    if independence == "No":
        oversight = f"{oversight} Reinforce manual checkpoints because AI is supporting only."
    elif independence == "Partial":
        oversight = f"{oversight} Maintain shared ownership between AI agents and human reviewers."
    else:
        oversight = f"{oversight} Validate automation periodically even when autonomy is high."

    ai_independent = blueprint["ai_independent"]
    if independence == "No":
        ai_independent = (
            f"{ai_independent} (AI prepares assets but requires human pairing for final integration and approval)."
        )

    notes = (
        f"Delivery mode: {delivery_mode}. Blockers: {row.get('ai_blockers')}. "
        f"{blueprint['notes']}"
    )

    llm_status = "not_requested"
    llm_solution_plan = ""
    llm_ai_independent = ""
    llm_human_collaboration = ""
    llm_references = ""
    if llm_insights:
        llm_status = llm_insights.get("status") or "unknown"
        llm_solution_plan = llm_insights.get("ai_solution_plan", "")
        llm_ai_independent = llm_insights.get("ai_independent_work", "")
        llm_human_collaboration = llm_insights.get("human_collaboration", "")
        llm_references = llm_insights.get("references", "")
        if llm_solution_plan:
            notes = f"{notes} LLM plan: {llm_solution_plan}"
        if llm_status.startswith("error"):
            notes = f"{notes} LLM error observed; review connection/settings."

    return {
        "challengeId": row.get("challengeId"),
        "name": row.get("name"),
        "ai_delivery_mode": delivery_mode,
        "ai_independence": independence,
        "confidence": row.get("confidence"),
        "estimated_ai_hours": row.get("estimated_ai_hours"),
        "problem_root_cause": root_cause,
        "problem_statement": problem_statement,
        "solution_blueprint": blueprint["solution_blueprint"],
        "ai_independent_components": ai_independent,
        "human_led_components": blueprint["human_led"],
        "solution_phases": blueprint["solution_phases"],
        "critical_risks": blueprint["critical_risks"],
        "oversight_requirements": oversight,
        "ai_acceleration": row.get("ai_acceleration"),
        "ai_reference_solutions": row.get("ai_reference_solutions"),
        "ai_speedup_estimate": speedup,
        "ai_blockers": row.get("ai_blockers"),
        "rationale": row.get("rationale"),
        "llm_status": llm_status,
        "llm_solution_plan": llm_solution_plan,
        "llm_ai_independent_work": llm_ai_independent,
        "llm_human_collaboration": llm_human_collaboration,
        "llm_references": llm_references,
        "analysis_notes": notes,
    }


def run(
    input_path: Path,
    output_path: Path,
    *,
    use_llm: bool,
    llm_model: str,
    llm_timeout: int,
    llm_max_tokens: int,
    llm_cooldown: float,
    llm_cache_path: Optional[Path],
    llm_refresh_cache: bool,
    markdown_output: Optional[Path],
    html_output: Optional[Path],
) -> None:
    if not input_path.exists():
        raise FileNotFoundError(f"Input CSV {input_path} was not found. Run analysis/report.py first.")

    api_key = os.getenv("OPENAI_API_KEY")
    if use_llm and not api_key:
        print("Warning: --use-llm was provided but OPENAI_API_KEY is not set; skipping LLM enrichment.")
        use_llm = False

    cache: Dict[str, Any] = {}
    cache_dirty = False
    cache_path: Optional[Path] = None
    if use_llm:
        cache_path = llm_cache_path
        if cache_path and not llm_refresh_cache:
            cache = load_llm_cache(cache_path)

    rows: list[Dict[str, Any]] = []
    with input_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for raw_row in reader:
            llm_payload: Optional[Dict[str, Any]] = None
            if use_llm:
                prompt = build_llm_prompt(raw_row)
                prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
                cache_key = f"{raw_row.get('challengeId', 'unknown')}:{prompt_hash}"
                if cache_key in cache:
                    llm_payload = cache[cache_key]
                else:
                    llm_payload = run_llm_research(
                        prompt,
                        model=llm_model,
                        api_key=api_key or "",
                        timeout=llm_timeout,
                        max_tokens=llm_max_tokens,
                    )
                    if cache_path:
                        cache[cache_key] = llm_payload
                        cache_dirty = True
                    if llm_cooldown > 0:
                        time.sleep(llm_cooldown)
            rows.append(build_super_row(raw_row, llm_payload))

    if use_llm and cache_dirty and cache_path:
        save_llm_cache(cache_path, cache)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "challengeId",
        "name",
        "ai_delivery_mode",
        "ai_independence",
        "confidence",
        "estimated_ai_hours",
        "problem_root_cause",
        "problem_statement",
        "solution_blueprint",
        "ai_independent_components",
        "human_led_components",
        "solution_phases",
        "critical_risks",
        "oversight_requirements",
        "ai_acceleration",
        "ai_reference_solutions",
        "ai_speedup_estimate",
        "ai_blockers",
        "rationale",
        "llm_status",
        "llm_solution_plan",
        "llm_ai_independent_work",
        "llm_human_collaboration",
        "llm_references",
        "analysis_notes",
    ]

    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    markdown_target = markdown_output if (markdown_output and str(markdown_output) != "-") else None
    html_target = html_output if (html_output and str(html_output) != "-") else None
    if markdown_target:
        write_markdown_report(rows, markdown_target)
    if html_target:
        write_html_report(rows, html_target)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Produce a supercharged AI analysis CSV with delivery playbooks."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("analysis/output/ai_feasibility_analysis.csv"),
        help="Input CSV path generated by analysis/report.py (default: analysis/output/ai_feasibility_analysis.csv).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("analysis/output/ai_super_analysis.csv"),
        help="Destination CSV for enriched analysis (default: analysis/output/ai_super_analysis.csv).",
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Call the OpenAI API for deeper research (requires OPENAI_API_KEY).",
    )
    parser.add_argument(
        "--llm-model",
        type=str,
        default="gpt-4o-mini",
        help="OpenAI model to use when --use-llm is enabled (default: gpt-4o-mini).",
    )
    parser.add_argument(
        "--llm-timeout",
        type=int,
        default=60,
        help="Timeout in seconds for each LLM request (default: 60).",
    )
    parser.add_argument(
        "--llm-max-tokens",
        type=int,
        default=600,
        help="Maximum tokens for the LLM response (default: 600).",
    )
    parser.add_argument(
        "--llm-cooldown",
        type=float,
        default=1.0,
        help="Seconds to sleep between LLM requests to respect rate limits (default: 1.0).",
    )
    parser.add_argument(
        "--llm-cache",
        type=Path,
        default=Path("analysis/output/ai_super_analysis_llm_cache.json"),
        help="Path to persist LLM responses for reuse (default: analysis/output/ai_super_analysis_llm_cache.json).",
    )
    parser.add_argument(
        "--llm-cache-refresh",
        action="store_true",
        help="Ignore any existing cache and fetch fresh LLM insights.",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("analysis/output/ai_super_analysis.md"),
        help="Path for the Markdown summary report (default: analysis/output/ai_super_analysis.md).",
    )
    parser.add_argument(
        "--html-output",
        type=Path,
        default=Path("analysis/output/ai_super_analysis.html"),
        help="Path for the HTML summary report (default: analysis/output/ai_super_analysis.html).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run(
        args.input,
        args.output,
        use_llm=args.use_llm,
        llm_model=args.llm_model,
        llm_timeout=args.llm_timeout,
        llm_max_tokens=args.llm_max_tokens,
        llm_cooldown=args.llm_cooldown,
        llm_cache_path=args.llm_cache,
        llm_refresh_cache=args.llm_cache_refresh,
        markdown_output=args.markdown_output,
        html_output=args.html_output,
    )


if __name__ == "__main__":
    main()
