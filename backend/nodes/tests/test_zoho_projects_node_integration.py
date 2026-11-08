"""Zoho Projects V3 contracts, mocked at the public HTTP boundary."""

import json

import httpx
import pytest
import respx

from nodes.core.registry import NODE_REGISTRY
from nodes.core.poll_trigger import ScheduledPollTriggerMixin
from nodes.core.oauth_refresh import ensure_fresh_oauth_token
from nodes.oauth.zoho_projects_oauth import OAUTH_PROVIDER, hosts_for
from nodes.zoho_projects_node import (
    OP_MODELS, OPS, ZohoProjectsNode, ZohoProjectsNodeConfig,
    ZohoProjectsOAuthCredential, _has_next_page, _identified_rows, zoho_request,
)


@pytest.fixture(autouse=True)
def guarded_transport(monkeypatch):
    monkeypatch.setattr("utils.ssrf.guarded_async_client", httpx.AsyncClient)


def _credential(location="eu"):
    return ZohoProjectsOAuthCredential(
        access_token="test-access", refresh_token="test-refresh",
        expires_at="2099-01-01T00:00:00+00:00", location=location,
        accounts=hosts_for(location)[0], accounts_server=hosts_for(location)[0],
        portal_id="123456789012345678", portal_name="Research",
    )


def _node(operation, **kwargs):
    model = OP_MODELS[operation]
    return ZohoProjectsNode(
        node_id="z1", node_type="automation-zoho-projects",
        node_data={"credential_id": "credential-id"},
        config=ZohoProjectsNodeConfig(config=model(**kwargs), credentials=_credential()),
        user_id="user-id", workflow_id="workflow-id",
    )


def test_registry_schema_and_scope_catalog_are_complete():
    assert NODE_REGISTRY["automation-zoho-projects"] is ZohoProjectsNode
    schema = ZohoProjectsNode.get_config_schema()
    assert len(schema["properties"]["config"]["oneOf"]) == len(OPS)
    assert set(ZohoProjectsNode.scope_registry._requirements) == set(OPS)
    assert set(schema["$defs"]["ZohoProjectsOAuthCredential"]["x-oauth-scopes"]) == set(
        ZohoProjectsNode.scope_registry.declared_scopes()
    )
    assert schema["properties"]["config"]["discriminator"]["propertyName"] == "operation"


def test_region_allowlist_rejects_mismatches_and_arbitrary_hosts():
    assert hosts_for("eu", "https://accounts.zoho.eu") == (
        "https://accounts.zoho.eu", "https://projects.zoho.eu",
    )
    with pytest.raises(ValueError):
        hosts_for("eu", "https://evil.example")
    with pytest.raises(ValueError):
        hosts_for("moon")
    with pytest.raises(ValueError):
        hosts_for({"location": "eu"})
    assert not _has_next_page({"has_next_page": "false"})
    assert _has_next_page({"has_next_page": "true"})
    with pytest.raises(ValueError, match="malformed"):
        _has_next_page({"has_next_page": []})
    for malformed in ([{"id": True, "name": "A"}], [{"id": {}, "name": "A"}], [{"id": "12", "name": []}]):
        with pytest.raises(ValueError):
            _identified_rows(malformed)


@pytest.mark.asyncio
@respx.mock
async def test_region_refresh_and_204_contract(monkeypatch):
    monkeypatch.setenv("ZOHO_PROJECTS_CLIENT_ID", "client-id")
    monkeypatch.setenv("ZOHO_PROJECTS_CLIENT_SECRET", "client-secret")
    token = respx.post("https://accounts.zoho.in/oauth/v2/token").mock(
        return_value=httpx.Response(200, json={"access_token": "new-token", "expires_in": 3600})
    )
    refreshed = (await OAUTH_PROVIDER.bind_refresh(_credential("in").model_dump())("old-refresh")).model_dump()
    assert refreshed["access_token"] == "new-token"
    assert refreshed["refresh_token"] is None  # shared refresh preserves the saved token
    assert b"grant_type=refresh_token" in token.calls[0].request.content
    respx.delete("https://projects.zoho.in/api/v3/portal/1/projects/2/tasks/3").mock(
        return_value=httpx.Response(204)
    )
    result = await zoho_request(
        {"location": "in", "access_token": "new-token"}, "DELETE",
        "/portal/1/projects/2/tasks/3",
    )
    assert result == {"status": "success", "http_status": 204}
    respx.post("https://projects.zoho.in/api/v3/portal/1/projects/2/tasks").mock(
        return_value=httpx.Response(202)
    )
    assert await zoho_request(
        {"location": "in", "access_token": "new-token"}, "POST",
        "/portal/1/projects/2/tasks",
    ) == {"status": "accepted", "http_status": 202}


