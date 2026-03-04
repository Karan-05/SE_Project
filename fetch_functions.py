''' This file Contains functions related to fetching from Topcoder API '''
import logging
import json
import os
from typing import List, Set

import requests
from progress.bar import Bar
from requests.exceptions import HTTPError, RequestException

from config import load_api_config
from http_utils import request_with_retries
from process import format_challenge, format_member, format_member_skills


API_CONFIG = load_api_config()
BASE_URL = API_CONFIG.base_url.rstrip("/")
CHALLENGES_ENDPOINT = f"{BASE_URL}/challenges"
RESOURCES_ENDPOINT = f"{BASE_URL}/resources"
SUBMISSIONS_ENDPOINT = f"{BASE_URL}/submissions"
MEMBERS_ENDPOINT = f"{BASE_URL}/members"
_missing_token_warned = False
_SESSION = requests.Session()
logger = logging.getLogger(__name__)


def get_data(total_pages: int, total_challenges: int, params, start_date_start_range, end_date_start_range, storage_directory):
    ''' Fetches the API, formats and stores as JSON in given directory '''

    directory_name: str = f'challengeData_{start_date_start_range}_{end_date_start_range}'
    curr_dir = os.path.join(storage_directory,
                            directory_name)

    try:
        os.mkdir(curr_dir)
        logger.info("Created storage directory %s", curr_dir)
    except FileExistsError:
        logger.debug("Storage directory %s already exists", curr_dir)
    except OSError as exc:
        logger.warning("Unable to create storage directory %s: %s", curr_dir, exc)

    try:
        total_pages_int = int(total_pages)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid total_pages value: {total_pages}") from None

    for i in range(1, total_pages_int + 1):
        params['page'] = i

        try:
            response = request_with_retries(
                "get",
                CHALLENGES_ENDPOINT,
                params=params,
                timeout=10.0,
                session=_SESSION,
            )
        except RequestException as exc:
            logger.error("Request failed for page %s after retries: %s", i, exc)
            continue

        challenge_list = response.json()

        with open(os.path.join(curr_dir, f'page{i}.json'), "w", encoding="utf-8") as my_file:
            bar = Bar('Processing', max=params["perPage"])
            processed_challenge = []
            for challenge in challenge_list:
                processed_challenge.append(format_challenge(challenge))
                bar.next()
            json.dump(processed_challenge, my_file, indent=4)
            bar.finish()
        logger.info('Downloaded and stored data from page %s', i)
    logger.info('All challenge pages downloaded')


def fetch_challenge_registrants(challenge_id: str):
    ''' Gets a list of all registrants for the challenge '''
    # Can add an env variable instead of static url
    member_url: str = f'{RESOURCES_ENDPOINT}?challengeId={challenge_id}'

    try:
        response = request_with_retries(
            "get",
            member_url,
            timeout=8.0,
            max_attempts=2 if os.environ.get("TOPCODER_FAST_RETRY", "").lower() in {"1", "true", "yes"} else 4,
            backoff_factor=0.4,
            session=_SESSION,
        )
    except HTTPError as http_err:
        status_code = getattr(http_err.response, "status_code", None)
        if status_code == 404:
            logger.info(
                'No registrants found for challenge %s (HTTP %s)',
                challenge_id,
                status_code,
            )
        else:
            logger.error(
                'HTTP error occurred while fetching registrants for challenge %s: %s',
                challenge_id,
                http_err,
            )
        return []
    except RequestException as err:
        logger.error(
            'Request error occurred while fetching registrants for challenge %s: %s',
            challenge_id,
            err,
        )
        return []
    else:
        member_registrant_date = response.json()
        registrant_list = []
        for member in member_registrant_date:
            handle = member.get("memberHandle")
            if handle:
                registrant_list.append(handle)
        return registrant_list


def fetch_challenge_submissions(challenge_id: str):
    ''' Gets a list of all members who made a submission to the challenge '''
    global _missing_token_warned

    headers = {}
    if API_CONFIG.bearer_token:
        headers['Authorization'] = f'Bearer {API_CONFIG.bearer_token}'
    else:
        if not _missing_token_warned:
            logger.warning(
                'TOPCODER_BEARER_TOKEN not provided; submissions data will be skipped.'
            )
            _missing_token_warned = True
        return set()

    url = f'{SUBMISSIONS_ENDPOINT}?challengeId={challenge_id}'
    try:
        response = request_with_retries(
            "get", url, headers=headers, timeout=10.0, max_attempts=5, session=_SESSION
        )
    except HTTPError as http_err:
        logger.error(
            'HTTP error occurred while fetching submissions for challenge %s: %s',
            challenge_id,
            http_err,
        )
        return set()
    except RequestException as err:
        logger.error(
            'Request error occurred while fetching submissions for challenge %s: %s',
            challenge_id,
            err,
        )
        return set()
    else:
        member_submission_data = response.json()
        submission_set: Set[str] = set()
        for member in member_submission_data:
            created_by = member.get("createdBy")
            if created_by:
                submission_set.add(created_by)
        return submission_set


def fetch_member_data(member: str):
    ''' Fetches member data from the given memeberHandle '''
    member = member.lower()
    url = f'{MEMBERS_ENDPOINT}/{member}/stats'
    try:
        response = request_with_retries("get", url, timeout=10.00, session=_SESSION)
    except HTTPError as http_err:
        status_code = getattr(http_err.response, "status_code", None)
        logger.error(
            'HTTP error retrieving stats for member %s (status=%s): %s',
            member,
            status_code,
            http_err,
        )
        raise FileNotFoundError(
            f'Error: Could not download data for member {member}'
        ) from http_err
    except RequestException as err:
        logger.error(
            'Request error retrieving stats for member %s: %s',
            member,
            err,
        )
        raise FileNotFoundError(
            f'Error: Could not download data for member {member}'
        ) from err

    member_json = response.json()
    if not member_json:
        raise FileNotFoundError(
            f'Error: Empty payload returned for member {member}')
    processed_member = format_member(member_json[0])
    return processed_member


def fetch_member_skills(member: str):
    member = member.lower()
    url = f'{MEMBERS_ENDPOINT}/{member}/skills'
    try:
        response = request_with_retries("get", url, timeout=10.00, session=_SESSION)
    except HTTPError as http_err:
        status_code = getattr(http_err.response, "status_code", None)
        if status_code == 404:
            logger.info('No skills payload for member %s (404)', member)
            return (None, None)
        logger.error(
            'HTTP error retrieving skills for member %s (status=%s): %s',
            member,
            status_code,
            http_err,
        )
        raise FileNotFoundError(
            f'Error: Could not download the Skill data for member {member}'
        ) from http_err
    except RequestException as err:
        logger.error(
            'Request error retrieving skills for member %s: %s',
            member,
            err,
        )
        raise FileNotFoundError(
            f'Error: Could not download the Skill data for member {member}'
        ) from err

    member_skill_json = response.json()
    return format_member_skills(member_skill_json)
