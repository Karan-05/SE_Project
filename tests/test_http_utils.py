from unittest.mock import Mock

import pytest
from requests.exceptions import RequestException

from http_utils import request_with_retries


def test_request_with_retries_eventually_succeeds():
    session = Mock()
    error = RequestException("boom")
    error.response = Mock(status_code=500)
    success_response = Mock()
    success_response.raise_for_status.return_value = None
    session.request.side_effect = [error, success_response]

    response = request_with_retries(
        "get",
        "https://example.com",
        session=session,
        max_attempts=3,
        backoff_factor=0,
    )

    assert response is success_response
    assert session.request.call_count == 2


def test_request_with_retries_raises_after_exhaustion():
    session = Mock()
    error = RequestException("boom")
    error.response = Mock(status_code=500)
    session.request.side_effect = [error, error, error]

    with pytest.raises(RequestException):
        request_with_retries(
            "get",
            "https://example.com",
            session=session,
            max_attempts=2,
            backoff_factor=0,
        )

    assert session.request.call_count == 2
