from __future__ import annotations

from src.public_repos.pilot import expansion


def candidate(repo_key: str, language: str, build: str, test: str, confidence: float = 0.9) -> dict[str, object]:
    return {
        "repo_key": repo_key,
        "language": language,
        "build_systems": [build],
        "test_frameworks": [test],
        "runnable_confidence": confidence,
    }


def test_replacements_avoid_hard_blocked_and_reuse() -> None:
    pool = [
        candidate("github.com/a/py", "python", "pyproject", "pytest"),
        candidate("github.com/b/js", "javascript", "npm", "jest"),
        candidate("github.com/c/java", "java", "maven", "junit"),
    ]
    current = [candidate("github.com/a/py", "python", "pyproject", "pytest")]
    attempted = {"github.com/a/py"}
    hard_blocked = {"github.com/b/js"}

    replacements = expansion.select_replacements(
        pool,
        current_entries=current,
        attempted_keys=attempted,
        hard_blocked=hard_blocked,
        max_new=2,
        rng_seed=0,
    )
    keys = [decision.repo_key for decision in replacements]
    assert keys == ["github.com/c/java"]
    assert replacements[0].reason
