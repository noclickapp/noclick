"""magicplan request and webhook contract regressions; no live keys are used."""
import json
from pathlib import Path
from urllib.parse import urlencode

import httpx
import pytest
from nodes import magicplan_node as native
from nodes.core.registry import NodeFactory

CREDS = {"credential_type": "magicplan_api_key", "api_key": "fixture-key-42", "customer_id": "fixture-customer-42"}
TEAM = "c32ea8d1-fee0-4c81-b402-eb3f85772cf8"
PROJECT = "c32ea8d1-fee3-4c81-b402-eb3f85772cf8"
PLAN = "6a45b1435520f"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="test", node_type="automation-magicplan", node_data={"config": config, "credentials": CREDS})


def transport(monkeypatch, handler):
    requests = []
    def reply(request):
        requests.append(request)
        return handler(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


# Independently specified expected routes and bodies from the pinned contract.
CASES = [
    ({"operation": "get_workspace"}, "GET", "/workspace", None),
    ({"operation": "update_workspace", "name": "RenovateRetail Hub"}, "PUT", "/workspace", {"name": "RenovateRetail Hub"}),
    ({"operation": "list_teams"}, "GET", "/teams", None),
    ({"operation": "create_team", "name": "Munich Team"}, "POST", "/teams", {"name": "Munich Team"}),
    ({"operation": "get_team", "team_id": TEAM}, "GET", f"/teams/{TEAM}", None),
    ({"operation": "update_team", "team_id": TEAM, "name": "New Team Name"}, "PUT", f"/teams/{TEAM}", {"name": "New Team Name"}),
    ({"operation": "add_team_members", "team_id": TEAM, "emails_json": '["jane.smith@example.com"]'}, "POST", f"/teams/{TEAM}/members", {"emails": ["jane.smith@example.com"]}),
    ({"operation": "remove_team_member", "team_id": TEAM, "email": "john.doe@example.com"}, "DELETE", f"/teams/{TEAM}/members", None),
    ({"operation": "list_users"}, "GET", "/workgroups/users", None),
    ({"operation": "list_plans"}, "GET", "/workgroups/plans", None),
    ({"operation": "get_plan", "plan_id": PLAN}, "GET", f"/plans/get/{PLAN}", None),
    ({"operation": "get_plan_statistics", "plan_id": PLAN}, "GET", f"/plans/statistics/{PLAN}", None),
    ({"operation": "get_plan_forms", "plan_id": PLAN}, "GET", f"/plans/forms/{PLAN}", None),
    ({"operation": "list_plan_files", "plan_id": PLAN}, "GET", f"/plans/{PLAN}/files", None),
    ({"operation": "reassign_plan_owner", "plan_id": PLAN, "user_id": TEAM}, "PUT", f"/plans/{PLAN}/owner", {"user_id": TEAM}),
    ({"operation": "export_plan", "plan_id": PLAN}, "POST", f"/plans/{PLAN}/custom-export", None),
    ({"operation": "list_projects"}, "GET", "/projects", None),
    ({"operation": "create_project", "name": "Victorian Manor Restoration", "email": "jane.doe@example.com"}, "POST", "/projects", {"name": "Victorian Manor Restoration", "email": "jane.doe@example.com"}),
    ({"operation": "get_project", "project_id": PROJECT}, "GET", f"/projects/{PROJECT}", None),
    ({"operation": "update_project", "project_id": PROJECT, "name": "New Name"}, "PUT", f"/projects/{PROJECT}", {"name": "New Name"}),
    ({"operation": "archive_project", "project_id": PROJECT}, "PUT", f"/projects/{PROJECT}/archive", {}),
    ({"operation": "list_project_files", "project_id": PROJECT}, "GET", f"/projects/{PROJECT}/files", None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_contract_requests(monkeypatch, config, method, path, body):
    requests = transport(monkeypatch, lambda _: httpx.Response(204))
    result = await node(config).execute({})
    request = requests[0]
    assert len(requests) == 1 and request.method == method
    assert str(request.url).split("?")[0] == native.BASE + path
    assert request.headers["key"] == CREDS["api_key"] and request.headers["customer"] == CREDS["customer_id"]
    assert (json.loads(request.content) if request.content else None) == body
    assert result["status"] == "success" and result["data"]["status_code"] == 204
    assert CREDS["api_key"] not in str(result)
    if config["operation"] == "remove_team_member":
        assert dict(request.url.params) == {"email": "john.doe@example.com"}


@pytest.mark.asyncio
async def test_query_encoding_and_optional_false(monkeypatch):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json={"data": []}))
    await node({"operation": "list_projects", "page": 2, "page_size": 50, "project_sort": "Projects.user_modified", "direction": "desc", "name": "Kitchen + café"}).execute({})
    assert dict(requests[-1].url.params) == {"page": "2", "page_size": "50", "sort": "Projects.user_modified", "direction": "desc", "name": "Kitchen + café"}
    await node({"operation": "list_plan_files", "plan_id": PLAN, "format_json": '["pdf", "jpg"]', "include_photos": False}).execute({})
    assert requests[-1].url.params.get_list("format") == ["pdf", "jpg"]
    assert requests[-1].url.params["include_photos"] == "false"
    await node({"operation": "update_workspace", "formats_json": '["pdf", "png"]', "notify_user": False}).execute({})
    assert json.loads(requests[-1].content) == {"formats": ["pdf", "png"], "notify_user": False}


@pytest.mark.parametrize("config", [
    {"operation": "get_plan", "plan_id": "../workspace"},
    {"operation": "get_team", "team_id": "bad-uuid"},
    {"operation": "create_project", "name": "X", "email": "not-email"},
    {"operation": "list_plan_files", "plan_id": PLAN, "format_json": '["exe"]'},
    {"operation": "add_team_members", "team_id": TEAM, "emails_json": '{}'},
    {"operation": "update_project", "project_id": PROJECT},
    {"operation": "list_projects", "page_size": 51},
    {"operation": "list_plans", "creation_date": "yesterday"},
    {"operation": "reassign_plan_owner", "plan_id": PLAN, "user_id": TEAM, "notify_user_flag": True},
])
def test_invalid_inputs(config):
    with pytest.raises(ValueError): native.MagicplanNode.parse_config({"config": config, "credentials": CREDS})


def test_manual_credential_defaults_and_header_rejection():
    cred = native.MagicplanAPIKeyCredential(api_key=" fixture-key ", customer_id="customer")
    assert cred.credential_type == "magicplan_api_key" and cred.api_key == "fixture-key"
    with pytest.raises(ValueError): native.MagicplanAPIKeyCredential(api_key="key\r\nInjected: bad", customer_id="customer")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_http_error_redaction_and_redirect_refusal(monkeypatch, status):
    requests = transport(monkeypatch, lambda _: httpx.Response(status, headers={"Location": "https://elsewhere.example/"}, json={"message": CREDS["api_key"]}))
    with pytest.raises(ValueError) as exc: await node({"operation": "list_projects"}).execute({})
    assert str(status) in str(exc.value) and CREDS["api_key"] not in str(exc.value)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_webhook_lifecycle_preserves_existing_endpoints(monkeypatch):
    state = {"webhook_url": "https://existing.example/hook"}
    def reply(request):
        if request.method == "GET": return httpx.Response(200, json=dict(state))
        state.update(json.loads(request.content))
        return httpx.Response(204)
    requests = transport(monkeypatch, reply)
    url = "https://example.hooks.example.test/hook"
    with pytest.raises(ValueError, match="already has a webhook"):
        await native.MagicplanNode._register_external_webhook(webhook_url=url, credential=CREDS, config={}, node_id="test")
    assert len(requests) == 1
    extra = await native.MagicplanNode._register_external_webhook(webhook_url=url, credential=CREDS, config={"replace_webhook_url": state["webhook_url"]}, node_id="test")
    assert state["webhook_url"] == url and extra["signing_secret"] == CREDS["api_key"]
    await native.MagicplanNode._unregister_external_webhook(credential=CREDS, config=extra, node_id="test")
    assert state["webhook_url"] == "https://existing.example/hook"
    state["webhook_url"] = None
    extra = await native.MagicplanNode._register_external_webhook(webhook_url=url, credential=CREDS, config={}, node_id="test")
    await native.MagicplanNode._unregister_external_webhook(credential=CREDS, config=extra, node_id="test")
    assert state["webhook_url"] is None
    state["webhook_url"] = "https://new-owner.example/hook"
    before = len(requests)
    await native.MagicplanNode._unregister_external_webhook(credential=CREDS, config=extra, node_id="test")
    assert len(requests) == before + 1 and state["webhook_url"] == "https://new-owner.example/hook"


def test_documented_form_event_authentication_and_agent_turn():
    example = json.loads((Path(__file__).parent / "fixtures/magicplan/project_updated.json").read_text())["body"]
    body, headers = urlencode(example).encode(), {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
    config = {"operation": "on_project_exported", "signing_secret": example["key"]}
    assert native.MagicplanNode.verify_webhook_signature(body, headers, config)
    assert not native.MagicplanNode.verify_webhook_signature(body, headers, {**config, "signing_secret": "wrong"})
    assert not native.MagicplanNode.verify_webhook_signature(body + b"&key=duplicate", headers, config)
    assert not native.MagicplanNode.verify_webhook_signature(json.dumps(example).encode(), {"Content-Type": "application/json"}, config)
    assert not native.MagicplanNode.verify_webhook_signature(body, headers, {})
    output = native.MagicplanNode.resolve_trigger_payload({"raw": body.decode(), "_webhook": {}}, config)
    assert "key" not in output["data"] and example["key"] not in str(output)
    event = native.MagicplanNode.resolve_agent_event(output)
    assert all(example[key] in event["text"] for key in ("email", "title", "project_id", "planid", "pdf"))
    assert event["conversation_key"] == example["project_id"]
    assert native.MagicplanNode.webhook_ack_response()["content"] == "<MagicPlanService><status>0</status></MagicPlanService>"


@pytest.mark.asyncio
async def test_trigger_transform_strips_key_before_workflow_dispatch():
    example = json.loads((Path(__file__).parent / "fixtures/magicplan/project_updated.json").read_text())["body"]
    config = {"operation": "on_project_exported"}
    transformed = await native.MagicplanNode.transform_trigger_payload({"raw": urlencode(example)}, config, pool=None, workflow_id=None, node_id="test")
    assert transformed["project_id"] == example["project_id"]
    assert example["key"] not in str(transformed) and "key" not in transformed
    assert native.MagicplanNode.resolve_trigger_payload(transformed, config)["data"] == transformed
