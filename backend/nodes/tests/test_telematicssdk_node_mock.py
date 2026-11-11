"""Contract route coverage plus success, rejection and persistent poll semantics."""
import copy
import json
from pathlib import Path

import httpx
import pytest
from nodes import telematicssdk_node as native
from nodes.core.registry import NodeFactory
from nodes.core.poll_trigger import poll_scope

ID = "00000000-0000-4000-8000-000000000001"
FIXTURE = json.loads((Path(__file__).parent / "fixtures/telematicssdk/contract.json").read_text())


def node(config):
    return NodeFactory.create_node(node_id="telematicssdk-test", node_type="automation-telematicssdk",
        node_data={"config": config, "credentials": {"credential_type": "telematicssdk_token", "access_token": "synthetic-token"}})


def transport(monkeypatch, bodies):
    calls = []
    def respond(request):
        calls.append(request)
        body = bodies[min(len(calls)-1, len(bodies)-1)]
        return httpx.Response(200, json=body)
    monkeypatch.setattr(native, "guarded_async_client", lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs))
    return calls


CASES = [
    ({"operation":"get_profile"}, "GET", "/v1/Management/users", None, {}),
    ({"operation":"find_users","email":"test@example.com"}, "GET", "/v1/Management/users/find", None, {"Email":"test@example.com","IncludeAccountInfo":"false","ShowInactiveUsers":"false"}),
    ({"operation":"list_users"}, "POST", "/v1/Management/users/GetFilteredPage", {"PageNumber":1,"PageSize":100,"Sort":"DateCreatedDesc","ShowInactiveUsers":False}, {}),
    ({"operation":"search_users","search_term":"Driver"}, "GET", "/v1/Management/users/quicksearch", None, {"SearchTerm":"Driver","ShowInactiveUsers":"false"}),
    ({"operation":"update_profile","first_name":"Tim","user_device_token":ID}, "PUT", "/v1/Management/users", {"FirstName":"Tim","SendVerificationCodeForEmailPhone":False}, {}),
    ({"operation":"delete_user","device_token":ID}, "DELETE", "/v1/Management/users/"+ID, None, {}),
    ({"operation":"update_sdk_settings","instance_id":ID,"enable_real_time_location":False}, "PATCH", f"/v1/Management/users/instances/{ID}/sdk", {"EnableRealTimeLocation":False}, {}),
    ({"operation":"create_instance","name":"Drivers"}, "POST", "/v1/Management/users/instances", {"Name":"Drivers"}, {}),
    ({"operation":"get_instance","instance_id":ID}, "GET", f"/v1/Management/users/instances/{ID}", None, {}),
    ({"operation":"update_instance","instance_id":ID,"description":"Fleet"}, "PUT", f"/v1/Management/users/instances/{ID}", {"Description":"Fleet"}, {}),
    ({"operation":"join_instance","invite_code":"abc"}, "POST", "/v1/Management/users/instances/change/abc", None, {}),
    ({"operation":"count_users","instance_ids":[ID],"is_rtd_enabled":False}, "POST", "/v1/Management/users/count", {"IncludeDeacivated":False,"Identifiers":{"InstanceIds":[ID]},"IsRtdEnabled":False}, {}),
    ({"operation":"get_wallets","blockchain_id":ID}, "GET", "/v1/Wallets", None, {"blockchainId":ID}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body,query", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_telematicssdk_routes(monkeypatch, config, method, path, body, query):
    response = {**FIXTURE["acknowledgement"], "Result": []} if config["operation"] == "find_users" else FIXTURE["acknowledgement"]
    calls = transport(monkeypatch, [response])
    assert await node(config).execute({}) == response
    assert len(calls) == 1
    request = calls[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "user.telematicssdk.com"
    assert request.headers["Authorization"] == "Bearer synthetic-token"
    assert dict(request.url.params) == query
    assert (json.loads(request.content) if request.content else None) == body
    if config["operation"] == "update_profile":
        assert request.headers["UserDeviceToken"] == ID


@pytest.mark.asyncio
async def test_telematicssdk_poll_baseline_dedup_pagination_and_agent_event(monkeypatch):
    first = copy.deepcopy(FIXTURE["page"])
    second = copy.deepcopy(first)
    second["Result"]["Users"][0]["DeviceToken"] = "00000000-0000-4000-8000-000000000002"
    second["Result"]["Users"].append(copy.deepcopy(second["Result"]["Users"][0]))
    more = copy.deepcopy(first)
    more["Result"]["HasNextPage"] = True
    calls = transport(monkeypatch, [first, more, second, more, second])
    obj = node({"operation":"on_new_user","instance_ids":[ID]})
    state = {}
    async def update(mutator, **kwargs):
        new_state, result = mutator(copy.deepcopy(state))
        if new_state is not None:
            state.clear(); state.update(new_state)
        return result
    obj._update_node_state = update
    assert (await obj.execute({}))["users"] == []
    output = await obj.execute({})
    assert output["new_user_count"] == 1
    event = obj.resolve_agent_event(output)
    assert "Test Driver" in event["text"] and second["Result"]["Users"][0]["DeviceToken"] in event["text"]
    assert obj.trigger_emitted_event(output)
    assert (await obj.execute({}))["users"] == []
    assert [json.loads(c.content)["PageNumber"] for c in calls] == [1,1,2,1,2]
    assert all(json.loads(c.content)["InstanceIds"] == [ID] for c in calls)
    assert poll_scope(native.TelematicsSDKNode, {"operation":"on_new_user","instance_ids":[ID]}) != poll_scope(native.TelematicsSDKNode, {"operation":"on_new_user"})


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [{"Status":401,"Title":"Expired token","Errors":[]}, {"Status":200,"Errors":[{"Message":"Rejected"}]}])
async def test_telematicssdk_error_envelopes_fail(monkeypatch, response):
    transport(monkeypatch, [response])
    with pytest.raises(ValueError):
        await node({"operation":"find_users"}).execute({})


def test_telematicssdk_manual_connect_default():
    assert native.TelematicsSDKToken(access_token="synthetic-token").credential_type == "telematicssdk_token"


@pytest.mark.asyncio
async def test_telematicssdk_malformed_evidence_fails(monkeypatch):
    transport(monkeypatch, [{"Status": 200}])
    with pytest.raises(ValueError, match="user list"):
        await node({"operation":"find_users"}).execute({})
