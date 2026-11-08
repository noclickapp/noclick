"""Offline requests verified against the official Enginemailer n8n source."""
import json
from unittest.mock import AsyncMock
import httpx
import pytest
import nodes.enginemailer_node as em
from nodes.core.run_op import run_node_operation
from nodes.core.connection_evidence import collect_evidence
from utils import ssrf

AUTH = {
    "credential_type": "enginemailer_api_key",
    "api_key": "em-synthetic-offline-key",
}
USER = "00000000-0000-4000-8000-000000000001"
CASES = [
    ("check_connection", "GET", "connect", {}),
    (
        "list_new_subscribers",
        "GET",
        "newsubscribers",
        {
            "limit": 50,
            "source": "API",
            "filter_form": 1,
            "filter_page": 2,
            "filter_popup": 3,
            "lastpollingdate": "2025-07-01T00:00:00Z",
        },
    ),
    (
        "list_unsubscribe_events",
        "GET",
        "unsubscribe",
        {
            "limit": 50,
            "filter": "campaign",
            "filter_campaign": 1,
            "filter_autoresponder": 2,
        },
    ),
    ("list_modified_subscribers", "GET", "subscribersmodified", {"limit": 50}),
    ("list_deleted_subscribers", "GET", "subscribersdeleted", {"limit": 50}),
    (
        "list_tagged_subscribers",
        "GET",
        "subscriberstagged",
        {"limit": 50, "filter_subcategory": 3},
    ),
    (
        "list_untagged_subscribers",
        "GET",
        "subscribersuntagged",
        {"limit": 50, "filter_subcategory": 3},
    ),
    (
        "list_autoresponder_triggered",
        "GET",
        "subscriberautorespondertriggered",
        {"limit": 50, "filter_autoresponder": 2},
    ),
    (
        "list_autoresponder_completed",
        "GET",
        "subscriberautorespondercompleted",
        {"limit": 50, "filter_autoresponder": 2},
    ),
    ("list_subcategories", "GET", "listsubcategories", {}),
    ("list_forms", "GET", "listforms", {}),
    ("list_pages", "GET", "listpages", {}),
    ("list_popups", "GET", "listpopups", {}),
    ("list_autoresponders", "GET", "listautoresponders", {}),
    ("list_campaigns", "GET", "listcampaigns", {}),
    ("list_domains", "GET", "listdomains", {}),
    ("list_templates", "GET", "listtemplates", {}),
    (
        "add_update_subscriber",
        "POST",
        "addupdatesubscriber",
        {
            "email": "name@email.com",
            "sourcetype": "Signup from website",
            "subcategories": [3],
            "customfields": [
                {"customfield_key": "first_name", "customfield_value": "John"}
            ],
            "updatetype": "Append",
        },
    ),
    ("unsubscribe_subscriber", "POST", "unsubscribe", {"email": "name@email.com"}),
    ("delete_subscriber", "POST", "deletesubscriber", {"email": "name@email.com"}),
    (
        "tag_subscriber",
        "POST",
        "tagtosubcategory",
        {"email": "name@email.com", "subcategories": [3]},
    ),
    (
        "untag_subscriber",
        "POST",
        "untagtosubcategory",
        {"email": "name@email.com", "subcategories": [3]},
    ),
    ("find_subscriber", "POST", "findsubscriber", {"email": "name@email.com"}),
    (
        "send_email",
        "POST",
        "sendemail",
        {
            "email": "name@email.com",
            "type": "html",
            "html": "<p>Hi John</p>",
            "subject": "Hello",
            "sender_email": "sender@example.test",
            "sender_name": "Sender",
            "substitution_tags": [{"Key": "firstname", "Value": "John"}],
            "cc_emails": "copy@example.test",
        },
    ),
]


