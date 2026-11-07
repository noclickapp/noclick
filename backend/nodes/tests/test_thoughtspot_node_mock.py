"""Offline ThoughtSpot factory, connect, picker and transport contracts."""
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import thoughtspot_node as api
from nodes.thoughtspot_node import ThoughtSpotNode, ThoughtSpotAccessTokenCredential, shape_credential
from nodes.core.registry import NodeFactory, NODE_REGISTRY
from nodes.core.binary_output import BinaryOutput, snapshot_safe
from nodes.core.connection_evidence import collect_evidence

NODE = "automation-thoughtspot"
USER = "00000000-0000-4000-8000-000000000001"
CID = "00000000-0000-4000-8000-000000000042"
OWNER = "00000000-0000-4000-8000-000000000002"
RID = "10000000-0000-4000-8000-000000000001"
COPY = "10000000-0000-4000-8000-000000000002"
VIZ = "20000000-0000-4000-8000-000000000001"
CREDENTIAL = {"credential_type": api.FAMILY, "base_url": "https://analytics.example.test",
              "access_token": "fixture-issued-token-42", "org_id": 7}


@pytest.fixture
def ensure_native_db_pool():
    yield


def token(**updates):
    return {"creation_time_in_millis": 1700000000000,
            "expiration_time_in_millis": 4102444800000,
            "valid_for_user_id": USER, "token_type": "BEARER",
            "scope": {"access_type": "FULL", "org_id": 7, "metadata_id": None}, **updates}


def item(rid=RID, kind="LIVEBOARD", name="Fixture Liveboard", author=USER):
    return {"metadata_id": rid, "metadata_name": name, "metadata_type": kind,
            "metadata_header": {"id": rid, "name": name, "author": author, "owner": rid,
                                "ownerOrgId": 7, "isDeleted": False},
            "visualization_headers": [{"id": VIZ, "name": "Fixture Viz", "owner": rid}],
            "metadata_detail": {"secret": "must-not-escape"}, "stats": {"secret": "must-not-escape"}}


def make(operation="get_current_user", credentials=None, **config):
    return NodeFactory.create_node("fixture-node", NODE, {
        "config": {"operation": operation, "label": "Saved canvas node", "_settings": {"retryOnFail": "false"}, **config},
        "credentials": deepcopy(credentials or CREDENTIAL),
    }, user_id=USER)


@pytest.fixture
def provider(monkeypatch):
    calls, replies = [], []
    async def callback(credential, endpoint, *, body=None, lease=None, report=False):
        calls.append((endpoint, deepcopy(body), report))
        if endpoint == "auth/token/validate":
            return token()
        if endpoint == "auth/session/user":
            return {"id": USER, "name": "fixture-user", "display_name": "Fixture Analyst",
                    "current_org": {"id": 7, "name": "Fixture Org"}, "account_status": "ACTIVE",
                    "privileges": ["do-not-export"], "secret": "must-not-escape"}
        if not replies:
            raise AssertionError("Unexpected fixture route " + endpoint)
        expected, result = replies.pop(0)
        assert endpoint == expected
        if isinstance(result, Exception):
            raise result
        return deepcopy(result)
    monkeypatch.setattr(api, "request", callback)
    return calls, replies


def test_real_factory_schema_and_saved_canvas_fields():
    assert NODE_REGISTRY[NODE] is ThoughtSpotNode
    node = make("get_liveboard", liveboard_id=RID)
    assert node.config.config.liveboard_id == RID
    schema = ThoughtSpotNode.get_config_schema()
    credential = schema["$defs"]["ThoughtSpotAccessTokenCredential"]
    assert set(credential["required"]) == {"base_url", "access_token", "org_id"}
    assert credential["properties"]["credential_type"]["const"] == api.FAMILY
    assert credential["properties"]["access_token"]["ui:widget"] == "password"
    assert "x-oauth-provider" not in credential
    operations = {s["properties"]["operation"]["const"] for s in schema["$defs"].values()
                  if "operation" in s.get("properties", {})}
    assert len(operations) == 19 and "export_liveboard_report" in operations
    assert "invoke" not in operations and "login" not in operations


