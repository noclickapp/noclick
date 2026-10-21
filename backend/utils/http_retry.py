"""Waiting out a provider's 429 the way it asks: ``RetryAfterTransport`` for any httpx client."""

import asyncio
import logging
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
# Longer than this, a call holds its caller (an agent's turn) too long: the 429 is the answer.
MAX_WAIT_S = 10.0
BACKOFF_S = 1.0


def parse_retry_after(value: Optional[str]) -> Optional[float]:
    """A Retry-After header (delta-seconds or an HTTP date) in seconds from now."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    return max(0.0, (when - datetime.now(when.tzinfo)).total_seconds())


class RetryAfterTransport(httpx.AsyncBaseTransport):
    """Sends a request the provider answered 429 (too many requests) again after the wait its ``Retry-After`` names
    (else 1s, 2s, 4s), ``retries`` times at most. A longer wait than ``max_wait_s``, the last 429, and a request whose
    body can't be sent twice (a multipart upload) are the caller's answer."""

    def __init__(self, inner: Optional[httpx.AsyncBaseTransport] = None, *, retries: int = MAX_RETRIES,
                 max_wait_s: float = MAX_WAIT_S) -> None:
        self._inner = inner or httpx.AsyncHTTPTransport()
        self._retries, self._max_wait_s = retries, max_wait_s

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        replayable = isinstance(request.stream, httpx.ByteStream)  # read before a send can buffer it
        for attempt in range(self._retries + 1):
            response = await self._inner.handle_async_request(request)
            if response.status_code != 429 or attempt == self._retries or not replayable:
                return response
            wait = parse_retry_after(response.headers.get("retry-after"))
            wait = BACKOFF_S * 2 ** attempt if wait is None else wait
            if wait > self._max_wait_s:
                return response
            await response.aclose()
            logger.info("http_429_retry host=%s wait_s=%.1f attempt=%d", request.url.host, wait, attempt + 1)
            await asyncio.sleep(wait)
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()
