"""Thin wrapper around the GitHub REST API with caching and retries."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator
from urllib.parse import quote

import requests


class GitHubClientError(RuntimeError):
    """Generic GitHub API failure."""


class GitHubRateLimitError(GitHubClientError):
    """Raised when GitHub reports a rate limit violation."""


class GitHubClient:
    """Convenience wrapper for GitHub REST calls used by the discovery stage."""

    def __init__(
        self,
        token: str | None = None,
        cache_dir: Path | None = None,
        request_timeout: int = 30,
        max_retries: int = 2,
    ) -> None:
        self._session = requests.Session()
        self._token = token
        self._cache_dir = cache_dir
        self._timeout = request_timeout
        self._max_retries = max_retries
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_key(self, method: str, url: str, params: dict[str, Any] | None) -> Path | None:
        if not self._cache_dir:
            return None
        payload = {"method": method, "url": url, "params": params or {}}
        data = json.dumps(payload, sort_keys=True).encode("utf-8")
        digest = hashlib.sha1(data).hexdigest()
        return self._cache_dir / f"{digest}.json"

    def _read_cache(self, path: Path | None) -> Any | None:
        if path and path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
        return None

    def _write_cache(self, path: Path | None, payload: Any) -> None:
        if not path:
            return
        try:
            path.write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            return

    def _request(self, method: str, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        url = f"https://api.github.com{endpoint}"
        cache_path = self._cache_key(method, url, params)
        cached = self._read_cache(cache_path)
        if cached is not None:
            return cached
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "public-repo-pipeline"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        attempt = 0
        last_error: GitHubClientError | None = None
        while attempt <= self._max_retries:
            response = self._session.request(method, url, params=params, timeout=self._timeout, headers=headers)
            if response.status_code == 403 and "rate limit" in response.text.lower():
                reset = response.headers.get("X-RateLimit-Reset")
                detail = f"rate_limit (reset={reset})" if reset else "rate_limit"
                raise GitHubRateLimitError(
                    f"GitHub API rate limit reached; set GITHUB_TOKEN and retry ({detail})."
                )
            if response.status_code in (502, 503, 504):
                last_error = GitHubClientError(f"GitHub temporary error {response.status_code}")
            elif response.status_code >= 400:
                raise GitHubClientError(f"GitHub error {response.status_code}: {response.text[:200]}")
            else:
                payload = response.json()
                self._write_cache(cache_path, payload)
                return payload
            attempt += 1
            time.sleep(min(2**attempt, 10))
        if last_error:
            raise last_error
        raise GitHubClientError("GitHub request failed")

    def search_repositories(
        self,
        query: str,
        sort: str = "updated",
        order: str = "desc",
        per_page: int = 100,
        max_pages: int = 10,
    ) -> Iterator[dict[str, Any]]:
        pages = min(max_pages, 10)
        for page in range(1, pages + 1):
            params = {
                "q": query,
                "sort": sort,
                "order": order,
                "per_page": per_page,
                "page": page,
            }
            payload = self._request("GET", "/search/repositories", params=params)
            items = payload.get("items") or []
            for item in items:
                yield item
            if len(items) < per_page:
                break

    def get_repo(self, owner: str, name: str) -> dict[str, Any]:
        owner_q = quote(owner)
        name_q = quote(name)
        return self._request("GET", f"/repos/{owner_q}/{name_q}")

    def list_directory(self, owner: str, name: str, path: str = "") -> list[dict[str, Any]]:
        owner_q = quote(owner)
        name_q = quote(name)
        path = path.strip("/")
        suffix = f"/contents/{quote(path)}" if path else "/contents"
        endpoint = f"/repos/{owner_q}/{name_q}{suffix}"
        try:
            payload = self._request("GET", endpoint)
        except GitHubClientError as exc:
            message = str(exc)
            if "404" in message:
                return []
            raise
        if isinstance(payload, list):
            return payload
        return []
