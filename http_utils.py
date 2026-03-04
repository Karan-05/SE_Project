"""HTTP helpers with shared retry/backoff semantics."""

from __future__ import annotations

import logging
import random
import time
from typing import Iterable

import requests
from requests import Response
from requests.exceptions import RequestException

logger = logging.getLogger(__name__)

DEFAULT_RETRY_STATUSES = (500, 502, 503, 504, 524)


def request_with_retries(
    method: str,
    url: str,
    *,
    max_attempts: int = 4,
    backoff_factor: float = 0.5,
    retry_statuses: Iterable[int] = DEFAULT_RETRY_STATUSES,
    session: requests.Session | None = None,
    **kwargs,
) -> Response:
    """Perform an HTTP request with exponential backoff retries."""
    if session is None:
        session = requests.Session()

    attempt = 0
    while True:
        attempt += 1
        try:
            response = session.request(method.upper(), url, **kwargs)
            response.raise_for_status()
            if attempt > 1:
                logger.info(
                    "Recovered %s %s after %s attempts",
                    method.upper(),
                    url,
                    attempt,
                )
            return response
        except RequestException as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            should_retry = attempt < max_attempts and (
                status_code is None or status_code in tuple(retry_statuses)
            )
            if not should_retry:
                logger.error(
                    "Giving up on %s %s after %s attempts (status=%s): %s",
                    method.upper(),
                    url,
                    attempt,
                    status_code,
                    exc,
                )
                raise

            sleep_time = backoff_factor * (2 ** (attempt - 1))
            jitter = random.uniform(0, backoff_factor)
            wait_time = sleep_time + jitter
            logger.warning(
                "Attempt %s/%s for %s %s failed (%s, status=%s). Retrying in %.2fs",
                attempt,
                max_attempts,
                method.upper(),
                url,
                exc,
                status_code,
                wait_time,
            )
            time.sleep(wait_time)
