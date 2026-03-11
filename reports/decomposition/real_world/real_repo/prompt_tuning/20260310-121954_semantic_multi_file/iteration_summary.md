# Prompt Tuning Iteration 20260310-121954_semantic_multi_file

- Timestamp (UTC): 20260310-121954
- Mode: dev
- Strategies: contract_first, failure_mode_first
- Task sources: experiments/real_repo_tasks/topcoder
- Notes: Improved multi-file prompting and oracle validation.

## Strategy Metrics
| Strategy | Tasks | Final Pass | Target Recall | Target Precision | Multi-File Edit | Multi-File Attempt | Avg Files | Under-loc GT | Under-loc Targets |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| contract_first | 4 | 0.00 | 0.75 | 1.00 | 0.00 | 0.00 | 1.00 | 1.00 | 0.50 |
| failure_mode_first | 4 | 0.00 | 0.75 | 1.00 | 0.00 | 0.00 | 1.00 | 1.00 | 0.50 |
| oracle_teacher | 4 | 0.00 | 0.00 | 0.00 | 0.25 | 0.00 | 0.00 | 0.00 | 0.00 |

## Delta vs Previous Iteration
- contract_first: final_pass Δ=0.00 (new=0.00, prev=0.00)
- failure_mode_first: final_pass Δ=0.00 (new=0.00, prev=0.00)
- oracle_teacher: final_pass Δ=0.00 (new=0.00, prev=0.00)

## Dominant Failures
- Top failing tests: tests_0
- Top failure modes: fail::
