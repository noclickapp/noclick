"""Exercise PowerPoint's native factory against fixture-only Graph requests.

These checks pin verbs, paths, payloads, pagination metadata and asynchronous
copy semantics without connecting to an account or modifying remote files.
"""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import microsoft_powerpoint_node as node
from nodes.core.run_op import run_node_operation

AUTH = {"credential_type": "microsoft_onedrive_oauth", "access_token": "fixture-token",
    "refresh_token": "fixture-refresh", "expires_at": "2099-01-01T00:00:00Z", "email": "fixture@example.test"}
IDS = {"drive_id": "drive1", "presentation_id": "deck1"}
ITEM = "/drives/drive1/items/deck1"
FIXTURE = json.loads((Path(__file__).parent / "fixtures/microsoft-powerpoint/responses.json").read_text())
DOCUMENTED = json.loads((Path(__file__).parent / "fixtures/microsoft-powerpoint/documented_responses.json").read_text())

CASES = [
    ("get_account", {}, "GET", "/me", None, "account"),
    ("get_my_drive", {}, "GET", "/me/drive", None, "drive"),
    ("get_root_folder", {"drive_id": "drive1"}, "GET", "/drives/drive1/root", None, "folder"),
    ("list_presentations", {"drive_id": "drive1", "folder_id": "folder1", "top": 25}, "GET", "/drives/drive1/items/folder1/children", None, "children"),
    ("get_presentation", IDS, "GET", ITEM, None, "presentation"),
    ("rename_presentation", {**IDS, "name": "Renamed.pptx"}, "PATCH", ITEM, {"name": "Renamed.pptx"}, "presentation"),
    ("move_presentation", {**IDS, "folder_id": "folder2"}, "PATCH", ITEM, {"parentReference": {"id": "folder2"}}, "presentation"),
    ("copy_presentation", {**IDS, "folder_id": "folder2", "name": "Copy.pptx"}, "POST", ITEM + "/copy", {"name": "Copy.pptx", "parentReference": {"driveId": "drive1", "id": "folder2"}}, "copy"),
    ("delete_presentation", IDS, "DELETE", ITEM, None, "empty"),
    ("preview_presentation", IDS, "POST", ITEM + "/preview", {}, "preview"),
    ("create_share_link", {**IDS, "link_type": "view", "link_scope": "organization"}, "POST", ITEM + "/createLink", {"type": "view", "scope": "organization"}, "permission"),
    ("list_permissions", IDS, "GET", ITEM + "/permissions", None, "permissions"),
    ("get_permission", {**IDS, "permission_id": "perm1"}, "GET", ITEM + "/permissions/perm1", None, "permission"),
    ("update_permission", {**IDS, "permission_id": "perm1", "role": "write"}, "PATCH", ITEM + "/permissions/perm1", {"roles": ["write"]}, "permission"),
    ("delete_permission", {**IDS, "permission_id": "perm1"}, "DELETE", ITEM + "/permissions/perm1", None, "empty"),
    ("list_versions", IDS, "GET", ITEM + "/versions", None, "versions"),
    ("get_version", {**IDS, "version_id": "1.0"}, "GET", ITEM + "/versions/1.0", None, "version"),
    ("restore_version", {**IDS, "version_id": "1.0"}, "POST", ITEM + "/versions/1.0/restoreVersion", None, "empty"),
    ("list_thumbnails", IDS, "GET", ITEM + "/thumbnails", None, "thumbnails"),
]


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    native = httpx.AsyncClient

    def send(request):
        requests.append(request)
        assert request.url.host == "graph.microsoft.com"
        assert request.headers["Authorization"] == "Bearer fixture-token"
        return replies.pop(0)

    monkeypatch.setattr(node.httpx, "AsyncClient", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, args=None):
    return await run_node_operation(node_type=node.MicrosoftPowerPointNode.integration_type,
        operation=operation, arguments=deepcopy(args or {}), credential_data=deepcopy(AUTH),
        user_id="00000000-0000-4000-8000-000000000001")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args,method,path,body,fixture", CASES)
async def test_microsoft_powerpoint_native_operations(transport, operation, args, method, path, body, fixture):
    requests, replies = transport
    if fixture == "empty":
        replies.append(httpx.Response(204))
    elif fixture == "copy":
        replies.append(httpx.Response(202, headers={"Location": "https://tenant.sharepoint.com/monitor/123"}))
    else:
        replies.append(httpx.Response(200, json=FIXTURE[fixture]))
    result = await run(operation, args)
    assert len(requests) == 1 and not replies
    request = requests[0]
    assert request.method == method and request.url.path == "/v1.0" + path
    assert (json.loads(request.content) if request.content else None) == body
    if operation == "list_presentations":
        assert dict(request.url.params) == {"$top": "25"}
        assert [item["name"] for item in result["items"]] == ["Quarterly Review.pptx"]
        assert result["next_link"] == FIXTURE["children"]["@odata.nextLink"]
    elif fixture == "copy":
        assert result["status"] == "accepted"
        assert result["monitor_url"] == "https://tenant.sharepoint.com/monitor/123"
    else:
        assert result["status"] == "success"
        if node.OPERATIONS[operation].collection:
            assert result["items"] == FIXTURE[fixture]["value"]
        elif fixture != "empty":
            assert result["data"] == FIXTURE[fixture]


