"""DataForSEO transport, configuration, credential and projection tests."""
import base64
import json
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from nodes.core import registry
from nodes.core.base import ConfigValidationError
from nodes.core.connection_evidence import collect_evidence
from nodes.core.run_op import run_node_operation
from nodes.dataforseo_node import DataForSEONode, ProviderStatusError, ROUTES

USER = "00000000-0000-4000-8000-000000000001"
OWNER = "00000000-0000-4000-8000-000000000002"
ORG = "00000000-0000-4000-8000-000000000003"
CID = "00000000-0000-4000-8000-000000000004"
WF = "00000000-0000-4000-8000-000000000005"
TASK = "01291721-1535-0066-0000-8f0635c0dc89"
CREDS = {"credential_type": "dataforseo_basic", "api_login": "api-user@example.com", "api_password": "synthetic-api-password"}
LOCATION = {"location_code": 2840, "location_name": "United States", "country_iso_code": "US", "location_type": "Country", "location_code_parent": None}
LANGUAGE = {"language_code": "en", "language_name": "English"}
LABS = {"labs_location_code": 2840, "labs_language_code": "en"}
ACCOUNT = {"login": CREDS["api_login"], "timezone": "UTC", "money": {"balance": 123}, "rates": {"private": "x"}}


@pytest.fixture
def ensure_native_db_pool():
    yield


def payload(result, code=20000, *, errors=0, outer=20000):
    return {"status_code": outer, "cost": 0, "tasks_count": 1, "tasks_error": errors,
        "tasks": [{"id": TASK, "status_code": code, "cost": 0, "status_message": "synthetic-api-password",
                   "result_count": len(result) if result is not None else 0, "result": result,
                   "data": {"password": CREDS["api_password"]}}]}


@pytest.fixture
def transport(monkeypatch):
    import utils.ssrf as ssrf
    native = httpx.AsyncClient
    state = SimpleNamespace(seen=[], replies=[], dns=[])
    async def dns(host, port, **kwargs):
        assert host == "api.dataforseo.com"
        state.dns.append(host)
        return {"8.8.8.8"}
    def handle(request):
        state.seen.append(request)
        assert state.replies, "Unexpected SEO request"
        status, body = state.replies.pop(0)
        return httpx.Response(status, content=body) if isinstance(body, bytes) else httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        kwargs["transport"] = httpx.MockTransport(handle)
        return native(**kwargs)
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", dns)
    monkeypatch.setattr(ssrf.httpx, "AsyncClient", client)
    return state


def node(operation, **args):
    return registry.NodeFactory.create_node("fixture", "automation-dataforseo",
        {"credentials": deepcopy(CREDS), "config": {"operation": operation, **args}},
        user_id=USER, organization_id=ORG, workflow_id=WF)


@pytest.mark.parametrize("tag", ["foreign", None, ""])
def test_factory_rejects_authoritative_foreign_type_even_with_attachment(tag):
    data = {"credentials": {**CREDS, "credential_type": tag},
        "config": {"operation": "get_account_metadata"}, "credentialIds": {"dataforseo_basic": CID}}
    with pytest.raises(ConfigValidationError):
        registry.NodeFactory.create_node("fixture", "automation-dataforseo", data)
    assert DataForSEONode.validate_config(data)["valid"] is False


@pytest.mark.parametrize("operation,args", [
    ("list_serp_languages", {"page_size": True}),
    ("list_serp_locations", {"country_code": "../private"}),
    ("get_google_organic_task_results", {"task_id": "../tasks"}),
    ("get_ranked_keywords", {**LABS, "target": "https://example.com/private?token=x"}),
    ("get_backlinks", {"target": "example.com", "include_subdomains": 0}),
    ("get_related_keywords", {**LABS, "keyword": "seo", "depth": True}),
    ("submit_google_organic_task", {"serp_location_code": 2840, "serp_language_code": "en", "keyword": "seo", "device": "mobile", "os": "windows"}),
    ("get_keyword_search_volume", {"keyword_location_code": 2840, "keyword_language_code": "en", "keywords": ["word " * 11]}),
    ("get_backlinks", {"target": "example.com", "callback_url": "https://outsider.example"}),
])
def test_strict_typed_boundaries(operation, args):
    with pytest.raises(ConfigValidationError):
        node(operation, **args)


