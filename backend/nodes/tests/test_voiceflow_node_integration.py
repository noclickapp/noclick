"""Offline Voiceflow project, environment and knowledge API regression fixtures.

Exercises staging connection evidence and exact request/readback behavior.
"""
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import voiceflow_node as wire
from nodes.voiceflow_node import VoiceflowNode, VoiceflowPATCredential, VoiceflowFullConfig, parse_metadata

CID = "00000000-0000-4000-8000-000000000001"
USER = "00000000-0000-4000-8000-000000000002"
KEY = {"credential_type": "voiceflow_pat", "personal_access_token": "vfp_SYNTHETIC_VOICEFLOW_TOKEN", "workspace_id": "workspace-one", "project_id": "project-one", "environment_alias": "owned-test"}
PROJECT = {"id": KEY["project_id"], "name": "Owned Test Project", "workspaceID": KEY["workspace_id"], "description": "Fixture", "image": "https://private.invalid", "createdAt": "2026-10-01T00:00:00Z"}
ENVIRONMENT = {"name": "Owned Test Environment", "alias": KEY["environment_alias"], "isMain": False, "releases": [], "createdAt": "2026-10-01T00:00:00Z", "trafficPercentage": 0}
DOCUMENT = {"id": "document-one", "data": {"type": "text", "name": "Owned Test Source", "url": "https://private.invalid", "accessTokenID": "PRIVATE_TOKEN_REFERENCE"},
    "status": {"type": "SUCCESS", "data": "PRIVATE_ERROR_TEXT"}, "smartChunking": {}, "chunks": [{"chunkID": "chunk-one", "content": "PRIVATE_DOCUMENT_TEXT", "metadata": {}}], "metadata": [{"key": "topic", "values": ["before"]}]}


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    def client(**kwargs):
        assert kwargs == {"timeout": 20, "follow_redirects": False, "trust_env": False}
        return original(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(wire, "guarded_async_client", lambda **kwargs: client(**kwargs))


def witnessed(request):
    assert str(request.url).startswith(wire.ORIGIN + "/v1/stable/")
    assert request.headers["Authorization"] == "Bearer " + KEY["personal_access_token"]
    assert KEY["personal_access_token"] not in str(request.url)
    if request.url.path == "/v1/stable/project/" + KEY["project_id"]:
        return httpx.Response(200, json={"project": PROJECT})
    if request.url.path == "/v1/stable/environment/" + KEY["environment_alias"]:
        assert dict(request.url.params) == {"projectID": KEY["project_id"]}
        return httpx.Response(200, json={"environment": ENVIRONMENT})
    assert request.url.params["projectID"] == KEY["project_id"]
    assert request.url.params["environmentAlias"] == KEY["environment_alias"]
    return None


async def native_operation(monkeypatch, operation, arguments=None):
    from nodes.core.run_op import run_node_operation
    monkeypatch.setattr("nodes.core.run_op.resolve_operation_credential", AsyncMock(return_value=dict(KEY)))
    # The synthetic current credential is admitted without a database approval
    # record; keep the real admission path from using the sentinel pool below.
    monkeypatch.setattr("repositories.credential_approvals.CredentialApprovalRepo.admit", AsyncMock(return_value=None))
    return await run_node_operation(node_type="automation-voiceflow", operation=operation, arguments=arguments or {}, user_id=USER, credential_id=CID, pool=object())


@pytest.mark.asyncio
async def test_actual_connect_evidence_requires_current_project_workspace_and_environment(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    from nodes.core.credential_connect import validate_for_connect
    match = True
    def response(request):
        result = witnessed(request)
        if not match and request.url.path.startswith("/v1/stable/project/"):
            return httpx.Response(200, json={"project": {**PROJECT, "workspaceID": "foreign"}})
        return result
    transport(monkeypatch, response)
    evidence = await collect_evidence(node_type="automation-voiceflow", credential_data=dict(KEY), user_id=USER)
    assert evidence.reachable is True and evidence.account_label == PROJECT["name"]
    monkeypatch.setattr("nodes.core.credential_connect._collect_evidence", collect_evidence)
    verdict = await validate_for_connect(credential_type="voiceflow_pat", credential_data=dict(KEY), user_id=USER)
    assert verdict.ok and verdict.evidence.account_label == PROJECT["name"]
    match = False
    evidence = await collect_evidence(node_type="automation-voiceflow", credential_data=dict(KEY), user_id=USER)
    assert evidence.reachable is not True and evidence.account_label is None


@pytest.mark.asyncio
async def test_actual_metadata_patch_and_delete_have_exact_body_and_readback(monkeypatch):
    state, writes = dict(DOCUMENT), []
    deleted = False
    def response(request):
        nonlocal deleted
        result = witnessed(request)
        if result is not None:
            return result
        if request.method == "PATCH":
            body = json.loads(request.content)
            assert body == {"metadata": [{"key": "topic", "values": ["changed"]}]}
            writes.append(request)
            state["metadata"] = body["metadata"]
            return httpx.Response(200, json={"message": "Updated"})
        if request.method == "DELETE":
            assert not request.content
            writes.append(request)
            deleted = True
            return httpx.Response(200, json={"message": "Deleted"})
        if request.url.path == "/v1/stable/document":
            return httpx.Response(200, json={"documents": [] if deleted else [state]})
        return httpx.Response(200, json={"document": state})
    transport(monkeypatch, response)
    result = await native_operation(monkeypatch, "update_document_metadata", {"document_id": DOCUMENT["id"], "metadata_json": '[{"key":"topic","values":["changed"]}]'})
    assert result["data"]["readback_verified"] is True and result["data"]["document"]["metadata"][0]["values"] == ["changed"]
    assert "PRIVATE_" not in str(result) and "url" not in result["data"]["document"]
    result = await native_operation(monkeypatch, "delete_document", {"document_id": DOCUMENT["id"], "confirm_delete": "DELETE_SELECTED_DOCUMENT"})
    assert result["data"] == {"deleted_document_id": DOCUMENT["id"], "readback_verified": True}
    assert len(writes) == 2


@pytest.mark.asyncio
async def test_wrong_document_target_refuses_before_patch(monkeypatch):
    requests = []
    def response(request):
        requests.append(request)
        return witnessed(request) or httpx.Response(200, json={"document": {**DOCUMENT, "id": "foreign"}})
    transport(monkeypatch, response)
    result = await native_operation(monkeypatch, "update_document_metadata", {"document_id": DOCUMENT["id"], "metadata_json": "[]"})
    assert result["status"] == "error" and all(request.method == "GET" for request in requests)


@pytest.mark.asyncio
async def test_retrieval_only_sends_no_model_and_filters_private_sources(monkeypatch):
    def response(request):
        result = witnessed(request)
        if result is not None:
            return result
        assert request.method == "POST" and request.url.path == "/v1/stable/knowledge-base/query"
        assert json.loads(request.content) == {"question": "Owned fixture?", "version": "draft", "synthesis": False, "chunkLimit": 1}
        return httpx.Response(200, json={"answer": {"output": None, "answerTokens": 0, "chunks": [{"chunkID": "chunk-one", "documentID": DOCUMENT["id"], "score": 0.8,
            "content": "Owned bounded fixture", "source": DOCUMENT["data"], "metadata": {"private": "PRIVATE_METADATA"}}]}})
    transport(monkeypatch, response)
    result = await native_operation(monkeypatch, "query_knowledge_base", {"question": "Owned fixture?", "chunk_limit": 1})
    assert result["data"]["synthesis"] is False and result["data"]["chunks"][0]["content"] == "Owned bounded fixture"
    assert "PRIVATE_" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,uncertain", [(200, True), (201, True), (202, True), (204, True), (403, False), (429, True), (503, True)])
async def test_write_status_uncertainty_no_replay_and_provider_privacy(monkeypatch, status, uncertain):
    calls = []
    def response(request):
        result = witnessed(request)
        if result is not None:
            return result
        if request.method == "PATCH":
            calls.append(request)
            return httpx.Response(status, json={"statusCode": 403 if status == 200 else status, "message": KEY["personal_access_token"] + " PRIVATE_PAYLOAD"})
        return httpx.Response(200, json={"document": DOCUMENT})
    transport(monkeypatch, response)
    result = await native_operation(monkeypatch, "update_document_metadata", {"document_id": DOCUMENT["id"], "metadata_json": "[]"})
    assert result["status"] == "error" and result["write_outcome_uncertain"] is uncertain and len(calls) == 1
    assert "PRIVATE_" not in str(result) and KEY["personal_access_token"] not in str(result)


@pytest.mark.asyncio
async def test_actual_list_and_picker_refetch_whole_collection_without_provider_paging(monkeypatch):
    list_requests = []
    def response(request):
        result = witnessed(request)
        if result is not None:
            return result
        assert request.url.path == "/v1/stable/document"
        assert set(request.url.params) == {"projectID", "environmentAlias"}
        list_requests.append(request)
        return httpx.Response(200, json={"documents": [DOCUMENT, {**DOCUMENT, "id": "document-two"}]})
    transport(monkeypatch, response)
    first = await native_operation(monkeypatch, "list_documents", {"limit": 1})
    second = await native_operation(monkeypatch, "list_documents", {"limit": 1, "page_token": first["data"]["next_page_token"]})
    assert first["data"]["total"] == 2 and second["data"]["items"][0]["id"] == "document-two"
    key = dict(KEY)
    options = await VoiceflowNode.load_field_options("document_id", key)
    assert len(options["options"]) == 2 and options["pagination_mode"].startswith("local")
    assert len(list_requests) == 3


def test_local_collection_pages_bind_credential_query_and_snapshot_without_provider_cursor():
    rows = [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}]
    key = dict(KEY)
    first = wire.local_page(rows, data=key, purpose="list_documents", limit=1)
    token = first["next_page_token"]
    second = wire.local_page(rows, data=key, purpose="list_documents", limit=1, token=token)
    assert second["items"][0]["id"] == "b" and second["next_page_token"] is None
    assert first["pagination_mode"].startswith("local")
    for replacement, purpose, changed_rows in (({**key, "environment_alias": "foreign"}, "list_documents", rows),
        ({**key, "personal_access_token": "vfp_OTHER_SYNTHETIC_TOKEN"}, "list_documents", rows),
        (key, "picker-document_id", rows), (key, "list_documents", rows + [{"id": "c", "name": "C"}])):
        with pytest.raises(ValueError):
            wire.local_page(changed_rows, data=replacement, purpose=purpose, limit=1, token=token)
    with pytest.raises(ValueError):
        wire.selected_collection({"documents": [], "nextPageToken": "invented"}, "documents", lambda row: row)


def test_models_body_errors_and_bounded_json_keep_tokens_private():
    with pytest.raises(ValueError) as caught:
        VoiceflowPATCredential.model_validate({**KEY, "project_id": "https://foreign/" + KEY["personal_access_token"]})
    assert KEY["personal_access_token"] not in str(caught.value)
    for operation in ("create_text_document", "run_agent", "publish_environment"):
        with pytest.raises(ValueError):
            VoiceflowFullConfig.model_validate({"config": {"operation": operation}})
    for payload in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}', b' ' * (wire.MAX_BODY + 1)):
        with pytest.raises(ValueError):
            wire.parse_json(payload)
    with pytest.raises(ValueError):
        parse_metadata('[],"injected_field":"unapproved"')
    with pytest.raises(ValueError):
        wire.safe_selected({"name": KEY["personal_access_token"]}, KEY)