def test_foreign_family_and_secret_errors_are_safe():
    for bad in ({**CREDENTIAL, "credential_type": "tableau_pat"},
                {**CREDENTIAL, "access_token": "private-value\r\nheader"},
                {**CREDENTIAL, "org_id": True},
                {**CREDENTIAL, "base_url": "https://analytics.example.test/private"},
                {**CREDENTIAL, "expires_at": "2020-01-01T00:00:00Z"}):
        with pytest.raises(ValueError) as error:
            make(credentials=bad)
        assert "private-value" not in str(error.value)
    with pytest.raises(ValueError):
        make("list_liveboards", record_size=-1)


@pytest.mark.asyncio
async def test_actual_manual_connect_emits_family_and_profile_evidence(monkeypatch, provider):
    from nodes.core import credential_connect
    monkeypatch.setattr(credential_connect, "_collect_evidence", collect_evidence)
    data = dict(CREDENTIAL)
    data.pop("credential_type")
    verdict = await credential_connect.validate_for_connect(
        credential_type=api.FAMILY, credential_data=data, user_id=USER)
    assert verdict.ok and verdict.credential_data["credential_type"] == api.FAMILY
    assert verdict.evidence.reachable is True
    assert verdict.evidence.account_label == "fixture-user"
    out = await make().execute({})
    assert out["data"]["id"] == USER and out["data"]["current_org"]["id"] == 7
    assert "must-not-escape" not in repr(out)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending_approval", "rejected"])
async def test_actual_factory_run_admission_prevents_transport(monkeypatch, status):
    gate = {"status": status, "message": "Fixture approval hold"}
    monkeypatch.setattr("utils.credential_approval.admit_node", AsyncMock(return_value=gate))
    request = AsyncMock(side_effect=AssertionError("provider reached"))
    monkeypatch.setattr(api, "request", request)
    assert await make().run({}) == gate
    request.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatcher_operation_cannot_be_overridden(provider):
    from nodes.core.run_op import run_node_operation
    out = await run_node_operation(node_type=NODE, operation="get_current_user",
        arguments={"operation": "delete_own_liveboard"}, user_id=USER, credential_data=CREDENTIAL)
    assert out["action"] == "get_current_user"


@pytest.mark.asyncio
async def test_scope_org_expiry_and_identity_mismatch():
    for status in (token(scope={"access_type": "FULL", "org_id": 8}),
                   token(expiration_time_in_millis=1),
                   token(token_type="UNKNOWN"),
                   token(scope={"access_type": "REPORT_BOOK_VIEW", "org_id": 7, "metadata_id": RID})):
        request = AsyncMock(return_value=status)
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(api, "request", request)
            with pytest.raises(ValueError):
                await api.validate_token(shape_credential(CREDENTIAL))
    with pytest.raises(ValueError):
        api.admit_scope({"scope": {"access_type": "REPORT_BOOK_VIEW", "metadata_id": RID}}, resource_id=COPY)


@pytest.mark.asyncio
async def test_metadata_projection_and_parent_fence(provider):
    calls, replies = provider
    replies.append(("metadata/search", [item()]))
    out = await make("get_liveboard", liveboard_id=RID).execute({})
    assert out["data"]["author"] == USER and out["data"]["owner"] == RID
    assert "must-not-escape" not in repr(out)
    replies.append(("metadata/search", [item()]))
    with pytest.raises(ValueError, match="not in"):
        await make("fetch_liveboard_data", liveboard_id=RID, visualization_id=COPY).execute({})
    assert not any(endpoint == "metadata/liveboard/data" for endpoint, _, _ in calls)


