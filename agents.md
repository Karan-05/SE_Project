# DataCollector / SE_Project agent instructions

You are working in this repository:

/Users/karanallagh/Desktop/DataCollector

Always use this Python environment for every command:
- source /Users/karanallagh/Desktop/DataCollector/venv/bin/activate

Before doing anything else in a new session:
1. Run `pwd`
2. Run `which python`
3. Run `python --version`
4. Confirm the active interpreter is from:
   /Users/karanallagh/Desktop/DataCollector/venv/bin/python

## Mission

Your job is to turn this repo into a paper-ready research artifact for an ASE-style submission.

You must do four things well:

1. Analyze the full Topcoder data pipeline end to end.
2. Verify exactly how the repo constructs the Topcoder challenge database and whether the 22,023-challenge claim is supported.
3. Run the largest honest end-to-end experiment pipeline that this repo and environment can support.
4. Improve the method only when the evidence supports improvement. Never fabricate a superior-method claim.

## Scientific honesty rules

- Never claim a flagship/superior algorithm unless the metrics actually support it.
- Never present one-seed luck as the result.
- Always compare against the strongest heuristic/teacher baseline.
- If imitation remains best, say so clearly.
- If learned override remains harmful, say so clearly.
- If the repo supports only a hybrid or negative-result paper, recommend that honestly.

## Repo-specific goals

### A. Data / database analysis
Trace and document, with code references:
- downloader / API backfill
- legacy Excel ingestion
- JSON normalization
- MySQL schema and loading
- export_real_tasks path
- preprocess path to parquet
- decomposition / RL / universal-agent experiment paths

Produce:
- reports/repo_analysis/data_pipeline_map.md
- reports/repo_analysis/topcoder_dataset_audit.md

The dataset audit must answer:
1. Where the Topcoder challenge records come from
2. Whether the 22,023-challenge claim is reproducible from code/data
3. Which files/tables are authoritative
4. Deduplication logic
5. Any gaps, uncertainty, or missing credentials

### B. Full-run capability audit
Figure out what “run on the entire project” actually means in this repo.

Distinguish between:
- full ETL/database build
- full raw-task export/preprocess
- full RL/decomposition benchmark
- sampled LLM-agent experiments vs whole-corpus runs

Produce:
- reports/repo_analysis/full_run_capability.md

### C. Main method selection
Treat all candidate methods honestly:
- heuristic/teacher imitation
- reduced-action flat RL
- TARL
- STRIDE
- any teacher-guided residual variants

Choose the best evidence-backed method.

If no learned method beats the teacher, do NOT force a flagship-superior-method claim.

Produce:
- reports/ase2026_aegis/main_method_decision.md

### D. Paper packaging
Based on the evidence, prepare the strongest paper framing that is actually supported.

Possible outcomes:
1. superior control method paper
2. hybrid teacher-guided control paper
3. negative-result / diagnostic paper

Produce:
- reports/ase2026_aegis/paper_positioning.md
- reports/ase2026_aegis/abstract_draft.md
- reports/ase2026_aegis/contributions_draft.md

## Execution policy

Work iteratively:
1. inspect
2. run
3. analyze outputs
4. make the smallest high-impact fix
5. rerun
6. summarize

Do not add speculative complexity unless metrics justify it.

## Required outputs

Always maintain/update:
- results/aegis_rl/
- reports/ase2026_aegis/
- reports/repo_analysis/

At the end of a session, write:
- reports/ase2026_aegis/session_log.md

That log must include:
- commands run
- files modified
- metrics observed
- blockers
- what to do next