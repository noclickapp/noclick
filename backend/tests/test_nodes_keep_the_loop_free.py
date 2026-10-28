"""Node operations run on the api container's event loop (agent tools, hosted MCP
links, runs): a sync wait or round trip inside one freezes every request there."""

import threading

import httpx
import pytest
import respx

from nodes.core.registry import NODE_REGISTRY, NodeFactory
from tests.loop_watch import longest_loop_gap


@pytest.mark.asyncio
@respx.mock
async def test_a_typeform_rate_limit_is_waited_out_without_holding_the_loop():
    from nodes.typeform_node import TYPEFORM_API_BASE

    route = respx.get(f"{TYPEFORM_API_BASE}/forms").mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "1"}),
        httpx.Response(200, json={"items": []}),
    ])
    node = object.__new__(NODE_REGISTRY["automation-typeform"])

    result, longest_gap = await longest_loop_gap(node._make_request("GET", "/forms", "token"))

    assert route.call_count == 2, "the request is retried once the wait is over"
    assert result == {"items": []}
    assert longest_gap < 0.5, f"the event loop stopped answering for {longest_gap:.1f}s"


@pytest.mark.asyncio
async def test_an_r2_poll_lists_the_bucket_off_the_loop(monkeypatch):
    import boto3

    listed_on = []

    class FakeS3:
        def list_objects_v2(self, **kwargs):
            listed_on.append(threading.current_thread())
            return {"Contents": [{"Key": "a.txt", "Size": 1}]}

    monkeypatch.setattr(boto3, "client", lambda *a, **k: FakeS3())
    node = NodeFactory.create_node(
        node_id="r2-1",
        node_type="automation-cloudflare",
        node_data={"config": {"operation": "cloudflare_r2_new_object", "account_id": "acct", "bucket_name": "b",
                              "r2_access_key_id": "k", "r2_secret_access_key": "s"}},
        sio=None, sid=None, workflow_id="wf", user_id="u",
    )

    async def every_item_is_new(items, id_fn):
        return items

    monkeypatch.setattr(node, "_filter_unseen", every_item_is_new)

    result = await node._trigger_r2_new_object()

    assert [item["key"] for item in result["result"]] == ["a.txt"]
    assert listed_on and listed_on[0] is not threading.main_thread(), "the bucket was listed on the event loop"
