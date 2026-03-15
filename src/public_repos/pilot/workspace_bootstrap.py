"""Workspace normalization + bootstrap planning logic for pilot repos."""

from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

LANGUAGE_BUCKETS = {
    "python": "python",
    "py": "python",
    "jupyter": "python",
    "ipython": "python",
    "javascript": "node",
    "typescript": "node",
    "tsx": "node",
    "jsx": "node",
    "node": "node",
    "nodejs": "node",
    "java": "java",
}

NODE_DEFAULT_TEST_STUB = "echo \"Error: no test specified\" && exit 1"


@dataclass(slots=True)
class BootstrapAdvice:
    """Safe bootstrap plan for a workspace."""

    required: bool = False
    reason: str | None = None
    category: str | None = None
    commands: list[str] = field(default_factory=list)


@dataclass(slots=True)
class WorkspaceNormalizationPlan:
    """Command + tooling plan inferred from snapshot + repo state."""

    language: str
    package_manager: str | None
    package_manager_spec: str | None
    build_system: str | None
    test_frameworks: list[str]
    install_command: str | None
    build_command: str | None
    test_command: str | None
    bootstrap: BootstrapAdvice
    runnable_confidence: float
    notes: str
    unsupported_reason: str | None
    command_inference_source: str
    required_tools: list[str]


def _normalize_language(value: str | None) -> str:
    return (value or "").strip().lower()


def _language_bucket(snapshot: Mapping[str, object], build_files: set[str]) -> str:
    candidates: set[str] = set()
    languages = snapshot.get("languages") or []
    if isinstance(languages, str):
        languages = [languages]
    for lang in languages:
        normalized = LANGUAGE_BUCKETS.get(_normalize_language(str(lang)), None)
        if normalized:
            candidates.add(normalized)
    hint = LANGUAGE_BUCKETS.get(_normalize_language(str(snapshot.get("language_hint"))), None)
    if hint:
        candidates.add(hint)
    if "package.json" in build_files or "pnpm-lock.yaml" in build_files or "yarn.lock" in build_files:
        candidates.add("node")
    if "pyproject.toml" in build_files or "requirements.txt" in build_files:
        candidates.add("python")
    if "pom.xml" in build_files or "build.gradle" in build_files or "gradlew" in build_files:
        candidates.add("java")
    if len(candidates) > 1:
        return "mixed"
    if candidates:
        return next(iter(candidates))
    return "other"


