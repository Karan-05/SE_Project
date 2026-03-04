# Meta-Selector Audit

Allowed numerical features:
statement_len, est_complexity, contract_completeness, pattern_confidence, decomposition_steps

| feature | coefficient | abs_coefficient |
| --- | --- | --- |
| est_complexity | 2.1694 | 2.1694 |
| strategy_contract_first | 0.6634 | 0.6634 |
| pitfall::base_case | 0.3512 | 0.3512 |
| statement_len | -0.3186 | 0.3186 |
| task_type_dp | 0.3127 | 0.3127 |
| contract_completeness | 0.1658 | 0.1658 |
| task_type_array | -0.1163 | 0.1163 |
| task_type_graph | -0.1124 | 0.1124 |
| strategy_simulation_trace | -0.1112 | 0.1112 |
| strategy_multi_view | -0.1112 | 0.1112 |
| strategy_semantic_diff | -0.1112 | 0.1112 |
| strategy_failure_mode_first | -0.1112 | 0.1112 |
| strategy_pattern_skeleton | -0.1112 | 0.1112 |
| strategy_role_decomposed | -0.1062 | 0.1062 |
| decomposition_steps | -0.1023 | 0.1023 |
| task_type_string | -0.0951 | 0.0951 |
| pitfall::unicode | -0.0819 | 0.0819 |
| pitfall::off_by_one | -0.0739 | 0.0739 |
| pitfall::large_input | 0.0716 | 0.0716 |
| pitfall::duplicates | -0.0697 | 0.0697 |
| pitfall::time_limit | -0.0532 | 0.0532 |
| task_type_number_theory | 0.0479 | 0.0479 |
| pitfall::small_values | 0.0479 | 0.0479 |
| pitfall::undirected | -0.0427 | 0.0427 |
| pitfall::overflow | -0.0424 | 0.0424 |
| pitfall::ood_shift | 0.0407 | 0.0407 |
| pitfall::no_solution | -0.0385 | 0.0385 |
| pitfall::non_square | -0.0355 | 0.0355 |
| task_type_mixed | -0.0355 | 0.0355 |
| pitfall::edge_case | 0.0228 | 0.0228 |
| pitfall::case_sensitivity | -0.0132 | 0.0132 |
| task_difficulty_S | 0.0131 | 0.0131 |
| task_difficulty_H | -0.0125 | 0.0125 |
| pattern_confidence | -0.0030 | 0.0030 |
| task_difficulty_M | 0.0006 | 0.0006 |
