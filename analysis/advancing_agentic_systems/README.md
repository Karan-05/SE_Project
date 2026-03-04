# Advancing Agentic Systems: Topcoder Challenge Interpretation

This mini research lab adapts ideas from *Advancing Agentic Systems: Dynamic Task Decomposition, Tool Integration and Evaluation using Novel Metrics and Dataset* to the Topcoder challenge corpus harvested by the repository.

The goal is to let you:

1. **Annotate every challenge** with an LLM-agent task graph that mixes sequential and parallel execution, matching the paper’s orchestrator/delegator/executor setup.
2. **Score generated plans** using agent-oriented metrics (Node/Tool precision, Edge F1, Structural Similarity Index, path-length similarity, complexity).
3. **Produce researcher-friendly artefacts** (CSV + JSON) so that human analysts can interpret how challenge attributes influence plan structure, tool selection, and execution risks.

All scripts stay self-contained (standard library only) and run over the existing `challenge_data/**/page*.json` dumps produced by the collector.

---

## Directory Layout

- `plan_generation.py` – turns a challenge object into a dynamic DAG plan, assigning tasks, dependencies, and tools based on heuristics influenced by track, challenge type, and complexity.
- `baselines.py` – defines “gold” canonical graphs per track/complexity bucket so we can compute Node/Edge/Tool F1 and Structural Similarity Index.
- `metrics.py` – implements the paper-inspired metrics on graph pairs, including SSI and path-length similarity.
- `report.py` – CLI entry point; walks all stored challenges, generates plans, scores them, and writes consolidated analytics to `output/`.
- `models.py` – typed structures representing nodes, edges, plans, and evaluation summaries.
- `tool_catalog.py` – curated catalogue of tools and agents available to the framework plus semantic tags used by the delegator.
- `README.md` (this file) – research notes and usage guidance.

Output artefacts land inside `analysis/advancing_agentic_systems/output/`.

---

## Mapping Paper Concepts to Topcoder Data

| Paper Concept | Implementation in This Lab |
| --- | --- |
| **Orchestrator** | `plan_generation.build_agentic_plan` inspects each challenge’s track/type/technologies and creates a DAG with coarse/fine granularity knobs. |
| **Delegator** | `plan_generation` binds nodes to tool bundles fetched from `tool_catalog.py` using lightweight semantic filters. |
| **Executor** | Plans include parallel group identifiers; `report.py` infers sequential vs parallel workload mixes and derives critical-path estimates. |
| **Feedback & Profiling** | `report.py` aggregates timing/complexity proxies (node counts, parallel depth) and flags hotspots when plans diverge from track baselines. |
| **Evaluation Metrics** | `metrics.py` computes Node/Tool precision/recall/F1, Edge F1, node-label similarity, Structural Similarity Index (SSI), path-length similarity, and graph complexity. |

---

## Usage

1. Ensure `challenge_data/**/page*.json` exists (generated via `init.py`/`automation.py`).
2. Run:
   ```bash
   python -m analysis.advancing_agentic_systems.report \
     --challenge-root challenge_data \
     --output-root analysis/advancing_agentic_systems/output
   ```
3. Inspect outputs:
   - `agentic_challenge_annotations.json` – per-challenge plan + metrics.
   - `agentic_challenge_metrics.csv` – flat table for analytic tools.
   - `track_complexity_summary.md` – researcher narrative with key findings and risk notes.
   - `paper_alignment_brief.md` – links metrics back to the paper’s core findings (structure vs. tool selection).

Optional flags (`--fine-grained`, `--include-incomplete`) toggle plan granularity and whether to include challenges lacking full metadata.

---

## Research Notes & Next Steps

- **Interpretation-first**: every output is human-readable and cross-links to original challenge IDs so you can trace back to raw statements while studying plan/tool decisions.
- **Extendable baselines**: adjust `baselines.py` to reflect alternative “gold” process templates (e.g., specialized QA flows, algorithmic contests).
- **LLM experiments**: swap the heuristic planner with live LLM calls; the metrics layer stays the same, letting you quantify improvements.
- **Dataset alignment**: `report.py` logs the complexity bucket (|V| + |E|) just like the paper’s dataset, enabling comparative charts vs AsyncHow scenarios.

Feel free to fork this mini lab for new research questions—e.g., overlaying member skill distributions or simulating tool-availability ablations.
