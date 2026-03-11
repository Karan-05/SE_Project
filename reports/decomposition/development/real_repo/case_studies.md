# Real Repository Case Studies (dev)

- Provider: mock
- Model: mock

## dev_repo_array_sum — contract_first
- Repo: `/Users/karanallagh/Desktop/DataCollector/experiments/real_repos/tiny_python_app` (tiny_python_app_fixture/dev_fixture_repo)
- Task flags: reportable=False fixture=True real_world=False
- Prompt: Implement calculator.task.solve so that it returns the sum of a list of numbers. Use the repository structure and respect the provided tests.
- Workspace setup: skipped (strategy=none)
- Target files: calculator/task.py
- Expected files (per spec): calculator/task.py
- Candidate files: calculator/task.py, tests/test_task.py, calculator/__init__.py
- Subtasks: Validate inputs vs contract, Implement core logic, Check edge cases, Generate minimal unit tests for critical behaviors, Add adversarial/edge-case tests, Run tests and interpret failures
- Final status: exhausted_repairs (pass_rate=0.00)
- Edited files: calculator/task.py
- Edit shape: single-file (expected multi-file=False)
- Build/test failures: build=0.0 tests=0.0
- Localization precision/recall: 1.00 / 0.33
- Localization note: Most edits aligned with planned targets.
- Failing tests after run: test_0
### Repair rounds
* Round 0 (initial focus=plan localized=False): status=tests_failed proposed=calculator/task.py files=calculator/task.py
* Round 1 (repair focus=Validate inputs vs contract localized=True): status=tests_failed proposed=calculator/task.py files=calculator/task.py
* Round 2 (repair focus=Implement core logic localized=True): status=tests_failed proposed=calculator/task.py files=calculator/task.py

