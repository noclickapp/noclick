"""WorkDrive requests and provider-published response fixtures, without an account."""
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
import respx
from pydantic import ValidationError

from nodes.core.registry import NODE_REGISTRY
from nodes.oauth.zoho_work_drive_oauth import OAUTH_PROVIDER
from nodes.zoho_work_drive_node import (
    OPS, OP_MODELS, ZohoWorkDriveConfig, ZohoWorkDriveNode,
    ZohoWorkDriveOAuthCredential, workdrive_request,
)

BASE = "https://www.zohoapis.com/workdrive/api/v1"
FIXTURES = Path(__file__).parent / "fixtures" / "zoho-work-drive"
CREDENTIAL = dict(credential_type="zoho_work_drive_oauth", access_token="test-access-token",
    refresh_token="test-refresh-token", expires_at="2099-01-01T00:00:00+00:00",
    accounts_server="https://accounts.zoho.com", api_domain="https://www.zohoapis.com")


@pytest.fixture(autouse=True)
def transport(monkeypatch):
    monkeypatch.setattr("nodes.zoho_work_drive_node.guarded_async_client", httpx.AsyncClient)
    monkeypatch.setattr("utils.ssrf.guarded_async_client", httpx.AsyncClient)


def node(operation, **values):
    return ZohoWorkDriveNode(node_id="wd", node_type="automation-zoho-work-drive",
        node_data={}, config=ZohoWorkDriveConfig(config=OP_MODELS[operation](**values),
            credentials=ZohoWorkDriveOAuthCredential(**CREDENTIAL)), user_id="u", workflow_id="w")


def test_discovery_scopes_and_schema():
    assert NODE_REGISTRY["automation-zoho-work-drive"] is ZohoWorkDriveNode
    assert set(ZohoWorkDriveNode.scope_registry._requirements) == set(OPS)
    assert len(OPS) == 23
    schema = ZohoWorkDriveNode.get_config_schema()
    assert len(schema["properties"]["config"]["oneOf"]) == 23
    credential = schema["$defs"]["ZohoWorkDriveOAuthCredential"]
    assert set(credential["x-oauth-scopes"]) == set(ZohoWorkDriveNode.scope_registry.declared_scopes())
    assert credential["x-oauth-provider"] == OAUTH_PROVIDER.provider


@pytest.mark.parametrize("operation,values,method,path,attributes", [
    ("create_folder", {"parent_id": "parent1", "name": "Collection"}, "POST", "/files", {"parent_id": "parent1", "name": "Collection"}),
    ("rename_file", {"resource_id": "file1", "name": "Budget"}, "PATCH", "/files/file1", {"name": "Budget"}),
    ("move_file", {"resource_id": "file1", "parent_id": "parent1"}, "PATCH", "/files/file1", {"parent_id": "parent1"}),
    ("trash_file", {"resource_id": "file1"}, "PATCH", "/files/file1", {"status": 51}),
    ("restore_file", {"resource_id": "file1"}, "PATCH", "/files/file1", {"status": 1}),
    ("copy_file", {"destination_id": "parent1", "source_id": "file1"}, "POST", "/files/parent1/copy", {"resource_id": "file1"}),
    ("create_comment", {"resource_id": "file1", "comment_html": "Fine"}, "POST", "/comments", {"resource_id": "file1", "comment_html": "Fine"}),
    ("edit_comment", {"comment_id": "file1-123", "comment_html": "Fine"}, "PATCH", "/comments/file1-123", {"comment_html": "Fine"}),
])
@respx.mock
async def test_write_wire_contract(operation, values, method, path, attributes):
    route = respx.route(method=method, url=BASE+path).mock(return_value=httpx.Response(200, json={"data": {"id": "result"}}))
    await node(operation, **values).execute({})
    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer test-access-token"
    assert request.headers["content-type"] == "application/vnd.api+json"
    assert json.loads(request.content) == {"data": {"type": "comments" if "comment" in operation else "files", "attributes": attributes}}