@pytest.mark.asyncio
@respx.mock
async def test_provider_errors_are_strict_and_do_not_echo_bodies():
    url = "https://projects.zoho.eu/api/v3/portals"
    route = respx.get(url)
    credential = _credential().model_dump()
    for status in (302, 500):
        route.mock(return_value=httpx.Response(status, text="secret bearer echo"))
        with pytest.raises(ValueError, match=f"HTTP {status}") as raised:
            await zoho_request(credential, "GET", "/portals")
        assert "secret" not in str(raised.value)
    for response, message in (
        (httpx.Response(200), "empty response"),
        (httpx.Response(200, text="secret bearer echo"), "non-JSON"),
        (httpx.Response(200, text="{broken", headers={"Content-Type": "application/json"}), "malformed JSON"),
        (httpx.Response(200, json=False), "unexpected JSON"),
    ):
        route.mock(return_value=response)
        with pytest.raises(ValueError, match=message) as raised:
            await zoho_request(credential, "GET", "/portals")
        assert "secret" not in str(raised.value)
    route.mock(side_effect=httpx.ConnectError("sensitive transport detail"))
    with pytest.raises(ValueError, match="could not be reached") as raised:
        await zoho_request(credential, "GET", "/portals")
    assert "sensitive" not in str(raised.value)


@pytest.mark.asyncio
@respx.mock
async def test_refresh_uses_current_saved_data_center_after_reread(monkeypatch):
    monkeypatch.setenv("ZOHO_PROJECTS_CLIENT_ID", "client-id")
    monkeypatch.setenv("ZOHO_PROJECTS_CLIENT_SECRET", "client-secret")
    route = respx.post("https://accounts.zoho.in/oauth/v2/token").mock(
        return_value=httpx.Response(200, json={"access_token": "new-token"})
    )

    async def simulated_locked_reread(**kwargs):
        # The shared refresh helper updates this dict under its lock before
        # invoking refresh(). The callback must read the updated location.
        kwargs["credential"].update(location="in", accounts_server="https://accounts.zoho.in")
        await kwargs["refresh"]("saved-refresh")

    monkeypatch.setattr("nodes.core.oauth_refresh.ensure_fresh_oauth_token", simulated_locked_reread)
    node = _node("list_portals")
    respx.get("https://projects.zoho.in/api/v3/portals").mock(
        return_value=httpx.Response(200, json=[{"id": "123456789012345678", "portal_name": "Research"}])
    )
    result = await node.execute({})
    assert result["data"][0]["portal_name"] == "Research"
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_locked_refresh_adopts_saved_region_before_call(monkeypatch):
    monkeypatch.setenv("ZOHO_PROJECTS_CLIENT_ID", "client-id")
    monkeypatch.setenv("ZOHO_PROJECTS_CLIENT_SECRET", "client-secret")
    route = respx.post("https://accounts.zoho.in/oauth/v2/token").mock(
        return_value=httpx.Response(200, json={"access_token": "new-token"})
    )
    credential = _credential("eu").model_dump()
    credential["expires_at"] = "2020-01-01T00:00:00+00:00"

    class SavedCredential:
        lock_key = "zoho-test-current-region"

        async def load(self):
            return {**credential, "location": "in", "accounts_server": "https://accounts.zoho.in", "refresh_token": "saved-refresh"}

        async def persist(self, new_data, metadata_updates):
            assert new_data["location"] == "in"
            return 1, None

    await ensure_fresh_oauth_token(
        credential_id=None, user_id=None, credential=credential,
        refresh=OAUTH_PROVIDER.bind_refresh(credential),
        additional_token_fields=OAUTH_PROVIDER.credential_fields,
        provider="zoho_projects", caller_path="execute", store=SavedCredential(),
    )
    assert route.called
    assert credential["location"] == "in"
    assert credential["access_token"] == "new-token"


