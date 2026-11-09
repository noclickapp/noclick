"""Native Desk operations with captured HTTP, without a live account."""
import json
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import teamwork_desk_node as desk
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {
    "credential_type": "teamwork_desk_api_key",
    "api_key": "desk-fixture-key",
    "site_url": "https://fixture.teamwork.com",
}
USER = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, responses = [], []
    monkeypatch.setattr(
        ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"])
    )

    async def handle(request):
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer desk-fixture-key"
        assert request.url.host == "fixture.teamwork.com"
        assert AUTH["api_key"] not in str(request.url)
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        status, body = response
        return httpx.Response(status, json=body)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(
        desk,
        "guarded_async_client",
        lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(handle)),
    )
    return requests, responses


async def run(operation, config=None, auth=AUTH):
    return await run_node_operation(
        node_type="automation-teamwork-desk",
        operation=operation,
        arguments=config or {},
        credential_data=deepcopy(auth),
        user_id=USER,
    )


# Provider paths and write envelopes pinned independently of the request table.
CASES = [
    ("list_tickets", {}, "GET", "/tickets.json", "tickets", None),
    ("get_ticket", {"ticket_id": 7}, "GET", "/tickets/7.json", "ticket", None),
    (
        "create_ticket",
        {
            "subject": "Support request",
            "message": "Please help",
            "customer": {"id": 2},
            "inbox": {"id": 3},
        },
        "POST",
        "/tickets.json",
        "ticket",
        {
            "subject": "Support request",
            "message": "Please help",
            "customer": {"id": 2},
            "inbox": {"id": 3},
            "notifyCustomer": False,
        },
    ),
    (
        "update_ticket",
        {
            "ticket_id": 7,
            "ticket": {"status": {"id": 2}, "agent": {"id": 4}, "tags": [{"id": 8}]},
        },
        "PATCH",
        "/tickets/7.json",
        "ticket",
        {"ticket": {"status": {"id": 2}, "agent": {"id": 4}, "tags": [{"id": 8}]}},
    ),
    (
        "list_messages",
        {"ticket_id": 7},
        "GET",
        "/tickets/7/messages.json",
        "messages",
        None,
    ),
    (
        "reply_to_ticket",
        {"ticket_id": 7, "message": "We can help"},
        "POST",
        "/tickets/7/messages.json",
        "ticket",
        {"message": "We can help", "isDraft": False},
    ),
]
for plural, singular in [
    ("customers", "customer"),
    ("companies", "company"),
    ("tags", "tag"),
]:
    data = (
        {"firstName": "Joe", "email": "joe@example.test"}
        if singular == "customer"
        else {"name": "Support"}
    )
    CASES.extend(
        [
            ("list_" + plural, {}, "GET", f"/{plural}.json", plural, None),
            (
                "get_" + singular,
                {singular + "_id": 7},
                "GET",
                f"/{plural}/7.json",
                singular,
                None,
            ),
            (
                "create_" + singular,
                {singular: data},
                "POST",
                f"/{plural}.json",
                singular,
                data if singular == "company" else {singular: data},
            ),
            (
                "update_" + singular,
                {singular + "_id": 7, singular: data},
                "PATCH",
                f"/{plural}/7.json",
                singular,
                {singular: data},
            ),
        ]
    )
CASES.extend(
    [
        ("list_inboxes", {}, "GET", "/inboxes.json", "inboxes", None),
        ("get_inbox", {"inbox_id": 7}, "GET", "/inboxes/7.json", "inbox", None),
        ("list_users", {}, "GET", "/users.json", "users", None),
        (
            "list_ticket_statuses",
            {},
            "GET",
            "/ticketstatuses.json",
            "ticketstatuses",
            None,
        ),
        (
            "list_ticket_priorities",
            {},
            "GET",
            "/ticketpriorities.json",
            "ticketpriorities",
            None,
        ),
    ]
)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,envelope,body", CASES)
async def test_native_wire_contract(
    transport, operation, config, method, path, envelope, body
):
    requests, responses = transport
    listed = operation.startswith("list_")
    row = {"id": 7, "name": "Support"}
    payload = {envelope: [row] if listed else row}
    if listed:
        payload["pagination"] = {"page": 1, "pageSize": 20, "hasMorePages": True}
    responses.append((201 if operation == "reply_to_ticket" else 200, payload))
    result = await run(operation, config)
    assert result["status"] == "success"
    assert result[envelope] == payload[envelope]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.path == "/desk/api/v2" + path
    assert (json.loads(request.content) if request.content else None) == body
    if listed:
        assert dict(request.url.params) == {"page": "1", "pageSize": "20"}
        assert result["pagination"]["hasMorePages"] is True