@pytest.mark.parametrize("operation,values,path", [
    ("get_user", {}, "/users/me"),
    ("list_teams", {"zuid": "747938014"}, "/users/747938014/teams"),
    ("get_team", {"team_id": "team1"}, "/teams/team1"),
    ("get_team_folder", {"teamfolder_id": "folder1"}, "/teamfolders/folder1"),
    ("get_file", {"resource_id": "file1"}, "/files/file1"),
    ("list_versions", {"resource_id": "file1"}, "/files/file1/versions"),
    ("list_comments", {"resource_id": "file1"}, "/files/file1/comments"),
    ("get_comment", {"comment_id": "file1-123"}, "/comments/file1-123"),
    ("list_links", {"resource_id": "file1"}, "/files/file1/links"),
    ("get_link", {"link_id": "link1"}, "/links/link1"),
])
@respx.mock
async def test_reads(operation, values, path):
    payload = json.loads((FIXTURES/"get-user-info.json").read_text())["body"]
    route = respx.get(BASE+path).mock(return_value=httpx.Response(200, json=payload))
    result = await node(operation, **values).execute({})
    assert result["data"] == payload
    assert route.call_count == 1
    assert not route.calls[0].request.content


@pytest.mark.parametrize("operation,values,path", [
    ("list_files", {"folder_id": "folder1"}, "/files/folder1/files"),
    ("list_team_folders", {"team_id": "team1"}, "/teams/team1/teamfolders"),
    ("search_files", {"team_id": "team1", "query": "annual report & budget"}, "/teams/team1/records"),
])
@respx.mock
async def test_pagination_and_encoded_search(operation, values, path):
    payload = {"data": [{"id": "file1"}], "links": {"next": "https://evil.example/next"}, "meta": {"has_next": True}}
    route = respx.get(BASE+path).mock(return_value=httpx.Response(200, json=payload))
    result = await node(operation, limit=25, offset=50, **values).execute({})
    params = dict(route.calls[0].request.url.params)
    assert params["page[limit]"] == "25" and params["page[offset]"] == "50"
    if operation == "search_files": assert params["search[all]"] == values["query"]
    assert result["data"] == payload
    assert route.call_count == 1


@pytest.mark.parametrize("operation,values,path", [
    ("delete_comment", {"comment_id": "comment1"}, "/comments/comment1"),
    ("revoke_link", {"link_id": "link1"}, "/links/link1"),
])
@respx.mock
async def test_empty_delete(operation, values, path):
    respx.delete(BASE+path).mock(return_value=httpx.Response(204))
    assert (await node(operation, **values).execute({}))["http_status"] == 204


@pytest.mark.parametrize("response", [
    httpx.Response(401, json={"errors": [{"title": "Invalid OAuth token"}]}),
    httpx.Response(200, json={"errors": [{"title": "Invalid OAuth token"}]}),
    httpx.Response(200, text="<html>login</html>"),
    httpx.Response(302, headers={"Location": "https://evil.example"}),
])
@respx.mock
async def test_failed_responses_refused(response):
    respx.get(BASE+"/users/me").mock(return_value=response)
    with pytest.raises(ValueError): await node("get_user").execute({})


@pytest.mark.parametrize("bad", ["../secret", "a/b", "a?b", "a#b", "a%2fb", "https://evil.example", ""])
def test_path_injection_refused(bad):
    with pytest.raises(ValidationError): node("get_file", resource_id=bad)


@pytest.mark.parametrize("bad", ["http://www.zohoapis.com", "https://evil.example", "https://www.zohoapis.com.evil.example", "https://www.zohoapis.com/path", "https://www.zohoapis.com:443"])
def test_api_origin_allowlist(bad):
    with pytest.raises(ValidationError): ZohoWorkDriveOAuthCredential(**{**CREDENTIAL, "api_domain": bad})


