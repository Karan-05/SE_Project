from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from src.public_repos.discovery import DiscoveryConfig, collect_search_candidates, enrich_github_metadata, load_benchmark_seed_candidates
from src.public_repos.scoring import compute_suitability
from src.public_repos.types import RepoCandidate, RepoIdentity


class StubGitHubClient:
    def __init__(self, repo_payloads: dict[tuple[str, str], dict[str, object]], directories: dict[tuple[str, str, str], list[dict[str, object]]]):
        self.repo_payloads = repo_payloads
        self.directories = directories

    def get_repo(self, owner: str, name: str) -> dict[str, object]:
        return self.repo_payloads[(owner, name)]

    def list_directory(self, owner: str, name: str, path: str = "") -> list[dict[str, object]]:
        return self.directories.get((owner, name, path.strip("/")), [])


def test_enrich_and_score_recognizes_build_and_tests() -> None:
    identity = RepoIdentity(host="github.com", owner="org", name="demo")
    candidate = RepoCandidate.from_identity(identity, source_type="host_search")
    repo_payload = {
        "description": "Demo repo",
        "language": "Python",
        "topics": ["ci"],
        "stargazers_count": 80,
        "forks_count": 10,
        "watchers_count": 5,
        "pushed_at": "2024-04-01T00:00:00Z",
        "archived": False,
        "default_branch": "main",
        "license": {"key": "mit"},
        "size": 1024,
    }
    directories = {
        ("org", "demo", ""): [
            {"name": "package.json", "type": "file"},
            {"name": "tests", "type": "dir"},
            {"name": ".github", "type": "dir"},
        ],
        ("org", "demo", ".github/workflows"): [
            {"name": "ci.yml", "type": "file"},
        ],
    }
    client = StubGitHubClient({("org", "demo"): repo_payload}, directories)
    enriched = enrich_github_metadata(client, candidate)
    assert enriched.has_build_files
    assert enriched.has_tests
    assert enriched.has_ci
    compute_suitability(enriched, min_stars=20, recent_days=365)
    assert enriched.suitability_score > 2.0


def test_seed_loader_rejects_invalid_slugs(tmp_path: Path) -> None:
    manifest = tmp_path / "seeds.jsonl"
    manifest.write_text(
        '\n'.join(
            [
                '{"repo_url": "https://github.com/acme/project-one"}',
                '{"repo": "missing_host"}',
                '{"repo_url": "https://invalid"}',
            ]
        )
    )
    owner_counts: dict[str, int] = defaultdict(int)
    seeds = load_benchmark_seed_candidates([manifest], max_per_owner=1, owner_counts=owner_counts)
    assert len(seeds) == 1
    assert seeds[0].owner == "acme"


def test_search_candidates_enforces_owner_cap() -> None:
    class SearchStub(StubGitHubClient):
        def __init__(self) -> None:
            payloads = {
                ("org", "alpha"): {
                    "description": "",
                    "language": "Python",
                    "stargazers_count": 50,
                    "forks_count": 5,
                    "watchers_count": 5,
                    "pushed_at": "2024-02-01T00:00:00Z",
                    "archived": False,
                    "default_branch": "main",
                    "license": None,
                    "size": 900,
                },
                ("org", "beta"): {
                    "description": "",
                    "language": "Python",
                    "stargazers_count": 60,
                    "forks_count": 6,
                    "watchers_count": 6,
                    "pushed_at": "2024-03-01T00:00:00Z",
                    "archived": False,
                    "default_branch": "main",
                    "license": None,
                    "size": 1100,
                },
            }
            directories = {("org", "alpha", ""): [], ("org", "beta", ""): []}
            super().__init__(payloads, directories)

        def search_repositories(self, query: str, per_page: int = 100, max_pages: int = 10):
            yield {
                "html_url": "https://github.com/org/alpha",
                "language": "Python",
                "stargazers_count": 50,
                "forks_count": 5,
                "watchers_count": 5,
                "pushed_at": "2024-02-01T00:00:00Z",
                "archived": False,
                "description": "",
                "size": 900,
            }
            yield {
                "html_url": "https://github.com/org/beta",
                "language": "Python",
                "stargazers_count": 60,
                "forks_count": 6,
                "watchers_count": 6,
                "pushed_at": "2024-03-01T00:00:00Z",
                "archived": False,
                "description": "",
                "size": 1100,
            }

    client = SearchStub()
    config = DiscoveryConfig(
        sources={"github_search"},
        min_stars=20,
        target_size=10,
        languages=["python"],
        recent_days=365,
        max_per_owner=1,
        seed=0,
    )
    owner_counts: dict[str, int] = defaultdict(int)
    results = collect_search_candidates(client, config, owner_counts)
    assert len(results) == 1
    assert results[0].name == "alpha"