@pytest.mark.asyncio
async def test_page_two_and_account_evidence(transport):
    requests, responses = transport
    responses.append(
        (
            200,
            {
                "inboxes": [{"id": 5, "name": "Billing"}],
                "pagination": {"page": 2, "hasMorePages": False},
            },
        )
    )
    result = await run("list_inboxes", {"page": 2, "page_size": 10})
    assert requests[0].url.params["page"] == "2"
    assert requests[0].url.params["pageSize"] == "10"
    assert result["items"] == [{"id": 5, "name": "Billing"}]
    assert desk.TeamworkDeskNode.connection_evidence.operation == "list_inboxes"


@pytest.mark.parametrize(
    "site",
    [
        "http://fixture.teamwork.com",
        "https://teamwork.com.attacker.test",
        "https://a.teamwork.com:444",
        "https://a@fixture.teamwork.com",
        "https://127.0.0.1",
        "https://a.b.teamwork.com",
    ],
)
def test_reject_untrusted_sites(site):
    with pytest.raises(ValueError):
        desk.TeamworkDeskAPIKeyCredential.model_validate({**AUTH, "site_url": site})


def test_manual_credential_and_eu_site():
    shaped = desk.TeamworkDeskAPIKeyCredential(
        api_key="  fixture-key  ",
        site_url="https://ACME.eu.teamwork.com/desk/tickets/7",
    )
    assert shaped.site_url == "https://acme.eu.teamwork.com"
    assert shaped.api_key == "fixture-key"
    assert shaped.credential_type == "teamwork_desk_api_key"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,payload",
    [
        (401, {"message": "Rejected desk-fixture-key"}),
        (429, {"message": "Rate limited"}),
        (302, {}),
        (200, {"errors": ["No access"]}),
        (200, {"ticket": []}),
    ],
)
async def test_errors_never_become_success(transport, status, payload):
    requests, responses = transport
    responses.append((status, payload))
    with pytest.raises(ValueError) as error:
        await run("get_ticket", {"ticket_id": 7})
    assert AUTH["api_key"] not in str(error.value)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_write_timeout_is_not_retried(transport):
    requests, responses = transport
    responses.append(httpx.ReadTimeout("timeout"))
    with pytest.raises(ValueError, match="outcome is unknown"):
        await run("reply_to_ticket", {"ticket_id": 7, "message": "Reply"})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_draft_reply_and_minimal_patch_do_not_send_unset_fields(transport):
    requests, responses = transport
    responses.extend([(201, {"ticket": {"id": 7}}), (200, {"ticket": {"id": 7}})])
    await run("reply_to_ticket", {"ticket_id": 7, "message": "Draft", "isDraft": True})
    await run("update_ticket", {"ticket_id": 7, "ticket": {"priority": {"id": 9}}})
    assert json.loads(requests[0].content) == {"message": "Draft", "isDraft": True}
    assert json.loads(requests[1].content) == {"ticket": {"priority": {"id": 9}}}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,config",
    [
        ("get_ticket", {"ticket_id": -1}),
        ("update_ticket", {"ticket_id": 7, "ticket": {}}),
        ("list_tickets", {"page": 0}),
        ("create_company", {"company": {}}),
    ],
)
async def test_invalid_inputs_fail_before_http(transport, operation, config):
    requests, _ = transport
    with pytest.raises(ValueError):
        await run(operation, config)
    assert requests == []


@pytest.mark.asyncio
async def test_ticket_search_serializes_documented_array_queries(transport):
    requests, responses = transport
    responses.append((200, {"tickets": []}))
    result = await run(
        "search_tickets",
        {"search": "Support", "inboxes": [2, 3], "exact": False, "tags": []},
    )
    assert result["tickets"] == []
    assert requests[0].url.path == "/desk/api/v2/search/tickets.json"
    assert requests[0].url.params["inboxes"] == "2,3"
    assert requests[0].url.params["exact"] == "false"
    assert requests[0].url.params["search"] == "Support"
    assert "tags" not in requests[0].url.params


@pytest.mark.asyncio
async def test_provider_published_customer_response(transport):
    from pathlib import Path

    fixture = json.loads(
        (Path(__file__).parent / "fixtures/teamwork-desk/customers.json").read_text()
    )
    requests, responses = transport
    responses.append((200, fixture["body"]))
    result = await run("list_customers", {"page_size": 1})
    assert result["customers"][0]["createdBy"] == {"id": 2, "type": "users"}
    assert result["customers"][0]["company"] is None
    assert result["pagination"]["hasMorePages"] is True
    assert result["customers"][0]["firstName"] == "Joe"
