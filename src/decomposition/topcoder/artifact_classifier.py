"""Heuristics for classifying Topcoder artifact URLs."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

from .repos import RepoURLInfo, normalize_repo_url

# Acquisition strategies
ACQUISITION_CLONE = "clone"
ACQUISITION_CLONE_OR_DOWNLOAD = "clone_or_source_download"
ACQUISITION_DOWNLOAD_ARCHIVE = "download_archive"
ACQUISITION_DOWNLOAD_RAW_FILE = "download_raw_file"
ACQUISITION_REJECT = "reject_non_repo"
ACQUISITION_SYNTHETIC = "synthetic_workspace_stub"

REPO_ACQUISITION_STRATEGIES = {
    ACQUISITION_CLONE,
    ACQUISITION_CLONE_OR_DOWNLOAD,
    ACQUISITION_DOWNLOAD_ARCHIVE,
}

GIT_HOSTS = {"github.com", "gitlab.com", "bitbucket.org"}
RAW_CODE_HOSTS = {
    "raw.githubusercontent.com",
    "rawgit.com",
    "rawcdn.githack.com",
    "codeberg.page",
}
GIST_HOSTS = {"gist.github.com", "gist.githubusercontent.com", "pastebin.com", "codepen.io"}
API_HOST_PATTERNS = (
    "execute-api.",
    "api.",
    ".api.",
    "api-",
    "-api.",
    "cloudfront.net",
    "amazonaws.com",
    "azure-api.net",
)
WEB_APP_HOST_PATTERNS = (
    "appspot.com",
    "herokuapp.com",
    "vercel.app",
    "azurewebsites.net",
)
DOC_KEYWORDS = ("docs", "documentation", "wiki", "help", "support", "guide", "blog")
APP_KEYWORDS = ("app", "demo", "preview", "portal", "dashboard", "staging", "beta")
ARCHIVE_EXTENSIONS = (".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz")
CODE_FILE_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".java",
    ".kt",
    ".kts",
    ".rb",
    ".go",
    ".rs",
    ".c",
    ".h",
    ".cpp",
    ".cc",
    ".cxx",
    ".cs",
    ".php",
    ".swift",
    ".m",
    ".mm",
    ".scala",
    ".sql",
    ".html",
    ".css",
    ".json",
    ".yml",
    ".yaml",
}
NON_SOURCE_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".jpeg", ".jpg", ".png", ".gif")

ARTIFACT_CONFIDENCE = {
    "git_repo": "high",
    "git_host_repo_page": "high",
    "source_archive": "high",
    "raw_code_file": "medium",
    "gist_or_snippet": "medium",
    "source_archive_attachment": "medium",
    "api_endpoint": "low",
    "web_app": "low",
    "docs_page": "low",
    "file_download_non_source": "low",
    "unknown": "low",
}


@dataclass(slots=True)
class ArtifactClassification:
    normalized_url: str
    host: str
    path: str
    artifact_type: str
    acquisition_strategy: str
    classification_reason: str
    confidence: str
    normalized_repo_key: Optional[str] = None
    normalized_repo_url: Optional[str] = None


@dataclass(slots=True)
class _ParsedURL:
    raw: str
    normalized_url: str
    host: str
    path: str
    query: str


_IP_PATTERN = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


def _sanitize_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value)
    cleaned = cleaned.strip("-")
    return cleaned or "artifact"


def _archive_key(host: str, path: str, normalized_url: str) -> str:
    digest = hashlib.sha1(normalized_url.encode("utf-8")).hexdigest()[:10]
    host_component = _sanitize_component(host)
    path_component = _sanitize_component(path)
    if len(path_component) > 96:
        path_component = path_component[:96]
    return f"{host_component}/{path_component}-{digest}"


def _parse_http_url(value: str) -> Optional[_ParsedURL]:
    trimmed = value.strip()
    if not trimmed:
        return None
    if "://" not in trimmed and not trimmed.startswith("//"):
        trimmed = f"https://{trimmed.lstrip('/')}"
    try:
        parsed = urlparse(trimmed)
    except ValueError:
        return None
    host = (parsed.netloc or "").split("@")[-1]
    host = host.lower()
    if not host:
        return None
    normalized = f"https://{host}{parsed.path or ''}"
    if parsed.query:
        normalized = f"{normalized}?{parsed.query}"
    return _ParsedURL(
        raw=value,
        normalized_url=normalized,
        host=host,
        path=parsed.path or "",
        query=parsed.query or "",
    )


def _classification_from_repo_info(info: RepoURLInfo, reason: str, is_direct_remote: bool) -> ArtifactClassification:
    strategy = ACQUISITION_CLONE if is_direct_remote else ACQUISITION_CLONE_OR_DOWNLOAD
    artifact_type = "git_repo" if is_direct_remote else "git_host_repo_page"
    return ArtifactClassification(
        normalized_url=info.normalized_url,
        host=info.repo_host,
        path=f"/{info.repo_path}",
        artifact_type=artifact_type,
        acquisition_strategy=strategy,
        classification_reason=reason,
        confidence="high",
        normalized_repo_key=info.repo_key,
        normalized_repo_url=info.normalized_url,
    )


def _looks_like_api(parsed: _ParsedURL) -> bool:
    host = parsed.host
    if _IP_PATTERN.match(host):
        return True
    lowered = host.lower()
    if any(pattern in lowered for pattern in API_HOST_PATTERNS):
        return True
    path_lower = parsed.path.lower()
    if any(token in path_lower for token in ("/api", "/apis", "swagger", "graphql", "openapi")):
        return True
    if parsed.query and "api" in parsed.query.lower():
        return True
    return False


def _looks_like_doc(parsed: _ParsedURL) -> bool:
    tokens = [parsed.host.lower(), parsed.path.lower()]
    return any(keyword in token for token in tokens for keyword in DOC_KEYWORDS)


def _looks_like_web_app(parsed: _ParsedURL) -> bool:
    host = parsed.host.lower()
    if any(pattern in host for pattern in WEB_APP_HOST_PATTERNS):
        return True
    parts = host.split(".")
    if parts and parts[0] in APP_KEYWORDS:
        return True
    path_lower = parsed.path.lower()
    return any(keyword in path_lower.split("/") for keyword in APP_KEYWORDS)


def _looks_like_archive(parsed: _ParsedURL) -> bool:
    lower_path = parsed.path.lower()
    return lower_path.endswith(ARCHIVE_EXTENSIONS) or "/archive/" in lower_path or "/releases/download/" in lower_path


def _looks_like_raw_code(parsed: _ParsedURL) -> bool:
    host = parsed.host.lower()
    path_lower = parsed.path.lower()
    if any(host.endswith(raw_host) for raw_host in RAW_CODE_HOSTS):
        return True
    for ext in CODE_FILE_EXTENSIONS:
        if path_lower.endswith(ext):
            return True
    return False


def _looks_like_file_download(parsed: _ParsedURL) -> bool:
    lower_path = parsed.path.lower()
    return any(lower_path.endswith(ext) for ext in NON_SOURCE_EXTENSIONS)


def _looks_like_gist(parsed: _ParsedURL) -> bool:
    return parsed.host.lower() in GIST_HOSTS


def classify_candidate_url(url: str) -> ArtifactClassification:
    trimmed = url.strip()
    if not trimmed:
        return ArtifactClassification(
            normalized_url=url,
            host="",
            path="",
            artifact_type="unknown",
            acquisition_strategy=ACQUISITION_REJECT,
            classification_reason="empty_url",
            confidence="low",
        )
    if trimmed.startswith("git@") or trimmed.endswith(".git"):
        info = normalize_repo_url(trimmed)
        if info:
            return _classification_from_repo_info(info, "ssh_or_dot_git", is_direct_remote=True)
    parsed = _parse_http_url(trimmed)
    if not parsed:
        return ArtifactClassification(
            normalized_url=trimmed,
            host="",
            path="",
            artifact_type="unknown",
            acquisition_strategy=ACQUISITION_REJECT,
            classification_reason="unparseable",
            confidence="low",
        )
    # Source archive detection first to avoid falling back to repo pages.
    if _looks_like_archive(parsed):
        base_repo: Optional[RepoURLInfo] = None
        segments = [segment for segment in parsed.path.split("/") if segment]
        if len(segments) >= 2 and parsed.host in GIT_HOSTS:
            base_hint = f"https://{parsed.host}/{segments[0]}/{segments[1]}"
            base_repo = normalize_repo_url(base_hint)
        normalized_repo_key = _archive_key(parsed.host, parsed.path, parsed.normalized_url)
        reason = "archive_url"
        if base_repo:
            reason = f"{reason}:{base_repo.repo_path}"
        return ArtifactClassification(
            normalized_url=parsed.normalized_url,
            host=parsed.host,
            path=parsed.path,
            artifact_type="source_archive",
            acquisition_strategy=ACQUISITION_DOWNLOAD_ARCHIVE,
            classification_reason=reason,
            confidence="high",
            normalized_repo_key=normalized_repo_key,
            normalized_repo_url=base_repo.normalized_url if base_repo else None,
        )
    if _looks_like_raw_code(parsed):
        return ArtifactClassification(
            normalized_url=parsed.normalized_url,
            host=parsed.host,
            path=parsed.path,
            artifact_type="raw_code_file",
            acquisition_strategy=ACQUISITION_DOWNLOAD_RAW_FILE,
            classification_reason="raw_code_or_source_file",
            confidence="medium",
            normalized_repo_key=_archive_key(parsed.host, parsed.path, parsed.normalized_url),
        )
    if _looks_like_gist(parsed):
        return ArtifactClassification(
            normalized_url=parsed.normalized_url,
            host=parsed.host,
            path=parsed.path,
            artifact_type="gist_or_snippet",
            acquisition_strategy=ACQUISITION_DOWNLOAD_RAW_FILE,
            classification_reason="gist_or_snippet_host",
            confidence="medium",
            normalized_repo_key=_archive_key(parsed.host, parsed.path, parsed.normalized_url),
        )
    if _looks_like_api(parsed):
        reason = "api_host_or_path"
        if _IP_PATTERN.match(parsed.host):
            reason = "direct_ip_api"
        return ArtifactClassification(
            normalized_url=parsed.normalized_url,
            host=parsed.host,
            path=parsed.path,
            artifact_type="api_endpoint",
            acquisition_strategy=ACQUISITION_REJECT,
            classification_reason=reason,
            confidence="low",
        )
    if _looks_like_doc(parsed):
        return ArtifactClassification(
            normalized_url=parsed.normalized_url,
            host=parsed.host,
            path=parsed.path,
            artifact_type="docs_page",
            acquisition_strategy=ACQUISITION_REJECT,
            classification_reason="documentation_host_or_path",
            confidence="low",
        )
    if _looks_like_file_download(parsed):
        return ArtifactClassification(
            normalized_url=parsed.normalized_url,
            host=parsed.host,
            path=parsed.path,
            artifact_type="file_download_non_source",
            acquisition_strategy=ACQUISITION_REJECT,
            classification_reason="non_source_file_extension",
            confidence="low",
        )
    if _looks_like_web_app(parsed):
        return ArtifactClassification(
            normalized_url=parsed.normalized_url,
            host=parsed.host,
            path=parsed.path,
            artifact_type="web_app",
            acquisition_strategy=ACQUISITION_REJECT,
            classification_reason="web_app_host_or_path",
            confidence="low",
        )
    if parsed.host in GIT_HOSTS:
        repo_info = normalize_repo_url(parsed.normalized_url)
        if repo_info:
            return _classification_from_repo_info(repo_info, "git_host_repo_page", is_direct_remote=False)
    return ArtifactClassification(
        normalized_url=parsed.normalized_url,
        host=parsed.host,
        path=parsed.path,
        artifact_type="unknown",
        acquisition_strategy=ACQUISITION_REJECT,
        classification_reason="unclassified_url",
        confidence=ARTIFACT_CONFIDENCE.get("unknown", "low"),
    )


__all__ = [
    "ArtifactClassification",
    "classify_candidate_url",
    "REPO_ACQUISITION_STRATEGIES",
    "ACQUISITION_CLONE",
    "ACQUISITION_CLONE_OR_DOWNLOAD",
    "ACQUISITION_DOWNLOAD_ARCHIVE",
    "ACQUISITION_DOWNLOAD_RAW_FILE",
    "ACQUISITION_REJECT",
    "ACQUISITION_SYNTHETIC",
]
