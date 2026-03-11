# Topcoder Self-Verify Experiment arch_template_check

> **Sample Estimate** — sample_size=100 seed=42 strategy=random

- Total problems: **100** (raw rows 100)
- Actionable attempted: 99 (success 11, failed 88)
- Non-actionable (insufficient context): 1
- Evaluation coverage: 99.00% | Parse failures captured: 0
- Completed successfully: **11** | Overall success rate: 11.00%
- Algo pass@final (provided tests only): 66.67% (8/12)
- Algorithmic coding: attempted 12, solved 8
- Non-coding deliverables: attempted 87, completed 3 (success 3.45%)
- Avg/Median/Max attempts to success: 0.73 / 1.00 / 1.00
- Fallback switches: 4 (rate 0.04) | Stagnation triggers: 4 (rate 0.04)
- Tests: provided/extracted=99 (success 11.11%) synthesized/self-check=0 (success 0.00%)
- Self-checks: attempted 0 (pass 0.00%) — excluded from pass@final
- LLM calls: total=260 avg/task=2.63 per_attempted=2.63 | Solve attempts logged: 48.0
- Runtime: start=2026-03-06T12:39:38.356111 end=2026-03-06T13:27:50.102402 wall=2891.7s avg/task=29.13s
- Artifact traces: `/Users/karanallagh/Desktop/DataCollector/artifacts/self_verifying/arch_template_check`

## Strategy usage
- Initial strategies: {'contract_first': 12}
- Final strategies: {'semantic_diff': 4, 'contract_first': 8}

## Error taxonomy
{'deliverable_parse_error': 84, 'success': 11, 'failed_tests': 4, 'non_actionable': 1}

Reports: 
- `/Users/karanallagh/Desktop/DataCollector/reports/experiments/arch_template_check/per_problem.csv`
- `/Users/karanallagh/Desktop/DataCollector/reports/experiments/arch_template_check/failures.csv`