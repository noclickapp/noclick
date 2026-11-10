"""PeerTube wire contracts and stateful poll behavior, using provider schema examples."""
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError

from nodes.cpy_node import PeerTubeConfig, PeerTubeNode, PeerTubeTokenCredential

FIXTURES = Path(__file__).parent / "fixtures" / "cpy"
CREDENTIAL = {
    "credential_type": "cpy_access_token",
    "instance_url": "https://peertube.cpy.re",
    "access_token": "test-access-token",
}


def node(operation, **values):
    return PeerTubeNode(
        node_id="cpy-test",
        node_type="automation-cpy",
        node_data={},
        config=PeerTubeConfig.model_validate(
            {"config": {"operation": operation, **values}, "credentials": CREDENTIAL}
        ),
        sio=Mock(),
        sid="sid",
        workflow_id="workflow",
        user_id="user",
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org",
        "https://user:password@example.org",
        "https://example.org:8080",
    ],
)
def test_cpy_rejects_unsafe_credential_origin(url):
    with pytest.raises(ValidationError):
        PeerTubeTokenCredential(instance_url=url, access_token="token")


def test_cpy_manual_credential_fields_and_defaults():
    credential = PeerTubeTokenCredential(
        instance_url="https://peertube.cpy.re/my-library/videos", access_token=" token "
    )
    assert credential.credential_type == "cpy_access_token"
    assert credential.instance_url == "https://peertube.cpy.re"
    assert credential.access_token == "token"
    with pytest.raises(ValidationError):
        PeerTubeTokenCredential(
            instance_url="https://example.org", access_token="Bearer token"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,values,method,path,expected",
    [
        ("get_my_account", {}, "GET", "/api/v1/users/me", None),
        ("get_video", {"video_id": 42}, "GET", "/api/v1/videos/42", None),
        (
            "get_channel",
            {"channel_handle": "framasoft@example.org"},
            "GET",
            "/api/v1/video-channels/framasoft@example.org",
            None,
        ),
        (
            "create_channel",
            {"name": "framasoft_videos", "display_name": "Videos of Framasoft"},
            "POST",
            "/api/v1/video-channels",
            {"name": "framasoft_videos", "displayName": "Videos of Framasoft"},
        ),
        (
            "update_channel",
            {"channel_handle": "framasoft_videos", "support": "Support our work"},
            "PUT",
            "/api/v1/video-channels/framasoft_videos",
            {"support": "Support our work"},
        ),
        (
            "add_playlist_video",
            {"playlist_id": 42, "video_id": 42, "start_timestamp": 10},
            "POST",
            "/api/v1/video-playlists/42/videos",
            {"videoId": 42, "startTimestamp": 10},
        ),
        (
            "remove_playlist_video",
            {"playlist_id": 42, "element_id": 2},
            "DELETE",
            "/api/v1/video-playlists/42/videos/2",
            None,
        ),
    ],
)
async def test_cpy_json_and_path_contract(
    monkeypatch, operation, values, method, path, expected
):
    calls = []

    def respond(request):
        calls.append(request)
        assert request.method == method
        assert request.url.path == path
        assert request.headers["authorization"] == "Bearer test-access-token"
        if expected is not None:
            assert json.loads(request.content) == expected
        return (
            httpx.Response(204)
            if method == "DELETE"
            else httpx.Response(
                200,
                json=(
                    {"id": 42, "username": "chocobozzz"}
                    if operation == "get_my_account"
                    else {"id": 42}
                ),
            )
        )

    monkeypatch.setattr(
        "nodes.cpy_node.guarded_async_client",
        lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    output = await node(operation, **values).execute({})
    assert len(calls) == 1
    assert output == (
        {"success": True}
        if method == "DELETE"
        else {"id": 42, "username": "chocobozzz"}
        if operation == "get_my_account"
        else {"id": 42}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,values,expected",
    [
        (
            "update_video",
            {"video_id": 42, "name": "What is PeerTube?", "download_enabled": False},
            {"name": "What is PeerTube?", "downloadEnabled": "false"},
        ),
        (
            "import_video",
            {
                "target_url": "https://example.org/video.mp4",
                "name": "What is PeerTube?",
                "channel_id": 3,
            },
            {
                "targetUrl": "https://example.org/video.mp4",
                "channelId": "3",
                "name": "What is PeerTube?",
            },
        ),
        (
            "create_playlist",
            {"display_name": "My playlist", "privacy": 3},
            {"displayName": "My playlist", "privacy": "3"},
        ),
    ],
)
async def test_cpy_multipart_without_file_upload(
    monkeypatch, operation, values, expected
):
    from email.parser import BytesParser
    from email.policy import default

    def respond(request):
        assert request.headers["content-type"].startswith(
            "multipart/form-data; boundary="
        )
        message = BytesParser(policy=default).parsebytes(
            ("Content-Type: " + request.headers["content-type"] + "\r\n\r\n").encode()
            + request.content
        )
        fields = {
            part.get_param("name", header="content-disposition"): part.get_content()
            for part in message.iter_parts()
        }
        assert fields == expected
        return httpx.Response(200, json={"video": {"id": 42}})

    monkeypatch.setattr(
        "nodes.cpy_node.guarded_async_client",
        lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    await node(operation, **values).execute({})


@pytest.mark.asyncio
async def test_cpy_numeric_video_reference_in_playlist_is_json_integer(monkeypatch):
    async def request(credential, method, path, **kwargs):
        assert kwargs["body"] == {"videoId": 42}
        return {"videoPlaylistElement": {"id": 2}}

    monkeypatch.setattr(PeerTubeNode, "_request", staticmethod(request))
    await node("add_playlist_video", playlist_id=42, video_id="42").execute({})


@pytest.mark.asyncio
async def test_cpy_expired_token_is_provider_rejection(monkeypatch):
    def respond(request):
        return httpx.Response(
            401,
            json={
                "error": "invalid_token",
                "error_description": "The access token expired",
            },
        )

    monkeypatch.setattr(
        "nodes.cpy_node.guarded_async_client",
        lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    with pytest.raises(ValueError, match="401.*access token expired"):
        await node("get_my_account").execute({})


@pytest.mark.asyncio
async def test_cpy_does_not_follow_redirect_or_leak_token(monkeypatch):
    def respond(request):
        return httpx.Response(
            302,
            headers={"location": "https://other.example.org"},
            text="test-access-token",
        )

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr("nodes.cpy_node.guarded_async_client", client)
    with pytest.raises(ValueError, match="302.*redacted"):
        await node("get_my_account").execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,fixture,values,key",
    [
        (
            "on_new_channel_video",
            "Video.json",
            {"channel_handle": "framasoft_videos"},
            "videos",
        ),
        ("on_new_channel", "VideoChannel.json", {}, "channels"),
    ],
)
async def test_cpy_poll_baseline_dedup_and_agent_event(
    monkeypatch, operation, fixture, values, key
):
    item = json.loads((FIXTURES / fixture).read_text())
    rows = [item]
    instance = node(operation, **values)
    state = {}

    async def update(mutator, **kwargs):
        nonlocal state
        new_state, result = mutator(state)
        if new_state is not None:
            state = new_state
        return result

    async def request(credential, method, path, **kwargs):
        assert kwargs["params"]["sort"] == "-createdAt"
        return {"total": len(rows), "data": rows}

    monkeypatch.setattr(instance, "_request", request)
    monkeypatch.setattr(instance, "_update_node_state", update)
    assert (await instance.execute({}))[key] == []
    assert instance.trigger_produced_no_event({})
    # A newly created resource keeps the provider-documented response shape.
    rows = [dict(item, id=43), item]
    output = await instance.execute({})
    assert [row["id"] for row in output[key]] == [43]
    assert instance.trigger_emitted_event(output)
    event = instance.resolve_agent_event(output)
    assert "43" in event["text"]
    assert ("What is PeerTube?" if key == "videos" else "Videos of Framasoft") in event[
        "text"
    ]
    assert (await instance.execute({}))[key] == []


@pytest.mark.asyncio
async def test_cpy_poll_paginates_and_never_commits_failed_page(monkeypatch):
    instance = node("on_new_channel_video", channel_handle="framasoft_videos")
    calls = []

    async def request(credential, method, path, **kwargs):
        start = kwargs["params"]["start"]
        calls.append(start)
        if start == 100:
            raise ValueError("provider unavailable")
        return {"data": [{"id": i + 1} for i in range(100)]}

    async def unexpected(*args, **kwargs):
        pytest.fail("must not change state after incomplete pagination")

    monkeypatch.setattr(instance, "_request", request)
    monkeypatch.setattr(instance, "_filter_unseen", unexpected)
    with pytest.raises(ValueError, match="provider unavailable"):
        await instance.execute({})
    assert calls == [0, 100]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,fixture,values,key",
    [
        (
            "on_new_channel_video",
            "videos_response.json",
            {"channel_handle": "framasoft_videos"},
            "videos",
        ),
        ("on_new_channel", "channels_response.json", {}, "channels"),
    ],
)
async def test_cpy_complete_published_list_examples(
    monkeypatch, operation, fixture, values, key
):
    body = json.loads((FIXTURES / fixture).read_text())
    instance = node(operation, **values)
    state = {"seen_ids": []}

    async def update(mutator, **kwargs):
        nonlocal state
        new_state, result = mutator(state)
        if new_state is not None:
            state = new_state
        return result

    async def request(*args, **kwargs):
        return body

    monkeypatch.setattr(instance, "_request", request)
    monkeypatch.setattr(instance, "_update_node_state", update)
    output = await instance.execute({})
    assert output[key] == body["data"]
    assert instance.trigger_emitted_event(output)
    assert instance.resolve_agent_event(output)["text"]
    assert (await instance.execute({}))[key] == []
    if key == "videos":
        assert (
            instance._video_reference(body["data"][0])
            == "a65bc12f-9383-462e-81ae-8207e8b434ee"
        )


@pytest.mark.asyncio
async def test_cpy_account_evidence_accepts_published_array_and_user_object(
    monkeypatch,
):
    published = json.loads((FIXTURES / "my_account_response.json").read_text())
    for body in (published, published[0]):

        async def request(*args, **kwargs):
            return body

        monkeypatch.setattr(PeerTubeNode, "_request", staticmethod(request))
        output = await node("get_my_account").execute({})
        assert output["username"] == "chocobozzz"
        assert output["id"] == 42
