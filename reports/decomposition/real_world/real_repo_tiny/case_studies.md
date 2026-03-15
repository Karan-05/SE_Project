# Real Repository Case Studies (real_world_research)

- Provider: openai
- Model: gpt-4.1-mini

## tc_arena_problem_tags_filter — cgcs
- Repo: `/Users/karanallagh/Desktop/DataCollector/experiments/real_repos/tc-template-node-postgres` (topcoder_arena_srm/a160ded4-e34a-4989-b2a2-d09ead684045)
- Task flags: reportable=True fixture=False real_world=True
- Prompt: Topcoder Arena 3.0 SRM API backlog: extend GET /api/v1/problems so the arena UI can filter problems by arbitrary skill tags (case-insensitive, comma-separated, or array form) and surface the normalized tag filters in the metadata payload. Tag filters must compose with existing difficulty and limit behavior while preserving stable sorting.
- Workspace setup: success (strategy=task_defined)
- Setup log: `/Users/karanallagh/Desktop/DataCollector/reports/decomposition/real_world/real_repo_tiny/runs/tc_arena_problem_tags_filter/cgcs/logs/setup_0_setup.log`
- Target files: modules/Problems/services/ProblemsService.js
- Expected files (per spec): modules/Problems/services/ProblemsService.js
- Implementation target files: modules/Problems/services/ProblemsService.js
- Support files: modules/Problems/controllers/ProblemsController.js, data/problems.json, config/test.json
- Candidate files: modules/Problems/services/ProblemsService.js
- Test files: test/problems.tags.spec.js, test/problems.list.spec.js, test/problems.components.meta.spec.js, test/problems.detail.spec.js
- Oracle patch files: modules/Problems/services/ProblemsService.js, test/problems.list.spec.js
- Allowed edit policy: implementation: modules/Problems/**/*.js; tests: test/problems.list.spec.js; support: data/problems.json, config/test.json, package.json
- Subtasks: contract::single_tag_filter, contract::multi_tag_union, contract::array_tag_filter, Generate minimal unit tests for critical behaviors, Add adversarial/edge-case tests, Run tests and interpret failures
- Final status: exhausted_repairs (pass_rate=0.00)
- Edited files: modules/Problems/services/ProblemsService.js
- Ground-truth files: modules/Problems/services/ProblemsService.js, test/problems.list.spec.js
- Edit shape: single-file (expected multi-file=False)
- Build/test failures: build=0.0 tests=0.0
- Localization precision/recall: 1.00 / 1.00
- Target precision/recall: 1.00 / 1.00
- Implementation precision/recall: 1.00 / 1.00
- Repair attempt multi-file rate: 0.00 (avg files/attempt=1.00)
- Contract coverage: 0.00 (satisfied=n/a, unsatisfied=single_tag_filter;multi_tag_union;array_tag_filter)
- Semantic failure categories: filtering:3
- Dominant semantic gap: filtering
- Localization note: Most edits aligned with planned targets.
- Oracle overlap: precision=1.00 recall=0.50 files=2
- Under-localized: fewer files edited than the ground-truth patch requires.
- Failing tests after run: test_0
- Dominant failure mode: fail:: (tests: tests_0)
### Repair rounds
* Round 0 (initial focus=plan localized=False): status=tests_failed proposed=modules/Problems/services/ProblemsService.js files=modules/Problems/services/ProblemsService.js
* Round 1 (repair focus=contract::multi_tag_union localized=True): status=tests_failed proposed=modules/Problems/services/ProblemsService.js files=modules/Problems/services/ProblemsService.js
* Round 2 (repair focus=contract::single_tag_filter localized=True): status=tests_failed proposed=modules/Problems/services/ProblemsService.js files=modules/Problems/services/ProblemsService.js

