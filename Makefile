PYTHON ?= python
DATA_RAW := data/raw
DATA_PROCESSED := data/processed
SEEDS ?= 10
EPISODES ?= 5
HORIZON ?= 50

.PHONY: preprocess train_supervised train_embeddings run_rl paper tests clean \
	decomp_benchmark decomp_rl decomp_rl_seeds decomp_multiagent decomp_meta \
	decomp_meta_audit decomp_frontier decomp_real decomp_all \
	toh_benchmark regression_eval end_to_end_eval final_artifacts paper_artifacts \
	docs_reference

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
