"""Exercise the native Linode factory against a fixture HTTP transport.

These tests check exact methods, parent paths, bodies, pagination and error
behavior without making provider requests or requiring a real token.
"""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import linode_node as node
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {"credential_type": "linode_personal_access_token", "access_token": "fixture-linode-token"}
CASES = json.loads((Path(__file__).parent / "fixtures/linode/operations.json").read_text())


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        assert request.url.host == "api.linode.com"
        assert request.headers["Authorization"] == "Bearer " + AUTH["access_token"]
        assert AUTH["access_token"] not in str(request.url)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        code, payload = reply
        return httpx.Response(code, json=payload)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(node, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, config=None):
    return await run_node_operation(node_type="automation-linode", operation=operation,
        arguments=config or {}, credential_data=deepcopy(AUTH),
        user_id="00000000-0000-4000-8000-000000000001")


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["operation"])
async def test_linode_all_operations(transport, case):
    requests, replies = transport
    replies.append((200, case["response"]))
    result = await run(case["operation"], case["config"])
    assert result["status"] == "success"
    assert len(requests) == 1 and not replies
    request = requests[0]
    assert request.method == case["method"] and request.url.path == "/v4" + case["path"]
    assert dict(request.url.params) == case.get("query", {})
    assert (json.loads(request.content) if request.content else None) == case.get("body")
    if case["operation"].startswith("list_"):
        assert result["data"] == case["response"]["data"]
        assert result["next_page"] is None
    if case["operation"] in {"boot_instance", "shutdown_instance", "reboot_instance"}:
        assert result["accepted"] is True and result["completed"] is False
    if case["method"] == "DELETE":
        assert result["deletion_acknowledged"] is True


async def test_linode_continuation_and_last_page(transport):
    requests, replies = transport
    replies.append((200, {"data": [{"id": 123}], "page": 2, "pages": 3, "results": 51}))
    result = await run("list_instances", {"page": 2, "page_size": 25})
    assert result["next_page"] == 3
    assert dict(requests[0].url.params) == {"page": "2", "page_size": "25"}
    replies.append((200, {"data": [], "page": 1, "pages": 0, "results": 0}))
    assert (await run("list_instances"))["next_page"] is None


@pytest.mark.parametrize("code", [401, 403, 404, 429, 500])
async def test_linode_provider_error_is_not_success_and_no_retry(transport, code):
    requests, replies = transport
    replies.append((code, {"errors": [{"reason": "Rejected fixture-linode-token", "field": "token"}]}))
    result = await run("get_profile")
    assert result["success"] is False and result["http_status"] == code
    assert result["message"] == "Rejected [redacted]"
    assert len(requests) == 1


async def test_linode_200_error_envelope(transport):
    _, replies = transport
    replies.append((200, {"errors": [{"reason": "Not allowed"}]}))
    assert (await run("get_profile"))["status"] == "error"


async def test_linode_transport_failure_write_is_unknown(transport):
    requests, replies = transport
    replies.append(httpx.ReadTimeout("fixture"))
    result = await run("create_instance", {"region": "us-east", "type": "g6-standard-2"})
    assert result["status"] == "unknown" and result["success"] is False
    assert len(requests) == 1


async def test_linode_redacts_password_and_token_from_provider_output(transport):
    _, replies = transport
    replies.append((200, {"id": 123, "root_pass": "not-shown", "nested": {"value": "fixture-root-password", "token": "fixture-linode-token"}}))
    result = await run("create_instance", {"region": "us-east", "type": "g6-standard-2", "image": "linode/debian9", "root_pass": "fixture-root-password"})
    assert "fixture-root-password" not in json.dumps(result)
    assert "fixture-linode-token" not in json.dumps(result)
    assert "root_pass" not in json.dumps(result)


@pytest.mark.parametrize("payload", [[], {"data": {}}, {"data": [], "page": "1", "pages": 1}])
async def test_linode_malformed_list_rejected(transport, payload):
    _, replies = transport
    replies.append((200, payload))
    with pytest.raises(ValueError):
        await run("list_instances")


