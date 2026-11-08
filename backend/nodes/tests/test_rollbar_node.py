"""Request, scope, and response contracts for the Rollbar node."""

import httpx
import pytest

from nodes import rollbar_node as module


ACCOUNT = "account-token"
POST = "post-token"
PROJECT = "project-token"
CREDS = module.RollbarAccessTokenCredential(
    account_access_token=ACCOUNT, project_read_write_token=PROJECT,
    project_post_server_token=POST,
)


@pytest.mark.parametrize(
    "config,method,path,query,body,post_token",
    [
        (module.RollbarListProjectsConfig(), "GET", "/projects", {}, None, False),
        (module.RollbarGetProjectConfig(project_id=7), "GET", "/project/7", {"project_id": 7}, None, False),
        (module.RollbarCreateProjectConfig(name="Sandbox"), "POST", "/projects", {}, {"name": "Sandbox"}, False),
        (module.RollbarDeleteProjectConfig(project_id=7), "DELETE", "/project/7", {"project_id": 7}, None, False),
        (module.RollbarListTeamsConfig(), "GET", "/teams", {}, None, False),
        (module.RollbarGetTeamConfig(team_id=3), "GET", "/team/3", {}, None, False),
        (module.RollbarCreateTeamConfig(name="Ops", access_level="light"), "POST", "/teams", {}, {"name": "Ops", "access_level": "light"}, False),
        (module.RollbarListTeamUsersConfig(team_id=3), "GET", "/team/3/users", {"page": 1}, None, False),
        (module.RollbarListProjectTeamsConfig(project_id=7), "GET", "/project/7/teams", {"project_id": 7}, None, False),
        (module.RollbarAssignTeamProjectConfig(team_id=3, project_id=7), "PUT", "/team/3/project/7", {"project_id": 7}, None, False),
        (module.RollbarListUsersConfig(email="a@example.com"), "GET", "/users", {"email": "a@example.com"}, None, False),
        (module.RollbarGetUserConfig(user_id=4), "GET", "/user/4", {}, None, False),
        (module.RollbarListItemsConfig(project_id=7, status="active", page=2), "GET", "/items", {"project_id": 7, "status": "active", "page": 2}, None, False),
        (module.RollbarGetItemConfig(project_id=7, item_id=8), "GET", "/item/8", {"project_id": 7}, None, False),
        (module.RollbarUpdateItemConfig(project_id=7, item_id=8, status="resolved"), "PATCH", "/item/8", {"project_id": 7}, {"status": "resolved"}, False),
        (module.RollbarListItemEventsConfig(project_id=7, item_id=8), "GET", "/item/8/events", {"project_id": 7, "page": 1, "limit": 20}, None, False),
        (module.RollbarListOccurrencesConfig(project_id=7, last_id=99), "GET", "/instances", {"project_id": 7, "page": 1, "limit": 20, "last_id": 99}, None, False),
        (module.RollbarGetOccurrenceConfig(project_id=7, occurrence_id=9), "GET", "/instance/9", {"project_id": 7}, None, False),
        (module.RollbarListEnvironmentsConfig(project_id=7), "GET", "/environments", {"project_id": 7, "page": 1, "limit": 20}, None, False),
        (module.RollbarTopActiveItemsConfig(project_id=7, hours=48), "GET", "/reports/top_active_items", {"project_id": 7, "hours": 48}, None, False),
        (module.RollbarListDeploysConfig(project_id=7), "GET", "/deploys", {"project_id": 7, "page": 1, "limit": 20}, None, False),
        (module.RollbarGetDeployConfig(project_id=7, deploy_id=2), "GET", "/deploy/2", {"project_id": 7}, None, False),
        (module.RollbarReportMessageConfig(environment="qa", message="smoke"), "POST", "/item/", {}, {"data": {"environment": "qa", "body": {"message": {"body": "smoke"}}, "level": "error", "platform": "python"}}, True),
        (module.RollbarReportDeployConfig(environment="qa", revision="abc"), "POST", "/deploy", {}, {"environment": "qa", "revision": "abc"}, True),
    ],
)
def test_all_operations_route_to_documented_endpoint(config, method, path, query, body, post_token):
    actual = module._operation_request(config)
    assert actual[0:2] == (method, path)
    assert query.items() <= actual[2].items()
    assert actual[3:] == (body, post_token)


@pytest.mark.asyncio
async def test_request_uses_separate_reporting_token_and_unwraps_result(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"err": 0, "result": {"id": 42}})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler)))

    read = await module.rollbar_request(module.RollbarListProjectsConfig(), CREDS)
    project = await module.rollbar_request(module.RollbarUpdateItemConfig(project_id=7, item_id=8, status="resolved"), CREDS)
    write = await module.rollbar_request(module.RollbarReportMessageConfig(environment="qa", message="smoke"), CREDS)
    assert read["data"] == project["data"] == write["data"] == {"id": 42}
    assert [request.headers["X-Rollbar-Access-Token"] for request in seen] == [ACCOUNT, PROJECT, POST]


@pytest.mark.asyncio
async def test_api_error_envelope_and_missing_post_token_are_rejected(monkeypatch):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"err": 1, "message": "denied"}))
    ))
    with pytest.raises(ValueError, match="denied"):
        await module.rollbar_request(module.RollbarListProjectsConfig(), CREDS)
    with pytest.raises(ValueError, match="post_server_item"):
        await module.rollbar_request(
            module.RollbarReportDeployConfig(environment="qa", revision="abc"),
            module.RollbarAccessTokenCredential(account_access_token=ACCOUNT),
        )


def test_update_requires_change_and_schema_exposes_distinct_token_fields():
    with pytest.raises(ValueError, match="at least one"):
        module._operation_request(module.RollbarUpdateItemConfig(project_id=7, item_id=8))
    schema = module.RollbarNode.get_config_schema()
    credential = schema["$defs"]["RollbarAccessTokenCredential"]["properties"]
    assert "account_access_token" in credential
    assert "project_read_write_token" in credential
    assert "project_post_server_token" in credential


@pytest.mark.asyncio
async def test_documented_project_teams_response(monkeypatch):
    # https://docs.rollbar.com/reference/list-a-projects-teams
    payload = {"err": 0, "result": [
        {"team_id": 272686, "project_id": 178029},
        {"team_id": 272687, "project_id": 178029},
    ]}
    real_client = httpx.AsyncClient
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ))
    result = await module.rollbar_request(
        module.RollbarListProjectTeamsConfig(project_id=178029), CREDS,
    )
    assert result["data"] == payload["result"]
