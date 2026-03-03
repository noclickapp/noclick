from datetime import datetime, timezone, timedelta

import pytest

from nodes.instagram_node import (
    InstagramNode,
    InstagramNodeConfig,
    InstagramOAuthCredential,
    InstagramGetProfileConfig,
)


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = ""
        self.headers = {}

    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_instagram_oauth_uses_facebook_graph_base(monkeypatch):
    captured = {}

    async def _fake_request(self, method, url, params=None, json=None):  # noqa: ARG001
        captured["url"] = url
        return _FakeResponse(200, {"id": "1784", "username": "demo"})

    monkeypatch.setattr("httpx.AsyncClient.request", _fake_request)

    creds = InstagramOAuthCredential(
        access_token="EAABfakeToken",
        instagram_user_id="17841400000000000",
        expires_at=(datetime.now(timezone.utc) + timedelta(days=10)).isoformat(),
        instagram_username="demo",
    )
    cfg = InstagramNodeConfig(
        config=InstagramGetProfileConfig(),
        credentials=creds,
    )
    node = InstagramNode(
        node_id="ig-1",
        node_type="automation-instagram",
        node_data={},
        config=cfg,
        sio=None,
        sid=None,
        workflow_id="wf-1",
    )

    result = await node.execute({})

    assert result["status"] == "success"
    assert captured["url"].startswith("https://graph.facebook.com/v21.0/")