@pytest.fixture
def transport(monkeypatch):
    requests, responses = [], []
    monkeypatch.setattr(
        ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"])
    )

    async def send(request):
        requests.append(request)
        assert request.url.host == "connect.enginemailer.com"
        assert request.headers["APIKEY"] == AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        return (
            responses.pop(0)
            if responses
            else httpx.Response(200, json=[{"id": 3, "Name": "Customers"}])
        )

    native = ssrf.guarded_async_client
    monkeypatch.setattr(
        em,
        "guarded_async_client",
        lambda **kw: native(**kw, transport=httpx.MockTransport(send)),
    )
    return requests, responses


async def run(op, arguments=None, auth=AUTH):
    return await run_node_operation(
        node_type="automation-enginemailer",
        operation=op,
        arguments=arguments or {},
        credential_data=auth,
        user_id=USER,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("op,method,path,arguments", CASES)
async def test_exact_published_wire_request(transport, op, method, path, arguments):
    result = await run(op, arguments)
    assert result == {"data": [{"id": 3, "Name": "Customers"}]}
    assert len(transport[0]) == 1
    req = transport[0][0]
    assert req.method == method and req.url.path == "/api/N8N/v1/" + path
    if method == "POST":
        assert json.loads(req.content) == arguments
        assert req.headers["Content-Type"].startswith("application/json")
    else:
        assert dict(req.url.params) == {k: str(v) for k, v in arguments.items()}
        assert not req.content


@pytest.mark.asyncio
async def test_connection_evidence_uses_account_subcategories(transport):
    evidence = await collect_evidence(
        node_type="automation-enginemailer", user_id=USER, credential_data=AUTH
    )
    assert evidence.reachable is True
    assert evidence.samples[0].label == "Customers"
    assert len(transport[0]) == 1 and transport[0][0].url.path.endswith(
        "/listsubcategories"
    )


@pytest.mark.asyncio
async def test_object_preserved_without_delivery_claim(transport):
    body = {"Status": "Accepted", "Message": "Queued"}
    transport[1].append(httpx.Response(200, json=body))
    assert await run("send_email", CASES[-1][3]) == body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,body",
    [
        (401, {"message": "Invalid API key"}),
        (429, {"message": "Too many requests"}),
        (500, {"message": "Service unavailable"}),
        (200, {"success": False, "message": "Rejected"}),
        (200, {"error": "Denied"}),
    ],
)
async def test_errors_do_not_pass_or_retry(transport, status, body):
    transport[1].append(httpx.Response(status, json=body))
    with pytest.raises(ValueError):
        await run("delete_subscriber", {"email": "name@email.com"})
    assert len(transport[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"Location": "https://other.test"}),
        httpx.Response(
            200, text="<html>Login</html>", headers={"Content-Type": "text/html"}
        ),
        httpx.Response(200, content=b""),
        httpx.Response(200, json="unexpected scalar"),
        httpx.Response(
            200, content=b"broken", headers={"Content-Type": "application/json"}
        ),
    ],
)
async def test_redirects_empty_or_invalid_json_fail(transport, response):
    transport[1].append(response)
    with pytest.raises(ValueError):
        await run("list_forms")
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_refused_key_is_redacted(transport):
    transport[1].append(
        httpx.Response(401, json={"message": "Rejected " + AUTH["api_key"]})
    )
    with pytest.raises(ValueError) as exc:
        await run("list_forms")
    assert AUTH["api_key"] not in str(exc.value) and "HTTP 401" in str(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "op,arguments",
    [
        ("tag_subscriber", {"email": "name@email.com", "subcategories": []}),
        ("find_subscriber", {"email": "invalid"}),
        ("send_email", {"email": "name@email.com"}),
        ("list_forms", {"url": "https://other.test"}),
        ("list_new_subscribers", {"limit": 0}),
    ],
)
async def test_bad_config_never_reaches_transport(transport, op, arguments):
    with pytest.raises(ValueError):
        await run(op, arguments)
    assert transport[0] == []


@pytest.mark.asyncio
async def test_foreign_credential_is_refused(transport):
    with pytest.raises(ValueError):
        await run("list_forms", auth={**AUTH, "credential_type": "other_api_key"})
    assert not transport[0]
