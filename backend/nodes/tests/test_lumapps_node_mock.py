"""LumApps native factory, metadata, drafts and guarded transport regressions.

Synthetic unit fixtures use MockTransport; no live LumApps requests are made.
"""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import json

import httpx
import pytest
from nodes.core import registry
from nodes.core.base import ConfigValidationError
from nodes.core.connection_evidence import collect_evidence
from nodes.core.run_op import run_node_operation
from nodes.lumapps_node import LumAppsNode, KIND

USER = "00000000-0000-4000-8000-000000000001"
OWNER = "00000000-0000-4000-8000-000000000002"
ORG = "00000000-0000-4000-8000-000000000003"
CID = "00000000-0000-4000-8000-000000000004"
WF = "00000000-0000-4000-8000-000000000005"
CREDS = {"credential_type": KIND, "access_token": "synthetic-issued-token",
    "api_origin": "https://go-cell-001.api.lumapps.com", "customer_id": "customer-1",
    "expires_at": "2099-01-01T00:00:00Z"}
ME = {"uid": "user-1", "id": "user-1", "customer": "customer-1", "fullName": "Fixture Owner",
    "email": "private@example.test", "settings": {"secret": "private"}, "apiProfile": "private"}
INSTANCE = {"uid": "instance-1", "id": "instance-1", "customer": "customer-1", "name": "Owned Intranet"}
CONTENT = {"uid": "content-1", "id": "content-1", "instance": "instance-1", "type": "page",
    "status": "DRAFT", "title": "Owned Draft", "version": 3, "template": {"components": []},
    "canonicalUrl": "https://private/content", "customer": "customer-1"}
COMMUNITY = {"uid": "community-1", "instance": "instance-1", "title": "Owned Community",
    "status": "LIVE", "privateDescription": "private"}
DOCUMENT = {"uid": "document-1", "instance": "instance-1", "name": "fixture.pdf",
    "isFolder": False, "content": [{"mimeType": "application/pdf", "size": 10,
        "url": "https://private/download", "servingUrl": "https://private/serve", "value": "private-blob"}]}
METADATA = {"uid": "metadata-1", "instance": "instance-1", "name": "Owned Topic", "values": "private"}

@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    import utils.ssrf as ssrf
    native = httpx.AsyncClient
    state = SimpleNamespace(seen=[], replies=[], dns=[], owner=deepcopy(ME), parent=deepcopy(INSTANCE))
    async def dns(host, port, **kwargs):
        assert host == "go-cell-001.api.lumapps.com"
        state.dns.append((host, kwargs))
        return {"8.8.8.8"}
    def handle(request):
        state.seen.append(request)
        if request.url.path.endswith("/user/get") and "uid" not in request.url.params:
            return httpx.Response(200, json=state.owner)
        if request.url.path.endswith("/instance/get"):
            return httpx.Response(200, json=state.parent)
        assert state.replies, "Unexpected LumApps resource request"
        code, payload = state.replies.pop(0)
        return httpx.Response(code, content=payload) if isinstance(payload, bytes) or payload is None else httpx.Response(code, json=payload)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        kwargs["transport"] = httpx.MockTransport(handle)
        return native(**kwargs)
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", dns)
    monkeypatch.setattr(ssrf.httpx, "AsyncClient", client)
    return state


def node(op, creds=None, **arguments):
    data = {"config": {"operation": op, **arguments}, "credentials": deepcopy(creds or CREDS)}
    return registry.NodeFactory.create_node("fixture", "automation-lumapps", data,
        user_id=USER, organization_id=ORG, workflow_id=WF)


def page(items=(), *, more=False, cursor=None):
    value = {"items": list(items), "more": more}
    if cursor is not None:
        value["cursor"] = cursor
    return value


def resources(state):
    return [r for r in state.seen if not (r.url.path.endswith("/instance/get")
        or (r.url.path.endswith("/user/get") and "uid" not in r.url.params))]


@pytest.mark.parametrize("tag", ["foreign", None, ""])
def test_factory_foreign_tag_cannot_be_reconciled_by_misleading_attachment(tag):
    data = {"credentials": {**CREDS, "credential_type": tag}, "config": {"operation": "get_current_user"},
        "credentialIds": {KIND: CID}}
    with pytest.raises(ConfigValidationError):
        registry.NodeFactory.create_node("fixture", "automation-lumapps", data)
    assert LumAppsNode.validate_config(data)["valid"] is False