@pytest.mark.asyncio
async def test_actual_dispatcher_basic_identity_projection(transport):
    transport.replies.append((200, payload([ACCOUNT])))
    result = await run_node_operation(node_type="automation-dataforseo", operation="get_account_metadata",
        arguments={}, credential_data=CREDS, user_id=USER, organization_id=ORG, workflow_id=WF)
    assert result["data"]["login"] == CREDS["api_login"]
    request = transport.seen[0]
    assert str(request.url) == "https://api.dataforseo.com/v3/appendix/user_data"
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"api-user@example.com:synthetic-api-password").decode()
    assert transport.dns and all(value not in json.dumps(result) for value in ("password", "money", "rates"))


@pytest.mark.asyncio
async def test_task_creation_receipt_and_actual_creator_path(transport):
    from nodes.agent.node_op_tools import resource_creators, extract_resource_id_from_output
    transport.replies.append((200, payload(None, 20100)))
    result = await node("submit_google_organic_task", serp_location_code=2840, serp_language_code="en", keyword="SEO", os="windows").execute({})
    body = json.loads(transport.seen[0].content)
    assert body == [{"location_code": 2840, "language_code": "en", "keyword": "SEO", "device": "desktop", "os": "windows", "depth": 10}]
    assert result["data"]["accepted"] is True and result["data"]["completed"] is False
    creators = resource_creators("automation-dataforseo")
    creator = next(item for item in creators if item[0] == "submit_google_organic_task")
    assert creator == ("submit_google_organic_task", "dataforseo_serp_task", "data.task_id")
    assert extract_resource_id_from_output(result, creator[2]) == TASK
    assert result["data"]["task_id"] == TASK


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [40601, 40602])
async def test_pending_result_is_not_completed(transport, code):
    transport.replies.append((200, payload(None, code, errors=1)))
    result = await node("get_google_organic_task_results", task_id=TASK).execute({})
    assert result["data"]["pending"] is True and result["data"]["completed"] is False
    assert transport.seen[0].url.path.endswith("/task_get/advanced/" + TASK)


@pytest.mark.asyncio
async def test_partial_organic_projection_and_no_query_urls(transport):
    row = {"keyword": "seo", "language_code": "en", "location_code": 2840, "items_count": 2,
           "items": [{"type": "organic", "rank_group": 1, "rank_absolute": 1, "title": "Public title",
                      "url": "https://example.com/page?private=secret#token", "html": "private"},
                     {"type": "paid", "url": "https://example.com/paid"}], "check_url": "https://search.example/?private=x"}
    transport.replies.append((200, payload([row], 40106, errors=1)))
    result = await node("get_google_organic_task_results", task_id=TASK).execute({})
    assert result["data"]["partial"] is True
    assert result["data"]["results"][0]["items"][0]["url"] == "https://example.com/page"
    assert len(result["data"]["results"][0]["items"]) == 1
    assert "private" not in json.dumps(result) and "check_url" not in json.dumps(result)


@pytest.mark.asyncio
async def test_paid_live_offset_false_zero_and_empty_page_contract(transport):
    results = {"target": "example.com", "location_code": 2840, "language_code": "en",
        "items_count": 1, "total_count": 2, "items": [{"keyword_data": {"keyword": "seo", "keyword_info": {"search_volume": 0, "cpc": None}},
        "ranked_serp_element": {"serp_item": {"type": "organic", "rank_group": 1, "url": "https://example.com/"}}}]}
    transport.replies.append((200, payload([results])))
    first = await node("get_ranked_keywords", **LABS, target="example.com", ignore_synonyms=False, page_size=1).execute({})
    query = json.loads(transport.seen[0].content)[0]
    assert query["offset"] == 0 and query["ignore_synonyms"] is False and query["include_clickstream_data"] is False
    assert query["item_types"] == ["organic"] and query["limit"] == 1
    assert first["data"]["items"][0]["keyword_info"] == {"search_volume": 0, "cpc": None}
    transport.replies.append((200, payload([results])))
    await node("get_ranked_keywords", **LABS, target="example.com", ignore_synonyms=False, page_size=1, page_token=first["data"]["next_page_token"]).execute({})
    assert json.loads(transport.seen[-1].content)[0]["offset"] == 1
    for change in [{"target": "other.com"}, {"page_size": 2}]:
        with pytest.raises(ValueError, match="cursor"):
            await node("get_ranked_keywords", **{**LABS, "target": "example.com", "page_size": 1, **change},
                page_token=first["data"]["next_page_token"]).execute({})
    transport.replies.append((200, payload([{**results, "items": None, "items_count": 0, "total_count": 0}])))
    empty = await node("get_ranked_keywords", **LABS, target="example.com").execute({})
    assert empty["data"]["items"] == [] and empty["data"]["has_more"] is False


