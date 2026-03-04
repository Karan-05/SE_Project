from datetime import datetime, timedelta

import pytest

from process import (
    format_challenge,
    format_legacy_excel_row,
    format_member,
    format_member_skills,
)


def test_format_challenge_normalises_fields():
    payload = {
        "id": "12345",
        "legacyId": "456",
        "legacy": {"directProjectId": None, "forumId": 789},
        "status": "Completed",
        "track": "Data Science",
        "type": "Code",
        "name": "Sample Challenge",
        "description": "Collect sample datasets.",
        "prizeSets": [
            {"type": "placement", "prizes": [{"value": "500"}, {"value": 200}]},
            {"type": "checkpoint", "prizes": [{"value": 50}]},
        ],
        "winners": [{"handle": "alice"}, {"handle": ""}],
        "registrationStartDate": "2023-01-01T00:00:00.000Z",
        "registrationEndDate": "2023-01-05T00:00:00.000Z",
        "submissionStartDate": "2023-01-02T00:00:00.000Z",
        "submissionEndDate": "2023-01-06T00:00:00.000Z",
        "startDate": "2023-01-01T00:00:00.000Z",
        "endDate": "2023-01-10T00:00:00.000Z",
        "tags": ["Python", "SQL"],
        "numOfSubmissions": 12,
        "numOfRegistrants": 34,
    }

    formatted = format_challenge(payload)

    assert formatted["challengeId"] == "12345"
    assert formatted["legacyId"] == 456
    assert formatted["directProjectId"] == 0
    assert formatted["forumId"] == 789
    assert formatted["totalPrizeCost"] == 750
    assert formatted["winners"] == "alice"
    assert formatted["registrationStartDate"] == "2023-01-01 00:00:00"
    assert formatted["submissionEndDate"] == "2023-01-06 00:00:00"
    assert formatted["technologies"] == "Python,SQL"


def test_format_member_sets_track_flags():
    payload = {
        "userId": 999,
        "handle": "SampleUser",
        "DEVELOP": {"challenges": 3},
        "DESIGN": {"challenges": 1},
        "DATA_SCIENCE": {"challenges": 0},
        "maxRating": {"rating": 2250, "track": "DSE", "subTrack": "Marathon"},
        "challenges": 12,
        "wins": 2,
    }

    formatted = format_member(payload)

    assert formatted["userId"] == 999
    assert formatted["memberHandle"] == "SampleUser"
    assert formatted["DEVELOP"] == 1
    assert formatted["DESIGN"] == 0
    assert formatted["DATA_SCIENCE"] == 0
    assert formatted["maxRating"] == 2250
    assert formatted["track"] == "DSE"
    assert formatted["wins"] == 2


@pytest.mark.parametrize(
    "skill_payload,expected",
    [
        (
            {
                "skills": {
                    "python": {
                        "tagName": "Python",
                        "sources": ["CHALLENGE"],
                    },
                    "ml": {
                        "tagName": "Machine Learning",
                        "sources": ["USER_ENTERED"],
                    },
                }
            },
            ("Machine Learning", "Python"),
        ),
        (
            {"skills": {}},
            (None, None),
        ),
    ],
)
def test_format_member_skills_groups_sources(skill_payload, expected):
    assert format_member_skills(skill_payload) == expected


def test_format_legacy_excel_row_parses_serial_dates_and_numbers():
    excel_serial = 45000.75
    row = {
        "challengeId": "abc-123",
        "legacyId": "3.0025288E7",
        "directProjectId": "4032.0",
        "status": "Completed",
        "trackType": "Development",
        "type": "Challenge",
        "name": "Legacy Challenge",
        "description": "<p>hello</p>",
        "totalPrizeCost": "1500.0",
        "winners": "alice,bob",
        "registrationStartDate": excel_serial,
        "registrationEndDate": excel_serial,
        "submissionStartDate": excel_serial,
        "submissionEndDate": excel_serial,
        "startDate": excel_serial,
        "endDate": excel_serial,
        "technologies": "Python,SQL",
        "numOfSubmissions": "5",
        "numOfRegistrants": "10",
        "forumId": "11900",
    }

    formatted = format_legacy_excel_row(row)
    expected_date = (datetime(1899, 12, 30) + timedelta(days=excel_serial)).strftime("%Y-%m-%d %H:%M:%S")

    assert formatted["challengeId"] == "abc-123"
    assert formatted["legacyId"] == 30025288
    assert formatted["directProjectId"] == 4032
    assert formatted["totalPrizeCost"] == 1500
    assert formatted["registrationStartDate"] == expected_date
    assert formatted["numOfSubmissions"] == 5
    assert formatted["numOfRegistrants"] == 10
