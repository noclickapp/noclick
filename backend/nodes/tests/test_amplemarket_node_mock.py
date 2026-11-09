"""Published Amplemarket examples exercised through the real node factory."""
import json
from pathlib import Path
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest
from nodes import amplemarket_node as am
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation

AUTH = {"credential_type": "amplemarket_api_key", "api_key": "amplemarket-fixture-secret"}
USER = "00000000-0000-4000-8000-000000000001"
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/amplemarket/responses.json").read_text())


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def wire(monkeypatch):
    requests, replies = [], []
    async def send(request):
        requests.append(request)
        assert request.url.host == "api.amplemarket.com"
        assert request.headers["Authorization"] == "Bearer " + AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        status, payload = replies.pop(0)
        return httpx.Response(status) if payload is None else httpx.Response(status, json=payload)
    native = httpx.AsyncClient
    monkeypatch.setattr(am.httpx, "AsyncClient", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None, auth=None):
    return await run_node_operation(node_type="automation-amplemarket", operation=operation,
        arguments=arguments or {}, credential_data=deepcopy(auth or AUTH), user_id=USER)


CASES = {
    "get_account_info": {}, "list_users": {},
    "find_person": {"email": "person@example.com", "reveal_email": True},
    "find_company": {"domain": "amplemarket.com"},
    "list_lead_lists": {},
    "create_lead_list": {"name": "Prospects", "shared": False, "owner": "owner@example.com", "type": "email", "leads": [{"email": "prospect@example.com"}]},
    "get_lead_list": {"lead_list_id": "list-1"},
    "add_leads_to_list": {"lead_list_id": "list-1", "leads": [{"email": "prospect@example.com"}]},
    "list_contacts": {"ids": ["contact-1", "contact-2"]},
    "create_contact": {"email": "prospect@example.com", "first_name": "Ada", "phone_numbers": [{"number": "+123456789", "kind": "mobile"}]},
    "get_contact": {"contact_id": "contact-1"},
    "get_contact_by_email": {"email": "ada+sales@example.com"},
    "list_accounts": {"tags": ["sales", "prospect"]}, "get_account": {"account_id": "account-1"},
    "list_sequences": {},
    "add_leads_to_sequence": {"sequence_id": "sequence-1", "leads": [{"email": "prospect@example.com", "data": {"nickname": "Ada"}}]},
    "list_tasks": {"user_id": "user-1", "automatic": False},
    "complete_task": {"task_id": "task-1", "set_lead_to_completed": True},
    "skip_task": {"task_id": "task-1"},
    "list_excluded_emails": {},
    "create_email_exclusions": {"excluded_emails": [{"email": "excluded@example.com"}]},
    "delete_email_exclusions": {"excluded_emails": [{"email": "excluded@example.com"}]},
    "list_calls": {"start_date_from": "2026-09-09T00:00:00Z"},
    "log_call": {"from_number": "+123456789", "to_number": "+198765432", "duration": 42, "answered": True, "human": True, "task_id": "00000000-0000-4000-8000-000000000001", "user_id": USER},
}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CASES)
async def test_published_examples_and_exact_wire(wire, operation):
    requests, replies = wire
    example = EXAMPLES.get(operation, {"status": 200, "body": None})  # Task acknowledgements document no response body.
    replies.append((example["status"], example["body"]))
    result = await run(operation, CASES[operation])
    assert result == {"status": "success", "data": example["body"]}
    request = requests[0]
    op = am.OPERATIONS[operation]
    assert request.method == op["method"]
    path = op["path"]
    from urllib.parse import quote
    for field, marker in op["path_fields"].items():
        path = path.replace("{" + marker + "}", quote(CASES[operation][field], safe=""))
    assert request.url.raw_path.split(b"?")[0] == path.encode()
    if operation == "log_call":
        assert json.loads(request.content)["from"] == "+123456789"
        assert "from_number" not in json.loads(request.content)
    if operation == "list_contacts":
        assert request.url.params.get_list("ids[]") == ["contact-1", "contact-2"]
    if operation == "list_accounts":
        assert request.url.params.get_list("tags[]") == ["sales", "prospect"]
    if operation == "list_tasks":
        assert request.url.params["automatic"] == "false"
    if operation == "create_contact":
        assert json.loads(request.content)["phone_numbers"][0]["kind"] == "mobile"
    if operation == "add_leads_to_sequence":
        assert json.loads(request.content)["leads"][0]["data"] == {"nickname": "Ada"}
    assert replies == []


