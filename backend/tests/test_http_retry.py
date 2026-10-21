"""A provider's 429 is waited out the way it asks (``utils/http_retry.py``): the request is sent again after the
wait its ``Retry-After`` names (else a short backoff), a few times at most, and a wait longer than a call should hold
or a body that can't be sent twice leaves the 429 to the caller."""

import httpx
import pytest

from utils import http_retry
from utils.http_retry import RetryAfterTransport, parse_retry_after

pytestmark = pytest.mark.asyncio

THROTTLED = {"error": {"code": "ApplicationThrottled",
                       "message": "Application is over its MailboxConcurrency limit."}}


@pytest.fixture
def waits(monkeypatch):
    waited = []

    async def sleep(seconds):
        waited.append(seconds)

    monkeypatch.setattr(http_retry.asyncio, "sleep", sleep)
    return waited


def _provider(*answers):
    """A provider answering each request with the next of ``answers``; ``seen`` keeps the bodies it got."""
    queue, seen = list(answers), []

    def handle(request):
        seen.append(request.content)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    return httpx.MockTransport(handle), seen


async def test_a_429_is_sent_again_after_the_wait_its_retry_after_names(waits):
    transport, seen = _provider(httpx.Response(429, headers={"Retry-After": "2"}, json=THROTTLED),
                                httpx.Response(200, json={"value": []}))
    async with httpx.AsyncClient(transport=RetryAfterTransport(transport)) as client:
        response = await client.post("https://graph.microsoft.com/v1.0/me/messages", json={"subject": "Hi"})
    assert response.status_code == 200 and response.json() == {"value": []}
    assert waits == [2.0] and seen == [b'{"subject":"Hi"}'] * 2


async def test_without_retry_after_it_backs_off_and_the_last_429_is_the_answer(waits):
    transport, seen = _provider(httpx.Response(429, json=THROTTLED))
    async with httpx.AsyncClient(transport=RetryAfterTransport(transport)) as client:
        response = await client.get("https://graph.microsoft.com/v1.0/me/messages")
    assert response.status_code == 429 and response.json() == THROTTLED
    assert waits == [1.0, 2.0, 4.0] and len(seen) == 1 + http_retry.MAX_RETRIES


async def test_a_wait_longer_than_a_call_should_hold_is_left_to_the_caller(waits):
    transport, seen = _provider(httpx.Response(429, headers={"Retry-After": "120"}, json=THROTTLED))
    async with httpx.AsyncClient(transport=RetryAfterTransport(transport)) as client:
        response = await client.get("https://graph.microsoft.com/v1.0/me/messages")
    assert response.status_code == 429 and not waits and len(seen) == 1


async def test_a_body_that_cant_be_sent_twice_is_not_sent_again(waits):
    transport, seen = _provider(httpx.Response(429, headers={"Retry-After": "1"}, json=THROTTLED))
    async with httpx.AsyncClient(transport=RetryAfterTransport(transport)) as client:
        response = await client.post("https://graph.microsoft.com/v1.0/me/drive/root/children",
                                     files={"file": ("a.txt", b"hello")})
    assert response.status_code == 429 and not waits and len(seen) == 1


async def test_other_answers_pass_through_untouched(waits):
    transport, seen = _provider(httpx.Response(503, headers={"Retry-After": "1"}), httpx.Response(200))
    async with httpx.AsyncClient(transport=RetryAfterTransport(transport)) as client:
        assert (await client.get("https://graph.microsoft.com/v1.0/me")).status_code == 503
    assert not waits and len(seen) == 1


async def test_retry_after_is_seconds_or_a_date():
    assert parse_retry_after("3") == 3.0
    assert parse_retry_after(None) is None and parse_retry_after("soon") is None
    assert parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0  # already past
