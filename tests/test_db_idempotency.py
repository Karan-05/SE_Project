import json
from pathlib import Path
from typing import Dict

import pytest

from schema_registry import TableRegistry
from uploader import Uploader


class FakeDB:
    def __init__(self):
        self.table_registry = TableRegistry({})
        self.storage: Dict[str, Dict] = {
            "challenges": {},
            "challenge_member_mapping": {},
            "members": {},
        }

    def upload_data(self, payload, table_key: str):
        if table_key == "challenges":
            key = payload["challengeId"]
        elif table_key == "challenge_member_mapping":
            key = (payload["challengeId"], payload["memberHandle"])
        elif table_key == "members":
            key = payload["memberHandle"]
        else:
            key = len(self.storage.get(table_key, {})) + 1

        self.storage.setdefault(table_key, {})
        self.storage[table_key][key] = payload
        return len(self.storage[table_key])

    def check_member(self, member_set, *, max_age_hours=None, force_refresh=False):
        if force_refresh:
            return member_set
        existing = set(self.storage["members"].keys())
        return {handle for handle in member_set if handle not in existing}


@pytest.fixture()
def fixture_directory(tmp_path: Path):
    challenge = {
        "challengeId": "123",
        "legacyId": 321,
        "directProjectId": 1,
        "status": "Completed",
        "trackType": "Dev",
        "type": "Code",
        "name": "Sample",
        "description": "Sample",
        "totalPrizeCost": 500,
        "winners": "",
        "registrationStartDate": "2023-01-01 00:00:00",
        "registrationEndDate": "2023-01-02 00:00:00",
        "submissionStartDate": "2023-01-01 00:00:00",
        "submissionEndDate": "2023-01-03 00:00:00",
        "startDate": "2023-01-01 00:00:00",
        "endDate": "2023-01-04 00:00:00",
        "technologies": "Python",
        "numOfSubmissions": 1,
        "numOfRegistrants": 1,
        "forumId": 0,
    }
    data_dir = tmp_path / "challengeData_2023-01-01_2023-01-31"
    data_dir.mkdir()
    with (data_dir / "page1.json").open("w", encoding="utf-8") as fp:
        json.dump([challenge], fp)
    return data_dir


def test_uploader_idempotent(monkeypatch, fixture_directory):
    fake_db = FakeDB()

    monkeypatch.setattr("uploader.fetch_challenge_registrants", lambda _: ["alice"])
    monkeypatch.setattr("uploader.fetch_challenge_submissions", lambda _: {"alice"})
    member_calls = {"data": 0, "skills": 0}

    def fake_member_data(handle):
        member_calls["data"] += 1
        return {
            "userId": 1,
            "memberHandle": handle,
            "DEVELOP": 1,
            "DESIGN": 0,
            "DATA_SCIENCE": 0,
            "maxRating": 2000,
            "track": "Dev",
            "subTrack": "Code",
            "registrations": 1,
            "wins": 0,
        }

    def fake_member_skills(handle):
        member_calls["skills"] += 1
        return ("python", "python")

    monkeypatch.setattr("uploader.fetch_member_data", fake_member_data)
    monkeypatch.setattr("uploader.fetch_member_skills", fake_member_skills)

    Uploader(
        str(fixture_directory),
        db_client=fake_db,
    )
    Uploader(
        str(fixture_directory),
        db_client=fake_db,
    )

    assert len(fake_db.storage["challenges"]) == 1
    assert len(fake_db.storage["challenge_member_mapping"]) == 1
    assert len(fake_db.storage["members"]) == 1
    assert member_calls["data"] == 1
    assert member_calls["skills"] == 1
