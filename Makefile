PYTHON ?= python
DATA_RAW := data/raw
DATA_PROCESSED := data/processed
SEEDS ?= 10
EPISODES ?= 5
HORIZON ?= 50
EVAL_SPLIT ?= test
EVAL_ITEMS_FILE ?= openai_artifacts/eval_items_$(EVAL_SPLIT).jsonl
BATCH_REQUEST_FILE ?= openai_artifacts/batch_requests.jsonl
SKIPPED_EVAL_FILE ?= openai_artifacts/skipped_eval_items.jsonl
CGCS_DIR ?= data/cgcs

.PHONY: preprocess train_supervised train_embeddings run_rl paper tests clean \
	decomp_benchmark decomp_rl decomp_rl_seeds decomp_multiagent decomp_meta \
	decomp_meta_audit decomp_frontier decomp_real decomp_all \
	toh_benchmark regression_eval end_to_end_eval final_artifacts paper_artifacts \
	docs_reference real_repo_preflight real_repo_run cgcs_dataset cgcs_debug_dataset paper_tables \
	paper_figures openai_upload openai_build_eval openai_build_batch openai_submit_batch \
	openai_poll_batch openai_debug_errors openai_graders openai_prepare_finetune \
	topcoder_index topcoder_select_executable topcoder_discover_repos topcoder_fetch_repos \
	topcoder_build_snapshots topcoder_prepare_workspaces topcoder_repo_report research_funnel_report \
	public_repo_discover public_repo_select public_repo_fetch public_repo_snapshots \
	public_repo_workspaces public_repo_report \
	public_repo_pilot_subset public_repo_validate_workspaces public_repo_seed_tasks \
	public_repo_run_pilot public_repo_audit_traces public_repo_eval_pack public_repo_pilot_report

preprocess:
	$(PYTHON) -m src.data.preprocess --raw-dir $(DATA_RAW) --output-dir $(DATA_PROCESSED)

train_supervised:
	$(PYTHON) train_supervised.py --feature-mode multimodal --use-embeddings

train_embeddings:
	$(PYTHON) train_embeddings.py

run_rl:
	$(PYTHON) rl_train.py

paper:
	@if ! command -v latexmk >/dev/null 2>&1; then \
		echo "latexmk not found. Install it (e.g., 'brew install latexmk') before running make paper."; \
		exit 127; \
	fi
	cd paper && latexmk -pdf main.tex

