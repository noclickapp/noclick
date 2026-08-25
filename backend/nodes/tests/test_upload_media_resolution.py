"""Verifies upload nodes route their media field through resolve_media_input,
so a resource_id / URL / base64 all work (not just the legacy input)."""

import base64

import pytest

from nodes.core.media_resolver import ResolvedMedia


def _make_node(cls, node_type):
    return cls(node_id="n", node_type=node_type, node_data={}, config=None)


async def test_twitter_upload_resolves_media_input(monkeypatch):
    from nodes.twitter_node import TwitterNode, TwitterUploadMediaConfig

    async def fake_resolve(value, **kwargs):
        assert value == "res-abc"  # the config value is passed through
        return ResolvedMedia(b"IMGBYTES", "image/png", "x.png")

    monkeypatch.setattr("nodes.core.media_resolver.resolve_media_input", fake_resolve)

    captured = {}

    async def fake_make_request(method, path, creds, **kwargs):
        captured["body"] = kwargs.get("json_body")
        return {"status": "success"}

    node = _make_node(TwitterNode, "automation-twitter")
    monkeypatch.setattr(node, "_make_request", fake_make_request)

    config = TwitterUploadMediaConfig(media_data="res-abc", media_type="image/png")
    await node._upload_media(config, credentials=None)

    # The resolved bytes (not the literal "res-abc") were uploaded.
    assert captured["body"]["media_data"] == base64.b64encode(b"IMGBYTES").decode()


async def test_telegram_resource_id_becomes_presigned_url(monkeypatch):
    from nodes.telegram_node import TelegramNode

    monkeypatch.setattr("nodes.core.media_resolver.is_resource_id", lambda v: v == "res-1")

    async def fake_resolve(value, **kwargs):
        return ResolvedMedia(b"x", "video/mp4", "v.mp4", download_url="https://r2.test/presigned")

    monkeypatch.setattr("nodes.core.media_resolver.resolve_media_input", fake_resolve)

    node = _make_node(TelegramNode, "automation-telegram")
    # A resource_id resolves to a fetchable URL; a plain URL / file_id passes through.
    assert await node._resolve_media_ref("res-1") == "https://r2.test/presigned"
    assert await node._resolve_media_ref("https://example.com/a.jpg") == "https://example.com/a.jpg"
    assert await node._resolve_media_ref("BAACAgQAAxk_file_id") == "BAACAgQAAxk_file_id"