@pytest.mark.asyncio
@respx.mock
async def test_create_task_uses_documented_v3_json_and_bearer(monkeypatch):
    async def no_refresh(**kwargs):
        return kwargs["credential"]
    monkeypatch.setattr("nodes.core.oauth_refresh.ensure_fresh_oauth_token", no_refresh)
    url = "https://projects.zoho.eu/api/v3/portal/123456789012345678/projects/99/tasks"
    route = respx.post(url).mock(return_value=httpx.Response(
        201, json={"id": "777", "name": "Ship docs"}, headers={"Content-Type": "application/json"},
    ))
    result = await _node(
        "create_task", portal_id="123456789012345678", project_id="99",
        name="Ship docs", tasklist_id="88", priority="high",
    ).execute({})
    assert result["data"]["id"] == "777"
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer test-access"
    assert json.loads(request.content) == {
        "name": "Ship docs", "priority": "high", "tasklist": {"id": "88"},
    }
    with pytest.raises(ValueError, match="numeric Zoho ID"):
        await _node("get_task", portal_id="../evil", project_id="99", task_id="777").execute({})


@pytest.mark.asyncio
@respx.mock
async def test_project_picker_accepts_documented_array_response():
    respx.get("https://projects.zoho.eu/api/v3/portal/123456789012345678/projects").mock(
        return_value=httpx.Response(200, json=[{"id": "99", "name": "Website Redesign"}])
    )
    result = await ZohoProjectsNode.load_field_options(
        "project_id", _credential().model_dump(), context={"portal_id": "123456789012345678"},
    )
    assert result == {"options": [{"value": "99", "label": "Website Redesign"}], "next_page_token": None}


@pytest.mark.asyncio
@pytest.mark.parametrize("field_name,resource,suffix", [
    ("project_id", "projects", ""),
    ("tasklist_id", "tasklists", "/99/tasklists"),
    ("task_id", "tasks", "/99/tasks"),
])
@respx.mock
async def test_picker_search_reaches_page_two_after_empty_matches(field_name, resource, suffix):
    url = f"https://projects.zoho.eu/api/v3/portal/123456789012345678/projects{suffix}"
    def respond(request):
        page = int(request.url.params["page"])
        assert request.url.params["per_page"] == "100"
        return httpx.Response(200, json={
            resource: [{"id": str(page), "name": "Other" if page == 1 else "Needle on page two"}],
            "page_info": {"page": page, "has_next_page": page == 1},
        })
    route = respx.get(url).mock(side_effect=respond)
    result = await ZohoProjectsNode.load_field_options(
        field_name, _credential().model_dump(),
        context={"portal_id": "123456789012345678", "project_id": "99"}, search="nEeDlE",
    )
    assert result == {"options": [{"value": "2", "label": "Needle on page two"}], "next_page_token": None}
    assert [call.request.url.params["page"] for call in route.calls] == ["1", "2"]


@pytest.mark.asyncio
@respx.mock
async def test_picker_search_returns_no_matches_only_after_exhaustion():
    url = "https://projects.zoho.eu/api/v3/portal/123456789012345678/projects"
    def respond(request):
        page = int(request.url.params["page"])
        return httpx.Response(200, json={
            "projects": [{"id": str(page), "name": "Other"}],
            "page_info": {"page": page, "has_next_page": page < 3},
        })
    route = respx.get(url).mock(side_effect=respond)
    result = await ZohoProjectsNode.load_field_options(
        "project_id", _credential().model_dump(), search="missing",
    )
    assert result == {"options": [], "next_page_token": None}
    assert len(route.calls) == 3