@pytest.mark.parametrize("origin", ["http://go-cell-001.api.lumapps.com", "https://go-cell-001.api.lumapps.com.evil.test",
    "https://go-cell-001.api.lumapps.com/api", "https://@go-cell-001.api.lumapps.com",
    "https://go-cell-001.api.lumapps.com:443", "https://127.0.0.1", "https://sites.lumapps.com",
    "https://go-cell-001.api.lumapps.com?token=private", "https://go-cell-001.api.lumapps.com\\evil"])
def test_only_production_cell_origin(origin):
    with pytest.raises(ConfigValidationError):
        node("get_current_user", creds={**CREDS, "api_origin": origin})


@pytest.mark.parametrize("op,args", [
    ("list_users", {"page_size": True}),
    ("list_documents", {"instance_id": "instance-1", "search_in_folder": 1}),
    ("get_content", {"instance_id": "instance-1", "content_id": "../other"}),
    ("create_content_draft", {"instance_id": "instance-1", "source_content_id": "content-1", "title": "Draft", "status": "LIVE"}),
    ("delete_content_draft", {"instance_id": "instance-1", "content_id": "content-1", "confirm_draft_delete": 1}),
])
def test_strict_input_types_and_no_publish_fields(op, args):
    with pytest.raises(ConfigValidationError):
        node(op, **args)


@pytest.mark.asyncio
async def test_real_dispatcher_headers_identity_and_projection(transport):
    result = await run_node_operation(node_type="automation-lumapps", operation="get_current_user",
        arguments={}, credential_data=CREDS, user_id=USER, organization_id=ORG, workflow_id=WF)
    assert result["data"] == {"id": "user-1", "fullName": "Fixture Owner", "customer": "customer-1", "name": "Fixture Owner"}
    request = transport.seen[0]
    assert request.url.path == "/_ah/api/lumsites/v1/user/get"
    assert request.headers["Authorization"] == "Bearer synthetic-issued-token"
    assert request.headers["x-lumapps-analytics"] == "off"
    assert "synthetic-issued-token" not in str(request.url)
    assert transport.dns and "private" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("op,args,endpoint,item", [
    ("list_users", {}, "user/list", ME),
    ("list_instances", {}, "instance/list", INSTANCE),
    ("list_content", {"instance_id": "instance-1"}, "content/list", CONTENT),
    ("list_communities", {"instance_id": "instance-1"}, "community/list", COMMUNITY),
    ("list_documents", {"instance_id": "instance-1", "search_in_folder": False}, "document/list", DOCUMENT),
    ("list_metadata", {"instance_id": "instance-1"}, "metadata/list", METADATA),
])
async def test_all_list_contracts_and_local_document_privacy(transport, op, args, endpoint, item):
    transport.replies.append((200, page([item])))
    result = await node(op, **args).execute({})
    request = resources(transport)[0]
    assert request.url.path.endswith("/" + endpoint)
    assert result["data"]["items"][0]["id"] == (item.get("uid") or item["id"])
    assert "private" not in json.dumps(result)
    if request.method == "POST":
        body = json.loads(request.content)
        assert body["maxResults"] == 30
        assert body["lang"] == ("en" if op == "list_documents" else ["en"])
        if op == "list_documents":
            assert body["docPath"] == "provider=local/site=instance-1"
            assert body["asApplication"] is False and body["searchInFolder"] is False
        else:
            assert body["instanceId"] == ["instance-1"]
            assert body["action"] in {"PAGE_READ", "COMMUNITY_READ"}
    else:
        assert request.url.params["maxResults"] == "30"


@pytest.mark.asyncio
@pytest.mark.parametrize("op,args,item", [
    ("get_user", {"user_id": "user-1"}, ME),
    ("get_content", {"instance_id": "instance-1", "content_id": "content-1"}, CONTENT),
    ("get_community", {"instance_id": "instance-1", "community_id": "community-1"}, COMMUNITY),
    ("get_document", {"instance_id": "instance-1", "resource_id": "document-1"}, DOCUMENT),
    ("get_metadata", {"instance_id": "instance-1", "metadata_id": "metadata-1"}, METADATA),
])
async def test_all_scoped_getters(transport, op, args, item):
    transport.replies.append((200, item))
    result = await node(op, **args).execute({})
    assert result["data"]["id"] == item["uid"]
    assert "private" not in json.dumps(result)
    if op == "get_document":
        assert json.loads(resources(transport)[0].content) == {"docPath": "provider=local/site=instance-1/resource=document-1"}


