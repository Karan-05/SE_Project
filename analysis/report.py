"""Generate challenge and member activity summaries for Topcoder datasets.

This script can operate on locally downloaded challenge JSON files (produced by
the existing collectors in this repository) and optional member mapping CSV
exports. It can also fetch fresh challenge data from the Topcoder API when the
`--from-api` arguments are provided.

Outputs are written as CSV/JSON/Markdown files into the chosen report
directory, ready for further analysis or inclusion in research artifacts.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import html
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from statistics import mean, median
import sys
import urllib.error
import urllib.parse
import urllib.request

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    import requests  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - fallback for minimal envs
    requests = None  # type: ignore[assignment]

from config import load_api_config
from process import format_challenge
from analysis.artifacts import ArtifactAnalyzer, SubmissionArtifact, artefact_results_to_rows


DEFAULT_PLATFORMS = {
    "kaggle": "Kaggle",
    "zindi": "Zindi",
    "herox": "HeroX",
    "devpost": "Devpost",
    "crowdforge": "CrowdForge",
    "freelancer": "Freelancer",
    "upwork": "Upwork",
    "hackerrank": "HackerRank",
    "codeforces": "Codeforces",
    "coderbyte": "Coderbyte",
    "kattis": "Kattis",
    "leetcode": "LeetCode",
    "topcoder": "Topcoder",
}

AI_KEYWORDS = (
    " ai ",
    " artificial intelligence",
    "machine learning",
    "deep learning",
    " llm",
    "langchain",
    "gpt",
    "copilot",
    "agent",
    "autonomous",
    "rag",
    "prompt",
    "hugging face",
    "openai",
    "anthropic",
    "autogen",
    "crew ai",
    "ai agent",
)

AI_FEASIBILITY_POSITIVE_HINTS = (
    "prototype",
    "automation",
    "api",
    "dataset",
    "model",
    "predict",
    "analysis",
    "classification",
    "code",
    "script",
    "tool",
    "proof of concept",
    "feature development",
    "bug fix",
    "integration",
    "testing",
    "benchmark",
    "deployment",
)

AI_FEASIBILITY_NEGATIVE_HINTS = (
    "design brief",
    "mockup",
    "storyboard",
    "presentation",
    "pitch",
    "writeup",
    "report",
    "documentation",
    "instructions",
    "illustration",
    "graphic",
    "video",
    "photograph",
    "business plan",
    "compliance",
    "legal",
    "policy",
    "community",
    "marketing",
    "usability study",
    "ux research",
)

PROBLEM_ANALYSIS_RULES: Tuple[Dict[str, Any], ...] = (
    {
        "category": "Data science & modeling",
        "keywords": ("dataset", "model", "training", "feature", "predict", "classification", "regression"),
        "root_issue": "Building or refining predictive models with reliable evaluation and feature handling.",
        "ai_speedup": "AutoML platforms automate baseline models, while code copilots draft feature engineering and evaluation scripts.",
        "ai_tools": "AutoML suites (H2O.ai, AutoGluon), Jupyter automation, code copilots.",
    },
    {
        "category": "Integration & automation",
        "keywords": ("integration", "api", "endpoint", "microservice", "workflow", "pipeline", "webhook"),
        "root_issue": "Connecting disparate services reliably and handling edge cases across APIs.",
        "ai_speedup": "LLM copilots synthesize interface glue code and unit tests, reducing manual wiring effort.",
        "ai_tools": "GitHub Copilot, OpenAI Code Interpreter patterns, Postman AI.",
    },
    {
        "category": "UI/UX & creative design",
        "keywords": ("design", "mockup", "wireframe", "storyboard", "visual", "brand", "creative"),
        "root_issue": "Delivering production-ready creative assets that align with subjective brand expectations.",
        "ai_speedup": "Generative design ideation tools help draft variations quickly, but sign-off still requires designers.",
        "ai_tools": "Figma AI, Midjourney, Adobe Firefly.",
    },
    {
        "category": "Documentation & research",
        "keywords": ("writeup", "documentation", "report", "whitepaper", "analysis", "research"),
        "root_issue": "Curating accurate narrative insights and references tailored to stakeholder needs.",
        "ai_speedup": "Summarization and drafting assistants accelerate outlines, but validation remains manual.",
        "ai_tools": "Notion AI, GPT drafting workflows, semantic search.",
    },
    {
        "category": "Testing & quality",
        "keywords": ("test", "qa", "quality", "bug", "regression", "automation"),
        "root_issue": "Creating comprehensive automated coverage and diagnosing regressions quickly.",
        "ai_speedup": "AI agents scaffold test cases, fuzz inputs, and triage failures from logs.",
        "ai_tools": "Test automation copilots, Mabl, CodiumAI.",
    },
    {
        "category": "Algorithmic optimization",
        "keywords": ("optimize", "algorithm", "heuristic", "performance", "solver", "combinatorial"),
        "root_issue": "Designing performant algorithms under constraints and verifying correctness.",
        "ai_speedup": "LLMs propose baseline heuristics and code skeletons; human experts tune for edge cases.",
        "ai_tools": "Competitive programming copilots, optimization libraries.",
    },
    {
        "category": "DevOps & deployment",
        "keywords": ("deploy", "infrastructure", "terraform", "kubernetes", "container", "ci/cd"),
        "root_issue": "Coordinating reliable infrastructure-as-code and rollout strategies.",
        "ai_speedup": "AI assistants generate IaC templates and pipeline YAML, reducing boilerplate.",
        "ai_tools": "Terraform assistants, GitHub Copilot for DevOps, AWS CodeWhisperer.",
    },
)


def _http_get_json(
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: float = 15.0,
):
    """Lightweight helper that returns (status_code, payload, response_headers)."""

    if requests is not None:
        try:
            response = requests.get(url, headers=headers, params=params, timeout=timeout)
        except requests.exceptions.RequestException as exc:  # type: ignore[attr-defined]
            print(f"Warning: GET {url} failed: {exc}", file=sys.stderr)
            return 599, None, {}
        try:
            payload = response.json()
        except ValueError:
            payload = None
        return response.status_code, payload, dict(response.headers)

    if params:
        query = urllib.parse.urlencode(params, doseq=True)
        separator = "&" if urllib.parse.urlparse(url).query else "?"
        url = f"{url}{separator}{query}"

    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = None
            return resp.status, payload, dict(resp.getheaders())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8") if exc.fp else ""
        try:
            payload = json.loads(body) if body else None
        except json.JSONDecodeError:
            payload = None
        headers_map = dict(exc.headers or {}) if hasattr(exc, "headers") and exc.headers else {}
        return exc.code, payload, headers_map
    except urllib.error.URLError:
        return 599, None, {}


@dataclass
class ChallengeRecord:
    challengeId: str
    legacyId: int
    name: str
    status: str | None
    trackType: str | None
    type: str | None
    registrationStartDate: Optional[str]
    registrationEndDate: Optional[str]
    submissionStartDate: Optional[str]
    submissionEndDate: Optional[str]
    startDate: Optional[str]
    endDate: Optional[str]
    numOfRegistrants: int
    numOfSubmissions: int
    totalPrizeCost: int
    winners: str
    description: str | None
    source_file: str
    registrant_count: int = 0
    submitter_count: int = 0
    winner_count: int = 0
    platform_mentions: Tuple[str, ...] = ()
    open_for_registration: bool = False
    open_for_submission: bool = False
    ai_related: bool = False
    ai_keywords: Tuple[str, ...] = ()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate Topcoder challenge data into research-ready reports."
    )
    parser.add_argument(
        "--challenge-dir",
        type=Path,
        default=Path("challenge_data"),
        help="Directory containing challengeData_* folders with JSON pages (default: challenge_data).",
    )
    parser.add_argument(
        "--member-mapping",
        type=Path,
        default=Path("snapshots/Challenge_Member_Mapping.csv"),
        help="Optional CSV mapping of challenge/member/submission data.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("analysis/output"),
        help="Directory to write report artifacts (default: analysis/output).",
    )
    parser.add_argument(
        "--as-of",
        type=str,
        default=None,
        help="Override the evaluation timestamp (UTC ISO format). Defaults to now.",
    )
    parser.add_argument(
        "--platform-keywords",
        type=str,
        nargs="*",
        default=None,
        help="Custom platform keywords to scan for in challenge descriptions (case-insensitive).",
    )
    parser.add_argument(
        "--from-api",
        action="store_true",
        help="Fetch fresh challenge data from the Topcoder API instead of local JSON files.",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Start date (YYYY-MM-DD) when fetching from the API.",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date (YYYY-MM-DD) when fetching from the API.",
    )
    parser.add_argument(
        "--status",
        type=str,
        nargs="*",
        default=["Active", "New"],
        help="Challenge status filter(s) when fetching from the API (default: Active New).",
    )
    parser.add_argument(
        "--track",
        type=str,
        default="Dev",
        choices=["Dev", "DS", "Des", "QA"],
        help="Challenge track when fetching from the API (default: Dev).",
    )
    parser.add_argument(
        "--download-artifacts",
        action="store_true",
        help="Download submission artifacts (requires bearer token) and run code complexity analysis.",
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=Path("analysis/artifacts_store"),
        help="Directory to cache downloaded artifacts and extracted code (default: analysis/artifacts_store).",
    )
    parser.add_argument(
        "--artifact-limit",
        type=int,
        default=3,
        help="Maximum submissions per challenge to download/analyse (default: 3).",
    )
    return parser.parse_args()


def ensure_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None

    patterns = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d")
    for pattern in patterns:
        try:
            return datetime.strptime(value, pattern).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def build_platform_lookup(keywords: Optional[Sequence[str]]) -> Dict[str, str]:
    if not keywords:
        return DEFAULT_PLATFORMS
    custom = {kw.lower(): kw for kw in keywords}
    return {**DEFAULT_PLATFORMS, **custom}


def detect_platform_mentions(description: Optional[str], lookup: Dict[str, str]) -> Tuple[str, ...]:
    if not description:
        return ()
    lowered = description.lower()
    found: Set[str] = set()
    for token, display in lookup.items():
        if token in lowered:
            found.add(display)
    return tuple(sorted(found))


def detect_ai_keywords(name: Optional[str], description: Optional[str]) -> Tuple[str, ...]:
    text_parts = []
    if name:
        text_parts.append(name.lower())
    if description:
        text_parts.append(description.lower())
    if not text_parts:
        return ()
    combined = " " + " ".join(text_parts) + " "
    found: Set[str] = set()
    for token in AI_KEYWORDS:
        if token.strip() and token in combined:
            found.add(token.strip())
    return tuple(sorted(found))


def load_local_challenges(challenge_dir: Path) -> List[Dict[str, Any]]:
    if not challenge_dir.exists():
        raise FileNotFoundError(f"Challenge directory {challenge_dir} does not exist.")

    challenge_by_id: Dict[str, Dict[str, Any]] = {}
    for json_path in sorted(challenge_dir.glob("challengeData_*/*.json")):
        with json_path.open("r", encoding="utf-8") as fh:
            try:
                payload = json.load(fh)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Failed to parse {json_path}: {exc}") from exc

        for raw in payload:
            challenge_id = raw.get("challengeId") or raw.get("id")
            if not challenge_id:
                continue
            record = dict(raw)
            record["source_file"] = str(json_path)
            challenge_by_id[challenge_id] = record
    return list(challenge_by_id.values())


def fetch_api_challenges(
    start_date: Optional[str],
    end_date: Optional[str],
    statuses: Sequence[str],
    track: str,
) -> List[Dict[str, Any]]:
    if requests is None:
        raise RuntimeError("requests package is required for --from-api mode.")
    if not start_date or not end_date:
        raise ValueError("Both --start-date and --end-date are required when using --from-api.")

    start_iso = _coerce_date_iso(start_date)
    end_iso = _coerce_date_iso(end_date)

    challenges: Dict[str, Dict[str, Any]] = {}
    api_config = load_api_config()
    base_url = api_config.base_url.rstrip("/")
    challenges_endpoint = f"{base_url}/challenges"
    for status in statuses:
        page = 1
        while True:
            params = {
                "page": page,
                "perPage": 50,
                "tracks[]": [track],
                "sortBy": "startDate",
                "sortOrder": "asc",
                "startDateStart": start_iso,
                "startDateEnd": end_iso,
            }
            if status.lower() != "all":
                params["status"] = status

            response = requests.get(challenges_endpoint, params=params, timeout=15.0)
            response.raise_for_status()
            payload = response.json()

            for raw in payload:
                formatted = format_challenge(raw)
                formatted["description"] = raw.get("description")
                formatted["source_file"] = f"api:{status}:{page}"
                challenges[formatted["challengeId"]] = formatted

            total_pages = int(response.headers.get("X-Total-Pages", "1"))
            if page >= total_pages:
                break
            page += 1
    return list(challenges.values())


def _coerce_date_iso(value: str) -> str:
    try:
        dt = datetime.strptime(value, "%Y-%m-%d")
        return dt.date().isoformat()
    except ValueError as exc:
        raise ValueError(f"Date {value} must be in YYYY-MM-DD format") from exc


def load_member_mapping(csv_path: Path) -> Dict[str, List[Dict[str, Any]]]:
    if not csv_path.exists():
        return {}

    mapping: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        for row in reader:
            if not row:
                continue
            if row[0] == "id" or "challengeId" in row[0]:
                # Skip header if present.
                continue
            if len(row) < 6:
                continue

            challenge_id = row[1]
            try:
                submission_flag = int(row[4])
            except ValueError:
                submission_flag = 0
            try:
                winning_position = int(row[5])
            except ValueError:
                winning_position = 0

            mapping[challenge_id].append(
                {
                    "memberHandle": row[3],
                    "submission": submission_flag,
                    "winningPosition": winning_position,
                }
            )
    return mapping


def build_challenge_records(
    raw_challenges: Iterable[Dict[str, Any]],
    member_map: Dict[str, List[Dict[str, Any]]],
    platforms_lookup: Dict[str, str],
    now: datetime,
) -> List[ChallengeRecord]:
    records: List[ChallengeRecord] = []
    for challenge in raw_challenges:
        challenge_id = challenge.get("challengeId")
        if not challenge_id:
            continue

        registrants = member_map.get(challenge_id, [])
        registrant_count = len(registrants)
        submitter_count = sum(1 for entry in registrants if entry.get("submission"))
        winner_count = sum(1 for entry in registrants if (entry.get("winningPosition") or 0) > 0)

        reg_start = ensure_datetime(challenge.get("registrationStartDate"))
        reg_end = ensure_datetime(challenge.get("registrationEndDate"))
        sub_start = ensure_datetime(challenge.get("submissionStartDate"))
        sub_end = ensure_datetime(challenge.get("submissionEndDate"))

        open_for_reg = bool(reg_start and reg_end and reg_start <= now <= reg_end)
        open_for_sub = bool(sub_start and sub_end and sub_start <= now <= sub_end)

        record = ChallengeRecord(
            challengeId=challenge_id,
            legacyId=int(challenge.get("legacyId") or 0),
            name=challenge.get("name") or "",
            status=challenge.get("status"),
            trackType=challenge.get("trackType"),
            type=challenge.get("type"),
            registrationStartDate=challenge.get("registrationStartDate"),
            registrationEndDate=challenge.get("registrationEndDate"),
            submissionStartDate=challenge.get("submissionStartDate"),
            submissionEndDate=challenge.get("submissionEndDate"),
            startDate=challenge.get("startDate"),
            endDate=challenge.get("endDate"),
            numOfRegistrants=int(challenge.get("numOfRegistrants") or 0),
            numOfSubmissions=int(challenge.get("numOfSubmissions") or 0),
            totalPrizeCost=int(challenge.get("totalPrizeCost") or 0),
            winners=challenge.get("winners") or "",
            description=challenge.get("description"),
            source_file=challenge.get("source_file", ""),
            registrant_count=registrant_count,
            submitter_count=submitter_count,
            winner_count=winner_count,
            platform_mentions=detect_platform_mentions(challenge.get("description"), platforms_lookup),
            open_for_registration=open_for_reg,
            open_for_submission=open_for_sub,
            ai_keywords=detect_ai_keywords(challenge.get("name"), challenge.get("description")),
        )
        record.ai_related = bool(record.ai_keywords)
        records.append(record)
    return records


def _fallback_start_date(record: ChallengeRecord) -> Optional[datetime]:
    for candidate in (
        record.startDate,
        record.registrationStartDate,
        record.submissionStartDate,
    ):
        dt = ensure_datetime(candidate)
        if dt:
            return dt
    return None


def _hours_between(start: Optional[str], end: Optional[str]) -> Optional[float]:
    start_dt = ensure_datetime(start)
    end_dt = ensure_datetime(end)
    if not start_dt or not end_dt:
        return None
    delta = end_dt - start_dt
    seconds = delta.total_seconds()
    if seconds < 0:
        return None
    return seconds / 3600.0


def _distribution(values: List[float]) -> Dict[str, float]:
    if not values:
        return {}
    return {
        "min": min(values),
        "max": max(values),
        "mean": mean(values),
        "median": median(values),
    }


def _strip_html_tags(text: str) -> str:
    """Remove HTML tags and extra whitespace from challenge descriptions."""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _clean_problem_statement(raw_text: Optional[str]) -> str:
    if not raw_text:
        return ""
    return _strip_html_tags(html.unescape(raw_text))


def _estimate_ai_delivery(record: ChallengeRecord) -> Tuple[str, str, int, str, str, str]:
    """Assign AI autonomy label, independence flag, and estimated hours."""
    # Base heuristic score: start neutral
    score = 0
    supporting_reasons: List[str] = []
    blocker_reasons: List[str] = []
    description = _clean_problem_statement(record.description).lower()

    if record.ai_related:
        score += 2
        supporting_reasons.append("flagged as AI-related")

    track = (record.trackType or "").lower()
    if track in {"data science", "practice", "qa"}:
        score += 2
        supporting_reasons.append(f"track {record.trackType} favours automation")
    elif track in {"design", "ui design", "ux", "studio"}:
        score -= 2
        blocker_reasons.append(f"track {record.trackType} needs human judgement")

    challenge_type = (record.type or "").lower()
    if challenge_type in {"code", "develop", "first2finish"}:
        score += 1
        supporting_reasons.append(f"type {record.type} focuses on implementation")
    elif challenge_type in {"design", "design first2finish"}:
        score -= 1
        blocker_reasons.append(f"type {record.type} emphasises creative output")

    positive_hits = [kw for kw in AI_FEASIBILITY_POSITIVE_HINTS if kw in description]
    if positive_hits:
        score += 1 + len(positive_hits) // 4
        supporting_reasons.append(f"automation keywords ({', '.join(sorted(set(positive_hits[:5])))}...)")

    negative_hits = [kw for kw in AI_FEASIBILITY_NEGATIVE_HINTS if kw in description]
    if negative_hits:
        score -= 1 + len(negative_hits) // 4
        blocker_reasons.append(f"human judgement keywords ({', '.join(sorted(set(negative_hits[:5])))}...)")

    if record.totalPrizeCost >= 10000:
        score -= 2
        blocker_reasons.append("large prize indicates higher complexity")
    elif record.totalPrizeCost >= 5000:
        score -= 1
        blocker_reasons.append("mid prize suggests substantive scope")

    window_hours = _hours_between(record.submissionStartDate, record.submissionEndDate)
    if window_hours and window_hours <= 72:
        score += 1
        supporting_reasons.append("short submission window")
    elif window_hours and window_hours >= 240:
        score -= 1
        blocker_reasons.append("long submission window implies complex deliverables")

    # Map numeric score to autonomy labels.
    if score >= 5:
        autonomy = "AI can execute independently"
        independence = "Yes"
        base_hours = 10
    elif score >= 2:
        autonomy = "AI with human oversight"
        independence = "Partial"
        base_hours = 28
    else:
        autonomy = "Human-led with AI assistance"
        independence = "No"
        base_hours = 56

    if record.totalPrizeCost >= 10000:
        base_hours += 20
    elif record.totalPrizeCost >= 5000:
        base_hours += 12
    elif record.totalPrizeCost >= 1000:
        base_hours += 6

    if window_hours:
        base_hours = min(base_hours, max(6, int(round(window_hours * 0.75))))

    estimated_hours = int(max(4, min(base_hours, 120)))

    # Confidence derived from absolute score magnitude.
    confidence = "High" if abs(score) >= 5 else "Medium" if abs(score) >= 3 else "Low"
    rationale_tokens = supporting_reasons + blocker_reasons
    rationale = "; ".join(rationale_tokens) if rationale_tokens else "limited metadata available"
    blocker_summary = "; ".join(blocker_reasons) if blocker_reasons else "no critical blockers identified"

    return autonomy, independence, estimated_hours, confidence, rationale, blocker_summary


def _analyze_problem_scope(record: ChallengeRecord) -> Tuple[str, str, str]:
    description = _clean_problem_statement(record.description)
    combined_text = f"{record.name}. {description}".lower()
    matched_rules: List[Dict[str, Any]] = []
    for rule in PROBLEM_ANALYSIS_RULES:
        if any(keyword in combined_text for keyword in rule["keywords"]):
            matched_rules.append(rule)
    if not matched_rules and description:
        return (
            "General software implementation with limited structured requirements.",
            "Pair an AI coding assistant with human review to explore prototypes rapidly.",
            "Code copilots, task-specific LLM agents.",
        )
    if not matched_rules:
        return (
            "Insufficient context to infer problem drivers.",
            "Gather fuller requirements; AI can expedite drafting user stories and acceptance tests.",
            "Requirement elicitation copilots, documentation assistants.",
        )
    categories = ", ".join(rule["category"] for rule in matched_rules[:2])
    root_issue = " & ".join(rule["root_issue"] for rule in matched_rules[:2])
    opportunities = " ".join(rule["ai_speedup"] for rule in matched_rules[:2])
    tools = " ".join(rule["ai_tools"] for rule in matched_rules[:2])
    if len(matched_rules) > 2:
        tools += " Additional domains detected; tailor assistants accordingly."
    return (
        f"{categories}: {root_issue}",
        opportunities,
        tools,
    )


def assess_ai_feasibility(record: ChallengeRecord) -> Dict[str, Any]:
    problem_statement = _clean_problem_statement(record.description)
    if not problem_statement:
        problem_statement = record.description or record.name
    autonomy, independence, estimated_hours, confidence, rationale, blockers = _estimate_ai_delivery(record)
    root_cause, ai_opportunity, ai_tools = _analyze_problem_scope(record)
    return {
        "challengeId": record.challengeId,
        "name": record.name,
        "ai_delivery_mode": autonomy,
        "ai_independence": independence,
        "estimated_ai_hours": estimated_hours,
        "confidence": confidence,
        "rationale": rationale,
        "ai_blockers": blockers,
        "problem_root_cause": root_cause,
        "ai_acceleration": ai_opportunity,
        "ai_reference_solutions": ai_tools,
        "problem_statement": problem_statement,
    }


def collect_submission_details(
    records: Sequence[ChallengeRecord],
) -> Dict[str, List[Dict[str, Any]]]:
    """Attempt to retrieve submission metadata for challenges that already have handles.

    Requires a valid `TOPCODER_BEARER_TOKEN`; when unavailable the resulting dict
    will be empty.
    """
    if requests is None:
        return {}
    api_config = load_api_config()
    if not api_config.bearer_token:
        return {}

    headers = {"Authorization": f"Bearer {api_config.bearer_token}"}
    base_url = api_config.base_url.rstrip("/")
    submissions_endpoint = f"{base_url}/submissions"
    submission_details: Dict[str, List[Dict[str, Any]]] = {}
    for record in records:
        challenge_submissions_url = f"{base_url}/challenges/{record.challengeId}/submissions"
        # The submissions endpoint currently lives at /submissions?challengeId=,
        # but the alternate path is supported and keeps requests consistent.
        status, payload, _ = _http_get_json(challenge_submissions_url, headers=headers)
        if status == 404:
            status, payload, _ = _http_get_json(
                submissions_endpoint,
                headers=headers,
                params={"challengeId": record.challengeId},
            )
            if status >= 400 or payload is None:
                continue
        elif status >= 400 or payload is None:
            continue

        # Filter to minimal useful fields so the JSON stays compact.
        compact_entries: List[Dict[str, Any]] = []
        for entry in payload:
            compact_entries.append(
                {
                    "submissionId": entry.get("id"),
                    "memberHandle": entry.get("createdBy"),
                    "status": entry.get("status"),
                    "score": entry.get("reviewScore"),
                    "created": entry.get("created"),
                    "updated": entry.get("updated"),
                    "artifact": entry.get("url") or entry.get("artifact", {}).get("url"),
                }
            )
        submission_details[record.challengeId] = compact_entries
    return submission_details


def write_challenge_summary(records: Sequence[ChallengeRecord], output_path: Path) -> None:
    fieldnames = [
        "challengeId",
        "legacyId",
        "name",
        "status",
        "trackType",
        "type",
        "registrationStartDate",
        "registrationEndDate",
        "submissionStartDate",
        "submissionEndDate",
        "startDate",
        "endDate",
        "open_for_registration",
        "open_for_submission",
        "numOfRegistrants",
        "numOfSubmissions",
        "registrant_count",
        "submitter_count",
        "winner_count",
        "totalPrizeCost",
        "winners",
        "platform_mentions",
        "ai_related",
        "ai_keywords",
        "source_file",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "challengeId": record.challengeId,
                    "legacyId": record.legacyId,
                    "name": record.name,
                    "status": record.status,
                    "trackType": record.trackType,
                    "type": record.type,
                    "registrationStartDate": record.registrationStartDate,
                    "registrationEndDate": record.registrationEndDate,
                    "submissionStartDate": record.submissionStartDate,
                    "submissionEndDate": record.submissionEndDate,
                    "startDate": record.startDate,
                    "endDate": record.endDate,
                    "open_for_registration": int(record.open_for_registration),
                    "open_for_submission": int(record.open_for_submission),
                    "numOfRegistrants": record.numOfRegistrants,
                    "numOfSubmissions": record.numOfSubmissions,
                    "registrant_count": record.registrant_count,
                    "submitter_count": record.submitter_count,
                    "winner_count": record.winner_count,
                    "totalPrizeCost": record.totalPrizeCost,
                    "winners": record.winners,
                    "platform_mentions": ";".join(record.platform_mentions),
                    "ai_related": int(record.ai_related),
                    "ai_keywords": ";".join(record.ai_keywords),
                    "source_file": record.source_file,
                }
            )


def write_open_challenges(records: Sequence[ChallengeRecord], output_path: Path) -> None:
    filtered = [
        record
        for record in records
        if record.open_for_registration or record.open_for_submission
    ]
    write_challenge_summary(filtered, output_path)


def write_submission_details(data: Dict[str, List[Dict[str, Any]]], output_path: Path) -> None:
    if not data:
        return
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def write_ai_feasibility(records: Sequence[ChallengeRecord], output_path: Path) -> None:
    rows = [assess_ai_feasibility(record) for record in records]
    write_rows_to_csv(rows, output_path)


def write_top_challenges(entries: Sequence[Dict[str, Any]], output_path: Path) -> None:
    if not entries:
        return
    fieldnames = sorted(entries[0].keys())
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for entry in entries:
            writer.writerow(entry)


def write_distribution_csv(distribution: Dict[str, float], output_path: Path) -> None:
    if not distribution:
        return
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["metric", "hours"])
        for key in sorted(distribution.keys()):
            writer.writerow([key, distribution[key]])


def write_rows_to_csv(rows: Sequence[Dict[str, Any]], output_path: Path) -> None:
    if not rows:
        return
    fieldnames: List[str] = sorted({key for row in rows for key in row.keys()})
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_language_summary(lang_map: Dict[str, int], output_path: Path) -> None:
    if not lang_map:
        return
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["language", "total_lines"])
        for language, total in sorted(lang_map.items(), key=lambda item: item[1], reverse=True):
            writer.writerow([language, total])


def summarize_artifacts(artifacts: Sequence[SubmissionArtifact], challenge_lookup: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    feasibility_summary: Dict[str, Dict[str, Any]] = {}
    type_breakdown: Dict[str, Counter] = defaultdict(Counter)
    high_complex: List[Dict[str, Any]] = []
    ai_vs_non: Dict[str, Dict[str, Any]] = {
        "AI": {"count": 0, "lines": 0, "submissions": 0, "prize": 0},
        "Non-AI": {"count": 0, "lines": 0, "submissions": 0, "prize": 0},
    }

    for artifact in artifacts:
        if artifact.lines_total <= 0:
            continue
        challenge = challenge_lookup.get(artifact.challenge_id, {})
        prize = challenge.get("totalPrizeCost", 0)
        challenge_type = challenge.get("type") or "Unknown"
        track = challenge.get("trackType") or "Unknown"
        status = challenge.get("status")
        ai_flag = bool(challenge.get("ai_related"))

        key = artifact.ai_feasibility or "Unknown"
        summary = feasibility_summary.setdefault(
            key,
            {
                "count": 0,
                "total_lines": 0,
                "total_prize": 0,
                "tests": 0,
                "frameworks": Counter(),
                "avg_lines": 0.0,
                "avg_prize": 0.0,
            },
        )
        summary["count"] += 1
        summary["total_lines"] += artifact.lines_total
        summary["total_prize"] += prize
        if artifact.tests_detected:
            summary["tests"] += 1
        for fw in artifact.frameworks or []:
            summary["frameworks"][fw] += 1

        type_breakdown[key][challenge_type] += 1

        bucket = "AI" if ai_flag else "Non-AI"
        ai_vs_non[bucket]["count"] += 1
        ai_vs_non[bucket]["lines"] += artifact.lines_total
        ai_vs_non[bucket]["prize"] += prize
        ai_vs_non[bucket]["submissions"] += 1

        if artifact.complexity_label == "Large":
            high_complex.append(
                {
                    "challengeId": artifact.challenge_id,
                    "submissionId": artifact.submission_id,
                    "handle": artifact.handle,
                    "lines_total": artifact.lines_total,
                    "files_total": artifact.files_total,
                    "ai_feasibility": artifact.ai_feasibility,
                    "frameworks": ",".join(artifact.frameworks or []),
                    "tests_detected": int(artifact.tests_detected),
                    "prize": prize,
                    "challengeType": challenge_type,
                    "trackType": track,
                    "status": status,
                    "llm_signals": ",".join(artifact.llm_signals or []),
                }
            )

    for key, summary in feasibility_summary.items():
        if summary["count"]:
            summary["avg_lines"] = summary["total_lines"] / summary["count"]
            summary["avg_prize"] = summary["total_prize"] / summary["count"]
            summary["tests_share"] = summary["tests"] / summary["count"]
        else:
            summary["avg_lines"] = summary["avg_prize"] = summary["tests_share"] = 0
        summary["frameworks"] = dict(summary["frameworks"])

    for bucket, stats in ai_vs_non.items():
        if stats["count"]:
            stats["avg_lines"] = stats["lines"] / stats["count"]
            stats["avg_prize"] = stats["prize"] / stats["count"]
        else:
            stats["avg_lines"] = stats["avg_prize"] = 0

    return {
        "feasibility_summary": feasibility_summary,
        "type_breakdown": {k: dict(v) for k, v in type_breakdown.items()},
        "high_complex": high_complex,
        "ai_vs_non": ai_vs_non,
    }


def write_counter_summary(counter: Counter, output_path: Path, label_header: str) -> None:
    if not counter:
        return
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([label_header, "count"])
        for label, count in counter.most_common():
            writer.writerow([label, count])


def write_status_by_track(matrix: Dict[str, Counter], output_path: Path) -> None:
    if not matrix:
        return
    statuses: Set[str] = set()
    for counter in matrix.values():
        statuses.update(counter.keys())
    ordered_statuses = sorted(statuses)

    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        header = ["trackType"] + ordered_statuses + ["total"]
        writer.writerow(header)
        for track, counter in sorted(matrix.items()):
            total = sum(counter.values())
            row = [track] + [counter.get(status, 0) for status in ordered_statuses] + [total]
            writer.writerow(row)


def compute_monthly_activity(records: Sequence[ChallengeRecord]) -> Dict[str, Dict[str, int]]:
    monthly: Dict[str, Dict[str, float]] = defaultdict(lambda: {
        "challenges": 0,
        "total_prize": 0,
        "open_for_registration": 0,
        "open_for_submission": 0,
        "total_submissions": 0,
        "submission_window_sum": 0.0,
        "submission_window_count": 0,
        "ai_challenges": 0,
        "ai_total_prize": 0,
        "ai_submissions": 0,
        "ai_submission_window_sum": 0.0,
        "ai_submission_window_count": 0,
    })
    for record in records:
        start = _fallback_start_date(record)
        if not start:
            continue
        key = start.strftime("%Y-%m")
        entry = monthly[key]
        entry["challenges"] += 1
        entry["total_prize"] += record.totalPrizeCost
        if record.open_for_registration:
            entry["open_for_registration"] += 1
        if record.open_for_submission:
            entry["open_for_submission"] += 1
        entry["total_submissions"] += record.numOfSubmissions
        window = _hours_between(record.submissionStartDate, record.submissionEndDate)
        if window is not None:
            entry["submission_window_sum"] += window
            entry["submission_window_count"] += 1
        if record.ai_related:
            entry["ai_challenges"] += 1
            entry["ai_total_prize"] += record.totalPrizeCost
            entry["ai_submissions"] += record.numOfSubmissions
            if window is not None:
                entry["ai_submission_window_sum"] += window
                entry["ai_submission_window_count"] += 1
    return dict(sorted(monthly.items()))


def write_monthly_activity(data: Dict[str, Dict[str, float]], output_path: Path) -> None:
    if not data:
        return
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "month",
                "challenges",
                "total_prize",
                "total_submissions",
                "open_for_registration",
                "open_for_submission",
                "avg_submission_window_hours",
                "ai_challenges",
                "ai_total_prize",
                "ai_submissions",
                "avg_ai_submission_window_hours",
            ]
        )
        for month, metrics in data.items():
            avg_window = (
                metrics["submission_window_sum"] / metrics["submission_window_count"]
                if metrics["submission_window_count"]
                else 0.0
            )
            avg_ai_window = (
                metrics["ai_submission_window_sum"] / metrics["ai_submission_window_count"]
                if metrics["ai_submission_window_count"]
                else 0.0
            )
            writer.writerow(
                [
                    month,
                    int(metrics["challenges"]),
                    int(metrics["total_prize"]),
                    int(metrics["total_submissions"]),
                    int(metrics["open_for_registration"]),
                    int(metrics["open_for_submission"]),
                    round(avg_window, 2),
                    int(metrics["ai_challenges"]),
                    int(metrics["ai_total_prize"]),
                    int(metrics["ai_submissions"]),
                    round(avg_ai_window, 2),
                ]
            )


def compute_metrics(records: Sequence[ChallengeRecord], member_map: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    unique_members: Set[str] = set()
    submitting_members: Set[str] = set()
    winning_members: Set[str] = set()
    for members in member_map.values():
        for entry in members:
            handle = entry.get("memberHandle")
            if not handle:
                continue
            unique_members.add(handle)
            if entry.get("submission"):
                submitting_members.add(handle)
            if (entry.get("winningPosition") or 0) > 0:
                winning_members.add(handle)

    open_for_registration = sum(1 for record in records if record.open_for_registration)
    open_for_submission = sum(1 for record in records if record.open_for_submission)
    status_counts = Counter(record.status for record in records)
    platform_counts = Counter(
        platform for record in records for platform in record.platform_mentions if platform.lower() != "topcoder"
    )
    track_counts = Counter(record.trackType or "Unknown" for record in records)
    challenge_type_counts = Counter(record.type or "Unknown" for record in records)
    monthly_activity = compute_monthly_activity(records)
    status_by_track: Dict[str, Counter] = defaultdict(Counter)
    for record in records:
        track_key = record.trackType or "Unknown"
        status_key = record.status or "Unknown"
        status_by_track[track_key][status_key] += 1
    total_prize = sum(record.totalPrizeCost for record in records)
    challenge_with_submissions = [record for record in records if record.numOfSubmissions > 0]
    total_reported_submissions = sum(record.numOfSubmissions for record in records)
    total_reported_registrants = sum(record.numOfRegistrants for record in records)
    ai_challenge_count = sum(1 for record in records if record.ai_related)
    ai_submission_total = sum(record.numOfSubmissions for record in records if record.ai_related)
    ai_total_prize = sum(record.totalPrizeCost for record in records if record.ai_related)
    submission_windows = [
        hours
        for record in records
        for hours in [_hours_between(record.submissionStartDate, record.submissionEndDate)]
        if hours is not None
    ]
    ai_submission_windows = [
        hours
        for record in records if record.ai_related
        for hours in [_hours_between(record.submissionStartDate, record.submissionEndDate)]
        if hours is not None
    ]
    non_ai_submission_windows = [
        hours
        for record in records if not record.ai_related
        for hours in [_hours_between(record.submissionStartDate, record.submissionEndDate)]
        if hours is not None
    ]
    registration_windows = [
        hours
        for record in records
        for hours in [_hours_between(record.registrationStartDate, record.registrationEndDate)]
        if hours is not None
    ]
    delivery_windows = [
        hours
        for record in records
        for hours in [_hours_between(record.startDate, record.endDate)]
        if hours is not None
    ]
    top_submission_challenges = [
        {
            "challengeId": record.challengeId,
            "name": record.name,
            "status": record.status,
            "numOfSubmissions": record.numOfSubmissions,
            "numOfRegistrants": record.numOfRegistrants,
            "totalPrizeCost": record.totalPrizeCost,
            "submission_window_hours": _hours_between(record.submissionStartDate, record.submissionEndDate),
        }
        for record in sorted(challenge_with_submissions, key=lambda r: r.numOfSubmissions, reverse=True)[:10]
    ]
    top_prize_challenges = [
        {
            "challengeId": record.challengeId,
            "name": record.name,
            "status": record.status,
            "totalPrizeCost": record.totalPrizeCost,
            "numOfSubmissions": record.numOfSubmissions,
            "numOfRegistrants": record.numOfRegistrants,
            "submission_window_hours": _hours_between(record.submissionStartDate, record.submissionEndDate),
        }
        for record in sorted(records, key=lambda r: r.totalPrizeCost, reverse=True)[:10]
    ]

    top_submitters = Counter()
    for record in records:
        for entry in member_map.get(record.challengeId, []):
            if entry.get("submission"):
                handle = entry.get("memberHandle")
                if handle:
                    top_submitters[handle] += 1

    return {
        "total_challenges": len(records),
        "open_for_registration": open_for_registration,
        "open_for_submission": open_for_submission,
        "status_counts": status_counts,
        "unique_members": len(unique_members),
        "submitting_members": len(submitting_members),
        "winning_members": len(winning_members),
        "platform_counts": platform_counts,
        "track_counts": track_counts,
        "challenge_type_counts": challenge_type_counts,
        "monthly_activity": monthly_activity,
        "status_by_track": status_by_track,
        "total_prize": total_prize,
        "challenges_with_submissions": len(challenge_with_submissions),
        "total_reported_submissions": total_reported_submissions,
        "total_reported_registrants": total_reported_registrants,
        "average_reported_submissions": (
            total_reported_submissions / len(records) if records else 0.0
        ),
        "average_reported_registrants": (
            total_reported_registrants / len(records) if records else 0.0
        ),
        "submission_window_distribution": _distribution(submission_windows),
        "registration_window_distribution": _distribution(registration_windows),
        "delivery_window_distribution": _distribution(delivery_windows),
        "top_submission_challenges": top_submission_challenges,
        "top_prize_challenges": top_prize_challenges,
        "artifact_summary": {},
        "ai_feasibility_counts": {},
        "complexity_counts": {},
        "ai_challenges": ai_challenge_count,
        "ai_total_prize": ai_total_prize,
        "ai_total_submissions": ai_submission_total,
        "ai_submission_window_distribution": _distribution(ai_submission_windows),
        "non_ai_submission_window_distribution": _distribution(non_ai_submission_windows),
        "top_submitters": top_submitters.most_common(20),
    }


def write_markdown_summary(metrics: Dict[str, Any], now: datetime, output_path: Path) -> None:
    lines = [
        f"# Topcoder Challenge Activity Report",
        "",
        f"_Generated at {now.isoformat()}_",
        "",
        f"- Total challenges analysed: {metrics['total_challenges']}",
        f"- Challenges open for registration: {metrics['open_for_registration']}",
        f"- Challenges open for submission: {metrics['open_for_submission']}",
        f"- Unique active members (registrants): {metrics['unique_members']}",
        f"- Members with submissions: {metrics['submitting_members']}",
        f"- Members with wins: {metrics['winning_members']}",
        f"- Total prize purse represented: ${metrics['total_prize']:,}",
        f"- Challenges with reported submissions: {metrics['challenges_with_submissions']}",
        f"- Total submissions reported by Topcoder API: {metrics['total_reported_submissions']}",
        f"- Avg submissions per challenge: {metrics['average_reported_submissions']:.2f}",
        f"- Avg registrants per challenge: {metrics['average_reported_registrants']:.2f}",
        (
            f"- AI-related challenges: {metrics['ai_challenges']} "
            f"({(metrics['ai_challenges'] / metrics['total_challenges'] * 100) if metrics['total_challenges'] else 0:.1f}% of total), "
            f"{metrics['ai_total_submissions']} submissions, ${metrics['ai_total_prize']:,} prize pool"
        ) if metrics.get('ai_challenges') else None,
        "",
        "## Challenge status counts",
    ]
    lines = [entry for entry in lines if entry is not None]
    for status, count in metrics["status_counts"].most_common():
        lines.append(f"- {status}: {count}")

    lines.append("")
    lines.append("## Alternative platform mentions")
    if metrics["platform_counts"]:
        for platform, count in metrics["platform_counts"].most_common():
            lines.append(f"- {platform}: {count} challenges")
    else:
        lines.append("- None detected in challenge descriptions.")

    lines.append("")
    lines.append("## Track breakdown")
    if metrics["track_counts"]:
        for track, count in metrics["track_counts"].most_common():
            lines.append(f"- {track}: {count} challenges")
    else:
        lines.append("- No track information available.")

    lines.append("")
    lines.append("## Monthly activity (top 6 months)")
    monthly_items = list(metrics["monthly_activity"].items())
    if monthly_items:
        monthly_items.sort(key=lambda item: item[1]["challenges"], reverse=True)
        for month, data in monthly_items[:6]:
            ai_challenges = int(data.get("ai_challenges", 0))
            ai_submissions = int(data.get("ai_submissions", 0))
            avg_ai_window = data.get("ai_submission_window_sum", 0.0)
            avg_ai_window = (
                avg_ai_window / data.get("ai_submission_window_count", 1)
                if data.get("ai_submission_window_count")
                else 0.0
            )
            lines.append(
                f"- {month}: {int(data['challenges'])} challenges, "
                f"${int(data['total_prize']):,} in prizes, "
                f"{int(data['open_for_registration'])} open for registration, "
                f"{int(data['open_for_submission'])} open for submission, "
                f"{int(data.get('total_submissions', 0))} submissions total, "
                f"{ai_challenges} AI-tagged ({ai_submissions} submissions, avg window {avg_ai_window:.1f} h)"
            )
    else:
        lines.append("- No dated challenge data available.")

    lines.append("")
    lines.append("## Status by track (selected)")
    status_by_track = metrics["status_by_track"]
    if status_by_track:
        for track, counter in sorted(status_by_track.items()):
            top_statuses = ", ".join(
                f"{status}: {count}" for status, count in counter.most_common(3)
            )
            lines.append(f"- {track}: {top_statuses}")
    else:
        lines.append("- No track/status combinations available.")

    lines.append("")
    lines.append("## Submission activity details")
    submission_dist = metrics["submission_window_distribution"]
    if submission_dist:
        lines.append(
            f"- Submission window (median): {submission_dist['median']:.1f} hours; range {submission_dist['min']:.1f}–{submission_dist['max']:.1f} hours"
        )
    else:
        lines.append("- Submission window durations unavailable in source data.")

    ai_dist = metrics.get("ai_submission_window_distribution") or {}
    if ai_dist:
        lines.append(
            f"- AI-tagged challenge window (median): {ai_dist.get('median', 0):.1f} hours"
        )
    non_ai_dist = metrics.get("non_ai_submission_window_distribution") or {}
    if non_ai_dist:
        lines.append(
            f"- Non-AI challenge window (median): {non_ai_dist.get('median', 0):.1f} hours"
        )

    lines.append(
        f"- Top challenge by submissions: {metrics['top_submission_challenges'][0]['name']} ("
        f"{metrics['top_submission_challenges'][0]['numOfSubmissions']} submissions)"
        if metrics["top_submission_challenges"]
        else "- No submission-rich challenges detected in dataset."
    )

    lines.append("")
    lines.append("## High-prize challenges (top 5)")
    if metrics["top_prize_challenges"]:
        for entry in metrics["top_prize_challenges"][:5]:
            lines.append(
                f"- {entry['name']}: ${entry['totalPrizeCost']:,} prize, "
                f"{entry['numOfSubmissions']} submissions, status {entry['status']}"
            )
    else:
        lines.append("- Prize information missing.")

    lines.append("")
    artifact_summary = metrics.get("artifact_summary") or {}
    lines.append("## Submission artifact analysis")
    if artifact_summary:
        lines.append(
            f"- Analysed submissions: {artifact_summary.get('analysed_submissions', 0)}"
        )
        lines.append(
            f"- Average lines per analysed submission: {artifact_summary.get('avg_lines', 0):.1f}"
        )
        lines.append(
            f"- Average files per analysed submission: {artifact_summary.get('avg_files', 0):.1f}"
        )
        feasibility = metrics.get("ai_feasibility_counts", {})
        if feasibility:
            joined = ", ".join(f"{label}: {count}" for label, count in feasibility.items())
            lines.append(f"- AI feasibility distribution: {joined}")
        complexity = metrics.get("complexity_counts", {})
        if complexity:
            joined = ", ".join(f"{label}: {count}" for label, count in complexity.items())
            lines.append(f"- Complexity distribution: {joined}")
        failures = artifact_summary.get("failures") or []
        if failures:
            lines.append(f"- Artifact download failures: {len(failures)} submissions (see logs)")
        artifact_insights = metrics.get("artifact_insights") or {}
        if artifact_insights.get("feasibility_summary"):
            for feas, summary in artifact_insights["feasibility_summary"].items():
                lines.append(
                    f"  - {feas} feasibility: {summary.get('count', 0)} submissions, "
                    f"avg {summary.get('avg_lines', 0):.0f} lines, "
                    f"avg prize ${summary.get('avg_prize', 0):.0f}"
                )
        if artifact_insights.get("high_complex"):
            top_complex = artifact_insights["high_complex"][:3]
            for entry in top_complex:
                lines.append(
                    f"  - High-complexity submission {entry['submissionId']} ({entry['lines_total']} lines, prize ${entry['prize']})"
                )
        if artifact_insights.get("ai_vs_non"):
            ai_vs_non = artifact_insights["ai_vs_non"]
            ai_stats = ai_vs_non.get("AI", {})
            non_stats = ai_vs_non.get("Non-AI", {})
            if ai_stats or non_stats:
                lines.append(
                    f"- AI vs Non-AI submissions average lines: "
                    f"{ai_stats.get('avg_lines', 0):.0f} vs {non_stats.get('avg_lines', 0):.0f}"
                )
    else:
        lines.append("- Artifact downloads/analysis skipped; provide --download-artifacts and a bearer token to enable.")

    lines.append("")
    lines.append("## Top submitters (by number of submissions)")
    if metrics["top_submitters"]:
        for handle, submissions in metrics["top_submitters"]:
            lines.append(f"- {handle}: {submissions} submission(s)")
    else:
        lines.append("- Submission details unavailable; provide TOPCODER_BEARER_TOKEN to enable.")

    lines.append("")
    lines.append("## Notes")
    lines.append(
        "- Submission content (artifacts) requires an authenticated bearer token. "
        "Populate the TOPCODER_BEARER_TOKEN environment variable before running "
        "this script to capture metadata for research review."
    )
    lines.append(
        "- Code complexity, development time, and AI competitiveness metrics are not "
        "present in the public API; deriving them requires downloading submission "
        "artifacts and pairing with human/AI benchmarking data."
    )

    with output_path.open("w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    now = (
        datetime.fromisoformat(args.as_of).replace(tzinfo=timezone.utc)
        if args.as_of
        else datetime.now(timezone.utc)
    )

    if args.from_api:
        raw_challenges = fetch_api_challenges(args.start_date, args.end_date, args.status, args.track)
    else:
        raw_challenges = load_local_challenges(args.challenge_dir)

    member_map = load_member_mapping(args.member_mapping)
    platforms_lookup = build_platform_lookup(args.platform_keywords)

    records = build_challenge_records(raw_challenges, member_map, platforms_lookup, now)
    metrics = compute_metrics(records, member_map)

    submission_details = collect_submission_details(records)
    artifact_rows: List[Dict[str, Any]] = []
    artifact_summary: Dict[str, Any] = {}
    artifact_insights: Dict[str, Any] = {}
    if submission_details and args.download_artifacts:
        api_config = load_api_config()
        token = api_config.bearer_token
        if token:
            analyzer = ArtifactAnalyzer(
                args.artifact_dir,
                token,
                api_config.base_url,
                download=True,
                limit_per_challenge=max(1, args.artifact_limit),
                debug_path=args.output_dir / "artifact_debug.log",
            )
            challenge_lookup = {
                record.challengeId: {
                    "challengeId": record.challengeId,
                    "name": record.name,
                    "type": record.type,
                    "trackType": record.trackType,
                    "status": record.status,
                    "totalPrizeCost": record.totalPrizeCost,
                    "ai_related": record.ai_related,
                }
                for record in records
            }
            artefacts, artifact_summary = analyzer.process(submission_details, challenge_lookup)
            artifact_rows = artefact_results_to_rows(artefacts)
            artifact_insights = summarize_artifacts(artefacts, challenge_lookup)
        else:
            print(
                "Warning: --download-artifacts provided but TOPCODER_BEARER_TOKEN is missing; skipping artifact analysis.")

    if artifact_summary:
        metrics["artifact_summary"] = artifact_summary
        metrics["ai_feasibility_counts"] = artifact_summary.get("feasibility_counts", {})
        metrics["complexity_counts"] = artifact_summary.get("complexity_counts", {})
        if artifact_insights:
            metrics["artifact_insights"] = artifact_insights

    write_challenge_summary(records, output_dir / "challenges_summary.csv")
    write_open_challenges(records, output_dir / "open_challenges.csv")
    write_ai_feasibility(records, output_dir / "ai_feasibility_analysis.csv")
    if submission_details:
        write_submission_details(submission_details, output_dir / "submission_details.json")
    write_markdown_summary(metrics, now, output_dir / "report.md")
    write_counter_summary(metrics["status_counts"], output_dir / "status_summary.csv", "status")
    write_counter_summary(metrics["track_counts"], output_dir / "track_summary.csv", "trackType")
    write_counter_summary(
        metrics["challenge_type_counts"], output_dir / "challenge_type_summary.csv", "challengeType"
    )
    write_counter_summary(metrics["platform_counts"], output_dir / "platform_mentions.csv", "platform")
    write_status_by_track(metrics["status_by_track"], output_dir / "status_by_track.csv")
    write_monthly_activity(metrics["monthly_activity"], output_dir / "monthly_activity.csv")
    write_top_challenges(metrics["top_submission_challenges"], output_dir / "top_submissions.csv")
    write_top_challenges(metrics["top_prize_challenges"], output_dir / "top_prize_challenges.csv")
    write_distribution_csv(
        metrics["submission_window_distribution"], output_dir / "submission_window_stats.csv"
    )
    write_distribution_csv(
        metrics["registration_window_distribution"], output_dir / "registration_window_stats.csv"
    )
    write_distribution_csv(
        metrics["delivery_window_distribution"], output_dir / "delivery_window_stats.csv"
    )
    write_distribution_csv(
        metrics.get("ai_submission_window_distribution", {}),
        output_dir / "ai_submission_window_stats.csv",
    )
    write_distribution_csv(
        metrics.get("non_ai_submission_window_distribution", {}),
        output_dir / "non_ai_submission_window_stats.csv",
    )

    if artifact_rows:
        write_rows_to_csv(artifact_rows, output_dir / "submission_analysis.csv")
        write_language_summary(
            metrics["artifact_summary"].get("languages", {}), output_dir / "submission_languages.csv"
        )
        write_language_summary(
            metrics["artifact_summary"].get("framework_counts", {}), output_dir / "submission_frameworks.csv"
        )
        write_language_summary(
            metrics["artifact_summary"].get("llm_counts", {}), output_dir / "submission_llm_signals.csv"
        )
        failures = metrics["artifact_summary"].get("failures") or []
        if failures:
            write_rows_to_csv(
                [{"submissionId": failure} for failure in failures],
                output_dir / "artifact_failures.csv",
            )
        summary_path = output_dir / "artifact_summary.json"
        with summary_path.open("w", encoding="utf-8") as fh:
            json.dump(metrics["artifact_summary"], fh, indent=2)
        artifact_insights = metrics.get("artifact_insights", {})
        if artifact_insights:
            feas_rows = []
            for feas, summary in artifact_insights.get("feasibility_summary", {}).items():
                row = {
                    "ai_feasibility": feas,
                    "count": summary.get("count", 0),
                    "avg_lines": round(summary.get("avg_lines", 0), 2),
                    "avg_prize": round(summary.get("avg_prize", 0), 2),
                    "tests_share": round(summary.get("tests_share", 0), 3),
                }
                feas_rows.append(row)
            write_rows_to_csv(feas_rows, output_dir / "ai_feasibility_summary.csv")

            type_rows = []
            for feas, breakdown in artifact_insights.get("type_breakdown", {}).items():
                for challenge_type, count in breakdown.items():
                    type_rows.append({
                        "ai_feasibility": feas,
                        "challengeType": challenge_type,
                        "count": count,
                    })
            write_rows_to_csv(type_rows, output_dir / "ai_feasibility_type_breakdown.csv")

            high_complex_rows = artifact_insights.get("high_complex", [])
            write_rows_to_csv(high_complex_rows, output_dir / "high_complex_challenges.csv")

            ai_vs_non_rows = []
            for bucket, stats in artifact_insights.get("ai_vs_non", {}).items():
                ai_vs_non_rows.append({
                    "segment": bucket,
                    "count": stats.get("count", 0),
                    "avg_lines": round(stats.get("avg_lines", 0), 2),
                    "avg_prize": round(stats.get("avg_prize", 0), 2),
                })
            write_rows_to_csv(ai_vs_non_rows, output_dir / "ai_vs_non_summary.csv")


if __name__ == "__main__":
    main()