@pytest.mark.asyncio
async def test_provider_rejection_and_redirect_never_retries(wire):
    requests, replies = wire
    replies.append((401, {"message": "Unauthorized"}))
    with pytest.raises(ValueError, match="401.*Unauthorized"):
        await run("get_account_info")
    replies.append((302, {"message": AUTH["api_key"]}))
    with pytest.raises(ValueError) as error:
        await run("get_account_info")
    assert AUTH["api_key"] not in str(error.value)
    assert len(requests) == 2


@pytest.mark.parametrize("bad", ["../tasks", "a/b", "a%2fb", "a?foo=bar", "https://evil.example"])
def test_path_inputs_refused(bad):
    with pytest.raises(ValueError):
        am.AmplemarketGetContactConfig(contact_id=bad)


def test_manual_api_key_defaults_and_shaping():
    assert am.AmplemarketAPIKeyCredential(api_key="  fixture-secret  ").model_dump() == {"credential_type": "amplemarket_api_key", "api_key": "fixture-secret"}
    for bad in ["Bearer token", "https://example.com/key", "<token>"]:
        with pytest.raises(ValueError):
            am.AmplemarketAPIKeyCredential(api_key=bad)


@pytest.mark.asyncio
async def test_poll_pagination_dedup_and_agent_event(wire, monkeypatch):
    requests, replies = wire
    body = deepcopy(EXAMPLES["list_calls"]["body"])
    rows = body["calls"]
    row = deepcopy(rows[0]); row["id"] = "new-call"
    first = {"calls": rows, "_links": {"next": {"href": "/calls?page[after]=next-page"}}}
    replies.extend([(200, first), (200, {"calls": [row]})])
    node = NodeFactory.create_node(node_id="amplemarket-poll", node_type="automation-amplemarket",
        node_data={"config": {"operation": "on_new_call", "user_id": "user-1", "start_date_from": "2026-09-01T00:00:00Z"}, "credentials": AUTH})
    seen = {r["id"] for r in rows}
    async def unseen(items, key):
        fresh = [item for item in items if key(item) not in seen]
        seen.update(key(item) for item in items)
        return fresh
    monkeypatch.setattr(node, "_filter_unseen", unseen)
    result = await node.execute({})
    assert result == {"calls": [row], "new_call_count": 1}
    assert requests[1].url.params["page[after]"] == "next-page"
    assert requests[1].url.params["user_id"] == "user-1"
    assert requests[1].url.params["start_date_from"] == "2026-09-01T00:00:00Z"
    assert node.should_propagate_output(result, {"operation": "on_new_call"})
    event = node.resolve_agent_event(result)
    assert "new-call" in event["text"] and row["from"] in event["text"] and row["to"] in event["text"]
    replies.append((200, {"calls": [row]}))
    assert await node.execute({}) == {"calls": [], "new_call_count": 0}
    assert node.resolve_agent_event({"calls": []}) is None
    assert not node.should_propagate_output({"new_call_count": 0}, {"operation": "on_new_call"})


@pytest.mark.asyncio
@pytest.mark.parametrize("href", ["https://evil.example/calls?page[after]=x", "/contacts?page[after]=x", "/calls?page[before]=x"])
async def test_poll_refuses_foreign_pagination_before_seen_mutation(wire, monkeypatch, href):
    _, replies = wire
    body = deepcopy(EXAMPLES["list_calls"]["body"])
    body["_links"] = {"next": {"href": href}}
    replies.append((200, body))
    node = NodeFactory.create_node(node_id="poll", node_type="automation-amplemarket",
        node_data={"config": {"operation": "on_new_call"}, "credentials": AUTH})
    unseen = AsyncMock(); monkeypatch.setattr(node, "_filter_unseen", unseen)
    with pytest.raises(ValueError):
        await node.execute({})
    unseen.assert_not_called()