clean:
	rm -rf artifacts/* reports/figs/* reports/tables/* embeddings/*

tests:
	pytest -q

decomp_benchmark:
	$(PYTHON) -m src.decomposition.runners.run_batch

decomp_rl:
	$(PYTHON) -m src.decomposition.runners.run_rl_integration --seed 42 --episodes $(EPISODES) --horizon $(HORIZON)

decomp_rl_seeds:
	@echo "Running RL rollouts across $(SEEDS) seeds"
	@for seed in `seq 1 $(SEEDS)`; do \
		echo "Seed $$seed"; \
		$(PYTHON) -m src.decomposition.runners.run_rl_integration --seed $$seed --episodes $(EPISODES) --horizon $(HORIZON); \
	done
	$(PYTHON) -m src.decomposition.evaluation --aggregate-seeds

decomp_multiagent:
	@echo "Running multi-agent rollouts across $(SEEDS) seeds"
	@for seed in `seq 1 $(SEEDS)`; do \
		echo "Multi-agent seed $$seed"; \
		$(PYTHON) -m src.decomposition.runners.run_multiagent --seed $$seed --episodes $(EPISODES) --horizon $(HORIZON); \
	done
	$(PYTHON) -m src.decomposition.evaluation --multiagent

decomp_meta:
	$(PYTHON) -m src.decomposition.runners.run_meta_selector

decomp_meta_audit:
	$(PYTHON) -m src.decomposition.runners.run_meta_selector --audit --loo-type

decomp_frontier:
	$(PYTHON) -m src.decomposition.evaluation --frontier

decomp_real:
	$(PYTHON) -m src.decomposition.runners.run_real_slice

decomp_all:
	$(MAKE) decomp_benchmark
	$(MAKE) decomp_rl_seeds
	$(MAKE) decomp_multiagent
	$(MAKE) decomp_meta
	$(MAKE) decomp_meta_audit
	$(MAKE) decomp_real
	$(PYTHON) -m src.decomposition.evaluation --aggregate-seeds --multiagent --frontier

toh_benchmark:
	$(PYTHON) -m src.benchmarks.toh.run --out_dir reports/llm_bench/tower_of_hanoi --seeds $(SEEDS) --min_disks 4 --max_disks 10 --token_budget 150

regression_eval:
	$(PYTHON) -m src.regression.run_regression --out_dir reports/regression --seed 42

end_to_end_eval:
	$(PYTHON) -m src.experiments.run_end_to_end --config configs/end_to_end.yaml --out_dir reports/end_to_end --seeds $(SEEDS) --base_seed 1 --bootstrap_seed 99

final_artifacts:
	$(PYTHON) -m src.final.compile_paper_artifacts --out_dir reports/final --seed 42

paper_artifacts: toh_benchmark regression_eval end_to_end_eval final_artifacts
	@echo "Tower-of-Hanoi benchmark → reports/llm_bench/tower_of_hanoi"
	@echo "Regression metrics → reports/regression"
	@echo "End-to-end ablations → reports/end_to_end"
	@echo "Compiled paper appendix assets → reports/final"

docs_reference:
	$(PYTHON) scripts/generate_module_docs.py

real_repo_preflight:
	$(PYTHON) scripts/prepare_real_repo_benchmark.py --prep-only

real_repo_run:
	$(PYTHON) scripts/prepare_real_repo_benchmark.py --mode real_world_research

paper_tables:
	$(PYTHON) scripts/make_paper_tables.py

paper_figures:
	$(PYTHON) scripts/make_paper_figures.py

openai_upload:
	$(PYTHON) scripts/openai_ops/upload_artifacts.py

topcoder_index:
	$(PYTHON) scripts/topcoder/build_corpus_index.py --tasks $(DATA_RAW)/tasks.csv
	@echo "Topcoder corpus index -> data/topcoder/corpus_index.jsonl"

topcoder_select_executable:
	$(PYTHON) scripts/topcoder/select_executable_subset.py --input data/topcoder/corpus_index.jsonl
	@echo "Executable subset -> data/topcoder/executable_subset.jsonl"

topcoder_discover_artifacts:
	$(PYTHON) scripts/topcoder/discover_repo_candidates.py --tasks $(DATA_RAW)/tasks.csv --pages-glob 'data/raw/page*.json.gz' --challenge-data-glob 'challenge_data/challengeData_*/*.json' --corpus-index data/topcoder/corpus_index.jsonl
	@echo "Artifact candidates -> data/topcoder/artifact_candidates.jsonl"
	@echo "Repo candidates -> data/topcoder/repo_candidates.jsonl"

topcoder_build_repo_candidates: topcoder_discover_artifacts
	@echo "Repo candidate summary -> data/topcoder/repo_candidates_summary.json"

topcoder_fetch_repos:
	$(PYTHON) scripts/topcoder/fetch_topcoder_repos.py --input data/topcoder/repo_candidates.jsonl --repo-root data/topcoder/repos
	@echo "Repo fetch manifest -> data/topcoder/repo_fetch_manifest.jsonl"

topcoder_build_snapshots:
	$(PYTHON) scripts/topcoder/build_repo_snapshots.py --repo-root data/topcoder/repos --fetch-manifest data/topcoder/repo_fetch_manifest.jsonl
	@echo "Repo snapshots -> data/topcoder/repo_snapshots.jsonl"

topcoder_prepare_workspaces:
	$(PYTHON) scripts/topcoder/prepare_workspaces.py --snapshots data/topcoder/repo_snapshots.jsonl --output data/topcoder/workspace_manifest.jsonl
	@echo "Workspace manifest -> data/topcoder/workspace_manifest.jsonl"

topcoder_source_report:
	$(PYTHON) scripts/topcoder/build_repo_acquisition_report.py
	@echo "Source acquisition report -> data/topcoder/source_acquisition_report.json"

topcoder_debug_repo_recovery:
	$(PYTHON) scripts/topcoder/debug_repo_recovery.py
	@echo "Repo recovery debug -> data/topcoder/repo_recovery_debug.json"

cgcs_dataset:
	$(PYTHON) scripts/build_cgcs_dataset.py
	@echo "CGCS dataset -> $(CGCS_DIR)"

cgcs_debug_dataset:
	$(PYTHON) scripts/openai_ops/debug_dataset_quality.py --input-dir $(CGCS_DIR)
	@echo "CGCS diagnostics printed for $(CGCS_DIR)"