async def test_linode_profile_requires_identity(transport):
    _, replies = transport
    replies.append((200, {}))
    with pytest.raises(ValueError):
        await run("get_profile")


@pytest.mark.parametrize("operation,config", [
    ("get_instance", {"linode_id": -1}),
    ("get_domain", {"domain_id": "../profile"}),
    ("list_instances", {"page_size": 24}),
    ("update_instance", {"linode_id": 123}),
    ("create_instance", {"region": "us-east", "type": "g6-standard-2", "image": "linode/debian9"}),
    ("create_instance", {"region": "us-east", "type": "g6-standard-2", "label": "bad--label"}),
    ("create_record", {"domain_id": 1234, "type": "A", "target": "::1"}),
    ("create_record", {"domain_id": 1234, "type": "CNAME", "target": "example.org"}),
    ("create_record", {"domain_id": 1234, "type": "TXT", "target": "text", "priority": 1}),
    ("update_record", {"domain_id": 1234, "record_id": 123456}),
])
async def test_linode_invalid_inputs_never_reach_network(transport, operation, config):
    requests, _ = transport
    with pytest.raises(ValueError):
        await run(operation, config)
    assert not requests


def test_linode_manual_token_default_and_shaping():
    assert node.LinodeTokenCredential(access_token="  fixture-linode-token  ").access_token == "fixture-linode-token"
    assert node.LinodeTokenCredential.model_fields["credential_type"].default == AUTH["credential_type"]
    for token in ("https://cloud.linode.com", "Bearer token", "<token>", "bad\ntoken"):
        with pytest.raises(ValueError):
            node.LinodeTokenCredential(access_token=token)


async def test_linode_connection_evidence_names_the_current_user(transport):
    from nodes.core.connection_evidence import collect_evidence
    _, replies = transport
    replies.append((200, {"username": "exampleUser", "email": "example-user@gmail.com"}))
    evidence = await collect_evidence(node_type="automation-linode",
        credential_data=AUTH, user_id="00000000-0000-4000-8000-000000000001", pool=None)
    assert evidence.reachable is True
    assert evidence.account_label == "exampleUser"


EVENT_EXAMPLE = json.loads((Path(__file__).parent / "fixtures/linode/events.json").read_text())["body"]