@pytest.mark.asyncio
async def test_locale_catalog_empty_and_dependent_google_language_picker(transport):
    transport.replies.append((200, payload([])))
    empty = await node("list_serp_locations", country_code="us").execute({})
    assert empty["data"]["items"] == []
    locale = {**LOCATION, "available_languages": [{**LANGUAGE, "available_sources": ["google"]},
        {"language_code": "fr", "language_name": "French", "available_sources": ["bing"]}]}
    transport.replies.append((200, payload([locale])))
    options = await DataForSEONode.load_field_options("labs_language_code", CREDS, {"labs_location_code": 2840})
    assert options["options"] == [{"value": "en", "label": "English"}]
    assert "Authorization" not in json.dumps(options)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [
    (401, {"error": "synthetic-api-password"}), (429, b"private"), (202, payload(None, 20100)),
    (200, b"malformed"), (200, {}), (200, payload([], outer=40200)),
    (200, payload(None, 40204, errors=1)), (200, {**payload([]), "tasks_error": True}),
    (200, {**payload([]), "tasks_count": 2}),
])
async def test_safe_http_outer_per_task_and_malformed_envelopes(transport, status, body):
    transport.replies.append((status, body))
    with pytest.raises((ValueError, httpx.HTTPStatusError)) as error:
        await node("get_account_metadata").execute({})
    assert "synthetic-api-password" not in str(error.value) and "private" not in str(error.value)
    assert len(transport.seen) == 1
    if isinstance(error.value, httpx.HTTPStatusError):
        assert str(error.value.request.url) == "https://dataforseo.invalid/api/"





@pytest.mark.asyncio
async def test_preparsed_foreign_type_before_io(transport):
    instance = node("get_account_metadata")
    instance.node_data["credentials"]["credential_type"] = "foreign"
    with pytest.raises(ConfigValidationError):
        await instance.execute({})
    assert not transport.seen


def test_actual_production_schema_helper_country_defaults_and_validation():
    import ast
    from pathlib import Path
    source = Path(__file__).resolve().parents[2] / "scripts/generate_socket_types.py"
    definitions = [item for item in ast.parse(source.read_text()).body
        if isinstance(item, ast.FunctionDef) and item.name == "_assert_no_incoherent_constraints"]
    assert len(definitions) == 1
    helpers = {}
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(source), "exec"), helpers)
    schema = DataForSEONode.get_config_schema()
    helpers["_assert_no_incoherent_constraints"]("dataforseo", schema)
    for name in ("DataForSEOSerpLocations", "DataForSEOKeywordLocations",
                 "DataForSEOSubmitSerp", "DataForSEOSearchVolume"):
        field = schema["$defs"][name]["properties"]["country_code"]
        assert field["default"] == "us" and field["maxLength"] == 2
        assert "minLength" not in field
    cases = [
        ("list_serp_locations", {}),
        ("list_keyword_locations", {}),
        ("submit_google_organic_task", {"serp_location_code": 2840, "serp_language_code": "en", "keyword": "seo"}),
        ("get_keyword_search_volume", {"keyword_location_code": 2840, "keyword_language_code": "en", "keywords": ["seo"]}),
    ]
    for operation, args in cases:
        assert node(operation, **args).config.config.country_code == "us"
        assert node(operation, **args, country_code="GB").config.config.country_code == "gb"
        for invalid in ("", "u", "usa", "1x", "../private"):
            with pytest.raises(ConfigValidationError):
                node(operation, **args, country_code=invalid)