openai_build_eval:
	$(PYTHON) scripts/openai_ops/build_eval_items.py --input-dir $(CGCS_DIR) --split $(EVAL_SPLIT) --output-file $(EVAL_ITEMS_FILE)
	@echo "Eval items -> $(EVAL_ITEMS_FILE)"

openai_build_batch:
	$(PYTHON) scripts/openai_ops/build_batch_requests.py --eval-items $(EVAL_ITEMS_FILE) --output $(BATCH_REQUEST_FILE) --skipped-output $(SKIPPED_EVAL_FILE) --summary-output openai_artifacts/batch_request_summary.json
	@echo "Batch requests -> $(BATCH_REQUEST_FILE)"

openai_submit_batch:
	$(PYTHON) scripts/openai_ops/submit_batch.py --requests-file $(BATCH_REQUEST_FILE)
	@echo "Batch metadata -> openai_artifacts/batches/latest.json"

openai_poll_batch:
	$(PYTHON) scripts/openai_ops/poll_batch.py --metadata openai_artifacts/batches/latest.json || true
	@echo "Normalized outputs -> openai_artifacts/normalized/latest.jsonl"

openai_debug_errors:
	$(PYTHON) scripts/openai_ops/debug_batch_errors.py
	@echo "Batch error breakdown -> openai_artifacts/normalized/latest_errors.jsonl"

openai_graders:
	$(PYTHON) scripts/openai_ops/run_graders.py --normalized-file openai_artifacts/normalized/latest.jsonl --run-id latest || true

openai_prepare_finetune:
	$(PYTHON) scripts/openai_ops/prepare_finetune_data.py

research_funnel_report:
	$(PYTHON) scripts/topcoder/build_funnel_report.py
	@echo "Funnel snapshot -> data/topcoder/funnel_report.json"

public_repo_discover:
	$(PYTHON) scripts/public_repos/discover_public_repos.py --source all --target-size 300 --languages python,javascript,typescript,java --min-stars 20 --out-dir data/public_repos --seed 0
	@echo "Public repo candidates -> data/public_repos/repo_candidates.jsonl"

public_repo_select:
	$(PYTHON) scripts/public_repos/select_repo_pool.py --input data/public_repos/repo_candidates.jsonl --target-size 100 --out-dir data/public_repos --seed 0 --exclude-archived --require-tests --require-build-files
	@echo "Selected repo pool -> data/public_repos/repo_pool_100.jsonl"

public_repo_fetch:
	$(PYTHON) scripts/public_repos/fetch_repo_pool.py --input data/public_repos/repo_pool_100.jsonl --repo-root data/public_repos/repos --manifest data/public_repos/repo_fetch_manifest.jsonl --summary data/public_repos/repo_fetch_summary.json
	@echo "Public repo fetch manifest -> data/public_repos/repo_fetch_manifest.jsonl"

public_repo_snapshots:
	$(PYTHON) scripts/public_repos/build_repo_snapshots.py --repo-root data/public_repos/repos --fetch-manifest data/public_repos/repo_fetch_manifest.jsonl --out-dir data/public_repos
	@echo "Public repo snapshots -> data/public_repos/repo_snapshots.jsonl"

public_repo_workspaces:
	$(PYTHON) scripts/public_repos/prepare_workspaces.py --snapshots data/public_repos/repo_snapshots.jsonl --out-dir data/public_repos
	@echo "Workspace manifest -> data/public_repos/workspace_manifest.jsonl"

public_repo_report:
	$(PYTHON) scripts/public_repos/build_public_repo_report.py
	@echo "Public repo report -> data/public_repos/public_repo_report.json"

# ---------------------------------------------------------------------------
# Public Repo Pilot Benchmark
# ---------------------------------------------------------------------------

PILOT_DIR ?= data/public_repos/pilot
PILOT_REPORTS_DIR ?= reports/decomposition/public_repo_pilot
PILOT_MAX_REPOS ?= 10
PILOT_MAX_TASKS ?= 20
PILOT_STRATEGIES ?= contract_first,failure_mode_first,cgcs

public_repo_pilot_subset:
	$(PYTHON) scripts/public_repos/select_cgcs_pilot_subset.py --input data/public_repos/cgcs_seed_pool.jsonl --out-dir $(PILOT_DIR) --max-repos $(PILOT_MAX_REPOS) --seed 0
	@echo "Pilot subset -> $(PILOT_DIR)/cgcs_pilot_subset.jsonl"

