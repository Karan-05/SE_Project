# Real Repo Benchmark Preflight

- Mode: real_world_research
- Provider: mock
- Model: mock-model
- Task sources: /Users/karanallagh/Desktop/DataCollector/experiments/real_repo_tasks/topcoder/a160ded4_problem_tags_filter
- Tasks detected: 1
- Runtime families: {'node': 1}
- Tasks requiring network: 1

| Check | Status | Message |
| --- | --- | --- |
| provider_configured | FAIL | Mock provider is not allowed in real_world_research mode. |
| model_configured | FAIL | Mock model is not allowed in real_world_research mode. |
| provider_runtime | PASS | Local provider runtime not required. |
| provider_ping | PASS | LLM ping succeeded. |
| source:/Users/karanallagh/Desktop/DataCollector/experiments/real_repo_tasks/topcoder/a160ded4_problem_tags_filter | PASS | Task source found. |
| repo_paths | PASS | All repo snapshots available. |
| tool:node | PASS | Command 'node' available. |
| tool:npm | PASS | Command 'npm' available. |
| setup_plan:tc_arena_problem_tags_filter | PASS | Setup plan ready. |
| test_commands:tc_arena_problem_tags_filter | PASS | Test Commands OK. |
| build_commands:tc_arena_problem_tags_filter | PASS | Build Commands not required. |
