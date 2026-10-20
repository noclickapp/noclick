"""Fetching a media URL: hosts that refuse anonymous clients still serve it.

Wikimedia (and others) answer ``403`` to a request that doesn't say who is
asking (httpx's default ``python-httpx/x.y``), so a public-domain recording on
Wikimedia Commons couldn't be transcribed. The fetch names NoClick and where
to reach it, as their User-Agent policy asks."""

import httpx
import pytest

from nodes.core import media_resolver

URL = "https://upload.wikimedia.org/wikipedia/commons/0/0e/En-us-Frank_and_Alice_dialogue.ogg"


def _like_wikimedia(seen):
    def answer(request: httpx.Request) -> httpx.Response:
        agent = request.headers.get("user-agent", "")
        seen.append(agent)
        if agent.startswith(("python-", "curl/")) or "http" not in agent:
            return httpx.Response(403, text="Please set a user-agent and respect our robot policy")
        return httpx.Response(200, content=b"OggS-audio", headers={"content-type": "application/ogg"})

    return answer


@pytest.mark.asyncio
async def test_a_url_fetch_names_noclick_so_a_host_with_a_user_agent_policy_serves_it(monkeypatch):
    seen = []

    def client(*, trusted_exact_urls=(), **kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(_like_wikimedia(seen)), **kwargs)

    monkeypatch.setattr("utils.ssrf.guarded_async_client", client)
    monkeypatch.setattr("utils.ssrf.assert_url_allowed", _allowed)

    made = await media_resolver.resolve_media_input(URL)

    assert (made.data, made.mime_type) == (b"OggS-audio", "application/ogg")
    assert len(seen) == 1 and "NoClick" in seen[0] and "https://noclick.com" in seen[0]


async def _allowed(url: str) -> None:
    return None