public_repo_validate_workspaces:
	$(PYTHON) scripts/public_repos/validate_cgcs_workspaces.py --subset $(PILOT_DIR)/cgcs_pilot_subset.jsonl --workspace-manifest data/public_repos/workspace_manifest.jsonl --out-dir $(PILOT_DIR) --report-dir $(PILOT_REPORTS_DIR) --bootstrap-mode safe --skip-build-if-missing --timeout-seconds 300
	@echo "Workspace validation -> $(PILOT_DIR)/workspace_validation.jsonl"

public_repo_debug_workspace_failures:
	$(PYTHON) scripts/public_repos/debug_workspace_failures.py --input $(PILOT_DIR)/workspace_validation.jsonl --out-dir $(PILOT_DIR) --report-dir $(PILOT_REPORTS_DIR)
	@echo "Workspace failure report -> $(PILOT_REPORTS_DIR)/workspace_failure_debug.md"

public_repo_seed_tasks:
	$(PYTHON) scripts/public_repos/generate_seeded_repair_tasks.py --validated $(PILOT_DIR)/workspace_validation.jsonl --out-dir $(PILOT_DIR) --mutations-per-task 1 --max-tasks $(PILOT_MAX_TASKS) --seed 0 --allow-runnable-without-build
	@echo "Task manifest -> $(PILOT_DIR)/tasks_manifest.jsonl"

public_repo_rescue_expand:
	$(PYTHON) scripts/public_repos/rescue_and_expand_pilot.py --seed-pool data/public_repos/cgcs_seed_pool.jsonl --workspace-manifest data/public_repos/workspace_manifest.jsonl --initial-subset $(PILOT_DIR)/cgcs_pilot_subset.jsonl --out-dir $(PILOT_DIR) --report-dir $(PILOT_REPORTS_DIR) --initial-pilot-size $(PILOT_MAX_REPOS) --target-validated-repos 5 --max-pilot-size 20 --max-rescue-rounds 3 --seed 0 --bootstrap-mode safe --skip-build-if-missing
	@echo "Rescue summary -> $(PILOT_DIR)/pilot_rescue_summary.json"

public_repo_complete_pilot:
	$(PYTHON) scripts/public_repos/run_complete_public_repo_pilot.py --seed-pool data/public_repos/cgcs_seed_pool.jsonl --workspace-manifest data/public_repos/workspace_manifest.jsonl --initial-subset $(PILOT_DIR)/cgcs_pilot_subset.jsonl --pilot-dir $(PILOT_DIR) --report-dir $(PILOT_REPORTS_DIR) --initial-pilot-size $(PILOT_MAX_REPOS) --target-validated-repos 5 --max-pilot-size 20 --max-seeded-tasks $(PILOT_MAX_TASKS) --seed 0 --bootstrap-mode safe --skip-build-if-missing
	@echo "Complete pilot summary -> $(PILOT_DIR)/complete_pilot_summary.json"

public_repo_run_pilot:
	$(PYTHON) scripts/public_repos/run_public_repo_pilot.py --tasks-manifest $(PILOT_DIR)/tasks_manifest.jsonl --runs-root $(PILOT_REPORTS_DIR)/runs --out-dir $(PILOT_REPORTS_DIR) --strategies $(PILOT_STRATEGIES)
	@echo "Pilot runs -> $(PILOT_REPORTS_DIR)/runs/"

public_repo_audit_traces:
	$(PYTHON) scripts/public_repos/audit_public_repo_trace_quality.py --runs-root $(PILOT_REPORTS_DIR)/runs --out-dir $(PILOT_REPORTS_DIR)
	@echo "Trace quality summary -> $(PILOT_REPORTS_DIR)/trace_quality_summary.json"

public_repo_eval_pack:
	$(PYTHON) scripts/public_repos/build_public_repo_eval_pack.py --input-dir data/cgcs --out-dir openai_artifacts
	@echo "Eval items -> openai_artifacts/public_repo_eval_items.jsonl"

public_repo_pilot_report:
	$(PYTHON) scripts/public_repos/build_public_repo_pilot_report.py --pilot-dir $(PILOT_DIR) --reports-dir $(PILOT_REPORTS_DIR) --eval-summary openai_artifacts/public_repo_eval_summary.json
	@echo "Pilot report -> $(PILOT_DIR)/public_repo_pilot_report.json"