@pytest.mark.asyncio
async def test_copy_readback_and_uncertain_id_never_replay(provider):
    calls, replies = provider
    replies.extend([("metadata/search", [item()]), ("metadata/copyobject", {"metadata_id": COPY}),
                    ("metadata/search", [item(COPY, name="Fixture Copy")])])
    out = await make("copy_liveboard", liveboard_id=RID, title="Fixture Copy", confirm_copy=True).execute({})
    assert out["readback_verified"] and out["data"]["id"] == COPY and not out["visibility_verified"]
    body = next(body for endpoint, body, _ in calls if endpoint == "metadata/copyobject")
    assert body == {"identifier": RID, "type": "LIVEBOARD", "title": "Fixture Copy", "description": ""}
    replies.extend([("metadata/search", [item()]), ("metadata/copyobject", {})])
    with pytest.raises(ValueError, match="usable ID"):
        await make("copy_liveboard", liveboard_id=RID, title="Other Copy", confirm_copy=True).execute({})
    assert sum(endpoint == "metadata/copyobject" for endpoint, _, _ in calls) == 2


@pytest.mark.asyncio
async def test_delete_current_author_expected_name_204_and_absence(provider):
    calls, replies = provider
    replies.append(("metadata/search", [item(author=OWNER)]))
    with pytest.raises(ValueError, match="current author"):
        await make("delete_own_liveboard", liveboard_id=RID, expected_name="Fixture Liveboard", confirm_delete=True).execute({})
    assert not any(endpoint == "metadata/delete" for endpoint, _, _ in calls)
    replies.extend([("metadata/search", [item()]), ("metadata/delete", None), ("metadata/search", [])])
    out = await make("delete_own_liveboard", liveboard_id=RID, expected_name="Fixture Liveboard", confirm_delete=True).execute({})
    assert out["absence_observed"] is True and out["hard_erasure_verified"] is False


def test_bounded_full_data_preserves_sampling_and_cell_content():
    content = {"column_names": ["sales", "calendar"], "data_rows": [{"sales": 12, "calendar": {"v": {"s": 694252800}}}],
               "record_offset": 0, "record_size": 2, "returned_data_row_count": 1,
               "available_data_row_count": 5, "sampling_ratio": .5}
    out = api.data_response({"metadata_id": RID, "contents": [content], "debug": "must-not-escape"},
                            resource_id=RID, offset=0, limit=2)
    assert out["contents"][0]["sampling_ratio"] == .5
    assert out["contents"][0]["data_rows"][0]["calendar"] == {"v": {"s": 694252800}}
    assert out["contents"][0]["next_record_offset"] == 1 and "debug" not in out
    with pytest.raises(ValueError, match="pagination"):
        api.data_response({"metadata_id": RID, "contents": [{**content, "returned_data_row_count": 99}]},
                          resource_id=RID, offset=0, limit=2)
    with pytest.raises(ValueError, match="visualization identity"):
        api.data_response({"metadata_id": RID, "contents": [content]},
                          resource_id=RID, offset=0, limit=2, visualization_ids={VIZ})


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,kind,endpoint,config", [
    ("fetch_answer_data", "ANSWER", "metadata/answer/data", {"answer_id": RID}),
    ("search_data", "LOGICAL_TABLE", "searchdata", {"data_source_id": RID, "query_string": "[sales]"}),
])
async def test_actual_answer_and_search_data_do_not_require_liveboard_visualization(provider, operation, kind, endpoint, config):
    calls, replies = provider
    chunk = {"column_names": ["sales"], "data_rows": [{"sales": 12}],
             "record_offset": 0, "record_size": 2, "returned_data_row_count": 1,
             "available_data_row_count": 1, "sampling_ratio": 1}
    replies.extend([("metadata/search", [item(kind=kind)]),
                    (endpoint, {"metadata_id": RID, "contents": [chunk]})])
    out = await make(operation, record_size=2, **config).execute({})
    assert out["data"]["contents"][0]["data_rows"] == [{"sales": 12}]
    body = next(body for route, body, _ in calls if route == endpoint)
    assert body["data_format"] == "FULL" and "visualization_identifiers" not in body


