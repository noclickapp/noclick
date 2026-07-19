"""GitHub hook registration idempotency (2026-07-19): rapid operation flips
raced the debounced config mirror, so stale-hook cleanup keyed on a remembered
id orphaned one live hook PER change — three hooks pointing at the same
webhook URL. Registration now sweeps every hook on OUR url before creating,
converging to exactly one regardless of interleaving. Plus: a malformed
(non-dict) node config in a delivery scan must skip loudly, not 500 every
webhook in the workflow (GitHub pings all failed on a transient list config)."""
from unittest.mock import AsyncMock, patch

import pytest

from nodes.github_rest_node import GithubRestNode

pytestmark = pytest.mark.asyncio


def _cred():
    return {"access_token": "tok"}


async def test_register_sweeps_every_hook_on_our_url(monkeypatch):
    listed = [
        {"id": 1, "config": {"url": "https://abc.hooks.example.test"}},   # ours (older op)
        {"id": 2, "config": {"url": "https://abc.hooks.example.test/"}},  # ours, trailing slash
        {"id": 3, "config": {"url": "https://other.hooks.example.test"}}, # different node — untouched
        {"id": 4, "config": {}},                                   # foreign hook, no url
    ]
    deleted = []
    monkeypatch.setattr(
        "nodes.github_rest_node.list_github_webhooks",
        AsyncMock(return_value=listed),
    )

    async def fake_unregister(token, owner, repo, hook_id):
        deleted.append(hook_id)

    monkeypatch.setattr("nodes.github_rest_node.unregister_github_webhook", fake_unregister)
    monkeypatch.setattr(
        "nodes.github_rest_node.register_github_webhook", AsyncMock(return_value=99)
    )

    result = await GithubRestNode._register_external_webhook(
        webhook_url="https://abc.hooks.example.test",
        credential=_cred(),
        config={"repository": "o/r", "operation": "on_issue_closed"},
        node_id="n1",
    )
    assert deleted == [1, 2], "exactly OUR url's hooks are swept"
    assert result["external_webhook_id"] == 99


async def test_sweep_failure_falls_back_to_remembered_id(monkeypatch):
    monkeypatch.setattr(
        "nodes.github_rest_node.list_github_webhooks",
        AsyncMock(side_effect=RuntimeError("403")),
    )
    deleted = []

    async def fake_unregister(token, owner, repo, hook_id):
        deleted.append(hook_id)

    monkeypatch.setattr("nodes.github_rest_node.unregister_github_webhook", fake_unregister)
    monkeypatch.setattr(
        "nodes.github_rest_node.register_github_webhook", AsyncMock(return_value=99)
    )

    await GithubRestNode._register_external_webhook(
        webhook_url="https://abc.hooks.example.test",
        credential=_cred(),
        config={"repository": "o/r", "operation": "on_issue_closed",
                "external_webhook_id": 42},
        node_id="n1",
    )
    assert deleted == [42]


async def test_register_still_registers_when_no_stale_hooks(monkeypatch):
    monkeypatch.setattr(
        "nodes.github_rest_node.list_github_webhooks", AsyncMock(return_value=[])
    )
    unregister = AsyncMock()
    monkeypatch.setattr("nodes.github_rest_node.unregister_github_webhook", unregister)
    monkeypatch.setattr(
        "nodes.github_rest_node.register_github_webhook", AsyncMock(return_value=7)
    )
    result = await GithubRestNode._register_external_webhook(
        webhook_url="https://abc.hooks.example.test",
        credential=_cred(),
        config={"repository": "o/r", "operation": "on_issue_closed"},
        node_id="n1",
    )
    assert unregister.await_count == 0
    assert result["external_webhook_id"] == 7


def test_delivery_scan_tolerates_malformed_node_config():
    from utils.webhook_routes import _get_node_type_for_webhook, _is_node_disabled, _node_cfg

    workflow = {"nodes": [
        {"id": "bad", "type": "x", "config": ["not", "a", "dict"]},   # the 2026-07-19 shape
        {"id": "worse", "type": "x", "config": "nope"},
        {"id": "good", "type": "trigger-webhook", "config": {"webhook_id": "wh-1"}},
    ]}
    # The scan skips malformed nodes and still finds the real trigger.
    assert _get_node_type_for_webhook(workflow, "wh-1") == ("trigger-webhook", "good")
    assert _node_cfg(workflow["nodes"][0]) == {}
    assert _node_cfg(workflow["nodes"][1]) == {}
    assert _node_cfg("not-a-node") == {}
    assert _is_node_disabled({"id": "bad", "config": []}) is False
