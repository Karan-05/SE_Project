# Real Repo Benchmark Preflight

- Mode: dev
- Provider: mock
- Model: mock-model
- Task sources: experiments/real_repo_tasks/topcoder
- Tasks detected: 4
- Runtime families: {'node': 4}
- Tasks requiring network: 4

| Check | Status | Message |
| --- | --- | --- |
| provider_configured | PASS | LLM provider 'mock' configured. |
| model_configured | PASS | LLM model 'mock-model' configured. |
| provider_runtime | PASS | Local provider runtime not required. |
| provider_ping | PASS | LLM ping succeeded. |
| source:experiments/real_repo_tasks/topcoder | PASS | Task source found. |
| repo_paths | PASS | All repo snapshots available. |
| tool:node | PASS | Command 'node' available. |
| tool:npm | PASS | Command 'npm' available. |
| setup_plan:tc_arena_component_metadata_summary | PASS | Setup plan ready. |
| test_commands:tc_arena_component_metadata_summary | PASS | Test Commands OK. |
| build_commands:tc_arena_component_metadata_summary | PASS | Build Commands not required. |
| setup_plan:tc_arena_problem_detail | PASS | Setup plan ready. |
| test_commands:tc_arena_problem_detail | PASS | Test Commands OK. |
| build_commands:tc_arena_problem_detail | PASS | Build Commands not required. |
| setup_plan:tc_arena_problem_listing | PASS | Setup plan ready. |
| test_commands:tc_arena_problem_listing | PASS | Test Commands OK. |
| build_commands:tc_arena_problem_listing | PASS | Build Commands not required. |
| setup_plan:tc_arena_problem_tags_filter | PASS | Setup plan ready. |
| test_commands:tc_arena_problem_tags_filter | PASS | Test Commands OK. |
| build_commands:tc_arena_problem_tags_filter | PASS | Build Commands not required. |