@pytest.mark.asyncio
async def test_instance_get_and_wrong_organization_or_parent_fail_closed(transport):
    assert (await node("get_instance", instance_id="instance-1").execute({}))["data"]["name"] == "Owned Intranet"
    transport.owner["customer"] = "other"
    with pytest.raises(ValueError, match="organization"):
        await node("list_users").execute({})
    assert not resources(transport)
    transport.owner = deepcopy(ME)
    transport.parent["customer"] = "other"
    with pytest.raises(ValueError, match="organization"):
        await node("list_content", instance_id="instance-1").execute({})
    assert not resources(transport)


@pytest.mark.asyncio
async def test_encrypted_bound_cursor_empty_pages_and_cycle(transport):
    transport.replies.append((200, page([ME], more=True, cursor="private-cursor")))
    first = (await node("list_users").execute({}))["data"]
    token = first["next_page_token"]
    assert token and "private-cursor" not in token
    transport.replies.append((200, page([])))
    assert (await node("list_users", page_token=token).execute({}))["data"]["items"] == []
    assert resources(transport)[-1].url.params["cursor"] == "private-cursor"
    before = len(resources(transport))
    with pytest.raises(ValueError, match="page token"):
        await node("list_users", page_token=token, query="changed").execute({})
    assert len(resources(transport)) == before
    transport.replies.append((200, page([ME], more=True, cursor="private-cursor")))
    with pytest.raises(ValueError, match="pagination"):
        await node("list_users", page_token=token).execute({})


@pytest.mark.asyncio
async def test_actual_picker_parent_and_opaque_next_page(transport):
    with pytest.raises(ValueError, match="instance"):
        await LumAppsNode.load_field_options("content_id", CREDS, {})
    assert not transport.seen
    transport.replies.append((200, page([CONTENT])))
    result = await LumAppsNode.load_field_options("content_id", CREDS, {"instance_id": "instance-1"}, search_query="Owned")
    assert result["options"] == [{"value": "content-1", "label": "Owned Draft", "metadata": {"instance_id": "instance-1"}}]
    body = json.loads(resources(transport)[0].content)
    assert body["query"] == "Owned" and body["instanceId"] == ["instance-1"]


@pytest.mark.asyncio
async def test_draft_creator_version_lock_notification_suppression_and_cleanup_ack(transport):
    from nodes.agent.node_op_tools import resource_creators
    created = {**CONTENT, "uid": "new-1", "id": "new-1", "title": "Draft"}
    transport.replies.extend([(200, CONTENT), (200, created)])
    result = await node("create_content_draft", instance_id="instance-1", source_content_id="content-1", title="Draft").execute({})
    body = json.loads(resources(transport)[-1].content)
    assert body["status"] == "DRAFT" and body["template"] == {"components": []}
    assert body["title"] == {"en": "Draft"}
    assert body["customer"] == "customer-1" and "id" not in body and "version" not in body
    assert resources(transport)[-1].url.params["sendNotifications"] == "false"
    assert ("create_content_draft", "lumapps_content", "data.id") in resource_creators("automation-lumapps")
    assert result["data"]["id"] == "new-1" and result["data"]["notifications_requested"] is False
    transport.replies.extend([(200, CONTENT), (200, {**CONTENT, "title": "Renamed", "version": 4})])
    await node("update_content_draft", instance_id="instance-1", content_id="content-1", title="Renamed").execute({})
    read, write = resources(transport)[-2:]
    assert read.url.params["action"] == "PAGE_EDIT"
    body = json.loads(write.content)
    assert body["version"] == 3 and body["status"] == "DRAFT" and body["title"] == {"en": "Renamed"}
    assert write.url.params["sendNotifications"] == "false"
    transport.replies.extend([(200, CONTENT), (204, b"")])
    ack = await node("delete_content_draft", instance_id="instance-1", content_id="content-1", confirm_draft_delete=True).execute({})
    assert ack["data"] == {"id": "content-1", "instance": "instance-1", "operation": "delete_content_draft",
        "http_status": 204, "acknowledged": True}


