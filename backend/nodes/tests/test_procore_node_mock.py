"""Procore transport contracts and rotating OAuth, without live credentials."""
import json
from unittest.mock import AsyncMock, Mock
from urllib.parse import parse_qs
import httpx
import pytest
import respx
from pydantic import ValidationError
from nodes.procore_node import ProcoreNode, ProcoreNodeConfig, ProcoreOAuthCredential
from nodes.oauth.procore_oauth import OAUTH_PROVIDER


def node(config, **credential):
    return ProcoreNode(node_id="procore-test", node_type="automation-procore", node_data={},
        config=ProcoreNodeConfig(config=config, credentials=ProcoreOAuthCredential(access_token="access", **credential)),
        sio=Mock(), sid="sid", workflow_id="workflow", user_id="user")


# Expected URLs are independently transcribed from the published API contract.
CASES = [
    ("get_current_user", {}, "GET", "/rest/v1.0/me"),
    ("list_companies", {}, "GET", "/rest/v1.0/companies"),
    ("list_projects", {"company_id": 1, "name": "Tower", "status": "Active"}, "GET", "/rest/v1.0/projects"),
    ("get_project", {"company_id": 1, "project_id": 2}, "GET", "/rest/v1.0/projects/2"),
    ("create_project", {"company_id": 1, "name": "Project F"}, "POST", "/rest/v1.0/projects"),
    ("update_project", {"company_id": 1, "project_id": 2, "active": False}, "PATCH", "/rest/v1.0/projects/2"),
    ("list_vendors", {"company_id": 1, "search": "ABC"}, "GET", "/rest/v1.0/vendors"),
    ("get_vendor", {"company_id": 1, "vendor_id": 3}, "GET", "/rest/v1.0/vendors/3"),
    ("create_vendor", {"company_id": 1, "name": "ABC"}, "POST", "/rest/v1.0/vendors"),
    ("update_vendor", {"company_id": 1, "vendor_id": 3, "name": "ABC"}, "PATCH", "/rest/v1.0/vendors/3"),
    ("list_project_users", {"company_id": 1, "project_id": 2, "search": "Pat"}, "GET", "/rest/v1.0/projects/2/users"),
    ("list_rfis", {"company_id": 1, "project_id": 2, "status": "open", "search": "Wall"}, "GET", "/rest/v1.0/projects/2/rfis"),
    ("get_rfi", {"company_id": 1, "project_id": 2, "rfi_id": 4}, "GET", "/rest/v1.0/projects/2/rfis/4"),
    ("create_rfi", {"company_id": 1, "project_id": 2, "subject": "Wall Color", "question": "What color?", "rfi_manager_id": 1}, "POST", "/rest/v1.0/projects/2/rfis"),
    ("update_rfi", {"company_id": 1, "project_id": 2, "rfi_id": 4, "question": "Revised?", "draft": False}, "PATCH", "/rest/v1.0/projects/2/rfis/4"),
    ("list_submittals", {"company_id": 1, "project_id": 2, "search": "Tile"}, "GET", "/rest/v1.1/projects/2/submittals"),
    ("get_submittal", {"company_id": 1, "project_id": 2, "submittal_id": 5}, "GET", "/rest/v1.1/projects/2/submittals/5"),
    ("create_submittal", {"company_id": 1, "project_id": 2, "number": "1", "title": "Tile"}, "POST", "/rest/v1.1/projects/2/submittals"),
    ("list_notes_logs", {"company_id": 1, "project_id": 2, "log_date": "2016-05-19"}, "GET", "/rest/v1.0/projects/2/notes_logs"),
    ("create_notes_log", {"company_id": 1, "project_id": 2, "date": "2016-05-19", "comment": "No Additional notes"}, "POST", "/rest/v1.0/projects/2/notes_logs"),
    ("list_locations", {"company_id": 1, "project_id": 2, "search": "Floor"}, "GET", "/rest/v1.0/projects/2/locations"),
    ("create_location", {"company_id": 1, "project_id": 2, "node_name": "Floor 1", "parent_id": 6}, "POST", "/rest/v1.0/projects/2/locations"),
]
BODIES = {
    "create_project": {"company_id": 1, "project": {"name": "Project F"}},
    "update_project": {"company_id": 1, "project": {"active": False}},
    "create_vendor": {"company_id": 1, "vendor": {"name": "ABC"}},
    "update_vendor": {"company_id": 1, "vendor": {"name": "ABC"}},
    "create_rfi": {"rfi": {"subject": "Wall Color", "question": {"body": "What color?"}, "rfi_manager_id": 1, "draft": True}},
    "update_rfi": {"rfi": {"question": {"body": "Revised?"}, "draft": False}},
    "create_submittal": {"submittal": {"number": "1", "title": "Tile"}},
    "create_notes_log": {"notes_log": {"date": "2016-05-19", "comment": "No Additional notes", "is_issue_day": False}},
    "create_location": {"location": {"node_name": "Floor 1", "parent_id": 6}},
}
QUERIES = {
    "list_projects": {"company_id": "1", "filters[name]": "Tower", "filters[by_status]": "Active"},
    "get_project": {"company_id": "1"}, "get_vendor": {"company_id": "1"},
    "list_vendors": {"company_id": "1", "filters[search]": "ABC"},
    "list_project_users": {"filters[search]": "Pat"},
    "list_rfis": {"search": "Wall", "filters[status]": "open"},
    "list_submittals": {"filters[query]": "Tile"},
    "create_submittal": {"send_emails": "false"},
    "list_notes_logs": {"log_date": "2016-05-19"},
    "list_locations": {"filters[search]": "Floor"},
}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path", CASES, ids=[c[0] for c in CASES])
async def test_procore_requests(operation, config, method, path):
    payload = [{"id": 1, "name": "ABC"}] if operation.startswith("list_") else {"id": 1, "name": "ABC"}
    with respx.mock(assert_all_called=True) as router:
        route = router.request(method, "https://api.procore.com" + path).mock(return_value=httpx.Response(200, json=payload))
        result = await node({"operation": operation, **config}).execute({})
    req = route.calls[0].request
    assert req.headers["Authorization"] == "Bearer access"
    assert req.headers.get("Procore-Company-Id") == ("1" if "company_id" in config else None)
    query = dict(QUERIES.get(operation, {}))
    if operation.startswith("list_"):
        query.update(page="1", per_page="100")
    assert dict(req.url.params) == query
    assert (json.loads(req.content) if req.content else None) == BODIES.get(operation)
    assert result["data"] == payload and result["operation"] == operation


