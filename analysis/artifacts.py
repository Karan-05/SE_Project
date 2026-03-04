"""Download and analyse Topcoder submission artifacts for research metrics."""

from __future__ import annotations

import json
import os
import shutil
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import urllib.error
import urllib.request

try:
    import requests  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - fallback
    requests = None  # type: ignore[assignment]

LANGUAGE_EXTENSIONS = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".java": "Java",
    ".kt": "Kotlin",
    ".cs": "C#",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".c": "C",
    ".rs": "Rust",
    ".go": "Go",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".m": "Objective-C",
    ".mm": "Objective-C++",
    ".scala": "Scala",
    ".sql": "SQL",
    ".sh": "Shell",
    ".bat": "Batch",
    ".ps1": "PowerShell",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".html": "HTML",
    ".css": "CSS",
    ".md": "Markdown",
    ".txt": "Plaintext",
}

TEXT_EXTENSIONS = set(LANGUAGE_EXTENSIONS.keys())

IGNORED_DIRECTORIES = {
    "__pycache__",
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "dist",
    "build",
    ".idea",
    ".vscode",
}


@dataclass
class SubmissionArtifact:
    challenge_id: str
    submission_id: str
    handle: Optional[str]
    status: Optional[str]
    score: Optional[float]
    artifact_url: Optional[str]
    lines_total: int = 0
    files_total: int = 0
    languages: Dict[str, int] | None = None
    tests_detected: bool = False
    avg_lines_per_file: float = 0.0
    complexity_label: str = "Unknown"
    ai_feasibility: str = "Unknown"
    frameworks: List[str] | None = None
    dependencies: List[str] | None = None
    llm_signals: List[str] | None = None
    notes: str | None = None