def _load_package_manifest(local_path: Path) -> Mapping[str, object]:
    package_json = local_path / "package.json"
    if not package_json.exists():
        return {}
    try:
        payload = json.loads(package_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _load_package_scripts(manifest: Mapping[str, object]) -> Mapping[str, str]:
    scripts = manifest.get("scripts") if isinstance(manifest, dict) else None
    if not isinstance(scripts, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, value in scripts.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        normalized[key.lower().strip()] = value.strip()
    return normalized


def _parse_package_manager_spec(manifest: Mapping[str, object]) -> tuple[str | None, str | None]:
    raw_value = str(manifest.get("packageManager") or "").strip()
    if not raw_value:
        return None, None
    if "@" not in raw_value:
        return raw_value, None
    name, version = raw_value.split("@", 1)
    name = name.strip()
    version = version.strip()
    return (name or None), (version or None)


def _uses_workspace_protocol(manifest: Mapping[str, object]) -> bool:
    workspaces = manifest.get("workspaces")
    if isinstance(workspaces, list) and workspaces:
        return True
    if isinstance(workspaces, dict) and workspaces.get("packages"):
        return True
    dependency_sections = (
        "dependencies",
        "devDependencies",
        "peerDependencies",
        "optionalDependencies",
        "resolutions",
    )
    for section in dependency_sections:
        deps = manifest.get(section)
        if not isinstance(deps, dict):
            continue
        for value in deps.values():
            if isinstance(value, str) and value.strip().startswith("workspace:"):
                return True
    return False


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


def _detect_package_manager(build_files: set[str]) -> tuple[str | None, str | None]:
    if "poetry.lock" in build_files:
        return "poetry", "poetry.lock"
    if "pnpm-lock.yaml" in build_files or "pnpm-workspace.yaml" in build_files:
        return "pnpm", "pnpm-lock.yaml"
    if "yarn.lock" in build_files:
        return "yarn", "yarn.lock"
    if "package-lock.json" in build_files or "npm-shrinkwrap.json" in build_files:
        return "npm", "package-lock.json"
    if "package.json" in build_files:
        return "npm", "package.json"
    if "requirements.txt" in build_files:
        return "pip", "requirements.txt"
    if "pyproject.toml" in build_files:
        return "pip", "pyproject.toml"
    if "setup.py" in build_files or "setup.cfg" in build_files:
        return "pip", "setup.py"
    if "pom.xml" in build_files:
        return "maven", "pom.xml"
    if "build.gradle" in build_files or "gradlew" in build_files:
        return "gradle", "build.gradle"
    return None, None


def _detect_build_system(
    snapshot: Mapping[str, object],
    package_manager: str | None,
    build_files: set[str],
) -> str | None:
    build_systems = snapshot.get("build_systems") or []
    if build_systems:
        first = build_systems[0]
        if isinstance(first, str) and first:
            return first
    if package_manager in {"poetry", "pipenv"}:
        return package_manager
    if "pyproject.toml" in build_files:
        return "pyproject"
    if "setup.py" in build_files:
        return "setuptools"
    if package_manager in {"npm", "yarn", "pnpm"}:
        return "nodejs"
    if "pom.xml" in build_files:
        return "maven"
    if "build.gradle" in build_files or "gradlew" in build_files:
        return "gradle"
    return None


def _infer_install_command(language: str, package_manager: str | None, build_files: set[str]) -> tuple[str | None, str | None]:
    if language == "python":
        if package_manager == "poetry":
            return "poetry install", "poetry.lock"
        if "requirements.txt" in build_files:
            return "pip install -r requirements.txt", "requirements.txt"
        if "pyproject.toml" in build_files or "setup.py" in build_files:
            return "pip install -e .", "pyproject.toml"
    if language == "node":
        if package_manager == "yarn":
            return "yarn install", "yarn.lock"
        if package_manager == "pnpm":
            return "pnpm install", "pnpm-lock.yaml"
        if package_manager == "npm":
            source = "package-lock.json" if "package-lock.json" in build_files else "package.json"
            return "npm install", source
        if "package.json" in build_files:
            return "npm install", "package.json"
    if language == "java":
        if "pom.xml" in build_files:
            return "mvn -B dependency:go-offline", "pom.xml"
        if "gradlew" in build_files:
            return "./gradlew --no-daemon assemble", "gradlew"
    return None, None


def _node_script_command(script_name: str, package_manager: str | None) -> str:
    if package_manager == "yarn":
        return f"yarn {script_name}"
    if package_manager == "pnpm":
        return f"pnpm run {script_name}"
    return f"npm run {script_name}"


def _infer_build_command(
    language: str,
    package_manager: str | None,
    build_files: set[str],
    scripts: Mapping[str, str],
) -> tuple[str | None, str | None]:
    if language == "python":
        if "pyproject.toml" in build_files or "setup.py" in build_files:
            return "python -m build", "pyproject.toml"
        return None, None
    if language == "node":
        script = scripts.get("build")
        if script:
            return _node_script_command("build", package_manager), "package.json:scripts.build"
        return None, None
    if language == "java":
        if "pom.xml" in build_files:
            return "mvn -B package", "pom.xml"
        if "gradlew" in build_files:
            return "./gradlew --no-daemon build", "gradlew"
    return None, None


def _infer_test_command(
    language: str,
    package_manager: str | None,
    test_frameworks: Sequence[str],
    build_files: set[str],
    scripts: Mapping[str, str],
) -> tuple[str | None, str | None]:
    frameworks = [fw.lower() for fw in test_frameworks if isinstance(fw, str)]
    if language == "python":
        if "pytest" in frameworks:
            return "pytest", "test_framework:pytest"
        if "tox" in frameworks:
            return "tox", "test_framework:tox"
        if "unittest" in frameworks or not frameworks:
            return "pytest", "language_default:python"
    if language == "node":
        script = scripts.get("test")
        if script and NODE_DEFAULT_TEST_STUB not in script:
            cmd = "test"
            if package_manager == "yarn":
                return "yarn test", "package.json:scripts.test"
            if package_manager == "pnpm":
                return "pnpm test", "package.json:scripts.test"
            return "npm test", "package.json:scripts.test"
        if any(fw in {"jest", "mocha", "vitest"} for fw in frameworks):
            if package_manager == "yarn":
                return "yarn test", "test_framework:js"
            if package_manager == "pnpm":
                return "pnpm test", "test_framework:js"
            return "npm test", "test_framework:js"
    if language == "java":
        if "pom.xml" in build_files:
            return "mvn -B test", "pom.xml"
        if "gradlew" in build_files:
            return "./gradlew --no-daemon test", "gradlew"
    return None, None


def _python_bootstrap_advice(build_command: str | None) -> BootstrapAdvice:
    commands: list[str] = []
    reason = None
    category = None
    missing_modules: list[str] = []
    if build_command and "python -m build" in build_command and not _module_available("build"):
        missing_modules.append("build")
    for module in ("setuptools", "wheel"):
        if not _module_available(module):
            missing_modules.append(module)
    needs_pip = not _module_available("pip")
    if needs_pip:
        commands.append("python -m ensurepip --upgrade")
        reason = "python packaging bootstrap incomplete"
        category = "missing_python_packaging_tool"
    if missing_modules:
        install_list = sorted(set(missing_modules))
        commands.append(f"python -m pip install --upgrade {' '.join(install_list)}")
        if "build" in install_list:
            reason = "python build module missing"
            category = "missing_python_build_module"
        elif not reason:
            reason = "python packaging tools missing"
            category = "missing_python_packaging_tool"
    return BootstrapAdvice(
        required=bool(commands),
        reason=reason,
        category=category,
        commands=commands,
    )


def _node_bootstrap_advice(package_manager: str | None, package_manager_spec: str | None) -> BootstrapAdvice:
    if package_manager not in {"yarn", "pnpm"}:
        return BootstrapAdvice()
    version = package_manager_spec or "latest"
    commands = ["corepack enable", f"corepack prepare {package_manager}@{version} --activate"]
    return BootstrapAdvice(
        required=True,
        reason="node_package_manager_activation",
        category="missing_corepack",
        commands=commands,
    )


def _collect_required_tools(language: str, package_manager: str | None, build_command: str | None) -> list[str]:
    required: list[str] = []
    if package_manager in {"poetry", "npm", "yarn", "pnpm"}:
        required.append(package_manager)
    if language == "node":
        required.append("node")
    if language == "java":
        if build_command and "mvn" in build_command:
            required.append("mvn")
        if build_command and "gradlew" in build_command:
            required.append("java")
    return required


def _confidence_score(
    install_command: str | None,
    build_command: str | None,
    test_command: str | None,
    package_manager: str | None,
    bootstrap_required: bool,
    unsupported_reason: str | None,
) -> float:
    score = 0.25
    if install_command:
        score += 0.2
    if build_command:
        score += 0.15
    if test_command:
        score += 0.3
    if package_manager:
        score += 0.05
    if bootstrap_required:
        score -= 0.05
    if unsupported_reason:
        score -= 0.1
    return max(0.0, min(score, 1.0))


def _build_notes(
    language: str,
    install_command: str | None,
    build_command: str | None,
    test_command: str | None,
    bootstrap: BootstrapAdvice,
) -> str:
    notes: list[str] = [f"language={language}"]
    if install_command:
        notes.append(f"install→{install_command.split()[0]}")
    if build_command:
        notes.append(f"build→{build_command}")
    if test_command:
        notes.append(f"tests→{test_command}")
    if bootstrap.required and bootstrap.reason:
        notes.append(f"needs_bootstrap:{bootstrap.reason}")
    return "; ".join(notes)


def plan_workspace_normalization(snapshot: Mapping[str, object]) -> WorkspaceNormalizationPlan:
    """Infer commands + bootstrap steps for a repo snapshot entry."""

    local_path = Path(str(snapshot.get("local_path") or ""))
    build_files = {Path(path).name.lower() for path in snapshot.get("detected_build_files", []) if isinstance(path, str)}
    language = _language_bucket(snapshot, build_files)
    package_manifest = _load_package_manifest(local_path) if local_path.exists() else {}
    package_manager_from_manifest, package_manager_spec = _parse_package_manager_spec(package_manifest)
    package_manager, pm_source = _detect_package_manager(build_files)
    if package_manager_from_manifest:
        package_manager = package_manager_from_manifest
        pm_source = "package.json:packageManager"
    workspace_protocol = _uses_workspace_protocol(package_manifest)
    if workspace_protocol and package_manager in {None, "", "npm"}:
        package_manager = "yarn"
        pm_source = pm_source or "package.json:workspaces"
    build_system = _detect_build_system(snapshot, package_manager, build_files)
    scripts = _load_package_scripts(package_manifest)
    test_frameworks = [str(fw).lower() for fw in snapshot.get("test_frameworks", []) if isinstance(fw, str)]

    install_command, install_source = _infer_install_command(language, package_manager, build_files)
    build_command, build_source = _infer_build_command(language, package_manager, build_files, scripts)
    test_command, test_source = _infer_test_command(language, package_manager, test_frameworks, build_files, scripts)

    if language == "python":
        bootstrap = _python_bootstrap_advice(build_command)
    elif language == "node":
        bootstrap = _node_bootstrap_advice(package_manager, package_manager_spec)
    else:
        bootstrap = BootstrapAdvice()
    unsupported_reason = None
    if language == "mixed":
        unsupported_reason = "mixed_language_workspace"
    elif language == "other":
        unsupported_reason = "unsupported_language_bucket"

    if not test_command and snapshot.get("has_tests"):
        unsupported_reason = None  # tests exist but inference failed -> handled later

    command_inference_source_parts: list[str] = []
    for source in (install_source, build_source, test_source, pm_source):
        if source:
            command_inference_source_parts.append(str(source))
    command_inference_source = " | ".join(dict.fromkeys(command_inference_source_parts))
    required_tools = _collect_required_tools(language, package_manager, build_command)

    notes = _build_notes(language, install_command, build_command, test_command, bootstrap)
    runnable_confidence = _confidence_score(
        install_command,
        build_command,
        test_command,
        package_manager,
        bootstrap.required,
        unsupported_reason,
    )
    return WorkspaceNormalizationPlan(
        language=language,
        package_manager=package_manager,
        package_manager_spec=package_manager_spec,
        build_system=build_system,
        test_frameworks=test_frameworks,
        install_command=install_command,
        build_command=build_command,
        test_command=test_command,
        bootstrap=bootstrap,
        runnable_confidence=round(runnable_confidence, 3),
        notes=notes,
        unsupported_reason=unsupported_reason,
        command_inference_source=command_inference_source,
        required_tools=required_tools,
    )
