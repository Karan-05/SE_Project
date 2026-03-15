from pathlib import Path

from src.decomposition.real_repo.edit_batch import RepoEdit, RepoEditBatch
from src.decomposition.real_repo.lint import lint_repo_edit_payload
from src.decomposition.real_repo.task import RepoTaskSpec


def make_task():
    return RepoTaskSpec(
        task_id="demo",
        prompt="Fix bug",
        repo_path=Path("."),
        target_files=["src/app.js", "src/service.js"],
        allowed_edit_paths=["src/**/*.js"],
    )


def test_lint_rejects_paths_outside_allowed_scope():
    task = make_task()
    batch = RepoEditBatch(edits=[RepoEdit(path="lib/util.js", content="// change")])
    errors = lint_repo_edit_payload(batch, task, metadata={})
    assert any("allowed scope" in err for err in errors)


def test_lint_requires_multi_file_targets_or_skip_rationale():
    task = make_task()
    metadata = {
        "multi_file_localization": True,
        "implementation_target_files": ["src/app.js", "src/service.js"],
    }
    batch = RepoEditBatch(edits=[RepoEdit(path="src/app.js", content="// change")])
    errors = lint_repo_edit_payload(batch, task, metadata=metadata)
    assert any("multi-file target" in err for err in errors)

    batch_with_skip = RepoEditBatch(
        edits=[RepoEdit(path="src/app.js", content="// change")],
        metadata={"skipped_targets": ["src/service.js"]},
    )
    errors_with_skip = lint_repo_edit_payload(batch_with_skip, task, metadata=metadata)
    assert not errors_with_skip


def test_lint_blocks_test_edits_when_not_allowed():
    task = make_task()
    batch = RepoEditBatch(edits=[RepoEdit(path="tests/api.spec.js", content="// change")])
    errors = lint_repo_edit_payload(batch, task, metadata={})
    assert any("test edits" in err for err in errors)

    allow_metadata = {"allow_test_edits": True}
    errors_allowed = lint_repo_edit_payload(batch, task, metadata=allow_metadata)
    assert not any("test edits" in err for err in errors_allowed)