@pytest.mark.asyncio
@respx.mock
async def test_picker_search_preserves_shared_frontend_lowercase_matching():
    respx.get("https://projects.zoho.eu/api/v3/portal/123456789012345678/projects").mock(
        return_value=httpx.Response(200, json={
            "projects": [{"id": "1", "name": "Straße"}, {"id": "2", "name": "SS display"}],
            "page_info": {"page": 1, "has_next_page": False},
        })
    )
    result = await ZohoProjectsNode.load_field_options("project_id", _credential().model_dump(), search="SS")
    assert result == {"options": [{"value": "2", "label": "SS display"}], "next_page_token": None}


@pytest.mark.asyncio
@respx.mock
async def test_picker_search_accumulates_sparse_matches_and_consumes_full_pages():
    url = "https://projects.zoho.eu/api/v3/portal/123456789012345678/projects"
    def respond(request):
        page = int(request.url.params["page"])
        return httpx.Response(200, json={
            "projects": [{"id": str(page * 100 + i), "name": f"Needle {page}-{i}"} for i in range(15)],
            "page_info": {"page": page, "has_next_page": True},
        })
    route = respx.get(url).mock(side_effect=respond)
    result = await ZohoProjectsNode.load_field_options("project_id", _credential().model_dump(), search="needle")
    assert len(result["options"]) == 30
    assert result["options"][-1]["value"] == "214"
    assert result["next_page_token"] == "3"
    assert len(route.calls) == 2
    continuation = await ZohoProjectsNode.load_field_options(
        "project_id", _credential().model_dump(), page_token=result["next_page_token"], search="needle",
    )
    assert continuation["options"][0]["value"] == "300"
    assert continuation["next_page_token"] == "5"


@pytest.mark.asyncio
@respx.mock
async def test_picker_without_search_preserves_single_page_browsing():
    route = respx.get("https://projects.zoho.eu/api/v3/portal/123456789012345678/projects").mock(
        return_value=httpx.Response(200, json={
            "projects": [{"id": "99", "name": "Unfiltered"}],
            "page_info": {"page": 4, "has_next_page": True},
        })
    )
    result = await ZohoProjectsNode.load_field_options("project_id", _credential().model_dump(), page_token="4")
    assert result == {"options": [{"value": "99", "label": "Unfiltered"}], "next_page_token": "5"}
    assert len(route.calls) == 1


@pytest.mark.asyncio
@respx.mock
async def test_picker_search_bound_raises_instead_of_returning_unreachable_cursor():
    def respond(request):
        page = int(request.url.params["page"])
        return httpx.Response(200, json={
            "projects": [{"id": str(page), "name": "Other"}],
            "page_info": {"page": page, "has_next_page": True},
        })
    route = respx.get("https://projects.zoho.eu/api/v3/portal/123456789012345678/projects").mock(side_effect=respond)
    with pytest.raises(ValueError, match="exceeded 10 pages"):
        await ZohoProjectsNode.load_field_options("project_id", _credential().model_dump(), search="missing")
    assert len(route.calls) == 10


@pytest.mark.asyncio
@pytest.mark.parametrize("data,message", [
    ({"projects": [], "page_info": {}}, "pagination metadata is missing"),
    ({"projects": [], "page_info": {"has_next_page": []}}, "pagination metadata is malformed"),
    ({"projects": [{"id": "99", "name": []}], "page_info": {"has_next_page": False}}, "unnamed item"),
    ({"projects": [{"id": "99", "name": "A"}], "page_info": {"page": 0, "has_next_page": True}}, "page did not advance"),
])
@respx.mock
async def test_picker_search_rejects_malformed_paging(data, message):
    route = respx.get("https://projects.zoho.eu/api/v3/portal/123456789012345678/projects").mock(
        return_value=httpx.Response(200, json=data)
    )
    with pytest.raises(ValueError, match=message):
        await ZohoProjectsNode.load_field_options("project_id", _credential().model_dump(), search="needle")
    assert len(route.calls) == 1


