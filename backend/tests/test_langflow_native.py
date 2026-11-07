"""Langflow factory, dispatcher and transport fixtures using staging shared helpers."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
import asyncio
import base64
import socket
import json
import logging

import httpx
import pytest
from nodes.core import registry
from nodes.core.base import ConfigValidationError
from nodes.core.connection_evidence import collect_evidence
from nodes.core.run_op import run_node_operation
from nodes.langflow_node import LangflowNode, KIND

USER = "00000000-0000-4000-8000-000000000001"
OWNER = "00000000-0000-4000-8000-000000000002"
ORG = "00000000-0000-4000-8000-000000000003"
CID = "00000000-0000-4000-8000-000000000004"
WORKFLOW = "00000000-0000-4000-8000-000000000005"
PROJECT = "00000000-0000-4000-8000-000000000006"
FLOW = "00000000-0000-4000-8000-000000000007"
FILE = "00000000-0000-4000-8000-000000000008"
CREDS = {"credential_type": KIND, "server_url": "https://langflow.example", "api_key": "synthetic-key"}
PROJECT_ROW = {"id": PROJECT, "name": "Owned Project", "parent_id": None, "auth_settings": {"secret": "private"}}
FLOW_ROW = {"id": FLOW, "name": "Empty", "folder_id": PROJECT, "is_component": False,
    "webhook": False, "mcp_enabled": False, "a2a_enabled": False, "access_type": "PRIVATE",
    "flow_type": "workflow",
    "data": {"nodes": [{"template": {"api_key": "flow-secret", "code": "private"}}]},
    "fs_path": "/private/server", "user_id": OWNER}
FILE_ROW = {"id": FILE, "name": "fixture", "size": 3, "path": "private-storage-path", "user_id": OWNER}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    import utils.ssrf as ssrf
    native = httpx.AsyncClient
    native_resolver = ssrf._resolve_host_addresses
    seen, replies, guards = [], [], []
    async def public_dns(host, port, **kwargs):
        assert host in {"langflow.example", "new.langflow.example"}
        guards.append((host, kwargs))
        return {"8.8.8.8"}
    def handle(request):
        seen.append(request)
        assert replies, "Unexpected Langflow request"
        code, payload = replies.pop(0)
        return httpx.Response(code, content=payload) if isinstance(payload, bytes) or payload is None else httpx.Response(code, json=payload)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        kwargs["transport"] = httpx.MockTransport(handle)
        return native(**kwargs)
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", public_dns)
    monkeypatch.setattr(ssrf.httpx, "AsyncClient", client)
    return SimpleNamespace(seen=seen, replies=replies, guards=guards, native_resolver=native_resolver)


def node(op, *, creds=None, **arguments):
    data = {"config": {"operation": op, **arguments}, "credentials": deepcopy(creds or CREDS)}
    return registry.NodeFactory.create_node("fixture", "automation-langflow", data, user_id=USER, organization_id=ORG)


def page(items, current=1, pages=1, total=None, size=50):
    return {"items": items, "page": current, "size": size, "pages": pages,
        "total": len(items) if total is None else total}


@pytest.mark.parametrize("bad", ["foreign", None, ""])
def test_factory_does_not_reconcile_foreign_authoritative_type(bad):
    data = {"config": {"operation": "list_projects"}, "credentials": {**CREDS, "credential_type": bad},
        "credentialIds": {KIND: CID}}
    with pytest.raises(ConfigValidationError):
        registry.NodeFactory.create_node("fixture", "automation-langflow", data)
    assert LangflowNode.validate_config(data)["valid"] is False


@pytest.mark.parametrize("origin", ["http://langflow.example", "https://localhost", "https://127.0.0.1",
    "https://10.0.0.1", "https://@langflow.example", "https://langflow.example/api",
    "https://langflow.example?api_key=private", "https://langflow.example\\evil"])
def test_owned_origin_is_strict(origin):
    with pytest.raises(ConfigValidationError):
        node("list_projects", creds={**CREDS, "server_url": origin})


@pytest.mark.parametrize("op,args", [("list_flows", {"page_size": True}), ("get_flow", {"project_id": PROJECT, "flow_id": "../x"}),
    ("delete_project", {"project_id": PROJECT, "confirm_delete": False}),
    ("upload_file", {"name": "_mcp_servers_x.json", "content_base64": "e30="}),
    ("upload_file", {"name": "x.txt", "content_base64": "https://private.example/file"})])
def test_strict_inputs(op, args):
    with pytest.raises(ConfigValidationError):
        node(op, **args)


@pytest.mark.asyncio
async def test_actual_dispatcher_header_transport_projection_and_empty(transport):
    transport.replies.extend([(200, [PROJECT_ROW]), (200, [])])
    result = await run_node_operation(node_type="automation-langflow", operation="list_projects", arguments={},
        credential_data=CREDS, user_id=USER, organization_id=ORG)
    assert result["data"]["projects"] == [{"id": PROJECT, "name": "Owned Project", "parent_id": None}]
    request = transport.seen[0]
    assert str(request.url) == CREDS["server_url"] + "/api/v1/projects/"
    assert request.headers["x-api-key"] == "synthetic-key" and "Authorization" not in request.headers
    assert "synthetic-key" not in str(request.url) + json.dumps(result)
    assert transport.guards
    assert (await node("list_projects").execute({}))["data"]["projects"] == []


@pytest.mark.asyncio
async def test_private_dns_is_rejected_before_transport(monkeypatch, transport):
    import utils.ssrf as ssrf
    monkeypatch.setattr(ssrf, "allow_private_hosts", lambda: False)
    # Keep the real resolver's public-IP validation; mock only the DNS answer.
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", transport.native_resolver)
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=[
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 443)),
    ]))
    with pytest.raises(ValueError):
        await node("list_projects").execute({})
    assert not transport.seen


@pytest.mark.asyncio
async def test_page_binding_project_envelope_and_private_flow_projection(transport):
    transport.replies.append((200, page([FLOW_ROW], pages=2, total=2)))
    first = await node("list_flows", project_id=PROJECT, components_only=False).execute({})
    query = dict(transport.seen[0].url.params)
    assert query["folder_id"] == PROJECT and "project_id" not in query
    assert query["get_all"] == "false" and query["components_only"] == "false"
    token = first["data"]["next_page_token"]
    assert PROJECT not in token and "synthetic-key" not in token
    assert all(secret not in json.dumps(first) for secret in ("flow-secret", "/private/server", OWNER, "template"))
    transport.replies.append((200, page([FLOW_ROW], current=2, pages=2, total=2)))
    await node("list_flows", project_id=PROJECT, page_token=token).execute({})
    assert transport.seen[-1].url.params["page"] == "2"
    before = len(transport.seen)
    with pytest.raises(ValueError):
        await node("list_flows", project_id=OWNER, page_token=token).execute({})
    assert len(transport.seen) == before
    transport.replies.append((200, {"folder": PROJECT_ROW, "flows": page([FLOW_ROW])}))
    project = await node("get_project", project_id=PROJECT).execute({})
    assert project["data"]["id"] == PROJECT and project["data"]["flows"]["items"][0]["id"] == FLOW
    assert "auth_settings" not in json.dumps(project)
    assert dict(transport.seen[-1].url.params) == {"page": "1", "size": "50"}
    transport.replies.append((200, {"folder": PROJECT_ROW, "flows": page([FLOW_ROW])}))
    await node("get_project", project_id=PROJECT, search="Empty").execute({})
    assert transport.seen[-1].url.params["search"] == "Empty"


@pytest.mark.asyncio
async def test_parent_scoped_flow_and_picker(transport):
    transport.replies.extend([(200, FLOW_ROW), (200, page([FLOW_ROW], size=100))])
    assert (await node("get_flow", project_id=PROJECT, flow_id=FLOW).execute({}))["data"]["id"] == FLOW
    options = await LangflowNode.load_field_options("flow_id", CREDS, context={"project_id": PROJECT})
    assert options["options"] == [{"value": FLOW, "label": "Empty"}]
    transport.replies.append((200, {**FLOW_ROW, "folder_id": OWNER}))
    with pytest.raises(ValueError):
        await node("delete_flow", project_id=PROJECT, flow_id=FLOW, confirm_delete=True).execute({})
    assert transport.seen[-1].method == "GET"


@pytest.mark.asyncio
async def test_project_crud_flow_crud_and_real_creator_paths(transport):
    transport.replies.extend([(201, PROJECT_ROW), (200, PROJECT_ROW), (201, {**FLOW_ROW, "data": {"nodes": [], "edges": []}}),
        (200, FLOW_ROW), (200, {**FLOW_ROW, "description": None}), (200, FLOW_ROW),
        (200, {"message": "Flow deleted successfully"}), (204, None)])
    created_project = await node("create_project", name="Owned Project").execute({})
    assert json.loads(transport.seen[0].content) == {"name": "Owned Project"}
    await node("update_project", project_id=PROJECT, name="Renamed").execute({})
    assert json.loads(transport.seen[1].content) == {"name": "Renamed"}
    created_flow = await node("create_empty_flow", project_id=PROJECT, name="Empty").execute({})
    body = json.loads(transport.seen[2].content)
    assert body["data"] == {"nodes": [], "edges": []}
    assert body["folder_id"] == PROJECT and body["access_type"] == "PRIVATE"
    assert all(body[flag] is False for flag in ("webhook", "mcp_enabled", "a2a_enabled"))
    from nodes.agent.node_op_tools import resource_creators, extract_resource_id_from_output
    creators = {item[0]: item for item in resource_creators("automation-langflow")}
    assert extract_resource_id_from_output(created_project, creators["create_project"][2]) == PROJECT
    assert extract_resource_id_from_output(created_flow, creators["create_empty_flow"][2]) == FLOW
    await node("update_flow_metadata", project_id=PROJECT, flow_id=FLOW, description=None).execute({})
    assert json.loads(transport.seen[4].content) == {"description": None}
    deleted = await node("delete_flow", project_id=PROJECT, flow_id=FLOW, confirm_delete=True).execute({})
    assert deleted["data"]["project_id"] == PROJECT
    deleted_project = await node("delete_project", project_id=PROJECT, confirm_delete=True).execute({})
    assert deleted_project["http_status"] == 204 and deleted_project["data"]["id"] == PROJECT


@pytest.mark.asyncio
async def test_file_multipart_name_query_privacy_reserved_denial_and_ack(transport, caplog):
    caplog.set_level(logging.DEBUG)
    transport.replies.extend([(201, FILE_ROW), (200, [FILE_ROW]), (200, FILE_ROW),
        (200, [FILE_ROW]), (200, {"detail": "File fixture deleted successfully"})])
    created = await node("upload_file", name="fixture.txt", content_base64=base64.b64encode(b"abc").decode()).execute({})
    request = transport.seen[0]
    assert request.headers["Content-Type"].startswith("multipart/form-data; boundary=")
    assert b'name="file"; filename="fixture.txt"' in request.content and b"abc" in request.content
    assert dict(request.url.params) == {"append": "false", "ephemeral": "false"}
    assert created["data"] == {"id": FILE, "name": "fixture", "size": 3}
    from nodes.agent.node_op_tools import resource_creators, extract_resource_id_from_output
    creator = {item[0]: item for item in resource_creators("automation-langflow")}["upload_file"]
    assert extract_resource_id_from_output(created, creator[2]) == FILE
    await node("rename_file", file_id=FILE, name="private-name.txt").execute({})
    assert transport.seen[2].url.params["name"] == "private-name.txt" and transport.seen[2].content == b""
    assert "private-name.txt" not in caplog.text and "synthetic-key" not in caplog.text
    assert (await node("delete_file", file_id=FILE, confirm_delete=True).execute({}))["data"] == {"id": FILE, "deleted": True}
    transport.replies.append((200, [{**FILE_ROW, "name": "_mcp_servers_" + USER}]))
    count = len(transport.seen)
    with pytest.raises(ValueError):
        await node("delete_file", file_id=FILE, confirm_delete=True).execute({})
    assert len(transport.seen) == count + 1 and transport.seen[-1].method == "GET"


@pytest.mark.asyncio
@pytest.mark.parametrize("code,payload", [(302, {}), (401, {"detail": "synthetic-key"}), (429, b"private"),
    (500, b"private"), (200, b"NaN"), (200, {"error": "synthetic-key"}), (200, [{"id": True}]),
    (200, b"x" * (2 * 1024 * 1024 + 1)), (200, [])])
async def test_secret_safe_errors_and_legitimate_empty(transport, code, payload):
    transport.replies.append((code, payload))
    if code == 200 and payload == []:
        assert (await node("list_projects").execute({}))["data"]["projects"] == []
        return
    with pytest.raises((ValueError, httpx.HTTPStatusError)) as exc:
        await node("list_projects").execute({})
    assert "synthetic-key" not in str(exc.value) and "private" not in str(exc.value)


@pytest.mark.asyncio
async def test_saved_key_uses_staging_resolver_with_trusted_context(monkeypatch, transport):
    import nodes.core.run_op
    resolver = AsyncMock(return_value={**CREDS, "api_key": "latest-key", "server_url": "https://new.langflow.example"})
    monkeypatch.setattr(nodes.core.run_op, "resolve_operation_credential", resolver)
    instance = node("list_projects")
    pool = object()
    instance.node_data.update(credential_id=CID, _approval_pool=pool)
    instance.workflow_id = WORKFLOW
    transport.replies.append((200, []))
    await instance.execute({})
    assert transport.seen[0].headers["x-api-key"] == "latest-key"
    assert transport.seen[0].url.host == "new.langflow.example"
    for call in resolver.call_args_list:
        assert call.args == (CID, USER, pool)
        assert call.kwargs == {"organization_id": ORG, "workflow_id": WORKFLOW}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["unavailable", "foreign"])
async def test_saved_credential_resolver_denial_before_transport(monkeypatch, transport, failure):
    import nodes.core.run_op
    resolver = AsyncMock(side_effect=ValueError("unavailable")) if failure == "unavailable" else AsyncMock(return_value={**CREDS, "credential_type": "foreign"})
    monkeypatch.setattr(nodes.core.run_op, "resolve_operation_credential", resolver)
    instance = node("list_projects")
    instance.node_data.update(credential_id=CID, _approval_pool=object())
    with pytest.raises(ValueError):
        await instance.execute({})
    assert not transport.seen


@pytest.mark.asyncio
async def test_missing_caller_preparsed_guard_actual_admission_and_access_tristate(monkeypatch, transport):
    instance = node("list_projects")
    instance.node_data["credential_id"] = CID
    instance.user_id = None
    with pytest.raises(ValueError, match="caller"):
        await instance.execute({})
    instance = node("list_projects")
    instance.node_data["credentials"]["credential_type"] = "foreign"
    with pytest.raises(ValueError):
        await instance.execute({})
    import utils.credential_approval
    pending = {"success": False, "executed": False, "_halt_downstream": True, "approval_required": True}
    monkeypatch.setattr(utils.credential_approval, "admit_node", AsyncMock(return_value=pending))
    assert await node("list_projects").run({}) == pending
    import nodes.core.run_op
    monkeypatch.setattr(nodes.core.run_op, "resolve_operation_credential", AsyncMock(return_value=CREDS))
    evidence = await collect_evidence(node_type="automation-langflow", credential_id=CID, user_id=USER, organization_id=ORG)
    assert evidence.reachable is None and evidence.account_label is None and not evidence.samples
    context = SimpleNamespace(run_operation=AsyncMock(return_value=pending))
    assert (await LangflowNode.validate_credential_access(CREDS, validation_context=context))["valid"] is None
    assert not transport.seen


@pytest.mark.asyncio
async def test_actual_empty_probe_is_reachability_without_identity(transport):
    transport.replies.append((200, []))
    result = await node("check_connection").execute({})
    assert result["data"] == {"management_api_reachable": True, "project_count": 0}
    assert LangflowNode.connection_evidence.proves == "reachability"
    context = SimpleNamespace(run_operation=AsyncMock(return_value=result))
    assert (await LangflowNode.validate_credential_access(CREDS, validation_context=context))["valid"] is True

@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"items": [FLOW_ROW], "page": 1, "size": True, "pages": 1, "total": 1},
    {"items": [FLOW_ROW], "page": 2, "size": 50, "pages": 2, "total": 2},
    {"items": [], "page": 1, "size": 50, "pages": "1", "total": 0},
])
async def test_malformed_paging_is_rejected(transport, payload):
    transport.replies.append((200, payload))
    with pytest.raises(ValueError):
        await node("list_flows", project_id=PROJECT).execute({})


@pytest.mark.asyncio
async def test_rotated_key_between_flow_parent_check_and_write_is_denied(monkeypatch, transport):
    import nodes.core.run_op
    loads = []
    async def load(*args, **kwargs):
        # execute's current load, then scoped GET, then attempted PATCH reload.
        loads.append(1)
        return {**CREDS, "api_key": "old" if len(loads) <= 2 else "new"}
    monkeypatch.setattr(nodes.core.run_op, "resolve_operation_credential", load)
    instance = node("update_flow_metadata", project_id=PROJECT, flow_id=FLOW, name="Renamed")
    instance.node_data.update(credential_id=CID, _approval_pool=object())
    transport.replies.append((200, FLOW_ROW))
    with pytest.raises(ValueError, match="changed"):
        await instance.execute({})
    assert len(transport.seen) == 1 and transport.seen[0].method == "GET"


@pytest.mark.asyncio
@pytest.mark.parametrize("ack", [
    {"message": "File deleted successfully"},
    {"detail": "File fixture deleted successfully"},
])
async def test_file_delete_documented_and_legacy_acknowledgements(transport, ack):
    # https://docs.langflow.org/api-files, DELETE /api/v2/files/{file_id}.
    transport.replies.extend([(200, [FILE_ROW]), (200, ack)])
    result = await node("delete_file", file_id=FILE, confirm_delete=True).execute({})
    assert result["data"] == {"id": FILE, "deleted": True}
    assert transport.seen[-1].method == "DELETE"


@pytest.mark.asyncio
@pytest.mark.parametrize("ack", [{}, {"message": "All files deleted successfully"},
    {"message": "File deletion failed"}, {"detail": True}, []])
async def test_file_delete_requires_explicit_single_file_acknowledgement(transport, ack):
    transport.replies.extend([(200, [FILE_ROW]), (200, ack)])
    with pytest.raises(ValueError, match="acknowledge"):
        await node("delete_file", file_id=FILE, confirm_delete=True).execute({})
