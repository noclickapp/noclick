"""Contract wire checks with synthetic data; no DocSpace account is used."""
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import onlyoffice_docspace_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-docspace-personal-token"
CREDENTIAL = {"credential_type": "onlyoffice_docspace_token", "base_url": "https://portal.onlyoffice.com", "access_token": TOKEN}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="docspace-test", node_type=native.NODE_TYPE,
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, body=None, status=200):
    calls = []
    def reply(request):
        calls.append(request)
        return httpx.Response(status, json=body if body is not None else {"response": {"id": 9846}, "status": 0, "statusCode": 200})
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


# These paths and bodies follow the pinned DocSpace 3.6 OpenAPI operations.
CASES = [
    ({"operation": "get_profile"}, "GET", "/people/@self", None),
    ({"operation": "list_users"}, "GET", "/people", None),
    ({"operation": "list_my_documents"}, "GET", "/files/@my", None),
    ({"operation": "list_rooms"}, "GET", "/files/rooms", None),
    ({"operation": "get_room", "room_id": 9846}, "GET", "/files/rooms/9846", None),
    ({"operation": "create_room", "title": "Team", "room_type": "EditingRoom"}, "POST", "/files/rooms", {"title": "Team", "roomType": "EditingRoom"}),
    ({"operation": "rename_room", "room_id": 9846, "title": "Team"}, "PUT", "/files/rooms/9846", {"title": "Team"}),
    ({"operation": "get_folder", "folder_id": 9846}, "GET", "/files/folder/9846", None),
    ({"operation": "list_folder_contents", "folder_id": 9846}, "GET", "/files/9846", None),
    ({"operation": "create_folder", "folder_id": 9846, "title": "Team"}, "POST", "/files/folder/9846", {"title": "Team"}),
    ({"operation": "rename_folder", "folder_id": 9846, "title": "Team"}, "PUT", "/files/folder/9846", {"title": "Team"}),
    ({"operation": "get_folder_path", "folder_id": 9846}, "GET", "/files/folder/9846/path", None),
    ({"operation": "get_file", "file_id": 9846}, "GET", "/files/file/9846", None),
    ({"operation": "rename_file", "file_id": 9846, "title": "Team.txt"}, "PUT", "/files/file/9846", {"title": "Team.txt"}),
    ({"operation": "list_file_versions", "file_id": 9846}, "GET", "/files/file/9846/history", None),
    ({"operation": "list_file_history", "file_id": 9846}, "GET", "/files/file/9846/log", None),
    ({"operation": "create_text_file", "title": "Team.txt", "content": "Hello", "create_new_if_exist": False}, "POST", "/files/@my/text", {"title": "Team.txt", "content": "Hello", "createNewIfExist": False}),
    ({"operation": "list_room_access", "room_id": 9846}, "GET", "/files/rooms/9846/share", None),
    ({"operation": "list_file_access", "file_id": 9846}, "GET", "/files/file/9846/share", None),
    ({"operation": "list_folder_access", "folder_id": 9846}, "GET", "/files/folder/9846/share", None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_onlyoffice_docspace_exact_contract_requests(monkeypatch, config, method, path, body):
    calls = transport(monkeypatch, {"response": {"files": [], "folders": [{"id": 9846, "title": "Team"}]}})
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert len(calls) == 1
    request = calls[0]
    assert request.method == method and request.url.path == "/api/2.0" + path
    assert request.url.host == "portal.onlyoffice.com"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert (json.loads(request.content) if request.content else None) == body
    paginated = config["operation"] in {"list_users", "list_my_documents", "list_rooms", "list_folder_contents", "list_file_history", "list_room_access", "list_file_access", "list_folder_access"}
    assert dict(request.url.params) == ({"count": "50", "startIndex": "0"} if paginated else {})
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_onlyoffice_docspace_page_and_evidence(monkeypatch):
    calls = transport(monkeypatch, {"response": {"folders": [{"id": 9, "title": "Finance"}], "files": None, "total": 101}})
    result = await node({"operation": "list_rooms", "count": 10, "start_index": 20}).execute({})
    assert result["items"] == [{"id": 9, "title": "Finance"}]
    assert dict(calls[0].url.params) == {"count": "10", "startIndex": "20"}
    assert result["page_size"] == 10 and result["start_index"] == 20
    assert native.OnlyofficeDocspaceNode.connection_evidence.identity_operation == "get_profile"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"error": TOKEN}), (302, {}), (200, {"error": {"message": TOKEN}}), (200, []), (200, {"response": {}, "statusCode": 403})])
async def test_onlyoffice_docspace_rejects_errors_without_echo_or_retry(monkeypatch, status, body):
    calls = transport(monkeypatch, body, status)
    with pytest.raises(ValueError) as caught:
        await node({"operation": "get_profile"}).execute({})
    assert len(calls) == 1 and TOKEN not in str(caught.value)


@pytest.mark.parametrize("url", ["http://portal.onlyoffice.com", "https://user:password@portal.onlyoffice.com", "https://portal.onlyoffice.com/api/2.0", "https://portal.onlyoffice.com?x=1", "https://portal.onlyoffice.com/#fragment"])
def test_onlyoffice_docspace_invalid_portal(url):
    with pytest.raises(ValidationError):
        native.OnlyofficeDocspaceTokenCredential.model_validate({**CREDENTIAL, "base_url": url})


def test_onlyoffice_docspace_manual_credentials_and_invalid_config():
    value = native.OnlyofficeDocspaceTokenCredential(base_url=CREDENTIAL["base_url"], access_token=TOKEN)
    assert value.credential_type == CREDENTIAL["credential_type"]
    for config in [{"operation": "get_file", "file_id": -1}, {"operation": "create_room", "title": "A", "room_type": 3}, {"operation": "create_folder", "folder_id": 1, "title": "x" * 166}, {"operation": "list_rooms", "count": 101}]:
        assert not native.OnlyofficeDocspaceNode.validate_config({"config": config, "credentials": CREDENTIAL})["valid"]
