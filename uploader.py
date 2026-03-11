''' This file contains fuctions to upload processed data to database '''
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Set

from progress.bar import Bar

from config import load_db_config
from dbConnect import dbConnect
from fetch_functions import (
    fetch_challenge_registrants,
    fetch_challenge_submissions,
    fetch_member_data,
    fetch_member_skills,
)

logger = logging.getLogger(__name__)


class Uploader:
    ''' Ths class contains functions to uplod data to the database '''

    def __init__(
        self,
        directory: str,
        db_config: Dict[str, str] | None = None,
        *,
        force_refresh_members: bool | None = None,
        member_cache_ttl_hours: int | None = None,
        db_client=None,
    ) -> None:
        if db_config is None:
            db_config = load_db_config().as_dict()
        elif hasattr(db_config, "as_dict"):
            db_config = db_config.as_dict()  # type: ignore[assignment]

        self.db_config = db_config
        self.member_set: Set[str] = set()
        self.db_obj = db_client or dbConnect(self.db_config)
        self.tables = self.db_obj.table_registry
        self.storage_directory = directory
        self.force_refresh_members = (
            force_refresh_members
            if force_refresh_members is not None
            else os.environ.get("TOPCODER_FORCE_REFRESH_MEMBERS", "false").lower() in {"1", "true", "yes"}
        )
        ttl_env = os.environ.get("TOPCODER_MEMBER_CACHE_TTL_HOURS")
        if member_cache_ttl_hours is not None:
            self.member_cache_ttl_hours = member_cache_ttl_hours
        elif ttl_env is not None:
            try:
                self.member_cache_ttl_hours = int(ttl_env)
            except ValueError:
                logger.warning("Invalid TOPCODER_MEMBER_CACHE_TTL_HOURS '%s'; defaulting to 720", ttl_env)
                self.member_cache_ttl_hours = 720
        else:
            self.member_cache_ttl_hours = 720  # default 30 days
        # Legacy Excel loads can skip registrant/submission lookups to avoid API storms.
        self.skip_member_fetch = os.environ.get("TOPCODER_SKIP_MEMBER_FETCH", "").lower() in {"1", "true", "yes"}

        # call the upload challenge function
        self.uploadChallenges(self.storage_directory)

        # Remove existing members from the set
        self.check_unique_members(self.member_set)
        # call the member upload function
        self.upload_members(self.member_set)

    # directory can be called in the constructor
    def uploadChallenges(self, directory):
        ''' Loads processed challenge from json file and upload it to DB while 
            fetching registrants and submissions from the API
        '''
        directory_path = Path(directory)
        if not directory_path.is_dir():
            raise NotADirectoryError(f'{directory} is not a valid directory')

        json_files: List[Path] = sorted(
            file_path
            for file_path in directory_path.iterdir()
            if file_path.is_file() and file_path.suffix == ".json"
        )
        page_files = [file_path for file_path in json_files if file_path.name.startswith("page")]
        file_list = page_files or json_files

        if not file_list:
            logger.warning('No JSON files found in %s', directory_path)
            return

        logger.info(
            'Uploading challenges from %s (%s files)',
            directory_path,
            len(file_list),
        )

        for file_path in file_list:
            try:
                with open(file_path, "r", encoding="utf-8") as curr_json_file:
                    challenge_json = json.load(curr_json_file)
            except json.JSONDecodeError as exc:
                logger.error('Failed to parse %s: %s', file_path, exc)
                continue
            except OSError as exception:
                logger.error(
                    'File %s could not be read: %s',
                    file_path,
                    exception,
                )
                continue

            if not isinstance(challenge_json, list):
                logger.error('File %s does not contain a list of challenges; skipping', file_path)
                continue

            challenge_progress = Bar(
                f"Uploading {file_path.name}", max=len(challenge_json))
            for challenge in challenge_json:
                challenge_primary_id: int = self.db_obj.upload_data(
                    challenge, "challenges")
                if challenge_primary_id != -1:
                    self.load_challenge_members(
                        challenge, challenge.get("winners"), challenge_primary_id)
                challenge_progress.next()
            challenge_progress.finish()
            logger.info(
                'Finished loading challenges and related members from %s',
                file_path.name,
            )

    def load_challenge_members(
        self,
        challenge: Dict[str, Any],
        challenge_winner: str | List[str] | None,
        challenge_primary_id: int,
    ):
        ''' Fetches all registrants, submissions and winners, loads it to the mapping 
            database based on challenge_id and challenge_winner
        '''
        if self.skip_member_fetch:
            return

        if isinstance(challenge_winner, list):
            winners_field = ",".join(
                handle for handle in challenge_winner if isinstance(handle, str) and handle
            )
        elif isinstance(challenge_winner, str):
            winners_field = challenge_winner
        else:
            winners_field = ""

        winners_list = [handle.strip() for handle in winners_field.split(",") if handle.strip()]
        winner_dict: Dict[str, int] = {}
        for position, winner in enumerate(winners_list):
            winner_dict[winner] = position + 1

        submission_set: Set[str] = fetch_challenge_submissions(
            challenge["challengeId"])
        registrants_list: List[str] = fetch_challenge_registrants(
            challenge["challengeId"])

        if registrants_list:
            for members in registrants_list:
                # append members to a list for future use
                self.member_set.add(members)
                new_member_obj = {
                    "challengeId": challenge["challengeId"],
                    "legacyId": challenge["legacyId"],
                    "memberHandle": members,
                    "submission": 1 if submission_set and members in submission_set else 0,
                    "winningPosition": winner_dict[members] if members in winner_dict else 0
                }
                self.db_obj.upload_data(
                    new_member_obj, "challenge_member_mapping")

    def check_unique_members(self, member_set: Set[str]):
        ''' Checks if the member already exists in the database and removes 
            from the set
        '''
        if not member_set:
            self.member_set = set()
            return
        new_set = self.db_obj.check_member(
            member_set,
            max_age_hours=self.member_cache_ttl_hours,
            force_refresh=self.force_refresh_members,
        )
        self.member_set = new_set

    def upload_members(self, member_set: Set[str]):
        ''' Fetches from API and Uploads member to the database from the given member_set '''
        logger.info('Loading %s unique members to the database', len(member_set))
        member_progress = Bar(
            "Uploading Members", max=len(member_set))
        for member in member_set:
            try:
                processed_member = fetch_member_data(member)
                processed_member["user_entered"], processed_member["participation_skill"] = fetch_member_skills(
                    member)
            except Exception as e:
                logger.exception('Failed to ingest member %s', member)
            else:
                self.db_obj.upload_data(processed_member, "members")
            member_progress.next()
        member_progress.finish()
        logger.info("Finished uploading members to the database")


# if __name__ == "__main__":
#     up = Uploader(
#         "/Users/mahirdhall/Desktop/WebScrapping/challengeData_2020-01-01_2020-02-02")