def poll_node(operation="on_new_event", **fields):
    config = {"operation": operation, **fields}
    instance = node.LinodeNode(node_id="linode-poll", node_type="automation-linode",
        node_data={"config": config}, config=node.LinodeNodeConfig(config=config, credentials=AUTH))
    state = {}

    async def update(mutator, **kwargs):
        new_state, result = mutator(deepcopy(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result

    instance._update_node_state = update
    instance.emit = AsyncMock()
    return instance, state


@pytest.mark.parametrize("operation", ["on_new_event", "on_event_finished"])
async def test_linode_trigger_baselines_then_emits_documented_event_once(transport, operation):
    requests, replies = transport
    instance, state = poll_node(operation)
    empty = {"data": [], "page": 1, "pages": 0, "results": 0}
    replies.extend([(200, empty), (200, deepcopy(EVENT_EXAMPLE)), (200, deepcopy(EVENT_EXAMPLE))])
    baseline = await instance.execute({})
    assert baseline["event_count"] == 0 and "seen_ids" in state
    assert instance.trigger_produced_no_event(baseline)
    result = await instance.execute({})
    assert result["events"] == EVENT_EXAMPLE["data"] and result["event_count"] == 1
    assert instance.trigger_emitted_event(result)
    assert instance.should_propagate_output(result, {"operation": operation})
    text = instance.resolve_agent_event(result)["text"]
    for value in ("adevi", "ticket_create", "failed", "Problem booting my Linode", "11111", "123", "/v4/support/tickets/11111"):
        assert value in text
    duplicate = await instance.execute({})
    assert duplicate["events"] == [] and instance.resolve_agent_event(duplicate) is None
    assert not instance.should_propagate_output(duplicate, {"operation": operation})
    for request in requests:
        assert request.url.path == "/v4/account/events"
        assert dict(request.url.params) == {"page": "1", "page_size": "500"}
        assert json.loads(request.headers["X-Filter"]) == {"+order_by": "created", "+order": "desc"}


async def test_linode_trigger_initial_history_is_not_replayed(transport):
    _, replies = transport
    instance, _ = poll_node()
    replies.extend([(200, deepcopy(EVENT_EXAMPLE)), (200, deepcopy(EVENT_EXAMPLE))])
    assert (await instance.execute({}))["events"] == []
    assert (await instance.execute({}))["events"] == []


async def test_linode_finished_trigger_detects_status_transition(transport):
    _, replies = transport
    instance, _ = poll_node("on_event_finished")
    pending = deepcopy(EVENT_EXAMPLE)
    pending["data"][0]["status"] = "started"
    replies.extend([(200, pending), (200, deepcopy(EVENT_EXAMPLE)), (200, deepcopy(EVENT_EXAMPLE))])
    assert (await instance.execute({}))["events"] == []
    assert (await instance.execute({}))["events"] == EVENT_EXAMPLE["data"]
    assert (await instance.execute({}))["events"] == []


async def test_linode_trigger_pages_before_updating_state(transport):
    requests, replies = transport
    instance, state = poll_node(action="ticket_create")
    first = deepcopy(EVENT_EXAMPLE)
    first.update(pages=2, results=2)
    second = deepcopy(EVENT_EXAMPLE)
    second.update(page=2, pages=2, results=2)
    second["data"][0]["id"] = 122
    replies.extend([(200, first), (200, second)])
    assert (await instance.execute({}))["events"] == []
    assert state["seen_ids"] == ["122", "123"]
    assert [r.url.params["page"] for r in requests] == ["1", "2"]
    assert json.loads(requests[0].headers["X-Filter"])["action"] == "ticket_create"
    before = deepcopy(state)
    replies.extend([(200, first), (429, {"errors": [{"reason": "rate limited"}]})])
    with pytest.raises(ValueError, match="HTTP 429"):
        await instance.execute({})
    assert state == before


async def test_linode_trigger_scope_change_rebaselines(transport):
    _, replies = transport
    instance, _ = poll_node(action="linode_boot")
    replies.append((200, deepcopy(EVENT_EXAMPLE)))
    assert (await instance.execute({}))["events"] == []
    instance._config = node.LinodeNodeConfig(config={"operation": "on_new_event", "action": "ticket_create"}, credentials=AUTH)
    replies.append((200, deepcopy(EVENT_EXAMPLE)))
    assert (await instance.execute({}))["events"] == []


@pytest.mark.parametrize("payload", [{"data": {}, "page": 1, "pages": 1},
    {"data": [{"id": 123}], "page": 1, "pages": 1},
    {"data": [], "page": 2, "pages": 2}])
async def test_linode_trigger_rejects_bad_response_without_baselining(transport, payload):
    _, replies = transport
    instance, state = poll_node()
    replies.append((200, payload))
    with pytest.raises(ValueError):
        await instance.execute({})
    assert state == {}


async def test_linode_trigger_refuses_truncated_history(transport):
    _, replies = transport
    instance, state = poll_node()
    for page in range(1, 21):
        replies.append((200, {"data": [], "page": page, "pages": 21, "results": 10001}))
    with pytest.raises(ValueError, match="10,000"):
        await instance.execute({})
    assert state == {}


async def test_linode_trigger_deduplicates_overlapping_pages(transport):
    _, replies = transport
    instance, state = poll_node()
    state.update(seen_ids=[])
    first = deepcopy(EVENT_EXAMPLE)
    first.update(pages=2, results=2)
    second = deepcopy(first)
    second["page"] = 2
    replies.extend([(200, first), (200, second)])
    result = await instance.execute({})
    assert result["events"] == EVENT_EXAMPLE["data"] and result["event_count"] == 1
