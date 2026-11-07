"""Rossum factory, dispatcher, picker and credential access fixtures.

Only synthetic private values and explicit MockTransport. Root lane required.
"""
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
import json

import httpx
import pytest
from nodes import rossum_node as native
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation
from nodes.core.credential_connect import validate_for_connect

NT = "automation-rossum"
USER = "11111111-1111-4111-8111-111111111111"
CID = "22222222-2222-4222-8222-222222222222"
ORIGIN = "https://fixture.rossum.app"
TOKEN = {"credential_type": native.TYPE, "tenant_url": ORIGIN, "organization_id": 7, "api_token": "synthetic-private-token"}
def url(resource, identifier): return f"{ORIGIN}/api/v1/{resource}/{identifier}"
ORGANIZATION = {"id": 7, "url": url("organizations", 7), "name": "Synthetic organization", "users": ["omit-user"], "settings": {"private": "omit-private"}}
WORKSPACE = {"id": 8, "url": url("workspaces", 8), "name": "Synthetic workspace", "organization": url("organizations", 7), "queues": [url("queues", 9)], "metadata": {"private": "omit-private"}}
QUEUE = {"id": 9, "url": url("queues", 9), "name": "Synthetic queue", "workspace": url("workspaces", 8), "counts": {"to_review": 1}, "status": "active", "metadata": {}, "hooks": ["omit-hook"], "inbox": "omit-address"}
ANNOTATION = {"id": 10, "url": url("annotations", 10), "queue": url("queues", 9), "organization": url("organizations", 7), "document": url("documents", 11), "status": "to_review", "email": "omit-email", "content": "omit-private-url"}
DOCUMENT = {"id": 11, "url": url("documents", 11), "annotations": [url("annotations", 10)], "mime_type": "application/pdf", "original_file_name": "omit-filename", "s3_name": "omit-key", "content": "omit-download"}
UPLOAD = {"id": 13, "url": url("uploads", 13), "queue": url("queues", 9), "organization": url("organizations", 7), "documents": [url("documents", 11)], "annotations": [url("annotations", 10)], "creator": "omit-user"}
TASK = {"id": 12, "url": url("tasks", 12), "type": "upload_created", "status": "succeeded", "expires_at": "2099-01-01T00:00:00Z", "content": {"upload": url("uploads", 13)}, "result_url": "https://private.example.test/omit-signed", "detail": "omit-provider-error"}
CONTENT = {"content": [{"id": 20, "url": url("annotations", 10) + "/content/20", "category": "section", "schema_id": "header", "children": [{"id": 21, "url": url("annotations", 10) + "/content/21", "category": "datapoint", "schema_id": "selected", "content": {"value": "synthetic-private-value", "rir_raw_text": "omit-OCR"}}]}]}


def node(operation, raw=TOKEN, **args):
    return NodeFactory.create_node(node_id="rossum-fixture", node_type=NT, node_data={"config": {"operation": operation, **args}, "credentials": deepcopy(raw)}, sio=None, sid=None, user_id=USER)


@pytest.fixture(autouse=True)
def admission(monkeypatch):
    monkeypatch.setattr("utils.credential_approval.admit_node", AsyncMock(return_value=None))


@pytest.fixture
def transport(monkeypatch):
    calls, responses = [], []
    async def receive(request):
        calls.append(request)
        data = responses.pop(0)
        if callable(data): data = data()
        return data if isinstance(data, httpx.Response) else httpx.Response(200, json=data)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(receive)) as value: yield value
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls, responses


@pytest.mark.parametrize("value", [True, "20", 1.5, 0, 101, 9007199254740993])
def test_actual_factory_strict_page_size_before_io(transport, value):
    with pytest.raises(ValueError): node("list_workspaces", page_size=value)
    assert transport[0] == []


@pytest.mark.parametrize("origin", ["http://fixture.rossum.app", "https://localhost", "https://fixture.rossum.app.evil.test", "https://user:pass@fixture.rossum.app", "https://fixture.rossum.app/api", "https://fixture.rossum.app:8443", "https://fixture.rossum.app?q=1"])
def test_tenant_credentials_refuse_unsafe_authorities_before_io(transport, origin):
    with pytest.raises(ValueError): node("check_connection", raw={**TOKEN, "tenant_url": origin})
    assert transport[0] == []


def test_actual_factory_original_discriminator_precedes_attachment_reconciliation(transport):
    with pytest.raises(ValueError):
        NodeFactory.create_node(node_id="foreign", node_type=NT, node_data={"credentials": {**TOKEN, "credential_type": "restream_bearer"}, "credentialIds": {native.TYPE: CID}, "config": {"operation": "check_connection"}}, sio=None, sid=None)
    assert transport[0] == []