class ArtifactAnalyzer:
    """Handles artifact downloads, extraction, and complexity heuristics."""

    def __init__(
        self,
        output_dir: Path,
        token: str,
        base_url: str,
        *,
        download: bool = False,
        limit_per_challenge: int = 3,
        http_timeout: float = 30.0,
        debug_path: Optional[Path] = None,
    ) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.download_enabled = download
        self.limit_per_challenge = limit_per_challenge
        self.http_timeout = http_timeout
        self.debug_path = debug_path or (output_dir / "artifact_debug.log")

    def process(
        self,
        submission_map: Dict[str, List[Dict[str, Any]]],
        challenges_by_id: Dict[str, Dict[str, Any]],
    ) -> Tuple[List[SubmissionArtifact], Dict[str, Any]]:
        results: List[SubmissionArtifact] = []
        aggregate_languages: Dict[str, int] = {}
        failures: List[str] = []

        for challenge_id, submissions in submission_map.items():
            if not submissions:
                continue
            limited_submissions = sorted(
                submissions,
                key=lambda item: (item.get("score") or 0, item.get("created") or ""),
                reverse=True,
            )[: self.limit_per_challenge]

            for submission in limited_submissions:
                record = SubmissionArtifact(
                    challenge_id=challenge_id,
                    submission_id=str(submission.get("submissionId") or submission.get("id") or "unknown"),
                    handle=submission.get("memberHandle"),
                    status=submission.get("status"),
                    score=self._coerce_float(submission.get("score")),
                    artifact_url=submission.get("artifact") or submission.get("url"),
                )
                if not record.artifact_url:
                    record.notes = "No artifact URL provided."
                    results.append(record)
                    continue

                if not self.download_enabled:
                    record.notes = "Download disabled; metrics unavailable."
                    results.append(record)
                    continue

                try:
                    artifact_path = self._download_artifact(record)
                except Exception as exc:  # pragma: no cover - network failure path
                    record.notes = f"Download failed: {exc}"
                    failures.append(record.submission_id)
                    self._log_debug(
                        f"[download] submission {record.submission_id} failed: {exc}"
                    )
                    results.append(record)
                    continue

                try:
                    extract_dir = self._extract_artifact(record, artifact_path)
                    metrics = self._analyse_directory(extract_dir)
                except Exception as exc:  # pragma: no cover - extraction failure path
                    record.notes = f"Extraction failed: {exc}"
                    results.append(record)
                    continue

                record.lines_total = metrics["lines_total"]
                record.files_total = metrics["files_total"]
                record.languages = metrics["languages"]
                record.tests_detected = metrics["tests_detected"]
                record.avg_lines_per_file = metrics["avg_lines_per_file"]
                record.frameworks = metrics.get("frameworks")
                record.dependencies = metrics.get("dependencies")
                record.llm_signals = metrics.get("llm_signals")
                record.complexity_label = self._complexity_label(record)
                record.ai_feasibility = self._ai_feasibility(record, challenges_by_id.get(challenge_id))
                record.notes = metrics["notes"]

                for lang, count in (record.languages or {}).items():
                    aggregate_languages[lang] = aggregate_languages.get(lang, 0) + count

                results.append(record)

        aggregates = self._build_aggregates(results, aggregate_languages, failures)
        return results, aggregates

    def _download_artifact(self, record: SubmissionArtifact) -> Path:
        headers = {"Authorization": f"Bearer {self.token}"}
        url = self._signed_artifact_url(record.submission_id) or record.artifact_url
        if not url:
            raise RuntimeError("No downloadable artifact URL available.")
        self._log_debug(f"[download] submission {record.submission_id} -> {url}")
        response_bytes: bytes

        if requests is not None:  # pragma: no cover - exercised in live env
            resp = requests.get(url, headers=headers, timeout=self.http_timeout)
            resp.raise_for_status()
            response_bytes = resp.content
        else:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=self.http_timeout) as resp:
                response_bytes = resp.read()

        submission_dir = self.output_dir / record.challenge_id
        submission_dir.mkdir(parents=True, exist_ok=True)
        ext = self._guess_extension(url)
        file_path = submission_dir / f"{record.submission_id}{ext}"
        with open(file_path, "wb") as fh:
            fh.write(response_bytes)
        return file_path

    def _signed_artifact_url(self, submission_id: str) -> Optional[str]:
        endpoint = f"{self.base_url}/submissions/{submission_id}/download"
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            if requests is not None:  # pragma: no cover - live path
                resp = requests.get(endpoint, headers=headers, timeout=self.http_timeout)
                if resp.status_code >= 400:
                    self._log_debug(
                        f"[download-url] submission {submission_id} status {resp.status_code}: {resp.text[:200]}"
                    )
                    return None
                data = resp.json()
            else:
                req = urllib.request.Request(endpoint, headers=headers)
                with urllib.request.urlopen(req, timeout=self.http_timeout) as fh:
                    data = json.loads(fh.read().decode("utf-8"))
            if isinstance(data, dict):
                for key in ("url", "downloadUrl", "preSignedUrl", "presignedUrl", "signedUrl"):
                    value = data.get(key)
                    if value:
                        return value
                self._log_debug(
                    f"[download-url] submission {submission_id} unexpected payload keys: {list(data.keys())}"
                )
        except Exception as exc:
            self._log_debug(
                f"[download-url] submission {submission_id} exception: {exc}"
            )
            return None
        return None

    def _extract_artifact(self, record: SubmissionArtifact, artifact_path: Path) -> Path:
        target_dir = artifact_path.parent / artifact_path.stem
        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.mkdir()

        suffix = artifact_path.suffix.lower()
        if suffix in {".zip"}:
            with zipfile.ZipFile(artifact_path, "r") as archive:
                archive.extractall(target_dir)
        elif suffix in {".tar", ".gz", ".tgz", ".bz2", ".xz"}:
            mode = "r"
            if suffix in {".gz", ".tgz"}:
                mode = "r:gz"
            elif suffix == ".bz2":
                mode = "r:bz2"
            elif suffix == ".xz":
                mode = "r:xz"
            with tarfile.open(artifact_path, mode) as archive:
                archive.extractall(target_dir)
        else:
            # Treat as a single file; copy to directory for analysis.
            shutil.copy2(artifact_path, target_dir / artifact_path.name)
        return target_dir

    def _analyse_directory(self, target_dir: Path) -> Dict[str, Any]:
        lines_total = 0
        files_total = 0
        languages: Dict[str, int] = {}
        tests_detected = False
        frameworks: set[str] = set()
        dependencies: set[str] = set()
        llm_signals: set[str] = set()

        for path in target_dir.rglob("*"):
            relative_parts = [part.lower() for part in path.parts]
            if any(part in IGNORED_DIRECTORIES for part in relative_parts):
                continue
            if path.is_dir():
                continue
            suffix = path.suffix.lower()
            if suffix not in TEXT_EXTENSIONS:
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except (UnicodeDecodeError, OSError):
                continue

            line_count = sum(1 for _ in content.splitlines())
            lines_total += line_count
            files_total += 1

            language = LANGUAGE_EXTENSIONS.get(suffix, "Other")
            languages[language] = languages.get(language, 0) + line_count

            if "test" in path.name.lower() or "spec" in path.name.lower():
                tests_detected = True

            lowered = content.lower()
            if suffix == ".json" and path.name == "package.json":
                try:
                    package_data = json.loads(content)
                except json.JSONDecodeError:
                    package_data = {}
                for deps_key in ("dependencies", "devDependencies", "peerDependencies"):
                    deps = package_data.get(deps_key, {}) if isinstance(package_data, dict) else {}
                    if isinstance(deps, dict):
                        for name in deps.keys():
                            dependencies.add(name)
                            frameworks.add(name)
            elif suffix == ".txt" and path.name.lower() == "requirements.txt":
                for line in content.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    name = line.split("==")[0].split(">=")[0].split("<=")[0].strip()
                    if name:
                        dependencies.add(name)
                        frameworks.add(name)
            elif suffix == ".toml" and path.name.lower() == "pyproject.toml":
                for line in content.splitlines():
                    stripped = line.strip()
                    if stripped and stripped[0].isalpha() and ("==" in stripped or "=" in stripped):
                        token = stripped.split("=")[0].strip().strip('"')
                        if token:
                            dependencies.add(token)

            llm_keywords = [
                "openai",
                "gpt",
                "chatgpt",
                "langchain",
                "anthropic",
                "claude",
                "llm",
                "prompt",
                "crew ai",
                "autogen",
                "vlm",
            ]
            for keyword in llm_keywords:
                if keyword in lowered:
                    llm_signals.add(keyword)
            framework_candidates = {
                "react": "React",
                "next.js": "Next.js",
                "angular": "Angular",
                "vue": "Vue",
                "django": "Django",
                "flask": "Flask",
                "fastapi": "FastAPI",
                "spring": "Spring",
                "express": "Express",
                "dotnet": ".NET",
                ".net": ".NET",
                "node": "Node.js",
                "pytorch": "PyTorch",
                "tensorflow": "TensorFlow",
                "hugging face": "Hugging Face",
            }
            for token, display in framework_candidates.items():
                if token in lowered:
                    frameworks.add(display)

        avg_lines = lines_total / files_total if files_total else 0.0
        return {
            "lines_total": lines_total,
            "files_total": files_total,
            "languages": languages,
            "tests_detected": tests_detected,
            "avg_lines_per_file": avg_lines,
            "frameworks": sorted(frameworks),
            "dependencies": sorted(dependencies),
            "llm_signals": sorted(llm_signals),
            "notes": None,
        }

    @staticmethod
    def _guess_extension(url: str) -> str:
        parsed = os.path.basename(url)
        for ext in (".zip", ".tar.gz", ".tgz", ".tar", ".bz2", ".xz"):
            if parsed.endswith(ext):
                if ext == ".tar.gz":
                    return ".tar.gz"
                return ext if ext.startswith(".") else f".{ext}"
        suffix = Path(parsed).suffix
        return suffix if suffix else ".bin"

    @staticmethod
    def _coerce_float(value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _complexity_label(record: SubmissionArtifact) -> str:
        lines = record.lines_total
        files = record.files_total
        if lines == 0 or files == 0:
            return "Unknown"
        if lines <= 500 and files <= 15:
            return "Compact"
        if lines <= 2000 and files <= 60:
            return "Moderate"
        return "Large"

    @staticmethod
    def _ai_feasibility(record: SubmissionArtifact, challenge: Optional[Dict[str, Any]]) -> str:
        if record.lines_total == 0:
            return "Insufficient Data"

        lines = record.lines_total
        languages = record.languages or {}
        key_langs = set(languages)
        ai_ready_languages = {"Python", "JavaScript", "TypeScript", "Java", "C#", "Go"}
        complexity = record.complexity_label
        frameworks = set(record.frameworks or [])
        llm_signals = set(record.llm_signals or [])
        tests = record.tests_detected

        if complexity == "Compact" and key_langs.issubset(ai_ready_languages):
            return "High"
        if lines <= 1200 and len(key_langs & ai_ready_languages) >= 1:
            if tests or frameworks or llm_signals:
                return "High"
            return "Medium"
        if lines <= 2500 and len(key_langs & ai_ready_languages) >= 1:
            if tests and frameworks:
                return "Medium"
            return "Low"
        return "Low"

    def _build_aggregates(
        self,
        submissions: Sequence[SubmissionArtifact],
        languages: Dict[str, int],
        failures: Sequence[str],
    ) -> Dict[str, Any]:
        analysed = [sub for sub in submissions if sub.lines_total > 0]
        if analysed:
            total_lines = sum(sub.lines_total for sub in analysed)
            total_files = sum(sub.files_total for sub in analysed)
            avg_lines = total_lines / len(analysed)
            avg_files = total_files / len(analysed)
        else:
            total_lines = total_files = 0
            avg_lines = avg_files = 0.0

        feasibility_counts: Dict[str, int] = {}
        complexity_counts: Dict[str, int] = {}
        framework_counts: Dict[str, int] = {}
        llm_counts: Dict[str, int] = {}
        tests_count = 0
        for sub in analysed:
            feasibility_counts[sub.ai_feasibility] = feasibility_counts.get(sub.ai_feasibility, 0) + 1
            complexity_counts[sub.complexity_label] = complexity_counts.get(sub.complexity_label, 0) + 1
            if sub.frameworks:
                for fw in sub.frameworks:
                    framework_counts[fw] = framework_counts.get(fw, 0) + 1
            if sub.llm_signals:
                for signal in sub.llm_signals:
                    llm_counts[signal] = llm_counts.get(signal, 0) + 1
            if sub.tests_detected:
                tests_count += 1

        return {
            "analysed_submissions": len(analysed),
            "total_lines": total_lines,
            "total_files": total_files,
            "avg_lines": avg_lines,
            "avg_files": avg_files,
            "languages": languages,
            "feasibility_counts": feasibility_counts,
            "complexity_counts": complexity_counts,
            "framework_counts": framework_counts,
            "llm_counts": llm_counts,
            "submissions_with_tests": tests_count,
            "failures": list(failures),
        }

    def _log_debug(self, message: str) -> None:
        try:
            self.debug_path.parent.mkdir(parents=True, exist_ok=True)
            with self.debug_path.open("a", encoding="utf-8") as fh:
                fh.write(f"{message}\n")
        except Exception:
            pass


def artefact_results_to_rows(submissions: Iterable[SubmissionArtifact]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for sub in submissions:
        languages = sub.languages or {}
        row = {
            "challengeId": sub.challenge_id,
            "submissionId": sub.submission_id,
            "handle": sub.handle,
            "status": sub.status,
            "score": sub.score,
            "lines_total": sub.lines_total,
            "files_total": sub.files_total,
            "avg_lines_per_file": sub.avg_lines_per_file,
            "tests_detected": int(sub.tests_detected),
            "languages": json.dumps(languages),
            "complexity_label": sub.complexity_label,
            "ai_feasibility": sub.ai_feasibility,
            "frameworks": json.dumps(sub.frameworks or []),
            "dependencies": json.dumps(sub.dependencies or []),
            "llm_signals": json.dumps(sub.llm_signals or []),
            "notes": sub.notes,
        }
        rows.append(row)
    return rows
