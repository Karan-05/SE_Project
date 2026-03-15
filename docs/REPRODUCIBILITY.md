# Reproducibility Guide

This document lists the commands required to rebuild the CGCS results, dataset, and paper assets from a clean checkout.

## 1. Environment

1. Create the local virtual environment and install dependencies:

   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. Confirm Topcoder snapshot data is available under `experiments/real_repo_tasks/topcoder`.

## 2. Real-repo benchmark

The `scripts/prepare_real_repo_benchmark.py` helper runs preflight checks and executes strategies.

- **Preflight only**

  ```bash
  make real_repo_preflight
  ```

  This validates provider credentials, prepares workspaces under `reports/decomposition/workspace_prep`, and writes the preflight report to `reports/decomposition/real_world/real_repo`.

- **Full benchmark run**

  ```bash
  make real_repo_run
  ```

  The command runs the configured strategies, including CGCS once it is registered, and stores logs in `reports/decomposition/real_world/real_repo`.

## 3. Dataset build + anonymization

1. Build the CGCS dataset directly from the run logs and traces:

   ```bash
   make cgcs_dataset
   ```

   Outputs `data/cgcs/{train,dev,test}.jsonl`.

2. Produce an anonymized copy suitable for artifact submission:

   ```bash
   python scripts/anonymize_artifact.py --source data/cgcs --dest artifacts/cgcs_anonymized
   ```

## 4. Paper tables and figures

Rebuild the summary tables and figures used in the ASE paper:

```bash
make paper_tables
make paper_figures
```

Tables are written to `reports/ase2026_aegis/cgcs_table_main.csv` and figures to `reports/ase2026_aegis/figure_cgcs_pass_rate.png`.

## 5. Dataset schema + logs

Refer to `docs/CGCS_DATASET_SCHEMA.md` for a detailed schema definition and to `reports/ase2026_aegis/session_log.md` for session-by-session provenance.
