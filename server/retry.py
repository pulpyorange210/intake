"""Shared retry policy for the Sheets and Slack calls: exponential backoff with jitter."""
from __future__ import annotations

import random
from typing import Optional

import httpx

BASE_SECONDS = 1.0
FACTOR = 2.0
MAX_ATTEMPTS = 5
CAP_SECONDS = 30.0


class HTTPStatusError(Exception):
    """An HTTP error response from an external API, carrying its status code."""

    def __init__(self, status: int, message: str = ""):
        super().__init__(f"HTTP {status}: {message}"[:500])
        self.status = status


def backoff(attempt: int, rng: Optional[random.Random] = None) -> float:
    """Delay before retry number `attempt` (1-based): full jitter over base x factor^(attempt-1), capped."""
    ceiling = min(CAP_SECONDS, BASE_SECONDS * FACTOR ** (attempt - 1))
    return (rng or random).uniform(0, ceiling)


def is_retryable(exc: BaseException) -> bool:
    """429 and 5xx are retried, and so are network failures and timeouts: the request may or may not have
    landed, which the callers handle (Sheets re-reads before appending; Slack alerts are rare enough that a
    duplicate after a timeout is acceptable). Any other 4xx is a permanent failure."""
    if isinstance(exc, HTTPStatusError):
        return exc.status == 429 or exc.status >= 500
    return isinstance(exc, (httpx.TransportError, TimeoutError, ConnectionError))