@pytest.mark.asyncio
async def test_preparsed_raw_foreign_credential_refuses_before_transport(transport):
    instance = node("check_connection")
    instance.node_data["credentials"]["credential_type"] = "foreign"
    with pytest.raises(ValueError): await instance.execute({})
    assert transport[0] == []


@pytest.mark.asyncio
async def test_actual_visible_form_connect_serializes_literal_and_resource_evidence(transport):
    transport[1].append(ORGANIZATION)
    visible = {"tenant_url": ORIGIN, "organization_id": "7", "api_token": TOKEN["api_token"]}
    verdict = await validate_for_connect(credential_type=native.TYPE, credential_data=visible, user_id=USER)
    assert verdict.ok and verdict.credential_data["credential_type"] == native.TYPE and verdict.credential_data["organization_id"] == 7
    assert verdict.evidence.account_label == "Synthetic organization"
    assert "omit" not in repr(verdict.evidence)
    assert transport[0][0].headers["authorization"] == "Bearer " + TOKEN["api_token"]


@pytest.mark.asyncio
async def test_real_dispatch_private_document_projection_and_exact_parents(transport):
    transport[1].extend([ORGANIZATION, WORKSPACE, QUEUE, ANNOTATION, DOCUMENT])
    result = await run_node_operation(node_type=NT, operation="get_document", arguments={"workspace_id": 8, "queue_id": 9, "annotation_id": 10}, user_id=USER, credential_data=TOKEN)
    assert result["data"] == {"id": 11, "annotation_id": 10, "mime_type": "application/pdf", "arrived_at": None}
    assert "omit" not in repr(result)
    assert [r.url.path for r in transport[0]] == ["/api/v1/organizations/7", "/api/v1/workspaces/8", "/api/v1/queues/9", "/api/v1/annotations/10", "/api/v1/documents/11"]


@pytest.mark.asyncio
async def test_foreign_queue_parent_blocks_document_read(transport):
    transport[1].extend([ORGANIZATION, WORKSPACE, {**QUEUE, "workspace": url("workspaces", 999)}])
    with pytest.raises(native.OutcomeUnverified): await node("get_document", workspace_id=8, queue_id=9, annotation_id=10).execute({})
    assert len(transport[0]) == 3


@pytest.mark.asyncio
async def test_selected_content_values_are_explicit_and_structure_has_no_values(transport):
    for operation, args in [("get_annotation_structure", {}), ("get_selected_values", {"schema_ids": ["selected", "absent"]})]:
        transport[1].extend([ORGANIZATION, WORKSPACE, QUEUE, ANNOTATION, CONTENT])
        result = await node(operation, workspace_id=8, queue_id=9, annotation_id=10, **args).execute({})
        assert "omit" not in repr(result)
        if args:
            assert result["data"]["fields"] == [{"id": 21, "schema_id": "selected", "category": "datapoint", "value": "synthetic-private-value"}]
            assert result["data"]["missing_schema_ids"] == ["absent"]
        else: assert "synthetic-private-value" not in repr(result)


@pytest.mark.asyncio
async def test_upload_202_is_accepted_not_completed_and_multipart_is_exact(transport):
    transport[1].extend([ORGANIZATION, WORKSPACE, QUEUE, httpx.Response(202, json={"url": url("tasks", 12)})])
    result = await node("import_document", workspace_id=8, queue_id=9, file_name="fixture.pdf", content_base64="JVBERg==", reject_identical=False).execute({})
    assert result["data"] == {"task_id": 12, "queue_id": 9, "accepted": True, "import_complete": False, "provider_status": 202}
    request = transport[0][-1]
    assert dict(request.url.params) == {"queue": "9", "reject_identical": "false"}
    assert request.headers["content-type"].startswith("multipart/form-data; boundary=")
    assert b'filename="fixture.pdf"' in request.content and b"%PDF" in request.content
    assert len(transport[0]) == 4


@pytest.mark.parametrize("value", ["https://private.example.test/file", "data:application/pdf;base64,JVBERg==", "!!!!", "JVBERg=", ""])
def test_malformed_file_refused_by_real_model_before_io(transport, value):
    with pytest.raises(ValueError): node("import_document", workspace_id=8, queue_id=9, file_name="fixture.pdf", content_base64=value)
    assert transport[0] == []


@pytest.mark.asyncio
async def test_task_no_redirect_verifies_upload_parent_without_extraction_claim(transport):
    transport[1].extend([ORGANIZATION, WORKSPACE, QUEUE, TASK, UPLOAD])
    result = await node("get_import_task", workspace_id=8, queue_id=9, task_id=12).execute({})
    assert transport[0][3].url.params["no_redirect"] == "true"
    assert result["data"]["upload_task_complete"] is True and result["data"]["extraction_status_verified"] is False
    assert "omit" not in repr(result) and len(transport[0]) == 5