@pytest.mark.asyncio
async def test_procore_pagination_and_empty_page():
    with respx.mock(assert_all_called=True) as router:
        route = router.get("https://api.procore.com/rest/v1.0/companies").mock(side_effect=[
            httpx.Response(200, json=[{"id": 1, "name": "ABC Drywall"}], headers={"Link": '<https://api.procore.com/rest/v1.0/companies?page=2&per_page=1>; rel="next"'}),
            httpx.Response(200, json=[]),
        ])
        first = await node({"operation": "list_companies", "per_page": 1}).execute({})
        second = await node({"operation": "list_companies", "page": first["next_page"], "per_page": 1}).execute({})
    assert first["next_page"] == 2
    assert second["next_page"] is None and second["data"] == []
    assert route.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [(401, {"error": "Invalid token"}), (403, {"message": "Forbidden"}), (429, {"error": "Rate limit"}), (200, {"errors": ["refused"]})])
async def test_procore_errors_are_not_success(status, payload):
    with respx.mock(assert_all_called=True) as router:
        router.get("https://api.procore.com/rest/v1.0/me").mock(return_value=httpx.Response(status, json=payload))
        with pytest.raises(ValueError):
            await node({"operation": "get_current_user"}).execute({})


@pytest.mark.asyncio
async def test_procore_empty_update_and_invalid_inputs():
    for config in [{"operation": "get_project", "company_id": 1, "project_id": -1}, {"operation": "list_companies", "per_page": 101}, {"operation": "create_rfi", "company_id": 1, "project_id": 2}]:
        with pytest.raises(ValidationError):
            node(config)
    with pytest.raises(ValueError, match="at least one"):
        await node({"operation": "update_project", "company_id": 1, "project_id": 2}).execute({})
    with pytest.raises(ValidationError):
        ProcoreOAuthCredential(access_token="Bearer token")


