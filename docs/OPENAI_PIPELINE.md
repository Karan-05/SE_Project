# OpenAI Research Operations Pipeline

This document describes how to operate the CGCS research pipeline end-to-end using the OpenAI Python SDK and the Responses API.

## Overview

1. **Eval item creation** – Convert CGCS repair traces into model-ready evaluation items via `scripts/openai_ops/build_eval_items.py`.
2. **Artifact upload** – Use `scripts/openai_ops/upload_artifacts.py` to persist datasets, reports, and traces; the returned IDs feed downstream jobs.
3. **Batch generation** – `scripts/openai_ops/build_batch_requests.py` wraps each eval item in a deterministic Responses API call.
4. **Batch execution** – Submit and poll batches with `scripts/openai_ops/submit_batch.py` and `scripts/openai_ops/poll_batch.py`. Outputs are normalized for grading.
5. **Graders & scoring** – `scripts/openai_ops/run_graders.py` blends LLM-based graders with deterministic Python checks.
6. **Fine-tune prep** – `scripts/openai_ops/prepare_finetune_data.py` filters the highest-quality attempts, producing leakage-safe JSONL splits.
7. **Optional fine-tuning** – `scripts/openai_ops/start_finetune.py` starts a guarded fine-tuning job once dataset size/quality checks pass.

All commands support deterministic seeds, emit paper-auditable logs, and gracefully degrade when credentials are absent.