@pytest.mark.asyncio
async def test_export_keeps_native_binary_marker_and_zip_contract(provider):
    _, replies = provider
    replies.extend([("metadata/search", [item()]), ("report/liveboard", (b"PK\x03\x04fixture", "application/octet-stream"))])
    out = await make("export_liveboard_report", liveboard_id=RID, file_format="CSV", confirm_export=True).execute({})
    assert isinstance(out["file"], BinaryOutput)
    assert out["file"].content_type == "application/zip" and out["file"].filename.endswith(".zip")
    assert snapshot_safe(out)["file"]["pending"] is True
    assert "base64" not in snapshot_safe(out)["file"]
    with pytest.raises(ValueError):
        api.report_file((b'{"error":"secret"}', "application/octet-stream"), file_format="CSV", liveboard=False)


@pytest.mark.asyncio
async def test_native_picker_parent_and_cursor_rejected_before_transport(provider):
    calls, _ = provider
    with pytest.raises(ValueError):
        await ThoughtSpotNode.load_field_options("visualization_id", CREDENTIAL, context={})
    assert calls == []
    import base64, json
    cursor = base64.urlsafe_b64encode(json.dumps({"scope": "different", "offset": 0}).encode()).decode()
    with pytest.raises(ValueError, match="cursor"):
        await ThoughtSpotNode.load_field_options("liveboard_id", CREDENTIAL, page_token=cursor)
    assert calls == []








class _Context:
    def __init__(self, value): self.value = value
    async def __aenter__(self): return self.value
    async def __aexit__(self, *_): return False


@pytest.mark.asyncio
@pytest.mark.parametrize("status,raw,media", [
    (200, b'{"error":{"message":{"debug":"fixture-issued-token-42"}}}', "application/json"),
    (401, b"fixture-issued-token-42", "text/plain"),
    (500, b"fixture-issued-token-42", "text/html"),
    (302, b"", "text/html"),
    (200, b"{}", "text/html"),
    (200, b"{not-json", "application/json"),
])
async def test_real_transport_errors_do_not_echo_token(monkeypatch, status, raw, media):
    calls = []
    async def handle(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer " + CREDENTIAL["access_token"]
        assert request.url == CREDENTIAL["base_url"] + "/api/rest/2.0/auth/session/user"
        assert CREDENTIAL["access_token"] not in str(request.url)
        return httpx.Response(status, content=raw, headers={"Content-Type": media})
    def client(**kwargs):
        assert "require_public" not in kwargs
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(api, "guarded_async_client", client)
    with pytest.raises(ValueError) as error:
        await api.request(shape_credential(CREDENTIAL), "auth/session/user")
    assert CREDENTIAL["access_token"] not in str(error.value) and len(calls) == 1


@pytest.mark.asyncio
async def test_real_stream_cap_and_retry_after_no_retry(monkeypatch):
    calls = []
    responses = [httpx.Response(429, headers={"Retry-After": "Tue, 06 Oct 2099 12:00:00 GMT"}),
                 httpx.Response(200, content=b"x" * (api.MAX_JSON + 1), headers={"Content-Type": "application/json"})]
    async def handle(request):
        calls.append(request)
        return responses.pop(0)
    monkeypatch.setattr(api, "guarded_async_client", lambda **_: httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    with pytest.raises(ValueError, match="429"):
        await api.request(shape_credential(CREDENTIAL), "auth/session/user")
    assert len(calls) == 1
    with pytest.raises(ValueError, match="size limit"):
        await api.request(shape_credential(CREDENTIAL), "auth/session/user")
    assert len(calls) == 2 and api.retry_after("12") == 12