@respx.mock
async def test_oauth_identity_and_regional_refresh(monkeypatch):
    monkeypatch.setenv("ZOHO_WORK_DRIVE_CLIENT_ID", "client")
    monkeypatch.setenv("ZOHO_WORK_DRIVE_CLIENT_SECRET", "secret")
    context = {"accounts_server": "https://accounts.zoho.eu", "api_domain": "https://www.zohoapis.eu"}
    payload = json.loads((FIXTURES/"get-user-info.json").read_text())["body"]
    identity = respx.get("https://www.zohoapis.eu/workdrive/api/v1/users/me").mock(return_value=httpx.Response(200, json=payload))
    assert await OAUTH_PROVIDER.account_name("access", context=context) == "Zylker Creation"
    assert identity.calls[0].request.headers["authorization"] == "Bearer access"
    token = respx.post("https://accounts.zoho.eu/oauth/v2/token").mock(return_value=httpx.Response(200, json={"access_token": "new-access", "expires_in": 3600}))
    refreshed = await OAUTH_PROVIDER.bind_refresh({**CREDENTIAL, **context})("refresh")
    assert refreshed.access_token == "new-access"
    assert refreshed.refresh_token is None
    assert parse_qs(token.calls[0].request.content.decode())["grant_type"] == ["refresh_token"]


@pytest.mark.parametrize("status", [200, 401])
@respx.mock
async def test_error_token_echo_is_redacted(status):
    respx.get(BASE+"/users/me").mock(return_value=httpx.Response(status,
        json={"errors": [{"title": "Rejected test-access-token test-refresh-token"}]}))
    with pytest.raises(ValueError) as error:
        await node("get_user").execute({})
    assert "test-access-token" not in str(error.value)
    assert "test-refresh-token" not in str(error.value)
    assert "Rejected" in str(error.value)


@respx.mock
async def test_execute_refreshes_before_request(monkeypatch):
    calls = []
    async def fresh(**kwargs):
        calls.append(kwargs)
        kwargs["credential"]["access_token"] = "fresh-access"
    monkeypatch.setattr("nodes.core.oauth_refresh.ensure_fresh_oauth_token", fresh)
    route = respx.get(BASE+"/users/me").mock(return_value=httpx.Response(200, json={"data": {}}))
    await node("get_user").execute({})
    assert calls[0]["provider"] == "zoho_work_drive"
    assert calls[0]["additional_token_fields"] == OAUTH_PROVIDER.credential_fields
    assert route.calls[0].request.headers["authorization"] == "Bearer fresh-access"


@pytest.mark.parametrize("case", json.loads((FIXTURES/"documented-requests.json").read_text()), ids=lambda case: case["operation"])
@respx.mock
async def test_node_sends_provider_documented_request(case):
    operation = case["operation"]
    request_body = json.loads(json.dumps(case["body"]))
    if "status" in request_body["data"]["attributes"]:
        # Docs' example quotes the number; the parameter table and OAS type it as integer.
        request_body["data"]["attributes"]["status"] = int(request_body["data"]["attributes"]["status"])
    route = respx.route(method=OPS[operation].method, host="www.zohoapis.com").mock(return_value=httpx.Response(200, json={"data": {"id": "result"}}))
    await node(operation, **case["config"]).execute({})
    assert json.loads(route.calls[0].request.content) == request_body


@pytest.mark.parametrize("fixture,operation,values", [
    ("get-user-info", "get_user", {}),
    ("create-comment", "create_comment", {"resource_id": "ly9zm850678101cec4b0698777ab4534a3002", "comment_html": "Fine"}),
    ("rename-file-folder", "rename_file", {"resource_id": "ly9zm1d1ee3b833c1438a9232ad6ac77bc8f2", "name": "User screenshot"}),
    ("search-records", "search_files", {"team_id": "ly9zmae16b43c258f458a9a57ac02c4f8d763", "query": "Notes"}),
])
@respx.mock
async def test_documented_responses_are_preserved(fixture, operation, values):
    body = json.loads((FIXTURES/(fixture+".json")).read_text())["body"]
    respx.route(method=OPS[operation].method, host="www.zohoapis.com").mock(return_value=httpx.Response(200, json=body))
    result = await node(operation, **values).execute({})
    assert result["data"] == body