@pytest.mark.asyncio
@respx.mock
async def test_picker_search_rejects_repeated_page_number_before_advancing():
    route = respx.get("https://projects.zoho.eu/api/v3/portal/123456789012345678/projects").mock(
        side_effect=[
            httpx.Response(200, json={"projects": [{"id": "1", "name": "Other"}], "page_info": {"page": 1, "has_next_page": True}}),
            httpx.Response(200, json={"projects": [{"id": "2", "name": "Other"}], "page_info": {"page": 1, "has_next_page": True}}),
        ]
    )
    with pytest.raises(ValueError, match="page did not advance"):
        await ZohoProjectsNode.load_field_options("project_id", _credential().model_dump(), search="needle")
    assert len(route.calls) == 2


@pytest.mark.asyncio
@respx.mock
async def test_picker_search_rejects_repeated_data_even_without_page_number():
    route = respx.get("https://projects.zoho.eu/api/v3/portal/123456789012345678/projects").mock(
        return_value=httpx.Response(200, json={
            "projects": [{"id": "1", "name": "Other"}], "page_info": {"has_next_page": True},
        })
    )
    with pytest.raises(ValueError, match="repeated items"):
        await ZohoProjectsNode.load_field_options("project_id", _credential().model_dump(), search="needle")
    assert len(route.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("token", ["", "0", "-1", "1.5", "../2", "２", 2])
@respx.mock
async def test_picker_rejects_invalid_page_token_before_http(token):
    with pytest.raises(ValueError, match="positive numeric page"):
        await ZohoProjectsNode.load_field_options("project_id", _credential().model_dump(), page_token=token, search="needle")
    assert not respx.calls


@pytest.mark.asyncio
@respx.mock
async def test_portal_evidence_rejects_empty_list():
    respx.get("https://projects.zoho.eu/api/v3/portals").mock(
        return_value=httpx.Response(200, json=[])
    )
    with pytest.raises(ValueError, match="No Zoho Projects portal"):
        await ZohoProjectsNode.load_field_options("portal_id", _credential().model_dump())


@pytest.mark.asyncio
@respx.mock
async def test_project_owner_picker_uses_verified_portal_owner():
    respx.get("https://projects.zoho.eu/api/v3/portals").mock(
        return_value=httpx.Response(200, json=[
            {"id": "123456789012345678", "portal_name": "Research", "owner": {"zpuid": "801234", "full_name": "Sole Admin"}},
            {"id": "123456789012345679", "portal_name": "Other", "owner": {"zpuid": "909999", "full_name": "Other Owner"}},
        ])
    )
    result = await ZohoProjectsNode.load_field_options(
        "owner_zpuid", _credential().model_dump(),
        context={"portal_id": "123456789012345678"},
    )
    assert result == {"options": [{"value": "801234", "label": "Sole Admin"}], "next_page_token": None}


@pytest.mark.asyncio
@respx.mock
async def test_task_poll_sorts_and_deduplicates_with_scoped_state(monkeypatch):
    async def no_refresh(**kwargs):
        return kwargs["credential"]
    monkeypatch.setattr("nodes.core.oauth_refresh.ensure_fresh_oauth_token", no_refresh)
    url = "https://projects.zoho.eu/api/v3/portal/123456789012345678/projects/99/tasks"
    route = respx.get(url).mock(return_value=httpx.Response(200, json={
        "tasks": [{"id": "777", "name": "New task"}],
        "page_info": {"has_next_page": False},
    }))
    node = _node("on_new_task", portal_id="123456789012345678", project_id="99")
    async def filter_unseen(items, id_fn):
        assert [id_fn(item) for item in items] == ["777"]
        return items
    monkeypatch.setattr(node, "_filter_unseen", filter_unseen)
    result = await node.execute({})
    assert result["new_count"] == 1
    assert route.calls[0].request.url.params["sort_by"] == "DESC(created_time)"
    assert route.calls[0].request.url.params["per_page"] == "200"


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("tasks", [
    [{"id": "777", "name": "A"}, {"id": "777", "name": "B"}],
    [{"id": True, "name": "A"}],
    [{"id": "777", "name": {"unsafe": True}}],
])
async def test_bad_poll_rows_never_advance_seen_state(monkeypatch, tasks):
    async def no_refresh(**kwargs):
        return kwargs["credential"]
    monkeypatch.setattr("nodes.core.oauth_refresh.ensure_fresh_oauth_token", no_refresh)
    respx.get("https://projects.zoho.eu/api/v3/portal/123456789012345678/projects/99/tasks").mock(
        return_value=httpx.Response(200, json={"tasks": tasks, "page_info": {"has_next_page": False}})
    )
    node = _node("on_new_task", portal_id="123456789012345678", project_id="99")
    async def would_advance(*args):
        pytest.fail("invalid poll must not write its cursor")
    monkeypatch.setattr(node, "_filter_unseen", would_advance)
    with pytest.raises(ValueError):
        await node.execute({})


@pytest.mark.asyncio
@respx.mock
async def test_duplicate_poll_ids_across_pages_never_advance_seen_state(monkeypatch):
    async def no_refresh(**kwargs):
        return kwargs["credential"]
    monkeypatch.setattr("nodes.core.oauth_refresh.ensure_fresh_oauth_token", no_refresh)
    pages = [
        httpx.Response(200, json={"tasks": [{"id": "777", "name": "A"}], "page_info": {"has_next_page": True}}),
        httpx.Response(200, json={"tasks": [{"id": "777", "name": "A"}], "page_info": {"has_next_page": False}}),
    ]
    respx.get("https://projects.zoho.eu/api/v3/portal/123456789012345678/projects/99/tasks").mock(side_effect=pages)
    node = _node("on_new_task", portal_id="123456789012345678", project_id="99")
    async def would_advance(*args):
        pytest.fail("duplicate poll must not write its cursor")
    monkeypatch.setattr(node, "_filter_unseen", would_advance)
    with pytest.raises(ValueError, match="duplicate task IDs"):
        await node.execute({})


@pytest.mark.asyncio
@respx.mock
async def test_declared_zoho_projects_exchange_and_refresh_context(monkeypatch):
    monkeypatch.setenv("ZOHO_PROJECTS_CLIENT_ID", "client-id")
    monkeypatch.setenv("ZOHO_PROJECTS_CLIENT_SECRET", "client-secret")
    token = respx.post("https://accounts.zoho.eu/oauth/v2/token").mock(
        return_value=httpx.Response(200, json={
            "access_token": "token", "refresh_token": "refresh", "expires_in": 3600,
            "scope": ",".join(OAUTH_PROVIDER.scopes),
        })
    )
    identity = respx.get("https://accounts.zoho.eu/oauth/user/info").mock(
        return_value=httpx.Response(200, json={"Email": "test@example.com"})
    )
    context = {"accounts": "https://accounts.zoho.com",
               "accounts_server": "https://accounts.zoho.eu", "location": "eu"}
    tokens, name = await OAUTH_PROVIDER.exchange(
        "grant", "https://app.example/callback", context=context
    )
    assert token.called and identity.called
    assert name == "test@example.com"
    assert tokens.accounts_server == context["accounts_server"]
    assert tokens.location == "eu"
    assert OAUTH_PROVIDER.scope_separator == ","
    assert set(OAUTH_PROVIDER.granted_scopes(tokens, OAUTH_PROVIDER.scopes)) == set(OAUTH_PROVIDER.scopes)
    credential = ZohoProjectsOAuthCredential(**tokens.model_dump())
    assert credential.portal_id is None  # selected by the authenticated picker
    assert b"grant_type=authorization_code" in token.calls[0].request.content
    assert identity.calls[0].request.headers["Authorization"] == "Bearer token"
    before = len(token.calls)
    for malicious in ("https://accounts.zoho.eu.evil.test", "http://accounts.zoho.eu", "https://127.0.0.1"):
        with pytest.raises(ValueError):
            await OAUTH_PROVIDER.exchange("grant", "https://app.example/callback",
                context={**context, "accounts_server": malicious})
    assert len(token.calls) == before
    identity.mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(KeyError):
        await OAUTH_PROVIDER.exchange("grant", "https://app.example/callback", context=context)
