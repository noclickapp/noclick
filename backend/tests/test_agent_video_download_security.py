"""Credential-boundary coverage for generated-video downloads."""

import httpx
import pytest

from nodes.agent_node import _download_agent_video


class RecordingClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def get(self, url, **kwargs):
        self.calls.append((str(url), kwargs))
        response = self.responses.pop(0)
        if response.request is None:
            response.request = httpx.Request("GET", url)
        return response


def response(status_code=200, *, url="https://example.test/file", location=None):
    headers = {"location": location} if location is not None else {}
    return httpx.Response(
        status_code,
        headers=headers,
        request=httpx.Request("GET", url),
        content=b"video",
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://generativelanguage.googleapis.com.attacker.example/collect",
        "https://generativelanguage.googleapis.com@attacker.example/collect",
        "http://generativelanguage.googleapis.com/v1beta/files/1:download",
        "https://generativelanguage.googleapis.com:8443/v1beta/files/1:download",
    ],
)
async def test_google_api_key_is_not_attached_to_lookalike_origins(url):
    client = RecordingClient([response(url=url)])

    await _download_agent_video(client, url, "secret-google-key")

    assert client.calls == [(url, {"headers": {}, "follow_redirects": False})]


async def test_google_api_key_is_attached_to_exact_official_origin():
    url = "https://generativelanguage.googleapis.com/v1beta/files/1:download"
    client = RecordingClient([response(url=url)])

    await _download_agent_video(client, url, "secret-google-key")

    assert client.calls[0][1]["headers"] == {
        "x-goog-api-key": "secret-google-key"
    }
    assert client.calls[0][1]["follow_redirects"] is False


async def test_google_api_key_is_stripped_from_cross_origin_redirect():
    source = "https://generativelanguage.googleapis.com/v1beta/files/1:download"
    signed = "https://storage.googleapis.com/generated-media/video.mp4?signature=x"
    client = RecordingClient(
        [
            response(302, url=source, location=signed),
            response(url=signed),
        ]
    )

    await _download_agent_video(client, source, "secret-google-key")

    assert client.calls[0][1]["headers"] == {
        "x-goog-api-key": "secret-google-key"
    }
    assert client.calls[1] == (
        signed,
        {"headers": {}, "follow_redirects": False},
    )


async def test_relative_redirect_rechecks_the_exact_google_origin():
    source = "https://generativelanguage.googleapis.com/v1beta/files/1:download"
    target = "https://generativelanguage.googleapis.com/v1beta/files/2:download"
    client = RecordingClient(
        [
            response(307, url=source, location="/v1beta/files/2:download"),
            response(url=target),
        ]
    )

    await _download_agent_video(client, source, "secret-google-key")

    assert client.calls[1] == (
        target,
        {
            "headers": {"x-goog-api-key": "secret-google-key"},
            "follow_redirects": False,
        },
    )
