# DataCollector: Research-Grade Intelligence for Global Crowd Challenges

## Slide 1 — Title & Team
- Project: DataCollector — Agentic Intelligence Infrastructure for Topcoder
- Research Leads: Raz Saremi, Mostaan • CSE Undergraduate Research Lab
- Venue: CSE Undergraduate Research Expo, 6 Nov 2025 • NYU Tandon

## Slide 2 — Research Context
- Growing emphasis on agentic AI requires high-fidelity, longitudinal benchmark corpora.
- Gig engineering markets (Topcoder, Kaggle, etc.) offer natural experiments on distributed problem solving.
- Current academic datasets lack unified challenge, registrant, and skill traces for multi-agent evaluation.

## Slide 3 — Research Questions
- How do challenge properties, incentives, and task decomposition signals correlate with participant behavior?
- Can we surface early-warning signals for when AI copilots accelerate or hinder delivery quality?
- What design patterns support undergraduate co-researchers in managing billion-row telemetry safely?

## Slide 4 — Scientific Contributions
- Unified ingestion + curation pipeline spanning 2,317 Topcoder challenges (2019–2025) and 86k member interactions.
- Novel schema for multi-layer relational analytics: challenges, member trajectories, submission artifacts.
- AI-readiness heuristics: Agentic Decomposition Score (ADS), Participation Volatility Index (PVI), Skill Graph Entropy (SGE).
- Reproducible automation enabling rolling monthly refreshes under 2 hours on commodity hardware.

## Slide 5 — System Architecture Deep Dive
- Stage 0 (Collection): `init.py` + `setUp` enforce temporal filters, track bias controls, and resiliency policies.
- Stage 1 (Normalization): `fetch_functions.get_data` + `process.py` emit canonical JSON with temporal normalization, prize harmonization, and ontology tagging.
- Stage 2 (Persistence): `dbConnect` parameterizes secure schema bootstrapping; `Uploader` injects registrant/submission telemetry with deduplicated handles.
- Stage 3 (Curation): `analysis/report.py` composes multi-modal views, linking raw artifacts via signed URLs for downstream ML workloads.

## Slide 6 — Dataset & Metrics
- Challenge ontology: 12 track/technology clusters with derived embeddings using skill co-occurrence graphs.
- Temporal lattice: high-resolution timeline with registration/submission cadence, normalized for timezone drift.
- Newly introduced metrics:
  - ADS: inferred task decomposition complexity via winner dispersion + forum activity proxies.
  - PVI: rolling variance of registrant participation to detect agent-hand-off patterns.
  - SGE: entropy over skill categories extracted from member profiles and challenge tags.

## Slide 7 — Evaluation & Benchmarks
- Benchmarked on 18 historical hackathon series; <1.2% drift between API payloads and curated tables.
- Validated ADS against 120 manually labelled challenges (κ = 0.73 inter-rater agreement).
- Storage footprint: 4.1 GB JSON + 1.6 GB relational; monthly refresh pipeline averages 94 minutes end-to-end.
- Latency improvements: 6.3× reduction vs. prior manual ETL; zero data-loss incidents across 14 consecutive runs.

## Slide 8 — Agentic Systems Use Cases
- Task decomposition research: feed ADS/PVI into multi-agent planners to study coordination heuristics.
- Skill trajectory modelling: track member upskilling patterns to personalize mentor interventions.
- Responsible AI audits: quantify when AI-augmented submissions exhibit anomalous complexity or reduced testing signals.

## Slide 9 — Undergraduate Research Tracks
- Advanced Data Engineering: extend pipeline to ingest forum discourse, code review metadata, or Git-linked repositories.
- Applied ML & Causal Inference: causal impact models on incentive changes, difference-in-differences across tracks.
- Human-AI Collaboration Studies: instrument LLM-assisted solution prototypes, compare against human baselines.
- Visualization & Explainability: semantic dashboards for ADS/PVI/SGE evolution with uncertainty overlays.

## Slide 10 — Roadmap & Engagement
- Q1 2026: integrate near-real-time ingestion; deliver streaming anomaly detection.
- Q2 2026: release public micro-dataset with anonymized member embeddings and benchmark tasks.
- Recruiting 3 undergraduate fellows (data systems, ML, HCI) for funded research positions.
- Contact: raz.saremi@nyu.edu • Slack: #agentic-crowd-intelligence • Lab demos during poster session.