@pytest.mark.asyncio
async def test_real_manual_connect_and_account_identity(transport):
    from nodes.core.credential_connect import shape_credential
    shaped, errors, resolved = shape_credential("dataforseo_basic", {**CREDS, "unknown": "private"})
    assert not errors and resolved[0] == "automation-dataforseo"
    assert "unknown" not in DataForSEONode.parse_config({"credentials": shaped, "config": {"operation": "get_account_metadata"}}).credentials.model_dump()
    transport.replies.append((200, payload([ACCOUNT])))
    evidence = await collect_evidence(node_type="automation-dataforseo", user_id=USER, credential_data=shaped)
    assert evidence.reachable is True and evidence.account_label == CREDS["api_login"]
    assert not evidence.samples

@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args,rows,suffix", [
    ("list_serp_languages", {}, [LANGUAGE], "/serp/google/languages"),
    ("list_keyword_locations", {"country_code": "us"}, [LOCATION], "/keywords_data/google_ads/locations/us"),
    ("list_keyword_languages", {}, [LANGUAGE], "/keywords_data/google_ads/languages"),
    ("list_labs_locations_and_languages", {}, [{**LOCATION, "available_languages": [{**LANGUAGE, "available_sources": ["google"]}]}], "/dataforseo_labs/locations_and_languages"),
    ("list_ready_google_organic_tasks", {}, [{"id": TASK, "se": "google", "se_type": "organic", "endpoint_html": "https://private.example/secret"}], "/serp/google/organic/tasks_ready"),
    ("get_keyword_search_volume", {"keyword_location_code": 2840, "keyword_language_code": "en", "keywords": ["seo"], "search_partners": False}, [{"keyword": "seo", "search_volume": 0, "competition": "LOW", "competition_index": 0, "cpc": None}], "/keywords_data/google_ads/search_volume/live"),
    ("get_related_keywords", {**LABS, "keyword": "seo", "depth": 0}, [{"location_code": 2840, "language_code": "en", "items_count": 1, "total_count": 1, "items": [{"keyword_data": {"keyword": "seo", "keyword_info": None}}]}], "/dataforseo_labs/google/related_keywords/live"),
    ("get_domain_rank_overview", {**LABS, "target": "example.com"}, [{"target": "example.com", "location_code": 2840, "language_code": "en", "items_count": 1, "total_count": 1, "items": [{"metrics": {"organic": {"count": 0, "etv": 0}}}]}], "/dataforseo_labs/google/domain_rank_overview/live"),
    ("get_backlinks_summary", {"target": "example.com", "include_subdomains": False}, [{"target": "example.com", "rank": 0, "backlinks": 0, "referring_domains": 0}], "/backlinks/summary/live"),
    ("get_backlinks", {"target": "example.com", "exclude_internal_backlinks": False}, [{"target": "example.com", "items_count": 1, "total_count": 1, "items": [{"domain_from": "example.org", "url_from": "https://example.org/page?private=x", "url_to": "https://example.com/", "dofollow": False}]}], "/backlinks/backlinks/live"),
])
async def test_remaining_native_routes_and_safe_projections(transport, operation, args, rows, suffix):
    transport.replies.append((200, payload(rows)))
    result = await node(operation, **args).execute({})
    assert transport.seen[0].url.path == "/v3" + suffix
    assert result["status"] == "success" and "private" not in json.dumps(result)
    if ROUTES[operation][0] == "POST":
        body = json.loads(transport.seen[0].content)
        assert len(body) == 1 and "operation" not in body[0] and "country_code" not in body[0]
        for key in ("search_partners", "include_subdomains", "exclude_internal_backlinks"):
            if key in args:
                assert body[0][key] is args[key]







@pytest.mark.asyncio
async def test_static_basic_credential_hook_preserves_resolved_credentials():
    assert await DataForSEONode.freshen_credential(CREDS, user_id=USER, credential_id=CID) == CREDS
    with pytest.raises(ValueError):
        await DataForSEONode.freshen_credential({**CREDS, "credential_type": "foreign"})
