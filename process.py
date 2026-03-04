''' This file contains methods to parse json objects into correct format '''

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from utility import parse_iso_dt, calculate_prizes


def format_challenge(challenge_obj):
    ''' Converts challenge_obj variables in correct required format '''
    legacy_obj = challenge_obj.get("legacy") or {}

    def _parse_dt(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        try:
            return parse_iso_dt(value)
        except ValueError:
            return None

    new_obj: Dict[str, Any] = {}
    new_obj["challengeId"] = challenge_obj.get("id")

    legacy_id = challenge_obj.get("legacyId")
    try:
        new_obj["legacyId"] = int(legacy_id) if legacy_id is not None else 0
    except (TypeError, ValueError):
        new_obj["legacyId"] = 0

    new_obj["directProjectId"] = legacy_obj.get("directProjectId", 0) or 0
    new_obj["status"] = challenge_obj.get("status")
    new_obj["trackType"] = challenge_obj.get("track")
    new_obj["type"] = challenge_obj.get("type")
    new_obj["name"] = challenge_obj.get("name")
    new_obj["description"] = challenge_obj.get("description")
    new_obj["totalPrizeCost"] = calculate_prizes(challenge_obj.get("prizeSets"))
    winners = challenge_obj.get("winners") or []
    new_obj["winners"] = ",".join(
        [winner.get("handle", "") for winner in winners if winner.get("handle")]
    )
    new_obj["registrationStartDate"] = _parse_dt(
        challenge_obj.get("registrationStartDate")
    )
    new_obj["registrationEndDate"] = _parse_dt(
        challenge_obj.get("registrationEndDate")
    )
    new_obj["submissionStartDate"] = _parse_dt(
        challenge_obj.get("submissionStartDate")
    )
    new_obj["submissionEndDate"] = _parse_dt(
        challenge_obj.get("submissionEndDate")
    )
    new_obj["startDate"] = _parse_dt(challenge_obj.get("startDate"))
    new_obj["endDate"] = _parse_dt(challenge_obj.get("endDate"))
    new_obj["technologies"] = ",".join(challenge_obj.get("tags") or [])
    new_obj["numOfSubmissions"] = challenge_obj.get("numOfSubmissions", 0)
    new_obj["numOfRegistrants"] = challenge_obj.get("numOfRegistrants", 0)
    new_obj["forumId"] = legacy_obj.get("forumId", 0) or 0

    return new_obj


EXCEL_EPOCH = datetime(1899, 12, 30)


def format_legacy_excel_row(row: Dict[str, Any]) -> Dict[str, Any]:
    '''Normalises a legacy Excel export row to the same schema as format_challenge.'''

    def _safe_string(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return str(value)

    def _safe_number(value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        try:
            cleaned = str(value).strip()
        except Exception:
            return None
        if not cleaned:
            return None
        cleaned = cleaned.replace(",", "")
        try:
            return float(cleaned)
        except ValueError:
            return None

    def _safe_int(value: Any) -> int:
        number = _safe_number(value)
        if number is None:
            return 0
        return int(number)

    def _excel_serial_to_str(value: Any) -> Optional[str]:
        number = _safe_number(value)
        if number is None or number <= 0:
            return None
        dt_value = EXCEL_EPOCH + timedelta(days=number)
        return dt_value.strftime("%Y-%m-%d %H:%M:%S")

    challenge_id = _safe_string(row.get("challengeId"))
    if not challenge_id:
        raise ValueError("Missing challengeId in legacy row")

    formatted: Dict[str, Any] = {
        "challengeId": challenge_id,
        "legacyId": _safe_int(row.get("legacyId")),
        "directProjectId": _safe_int(row.get("directProjectId")),
        "status": _safe_string(row.get("status")),
        "trackType": _safe_string(row.get("trackType")),
        "type": _safe_string(row.get("type")),
        "name": _safe_string(row.get("name")),
        "description": row.get("description"),
        "totalPrizeCost": _safe_int(row.get("totalPrizeCost")),
        "winners": row.get("winners") or "",
        "registrationStartDate": _excel_serial_to_str(row.get("registrationStartDate")),
        "registrationEndDate": _excel_serial_to_str(row.get("registrationEndDate")),
        "submissionStartDate": _excel_serial_to_str(row.get("submissionStartDate")),
        "submissionEndDate": _excel_serial_to_str(row.get("submissionEndDate")),
        "startDate": _excel_serial_to_str(row.get("startDate")),
        "endDate": _excel_serial_to_str(row.get("endDate")),
        "technologies": row.get("technologies") or "",
        "numOfSubmissions": _safe_int(row.get("numOfSubmissions")),
        "numOfRegistrants": _safe_int(row.get("numOfRegistrants")),
        "forumId": _safe_int(row.get("forumId")),
    }
    return formatted


def format_member(member_obj):
    new_obj: Dict[str, Any] = {}
    new_obj["userId"] = member_obj.get("userId")
    new_obj["memberHandle"] = member_obj.get("handle")

    def _flag(track_key: str) -> int:
        track_obj = member_obj.get(track_key) or {}
        challenges = track_obj.get("challenges", 0)
        return 1 if isinstance(challenges, (int, float)) and challenges > 1 else 0

    new_obj["DEVELOP"] = _flag("DEVELOP")
    new_obj["DESIGN"] = _flag("DESIGN")
    new_obj["DATA_SCIENCE"] = _flag("DATA_SCIENCE")

    max_rating = member_obj.get("maxRating") or {}
    new_obj["maxRating"] = (max_rating.get("rating") or 0)
    new_obj["track"] = max_rating.get("track")
    new_obj["subTrack"] = max_rating.get("subTrack")
    new_obj["registrations"] = member_obj.get("challenges", 0)
    new_obj["wins"] = member_obj.get("wins", 0)

    return new_obj


def format_member_skills(member_skill_obj):
    user_entered: List[str] = []
    participation_skill: List[str] = []
    skills = (member_skill_obj or {}).get("skills", {})

    for skill in skills.values():
        sources = skill.get("sources", [])
        tag_name = skill.get("tagName")
        if not tag_name:
            continue
        if sources and sources[0] == "CHALLENGE":
            participation_skill.append(tag_name)
        else:
            user_entered.append(tag_name)

    user_entered_str = ",".join(user_entered) if user_entered else None
    participation_skill_str = ",".join(participation_skill) if participation_skill else None

    return (user_entered_str, participation_skill_str)