@pytest.mark.asyncio
async def test_procore_oauth_exchange_and_rotation(monkeypatch):
    monkeypatch.setenv("PROCORE_CLIENT_ID", "client")
    monkeypatch.setenv("PROCORE_CLIENT_SECRET", "secret")
    callback = "https://app.example.com/api/auth/oauth/procore/callback"
    monkeypatch.setenv("PROCORE_REDIRECT_URI", callback)
    with respx.mock(assert_all_called=True) as router:
        route = router.post("https://login.procore.com/oauth/token").mock(side_effect=[
            httpx.Response(200, json={"access_token": "first", "refresh_token": "renew", "expires_in": 5400}),
            httpx.Response(200, json={"access_token": "second", "refresh_token": "rotated", "expires_in": 5400}),
        ])
        router.get("https://api.procore.com/rest/v1.0/me").mock(return_value=httpx.Response(200, json={"id": 1, "login": "pat@example.com", "name": "Pat"}))
        first, name = await OAUTH_PROVIDER.exchange("code", callback)
        second = await OAUTH_PROVIDER.refresh(first.refresh_token)
    assert name == "pat@example.com" and second.refresh_token == "rotated"
    assert parse_qs(route.calls[0].request.content.decode()) == {"grant_type": ["authorization_code"], "code": ["code"], "client_id": ["client"], "client_secret": ["secret"], "redirect_uri": [callback]}
    assert parse_qs(route.calls[1].request.content.decode()) == {"grant_type": ["refresh_token"], "refresh_token": ["renew"], "client_id": ["client"], "client_secret": ["secret"], "redirect_uri": [callback]}


@pytest.mark.asyncio
async def test_procore_refresh_requires_successor(monkeypatch):
    monkeypatch.setenv("PROCORE_CLIENT_ID", "client")
    monkeypatch.setenv("PROCORE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("PROCORE_REDIRECT_URI", "https://app.example.com/callback")
    with respx.mock(assert_all_called=True) as router:
        router.post("https://login.procore.com/oauth/token").mock(return_value=httpx.Response(200, json={"access_token": "new", "expires_in": 5400}))
        with pytest.raises(ValueError, match="refresh_token"):
            await OAUTH_PROVIDER.refresh("consumed")


@pytest.mark.asyncio
async def test_procore_shared_refresh_hooks_adopt_tokens(monkeypatch):
    async def rotate(**kwargs):
        kwargs["credential"].update(access_token="fresh", refresh_token="successor", expires_at="2099-01-01T00:00:00Z")
        return "fresh"
    refresh = AsyncMock(side_effect=rotate)
    monkeypatch.setattr("nodes.core.oauth_refresh.ensure_fresh_oauth_token", refresh)
    n = node({"operation": "get_current_user"}, refresh_token="old", expires_at="2000-01-01T00:00:00Z")
    assert await n._token(n.config.credentials) == "fresh"
    assert n.config.credentials.refresh_token == "successor"
    assert refresh.call_args.kwargs["provider"] == "procore"
    freshen = AsyncMock(return_value={"access_token": "current"})
    monkeypatch.setattr("nodes.core.oauth_refresh.freshen_oauth_credential", freshen)
    assert await ProcoreNode.freshen_credential({"refresh_token": "old"}) == {"access_token": "current"}
    freshen.assert_awaited_once()


@pytest.mark.asyncio
async def test_procore_vendor_compact_view_properties():
    # Compact-view id and name examples from the published vendor reference.
    # Its overlapping oneOf alternatives prevent spec validation of this object.
    payload = {"id": 161072, "name": "SID Architecture"}
    with respx.mock(assert_all_called=True) as router:
        router.get("https://api.procore.com/rest/v1.0/vendors/161072").mock(return_value=httpx.Response(200, json=payload))
        result = await node({"operation": "get_vendor", "company_id": 1, "vendor_id": 161072}).execute({})
    assert result["data"] == payload


def test_procore_native_config_metadata():
    raw = {"config": {"operation": "get_current_user", "credentialIds": {"procore_oauth": "saved"}},
           "credentials": {"access_token": "access"}}
    config = ProcoreNode.parse_config(raw)
    assert config.config.operation == "get_current_user"
    assert config.credentials.credential_type == "procore_oauth"
    assert ProcoreNode.validate_config(raw)["valid"] is True
