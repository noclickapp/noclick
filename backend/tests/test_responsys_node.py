"""Native Responsys routes, metadata privacy and concrete write outcomes.

Prepared offline fixtures; no vendor account or network transport is used.
"""
import json
from urllib.parse import parse_qs

import httpx
import pytest

from nodes import responsys_node as native
from nodes.core.registry import NodeFactory

ENDPOINT = "https://owned-api.responsys.net"
TOKEN = "fixture-native-token-731"
USER = "11111111-1111-4111-8111-111111111111"
CID = "22222222-2222-4222-8222-222222222222"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def credential(**extra):
    return {"credential_type": "responsys_auth_token", "account_endpoint": ENDPOINT, "auth_token": TOKEN, **extra}


def node(operation, *, cred=None, selected=False, **arguments):
    data = {"config": {"operation": operation, **arguments}, "credentials": cred or credential()}
    if selected:
        data["credentialIds"] = {data["credentials"]["credential_type"]: CID}
    return NodeFactory.create_node("responsys-fixture", "automation-responsys", data, user_id=USER)


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], {}
    def handler(request):
        calls.append(request)
        key = (request.method, request.url.path)
        response = replies.get(key)
        if response is not None:
            return response(request) if callable(response) else httpx.Response(200, json=response)
        if key == ("GET", native.PREFIX + "/settings/account/endpoint"):
            return httpx.Response(200, json={"apiType": "rest", "endPoint": ENDPOINT})
        if key == ("GET", native.PREFIX + "/folders"):
            return httpx.Response(200, json={"folders": [{"id": 19, "name": "Owned", "accountId": 900}], "links": []})
        raise AssertionError("Unexpected native route: " + str(key))
    monkeypatch.setattr(native, "guarded_async_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kw))
    return calls, replies


async def test_actual_factory_account_pair_and_private_projection(transport):
    calls, replies = transport
    replies[("GET", native.PREFIX + "/settings/account")] = {
        "name": "Owned Account", "endpoint": ENDPOINT, "fileSystemLocation": "/private", "includedImages": ["secret"], "unsubscribeHandler": "https://private.test"}
    result = await node("get_account_settings").run({})
    assert result == {"status": "success", "data": {"name": "Owned Account"}}
    assert len(calls) == 2
    assert all(r.headers["Authorization"] == TOKEN for r in calls)
    assert all(r.url.host == "owned-api.responsys.net" for r in calls)


@pytest.mark.parametrize("origin", ["https://evil.test", "https://login2.responsys.net", "http://owned-api.responsys.net", ENDPOINT + "/rest", ENDPOINT + ":443", ENDPOINT + "?key=x", "https://owned-api.responsys.net.evil.test"])
def test_factory_rejects_unissued_account_route(origin):
    with pytest.raises(ValueError):
        node("list_folders", cred=credential(account_endpoint=origin))


@pytest.mark.parametrize("mutation", [{"auth_token": 17}, {"credential_type": "other_api_key"}, {"credential_type": None, "id": CID}])
def test_original_credential_tags_and_types_before_lens(mutation):
    with pytest.raises(ValueError):
        node("list_folders", cred=credential(**mutation), selected=True)


async def test_pending_resource_reference_builds_but_never_requests(transport):
    n = node("get_folder_content", folder_name="{{node_previous.data.folder_name}}")
    assert n.config.config.folder_name.startswith("{{")
    with pytest.raises(native.ResponsysError, match="Resolve"):
        await n.run({})
    assert transport[0] == []


async def test_pair_mismatch_stops_before_metadata(transport):
    calls, replies = transport
    replies[("GET", native.PREFIX + "/settings/account/endpoint")] = {"apiType": "rest", "endPoint": "https://other-api.responsys.net"}
    with pytest.raises(native.ResponsysError, match="different issued"):
        await node("list_folders").run({})
    assert len(calls) == 1


async def test_folder_page_and_foreign_next_url(transport):
    calls, replies = transport
    replies[("GET", native.PREFIX + "/folders")] = {"folders": [{"id": 19, "name": "Owned", "accountId": 900}], "links": [{"rel": "next", "href": native.PREFIX + "/folders?offset=200&limit=200", "method": "GET"}]}
    result = await node("list_folders").run({})
    assert result["data"] == {"items": [{"id": "19", "name": "Owned"}], "offset": 0, "next_offset": 200, "has_more": True}
    replies[("GET", native.PREFIX + "/folders")]["links"][0]["href"] = "https://evil.test/folders?offset=200"
    with pytest.raises(native.ResponsysError, match="outside"):
        await node("list_folders").run({})
    assert all(r.url.host == "owned-api.responsys.net" for r in calls)


async def test_folder_content_parent_collision_refused(transport):
    _, replies = transport
    replies[("GET", native.PREFIX + "/folders/Owned/content")] = {"riObjects": [{"id": 3, "name": "Foreign", "folderId": 20}], "links": []}
    with pytest.raises(native.ResponsysError, match="foreign folder"):
        await node("get_folder_content", folder_name="Owned").run({})


@pytest.mark.parametrize("items_envelope", [False, True])
async def test_documented_profile_inventory_shapes(transport, items_envelope):
    _, replies = transport
    rows = [{"name": "OwnedList", "fields": [{"fieldName": "CODE", "fieldType": "STR25", "private": "excluded"}], "records": [{"email": "private.test"}]}]
    replies[("GET", native.PREFIX + "/lists")] = {"items": rows} if items_envelope else rows
    result = await node("list_profile_lists").run({})
    assert result["data"] == {"items": [{"name": "OwnedList", "fields": [{"fieldName": "CODE", "fieldType": "STR25"}]}], "continuation_known": False}


async def test_ordinary_metadata_create_bodies_and_acknowledgements(transport):
    calls, replies = transport
    replies[("POST", native.PREFIX + "/folders")] = {"success": True, "folderId": 30}
    result = await node("create_folder", folder_name="Disposable").run({})
    assert result["data"]["readback_required"] is True
    assert json.loads(calls[-1].content) == {"folderName": "Disposable"}
    replies[("POST", native.PREFIX + "/lists")] = {"listName": "NewList ", "message": "List Has Been Created."}
    result = await node("create_profile_list", folder_name="Owned", list_name="NewList", fields_json='[{"fieldName":"CODE","fieldType":"STR25"}]').run({})
    assert result["data"]["accepted"] is True
    assert json.loads(calls[-1].content) == {"listName": "NewList", "listFolderName": "Owned", "fields": [{"fieldName": "CODE", "fieldType": "STR25"}]}
    replies[("POST", native.PREFIX + "/folders/Owned/suppData")] = True
    result = await node("create_supplemental_table", folder_name="Owned", table_name="NewTable", primary_keys=["CODE"], fields_json='[{"fieldName":"CODE","fieldType":"STR25"}]').run({})
    assert result["data"]["readback_required"] is True
    assert json.loads(calls[-1].content) == {"table": {"objectName": "NewTable"}, "fields": [{"fieldName": "CODE", "fieldType": "STR25", "dataExtractionKey": False}], "primaryKeys": ["CODE"]}


async def test_singular_field_route_and_rename_move_parent(transport):
    calls, replies = transport
    replies[("GET", native.PREFIX + "/folder/Owned/suppData/Existing")] = {"suppData": {"objectName": "Existing", "folderName": "Owned"}, "fields": []}
    replies[("PUT", native.PREFIX + "/folders/Owned/suppData/Existing")] = {"status": True, "message": "Updated"}
    result = await node("update_supplemental_table", folder_name="Owned", table_name="Existing", destination_folder_name="Owned", destination_table_name="Renamed").run({})
    assert result["data"]["table_name"] == "Renamed"
    assert any(r.url.path == native.PREFIX + "/folder/Owned/suppData/Existing" and r.url.params["ft"] == "all" for r in calls)
    assert json.loads(calls[-1].content) == {"folderName": "Owned", "tableName": "Renamed"}
    replies[("GET", native.PREFIX + "/folder/Owned/suppData/Existing")]["suppData"]["folderName"] = "Foreign"
    before = len(calls)
    with pytest.raises(native.ResponsysError, match="parent"):
        await node("delete_supplemental_table", folder_name="Owned", table_name="Existing").run({})
    assert all(r.method == "GET" for r in calls[before:])


async def test_delete_does_not_claim_documentation_copy_error_as_identity(transport):
    calls, replies = transport
    replies[("GET", native.PREFIX + "/folder/Owned/suppData/Existing")] = {"suppData": {"objectName": "Existing", "folderName": "Owned"}, "fields": []}
    replies[("DELETE", native.PREFIX + "/folders/Owned/suppData/Existing/table")] = {"petName": "IncorrectExample"}
    result = await node("delete_supplemental_table", folder_name="Owned", table_name="Existing").run({})
    assert result["data"]["deletion_verified"] is False
    assert "petName" not in result["data"]
    assert calls[-1].method == "DELETE"


@pytest.mark.parametrize("status", [202, 302, 503])
async def test_non_json_write_outcome_is_unknown_without_retry(transport, status):
    calls, replies = transport
    replies[("POST", native.PREFIX + "/folders")] = lambda r: httpx.Response(status, content=b"not-json", headers={"Location": "https://evil.test"})
    with pytest.raises(native.ResponsysError) as exc:
        await node("create_folder", folder_name="Disposable").run({})
    assert exc.value.uncertain is True
    assert sum(r.method == "POST" for r in calls) == 1


async def test_campaign_projection_excludes_sender_body_and_links(transport):
    _, replies = transport
    replies[("GET", native.PREFIX + "/campaigns")] = {"campaigns": [{"id": 45, "name": "OwnedCampaign", "type": "email", "subject": "private", "fromEmail": "private@test", "links": ["private"], "messagePath": "/private"}], "links": []}
    result = await node("list_campaigns").run({})
    assert result["data"]["items"] == [{"id": "45", "name": "OwnedCampaign", "type": "email"}]


async def test_auth_material_echo_and_role401_are_not_exposed(transport):
    _, replies = transport
    replies[("GET", native.PREFIX + "/folders")] = {"folders": [{"id": 19, "name": TOKEN}], "links": []}
    with pytest.raises(native.ResponsysError) as exc:
        await node("list_folders").run({})
    assert TOKEN not in str(exc.value)
    replies[("GET", native.PREFIX + "/folders")] = lambda r: httpx.Response(401, json={"errorCode": "INSUFFICIENT_ACCESS", "errorMessage": "Denied"})
    with pytest.raises(native.ResponsysError, match="permissions") as exc:
        await node("list_folders").run({})
    assert exc.value.http_status == 401 and not hasattr(exc.value, "status_code")
    assert TOKEN not in str(exc.value)


async def test_exact_native_password_form_and_no_output_token(transport):
    calls, replies = transport
    next_token = "fixture-successor-732"
    replies[("POST", native.PREFIX + "/auth/token")] = {"authToken": next_token, "issuedAt": 1464258268624, "endPoint": ENDPOINT}
    cred = {"credential_type": "responsys_password", "account_endpoint": ENDPOINT, "login_origin": "https://login2.responsys.net", "user_name": "fixture-user", "password": "fixture pass"}
    result = await node("get_account_endpoint", cred=cred).run({})
    request = calls[0]
    assert request.url.host == "login2.responsys.net"
    assert "Authorization" not in request.headers
    assert parse_qs(request.content.decode()) == {"auth_type": ["password"], "user_name": ["fixture-user"], "password": ["fixture pass"]}
    assert calls[-1].headers["Authorization"] == next_token
    assert result["data"] == {"api_type": "rest", "endpoint_matches": True}
    assert next_token not in json.dumps(result)
