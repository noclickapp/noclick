"""Force24 wire tests with synthetic responses, not live-provider evidence."""
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import force24_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

TOKEN = "synthetic-force24-access-token"
AUTH = {"credential_type": "force24_access_token", "access_token": TOKEN}
LIST_ID = "af22ce32-e01a-4aee-a532-8ba680e13c59"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="force24-test", node_type=native.NODE_TYPE,
        node_data={"config": config, "credentials": credential or AUTH})


def transport(monkeypatch, body=None, *, status=200, content=None, media="application/json"):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, **({"content": content} if content is not None else {"json": body}), headers={"Content-Type": media})

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


READ_CASES = [
    ({"operation": "list_recent_contacts", "from_version_number": 7, "count": 5, "fields": "emailAddress", "marketing_list_id": LIST_ID, "source_key": "crm", "has_external_id": False}, "/contacts/recents", {"fromVersionNumber": "7", "count": "5", "fields": "emailAddress", "marketingListId": LIST_ID, "sourceKey": "crm", "hasExternalId": "false"}, {"items": [{"id": 4}], "nextVersionNumber": 12}),
    ({"operation": "get_contact", "contact_id": 4}, "/contacts/4", {"fields": "*"}, {"id": 4, "emailAddress": "person@example.com"}),
    ({"operation": "find_contacts", "email_address": "person+sales@example.com", "external_id": "x&y", "source_key": "crm"}, "/contacts/find", {"fields": "*", "emailAddress": "person+sales@example.com", "externalId": "x&y", "sourceKey": "crm"}, [{"id": 4}]),
    ({"operation": "list_marketing_lists", "skip": 2, "take": 3, "keyword": "sales", "include_test_lists": True, "descending": True, "sort_by_field": "totalContacts"}, "/marketing-lists", {"skip": "2", "take": "3", "keyword": "sales", "includeTestLists": "true", "descending": "true", "sortByField": "totalContacts"}, {"items": [{"id": LIST_ID, "name": "Sales"}], "totalCount": 6, "moreItemsAvailable": True}),
    ({"operation": "get_marketing_list", "marketing_list_id": LIST_ID}, "/marketing-lists/" + LIST_ID, {}, {"id": LIST_ID, "name": "Sales"}),
    ({"operation": "list_contact_fields"}, "/schemas/contact/fields", {}, [{"name": "firstName"}]),
    ({"operation": "list_email_campaigns", "skip": 5, "take": 2}, "/email/campaigns", {"skip": "5", "take": "2", "descending": "false", "sortByField": "createdOn"}, {"items": [{"id": 3}], "totalCount": 9, "moreItemsAvailable": True}),
    ({"operation": "get_email_campaign", "campaign_id": 3}, "/email/campaigns/3", {}, {"id": 3, "name": "Welcome"}),
    ({"operation": "get_email_campaign_stats", "campaign_id": 3, "start_date": "2025-01-01", "end_date": "2025-02-01"}, "/email/campaigns/3/stats", {"startDate": "2025-01-01", "endDate": "2025-02-01"}, {"sent": 4}),
    *[({"operation": "list_email_" + kind, "from_version_number": 9, "count": 2}, "/email/" + kind, {"fromVersionNumber": "9", "count": "2"}, {"items": [{"id": 4}], "nextVersionNumber": 10}) for kind in ["opens", "clicks", "unsubscribes", "bounces"]],
    ({"operation": "list_sent_emails", "offset": "5248921", "count": 10}, "/email/sent-items", {"offset": "5248921", "count": "10"}, {"items": [{"id": 4}], "nextOffset": 5248922}),
    ({"operation": "list_web_activity", "offset": "next", "count": 0}, "/web-activity", {"offset": "next", "count": "0"}, {"items": None, "nextOffset": 8}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,path,query,body", READ_CASES)
async def test_reads_exact_path_query_auth_and_provider_data(monkeypatch, config, path, query, body):
    requests = transport(monkeypatch, body)
    instance = node(config)
    instance.emit = AsyncMock()
    result = await instance.execute({})
    instance.emit.assert_awaited_once_with(result)
    assert result["status"] == "success" and len(requests) == 1
    request = requests[0]
    assert request.method == "GET" and request.url.host == "api.data-crypt.com"
    assert request.url.path == "/api/v1.3" + path
    assert dict(request.url.params) == query and not request.content
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert request.headers["Accept"] == "application/json"
    if "nextVersionNumber" in body:
        assert result["next_version_number"] == body["nextVersionNumber"]
    if "nextOffset" in body:
        assert result["next_offset"] == str(body["nextOffset"])
    if "moreItemsAvailable" in body:
        assert result["has_more"] and result["next_skip"] == config["skip"] + len(body["items"])


WRITE_CASES = [
    *[({"operation": kind + "_contact", "email_address": "person@example.com", "fields_json": {"firstName": "Alex"}, "external_id": "crm-1", "source_key": "crm", "fields": "id,emailAddress"}, "POST", "/contacts/" + kind, {"items": [{"emailAddress": "person@example.com", "externalId": "crm-1", "fields": {"firstName": "Alex"}}], "sourceKey": "crm", "fields": "id,emailAddress"}, {"items": [{"status": "Failed", "statusDetail": "Invalid field", "log": {"field": ["Invalid field"]}}]}) for kind in ["create", "update", "upsert"]],
    ({"operation": "create_marketing_list", "name": "Sales", "lock_status": "readWrite"}, "POST", "/marketing-lists", {"name": "Sales", "lockStatus": "readWrite"}, {"id": LIST_ID, "name": "Sales"}),
    ({"operation": "update_marketing_list", "marketing_list_id": LIST_ID, "name": "Customers", "is_test": False}, "PATCH", "/marketing-lists/" + LIST_ID, {"name": "Customers", "isTest": False}, None),
    ({"operation": "delete_marketing_list", "marketing_list_id": LIST_ID}, "DELETE", "/marketing-lists/" + LIST_ID, None, None),
    ({"operation": "delete_contact", "contact_id": 4}, "DELETE", "/contacts/4", None, None),
    ({"operation": "add_contact_to_list", "marketing_list_id": LIST_ID, "contact_id": 4}, "POST", "/marketing-lists/" + LIST_ID + "/contacts/4/add", None, None),
    ({"operation": "remove_contact_from_list", "marketing_list_id": LIST_ID, "contact_id": 4}, "POST", "/marketing-lists/" + LIST_ID + "/contacts/4/remove", None, None),
    ({"operation": "send_email_campaign", "campaign_id": 3, "contact_id": 4}, "POST", "/email/campaigns/3/send-item", {"contactId": 4}, None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body,response", WRITE_CASES)
async def test_writes_exact_body_no_retries_and_preserve_item_outcomes(monkeypatch, config, method, path, body, response):
    requests = transport(monkeypatch, response, content=b"" if response is None else None)
    instance = node(config)
    instance.emit = AsyncMock()
    result = await instance.execute({})
    instance.emit.assert_awaited_once_with(result)
    assert result["status"] == "success" and len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == "/api/v1.3" + path
    assert request.url.host == "api.data-crypt.com" and not request.url.query
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert (json.loads(request.content) if request.content else None) == body
    if response is None:
        assert result["acknowledged"] is True
    if config["operation"] in {"create_contact", "update_contact", "upsert_contact"}:
        assert result["items"] == response["items"] and "Inspect" in result["note"]


def test_wire_cases_cover_every_operation_and_connection_needs_only_credential():
    assert NODE_REGISTRY[native.NODE_TYPE] is native.Force24Node
    assert {c[0]["operation"] for c in READ_CASES + WRITE_CASES} == set(native.OPERATIONS)
    cfg = native.Force24Node.parse_config({"config": {"operation": native.Force24Node.connection_evidence.operation}, "credentials": AUTH})
    assert cfg.config.operation == "list_marketing_lists"
    assert native.Force24AccessTokenCredential(access_token=TOKEN).credential_type == "force24_access_token"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 429, 500])
async def test_error_verbatim_reason_redacted_and_not_retried(monkeypatch, status):
    requests = transport(monkeypatch, {"detail": "Token rejected " + TOKEN}, status=status)
    with pytest.raises(ValueError, match=r"Token rejected \[redacted\]"):
        await node({"operation": "send_email_campaign", "campaign_id": 3, "contact_id": 4}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body,media,content", [({"error": "bad"}, "application/json", None), ([], "application/json", None), ({"items": "bad"}, "application/json", None), ({}, "text/html", None), ({}, "application/json", b"not json"), ({}, "application/json", b"x" * 4_000_001)])
async def test_bad_collections_and_representations_fail(monkeypatch, body, media, content):
    transport(monkeypatch, body, media=media, content=content)
    with pytest.raises(ValueError):
        await node({"operation": "list_marketing_lists"}).execute({})


@pytest.mark.asyncio
async def test_secret_never_returned_and_empty_nullable_page(monkeypatch):
    transport(monkeypatch, {"items": [{"name": TOKEN}], "moreItemsAvailable": False, "totalCount": 1})
    result = await node({"operation": "list_marketing_lists"}).execute({})
    assert TOKEN not in str(result) and result["next_skip"] is None
    transport(monkeypatch, {"items": None, "moreItemsAvailable": False, "totalCount": 0})
    assert (await node({"operation": "list_marketing_lists"}).execute({}))["items"] == []


@pytest.mark.asyncio
async def test_empty_acknowledgement_does_not_ignore_unexpected_payload(monkeypatch):
    transport(monkeypatch, {"error": "failure"})
    with pytest.raises(ValueError, match="acknowledgement"):
        await node({"operation": "delete_contact", "contact_id": 4}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_contact", "contact_id": 0},
    {"operation": "get_contact", "contact_id": "../find"},
    {"operation": "get_marketing_list", "marketing_list_id": "../contacts"},
    {"operation": "list_marketing_lists", "take": 501},
    {"operation": "list_recent_contacts", "count": 1001},
    {"operation": "list_recent_contacts", "from_version_number": -1},
    {"operation": "list_sent_emails", "offset": "https://evil.invalid"},
    {"operation": "create_contact", "email_address": "person@example.com", "fields_json": "[]"},
    {"operation": "create_contact", "email_address": "person@example.com", "fields_json": '{"x":NaN}'},
    {"operation": "update_marketing_list", "marketing_list_id": LIST_ID},
    {"operation": "get_email_campaign_stats", "campaign_id": 3, "start_date": "2025-02-01", "end_date": "2025-01-01"},
    {"operation": "list_contact_fields", "url": "https://evil.invalid"},
])
def test_invalid_config_refused_before_network(config):
    with pytest.raises((ValueError, ValidationError)):
        native.Force24Node.parse_config({"config": config, "credentials": AUTH})


@pytest.mark.parametrize("token", ["", "Bearer example-token", "https://evil.invalid", "token\r\nInjected: yes"])
def test_bad_tokens_refused(token):
    with pytest.raises((ValueError, ValidationError)):
        native.Force24AccessTokenCredential(access_token=token)