@pytest.mark.asyncio
async def test_microsoft_powerpoint_encodes_ids_without_changing_route(transport):
    requests, replies = transport
    replies.append(httpx.Response(200, json=FIXTURE["presentation"]))
    await run("get_presentation", {"drive_id": "drive/with?query", "presentation_id": "deck#?%/part"})
    assert requests[0].url.raw_path == b"/v1.0/drives/drive%2Fwith%3Fquery/items/deck%23%3F%25%2Fpart"
    assert not requests[0].url.query


@pytest.mark.asyncio
@pytest.mark.parametrize("code,message", [(401, "Access token is invalid"), (403, "Access denied"), (404, "Item not found"), (429, "Too many requests")])
async def test_microsoft_powerpoint_preserves_graph_error(transport, code, message):
    _, replies = transport
    replies.append(httpx.Response(code, json={"error": {"code": "fixture", "message": message}}))
    with pytest.raises(ValueError, match=message):
        await run("get_account")


@pytest.mark.asyncio
async def test_microsoft_powerpoint_rejects_redirect_and_malformed_collection(transport):
    requests, replies = transport
    replies.append(httpx.Response(302, headers={"Location": "https://example.test/steal"}))
    with pytest.raises(ValueError, match="redirect"):
        await run("get_account")
    assert len(requests) == 1
    replies.append(httpx.Response(200, json={"value": "invalid"}))
    with pytest.raises(ValueError, match="invalid collection"):
        await run("list_versions", IDS)


@pytest.mark.parametrize("name", ["../bad.pptx", "file.txt", "bad:name.pptx", "file.pptx\n"])
def test_microsoft_powerpoint_refuses_nonpresentation_names(name):
    with pytest.raises(ValidationError):
        node.CONFIG_MODELS["rename_presentation"](**IDS, name=name)


def test_microsoft_powerpoint_scopes_and_evidence_resolve():
    assert set(node.POWERPOINT_SCOPES) == set(node.OPERATIONS)
    assert node.MicrosoftPowerPointNode.connection_evidence.identity_operation == "get_account"
    credential = node.OneDriveOAuthCredential(**AUTH)
    assert credential.credential_type == "microsoft_onedrive_oauth"
    assert credential.model_fields["credential_type"].default == "microsoft_onedrive_oauth"
    extra = credential.model_config["json_schema_extra"]
    assert extra["x-oauth-provider"] == "microsoft"
    assert set(node.POWERPOINT_SCOPES.declared_scopes()) <= set(extra["x-oauth-scopes"])


@pytest.mark.asyncio
async def test_microsoft_powerpoint_connection_names_actual_account(transport):
    from nodes.core.connection_evidence import collect_evidence
    requests, replies = transport
    replies.append(httpx.Response(200, json=FIXTURE["account"]))
    evidence = await collect_evidence(node_type="automation-microsoft-powerpoint",
        user_id="00000000-0000-4000-8000-000000000001", credential_data=deepcopy(AUTH))
    assert evidence.reachable is True and evidence.account_label == "Fixture Account"
    assert len(requests) == 1 and requests[0].url.path == "/v1.0/me"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args,method,path,body,fixture", [case for case in CASES if case[-1] not in {"empty", "copy"}])
async def test_microsoft_powerpoint_parses_published_graph_responses(transport, operation, args, method, path, body, fixture):
    """The node accepts Microsoft's examples even when Graph's pin demands @odata.type."""
    if operation == "list_presentations":
        contract_path = "/drives/{drive-id}/items/{driveItem-id}/children"
    elif operation == "get_root_folder":
        contract_path = "/drives/{drive-id}/root"
    elif operation == "get_account":
        contract_path = "/me"
    elif operation == "get_my_drive":
        contract_path = "/me/drive"
    else:
        contract_path = path.replace("/drives/drive1/items/deck1", "/drives/{drive-id}/items/{driveItem-id}")
        contract_path = contract_path.replace("/permissions/perm1", "/permissions/{permission-id}").replace("/versions/1.0", "/versions/{driveItemVersion-id}")
    witness = DOCUMENTED[method + " " + contract_path]
    assert witness["source"].startswith("https://raw.githubusercontent.com/microsoftgraph/")
    requests, replies = transport
    replies.append(httpx.Response(200, json=witness["body"]))
    result = await run(operation, args)
    assert len(requests) == 1 and result["status"] == "success"
    if not node.OPERATIONS[operation].collection:
        assert result["data"] == witness["body"]


@pytest.mark.asyncio
async def test_microsoft_powerpoint_refresh_uses_shared_choke_point(monkeypatch):
    from nodes.core import oauth_refresh
    refresh = AsyncMock(return_value=AUTH)
    monkeypatch.setattr(oauth_refresh, "freshen_oauth_credential", refresh)
    assert await node.MicrosoftPowerPointNode.freshen_credential(AUTH) == AUTH
    assert refresh.await_args.kwargs["provider"] == "microsoft"