@pytest.mark.asyncio
async def test_metadata_patch_preserves_settings_and_independent_readback(transport):
    changed = {**QUEUE, "name": "Renamed", "metadata": {"fixture": "owned"}}
    transport[1].extend([ORGANIZATION, WORKSPACE, QUEUE, changed, changed])
    result = await node("update_queue_metadata", workspace_id=8, queue_id=9, name="Renamed", metadata={"fixture": "owned"}).execute({})
    assert json.loads(transport[0][3].content) == {"name": "Renamed", "metadata": {"fixture": "owned"}}
    assert transport[0][4].method == "GET" and result["data"]["readback_verified"] is True


@pytest.mark.asyncio
async def test_delete_204_requires_empty_name_match_and_authenticated_404(transport):
    transport[1].extend([ORGANIZATION, {**WORKSPACE, "queues": []}, httpx.Response(204), httpx.Response(404, json={"detail": "omit-provider"})])
    result = await node("delete_empty_workspace", workspace_id=8, expected_name="Synthetic workspace").execute({})
    assert result["data"]["deleted"] is True and transport[0][-1].method == "GET"
    assert transport[0][-1].headers["authorization"].startswith("Bearer ")


@pytest.mark.asyncio
async def test_cursor_preserved_and_foreign_or_scope_changed_next_refused(transport):
    next_url = ORIGIN + "/api/v1/workspaces?organization=7&page_size=20&cursor=opaque%2Fsigned%3D"
    transport[1].extend([ORGANIZATION, {"results": [WORKSPACE], "pagination": {"next": next_url, "previous": None}}])
    result = await node("list_workspaces").execute({})
    assert result["data"]["next_page_url"] == next_url
    transport[1].extend([ORGANIZATION, {"results": [], "pagination": {"next": None, "previous": next_url}}])
    await node("list_workspaces", continuation_url=next_url).execute({})
    assert str(transport[0][-1].url) == next_url
    for unsafe in [next_url.replace("fixture.rossum.app", "evil.example.test"), next_url.replace("organization=7", "organization=99"), next_url + "&cursor=duplicate"]:
        transport[1].append(ORGANIZATION)
        with pytest.raises(native.OutcomeUnverified): await node("list_workspaces", continuation_url=unsafe).execute({})
    assert all(request.url.host == "fixture.rossum.app" for request in transport[0])


@pytest.mark.asyncio
@pytest.mark.parametrize("status,valid", [(401, False), (403, None), (429, None), (500, None)])
async def test_connection_rejection_and_unknown_are_distinct_and_redacted(transport, status, valid):
    transport[1].append(httpx.Response(status, json={"detail": TOKEN["api_token"]}))
    verdict = await native.RossumNode.validate_credential_access(TOKEN)
    assert verdict["valid"] is valid and TOKEN["api_token"] not in repr(verdict)


@pytest.fixture
def stored(monkeypatch):
    state = {"credential": deepcopy(TOKEN)}
    async def resolve(*args, **kwargs): return deepcopy(state["credential"])
    monkeypatch.setattr(native, "resolve_credential_with_owner_fallback", resolve)
    return state


@pytest.mark.asyncio
async def test_saved_missing_caller_and_foreign_credential_refuse_before_transport(stored, transport):
    with pytest.raises(ValueError):
        await native.Authority.create(TOKEN, pool=object(), credential_id=CID, organization_id=None)
    stored["credential"]["credential_type"] = "foreign"
    with pytest.raises(ValueError):
        await native.Authority.create(TOKEN, pool=object(), user_id=USER, credential_id=CID, organization_id=None)
    assert transport[0] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["access", "kind", "token"])
async def test_saved_credential_change_during_response_blocks_result(stored, transport, change):
    auth = await native.Authority.create(TOKEN, pool=object(), user_id=USER, credential_id=CID, organization_id=None)
    def changed():
        if change == "access": stored["credential"] = None
        elif change == "kind": stored["credential"]["credential_type"] = "foreign"
        else: stored["credential"]["api_token"] = "replacement-private-token"
        return ORGANIZATION
    transport[1].append(changed)
    with pytest.raises(ValueError): await native.operate(auth, native.CheckConnection())
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_actual_parent_picker_checks_org_and_returns_integer_values(transport):
    transport[1].extend([ORGANIZATION, WORKSPACE, {"results": [QUEUE], "pagination": {"next": None, "previous": None}}])
    result = await native.RossumNode.load_field_options("queue_id", TOKEN, context={"workspace_id": 8})
    assert result == {"options": [{"value": 9, "label": "Synthetic queue"}], "next_page_token": None}
    assert dict(transport[0][-1].url.params) == {"workspace": "8", "page_size": "100"}
