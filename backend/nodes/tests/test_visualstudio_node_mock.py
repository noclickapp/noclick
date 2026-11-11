"""Wire and connection checks for the pinned VSOnline v1 contract.

Values below are schema-shaped test data, not claimed provider examples.
"""
import json
from unittest.mock import Mock
import httpx
import pytest
import respx
from pydantic import ValidationError
from nodes.visualstudio_node import (BASE, CONFIG_MODELS,
    VisualstudioNode, VisualstudioNodeConfig, VisualstudioTokenCredential)

ENV = "12345678-1234-4234-8234-123456789abc"
TOKEN = "test-user-token"


def node(operation, **values):
    config = CONFIG_MODELS[operation](**values)
    return VisualstudioNode(node_id="vso", node_type="automation-visualstudio", node_data={},
        config=VisualstudioNodeConfig(config=config, credentials=VisualstudioTokenCredential(access_token=TOKEN)),
        sio=Mock(), sid="sid", workflow_id="workflow", user_id="user")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,values,method,path,query,body", [
    ("list_environments", {"name":"dev", "plan_id":"plan", "deleted":True}, "GET", "/api/v1/Environments", {"name":"dev","planId":"plan","deleted":"true"}, None),
    ("get_environment", {"environment_id":ENV}, "GET", f"/api/v1/Environments/{ENV}", {"deleted":"false"}, None),
    ("create_environment", {"environment_type":"cloud","friendly_name":"Build", "container_image":"ubuntu:latest", "auto_shutdown_delay_minutes":30}, "POST", "/api/v1/Environments", {}, {"type":"cloud","friendlyName":"Build","containerImage":"ubuntu:latest","autoShutdownDelayMinutes":30}),
    ("update_environment", {"environment_id":ENV,"friendly_name":"Renamed","auto_shutdown_delay_minutes":0}, "PATCH", f"/api/v1/Environments/{ENV}", {}, {"friendlyName":"Renamed","autoShutdownDelayMinutes":0}),
    ("delete_environment", {"environment_id":ENV}, "DELETE", f"/api/v1/Environments/{ENV}", {}, None),
    ("start_environment", {"environment_id":ENV}, "POST", f"/api/v1/Environments/{ENV}/start", {}, None),
    ("shutdown_environment", {"environment_id":ENV}, "POST", f"/api/v1/Environments/{ENV}/shutdown", {}, None),
    ("archive_environment", {"environment_id":ENV}, "POST", f"/api/v1/Environments/{ENV}/archive", {}, None),
    ("get_environment_archive", {"environment_id":ENV}, "GET", f"/api/v1/Environments/{ENV}/archive", {}, None),
    ("export_environment", {"environment_id":ENV}, "POST", f"/api/v1/Environments/{ENV}/export", {}, None),
    ("restore_environment", {"environment_id":ENV}, "PATCH", f"/api/v1/Environments/{ENV}/restore", {}, None),
    ("update_recent_folders", {"environment_id":ENV,"recent_folder_paths":[]}, "PATCH", f"/api/v1/Environments/{ENV}/folder", {}, {"recentFolderPaths":[]}),
    ("get_environment_state", {"environment_id":ENV}, "GET", f"/api/v1/Environments/{ENV}/state", {}, None),
    ("get_billing", {}, "GET", "/api/v1/Billing", {}, None),
    ("list_locations", {}, "GET", "/api/v1/Locations", {}, None),
    ("get_location", {"location":"eastus","plan_id":"p"}, "GET", "/api/v1/Locations/eastus", {"planId":"p"}, None),
    ("get_agent", {"family":"linux-x64"}, "GET", "/api/v1/Agents/linux-x64", {}, None),
    ("get_port_info", {"environment_id":ENV,"port_number":3000}, "GET", f"/api/v1/Tunnel/{ENV}/portInfo", {"portNumber":"3000"}, None),
])
async def test_wire(operation, values, method, path, query, body):
    with respx.mock(assert_all_called=True) as router:
        route = router.request(method, BASE + path).mock(return_value=httpx.Response(204))
        result = await node(operation, **values).execute({})
        request = route.calls[0].request
    assert result == {"data":None,"http_status":204}
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert dict(request.url.params) == query
    if body is None:
        assert not request.content
    else:
        assert json.loads(request.content) == body


def test_manual_credentials_and_invalid_inputs():
    assert VisualstudioTokenCredential(access_token=TOKEN).credential_type == "visualstudio_token"
    for token in ["", "Bearer secret", "secret\r\nX-Injected: yes"]:
        with pytest.raises(ValidationError):
            VisualstudioTokenCredential(access_token=token)
    with pytest.raises(ValidationError):
        CONFIG_MODELS["get_environment"](environment_id="../../admin")
    with pytest.raises(ValidationError):
        CONFIG_MODELS["update_environment"](environment_id=ENV)
    with pytest.raises(ValidationError):
        CONFIG_MODELS["get_port_info"](environment_id=ENV,port_number=65536)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301,401,403,429,500])
async def test_failures_redact_token_and_do_not_follow_or_retry(status):
    with respx.mock:
        route = respx.get(BASE + "/api/v1/Environments").mock(return_value=httpx.Response(status,text="denied " + TOKEN,headers={"Location":"https://other.example/"}))
        with pytest.raises(ValueError,match=f"{status}: denied \\[redacted\\]"):
            await node("list_environments").execute({})
        assert route.call_count == 1


@pytest.mark.asyncio
async def test_list_response_and_account_connection_evidence():
    from pathlib import Path
    from nodes.core.connection_evidence import collect_evidence
    data = json.loads((Path(__file__).parent / "fixtures/visualstudio/environments.json").read_text())
    with respx.mock:
        respx.get(BASE + "/api/v1/Environments").mock(return_value=httpx.Response(200,json=data))
        assert (await node("list_environments").execute({}))["data"] == data
        evidence = await collect_evidence(node_type="automation-visualstudio", user_id="user", credential_data={"credential_type":"visualstudio_token","access_token":TOKEN})
    assert evidence.reachable is True
    assert "Build environment" in str(evidence.samples)