@pytest.mark.asyncio
@pytest.mark.parametrize("current", [{**CONTENT, "status": "LIVE"}, {**CONTENT, "version": None}])
async def test_draft_update_refuses_live_or_unversioned_source(transport, current):
    transport.replies.append((200, current))
    with pytest.raises(ValueError):
        await node("update_content_draft", instance_id="instance-1", content_id="content-1", title="Changed").execute({})
    assert all(r.method == "GET" for r in resources(transport))


@pytest.mark.asyncio
@pytest.mark.parametrize("code,payload", [(302, {}), (401, {"error": "synthetic-issued-token"}),
    (429, b"private"), (500, b"private"), (200, b"NaN"), (200, {"errors": [{"message": "private"}]}),
    (200, {"items": [], "more": "false"}), (200, {"items": [], "more": True, "cursor": "next"}),
    (200, page([{"uid": True}])), (200, b"x" * (2 * 1024 * 1024 + 1))])
async def test_bounded_secret_safe_failure_and_malformed_success(transport, code, payload):
    transport.replies.append((code, payload))
    with pytest.raises((ValueError, httpx.HTTPStatusError)) as exc:
        await node("list_users").execute({})
    assert "private" not in str(exc.value) and "synthetic-issued-token" not in str(exc.value)
    if isinstance(exc.value, httpx.HTTPStatusError):
        assert str(exc.value.request.url) == "https://lumapps.invalid/api/"


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"items": []}])
async def test_publisher_optional_more_and_items_allow_empty_final_page(transport, payload):
    transport.replies.append((200, payload))
    result = await node("list_users").execute({})
    assert result["data"] == {"items": [], "has_more": False, "next_page_token": None}


@pytest.mark.asyncio
async def test_expired_token_and_preparsed_foreign_type_deny_transport(transport):
    with pytest.raises(ValueError, match="expired"):
        await node("get_current_user", creds={**CREDS, "expires_at": "2000-01-01T00:00:00Z"}).execute({})
    instance = node("get_current_user")
    instance.node_data["credentials"]["credential_type"] = "foreign"
    with pytest.raises(ConfigValidationError):
        await instance.execute({})
    assert not transport.seen


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked", [{"executed": False, "status": "pending_approval"},
    {"_halt_downstream": True, "status": "rejected"}])
async def test_real_collector_and_current_validation_keep_blocked_unverified(monkeypatch, transport, blocked):
    context = SimpleNamespace(run_operation=AsyncMock(return_value=blocked))
    assert (await LumAppsNode.validate_credential_access(CREDS, validation_context=context))["valid"] is None
    monkeypatch.setattr(LumAppsNode, "run", AsyncMock(return_value=blocked))
    result = await collect_evidence(node_type="automation-lumapps", user_id=USER, credential_data=CREDS)
    assert result.reachable is None and not result.samples and result.account_label is None
    assert not transport.seen


@pytest.mark.asyncio
async def test_actual_token_owner_evidence_and_manual_connect_shape(transport):
    from nodes.core.credential_connect import shape_credential
    shaped, errors, resolved = shape_credential(KIND, {**CREDS, "unknown": "retain-shaping-extra"})
    assert shaped["api_origin"] == CREDS["api_origin"]
    assert not errors and resolved[0] == "automation-lumapps"
    assert LumAppsNode.parse_config({"credentials": shaped, "config": {"operation": "get_current_user"}}).credentials.model_dump() == CREDS
    evidence = await collect_evidence(node_type="automation-lumapps", user_id=USER, credential_data=CREDS)
    assert evidence.reachable is True and evidence.account_label == "Fixture Owner" and not evidence.samples
    assert "private" not in json.dumps(evidence.__dict__)


@pytest.mark.asyncio
async def test_actual_base_run_admission_no_request(monkeypatch, transport):
    import utils.credential_approval
    pending = {"executed": False, "status": "pending_approval", "_halt_downstream": True}
    admission = AsyncMock(return_value=pending)
    monkeypatch.setattr(utils.credential_approval, "admit_node", admission)
    assert await node("get_current_user").run({}) == pending
    assert not transport.seen


def test_saved_resource_reference_is_validated_at_runtime():
    data = {"credentials": CREDS, "config": {"operation": "get_user", "user_id": "{{ $('lookup').id }}"}}
    assert LumAppsNode.validate_config(data)["valid"] is True
    with pytest.raises(ConfigValidationError):
        LumAppsNode.parse_config(data)
    data["config"]["user_id"] = "invalid resource id"
    assert LumAppsNode.validate_config(data)["valid"] is False
