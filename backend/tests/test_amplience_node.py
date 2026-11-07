"""Native Amplience factory, collector, dispatcher and selector regressions."""
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import httpx
import pytest
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation
from nodes.core.connection_evidence import collect_evidence
from nodes.amplience_node import AmplienceNode, _credential

TYPE = "automation-amplience"
USER, KEY = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
HUB, REPO, CONTENT_TYPE, FOLDER = "hub-fixture", "repo-fixture", "type-fixture", "folder-fixture"
ITEM = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
RAW = {"credential_type": "amplience_pat", "token": "synthetic-amplience-issued-token", "reference_hub_id": HUB}
HUB_ROW = {"id": HUB, "name": "Opt-in hub", "organizationId": "PRIVATE-ORG", "settings": {"secret": "PRIVATE"}, "_links": {"self": {"href": "https://private.example.test/PRIVATE"}}}
REPO_ROW = {"id": REPO, "type": "CONTENT", "status": "ACTIVE", "label": "Opt-in repository", "contentTypes": [{"contentTypeUri": "PRIVATE-URI"}], "features": ["PRIVATE"]}
ITEM_ROW = {"id": ITEM, "contentRepositoryId": REPO, "label": "Opt-in item", "status": "ACTIVE", "version": 2, "createdDate": "2026-01-01T00:00:00Z", "publishingStatus": "NONE", "body": {"_meta": {"name": "PRIVATE"}, "answer": "PRIVATE-CONTENT"}, "createdBy": "PRIVATE-ACTOR", "deliveryId": "PRIVATE", "deliveryKey": "PRIVATE", "_links": HUB_ROW["_links"]}
FOLDER_ROW = {"id": FOLDER, "name": "Opt-in folder", "_links": HUB_ROW["_links"]}


def hal(resource, rows, page=0, size=20, total_pages=1, total_elements=None):
    return {"_embedded": {resource: deepcopy(rows)}, "_links": {"next": {"href": "https://private.example.test/PRIVATE"}}, "page": {"number": page, "size": size, "totalPages": total_pages, "totalElements": total_elements if total_elements is not None else max(len(rows), 1)}}


@pytest.fixture(autouse=True)
def ensure_native_db_pool(): yield


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], {}
    def handle(request):
        calls.append(request)
        assert request.method == "GET" and request.url.host == "api.amplience.net" and request.url.scheme == "https"
        assert request.headers["Authorization"] == "Bearer " + RAW["token"]
        assert request.headers["Accept"] == "application/hal+json"
        assert RAW["token"] not in str(request.url) and not request.content
        path = request.url.path.removeprefix("/v2/content")
        page, size = int(request.url.params.get("page", 0)), int(request.url.params.get("size", 20))
        defaults = {
            "/hubs": hal("hubs", [HUB_ROW], page, size), "/hubs/" + HUB: HUB_ROW,
            "/hubs/" + HUB + "/content-repositories": hal("content-repositories", [REPO_ROW], page, size),
            "/content-repositories/" + REPO: REPO_ROW,
            "/hubs/" + HUB + "/content-types": hal("content-types", [{"id": CONTENT_TYPE, "status": "ACTIVE", "settings": {"label": "PRIVATE"}, "contentTypeUri": "PRIVATE"}], page, size),
            "/content-types/" + CONTENT_TYPE: {"id": CONTENT_TYPE, "status": "ACTIVE", "settings": {"label": "PRIVATE"}},
            "/content-repositories/" + REPO + "/content-items": hal("content-items", [ITEM_ROW], page, size),
            "/content-items/" + ITEM: ITEM_ROW,
            "/content-repositories/" + REPO + "/folders": hal("folders", [FOLDER_ROW], page, size),
            "/folders/" + FOLDER: FOLDER_ROW,
            "/folders/" + FOLDER + "/folders": hal("folders", [{"id": "child-fixture", "name": "Opt-in child"}], page, size),
        }
        assert path in defaults
        reply = replies.get(path, (200, defaults[path]))
        if callable(reply): reply = reply(request)
        if isinstance(reply, Exception): raise reply
        status, payload = reply
        return httpx.Response(status, content=payload if isinstance(payload, bytes) else json.dumps(payload).encode())
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 20, "follow_redirects": False, "trust_env": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as instance: yield instance
    monkeypatch.setattr("nodes.amplience_node.guarded_async_client", client)
    return calls, replies


async def run(operation, **arguments):
    return await run_node_operation(node_type=TYPE, operation=operation, arguments=arguments, credential_data=deepcopy(RAW), user_id=USER)


@pytest.mark.asyncio
async def test_real_factory_and_collector_prove_catalog_reachability_only(transport):
    node = NodeFactory.create_node("fixture", TYPE, {"credentials": RAW, "config": {"operation": "check_connection", "label": "Saved canvas"}}, user_id=USER)
    result = await node.execute({})
    assert result["protected_reachability_verified"] and not result["principal_identity_proven"] and not result["organization_ownership_proven"]
    evidence = await collect_evidence(node_type=TYPE, user_id=USER, credential_data=deepcopy(RAW))
    assert evidence.reachable is True and AmplienceNode.connection_evidence.proves == "reachability" and not evidence.account_label
    assert "PRIVATE" not in json.dumps(asdict(evidence))


OPERATIONS = [
    ("check_connection", {}), ("list_hubs", {}), ("get_hub", {"hub_id": HUB}),
    ("list_repositories", {"hub_id": HUB}), ("get_repository", {"hub_id": HUB, "repository_id": REPO}),
    ("list_content_types", {"hub_id": HUB}), ("get_content_type", {"hub_id": HUB, "content_type_id": CONTENT_TYPE}),
    ("list_content_items", {"hub_id": HUB, "repository_id": REPO}),
    ("get_content_item", {"hub_id": HUB, "repository_id": REPO, "content_item_id": ITEM}),
    ("list_folders", {"hub_id": HUB, "repository_id": REPO}),
    ("get_folder", {"hub_id": HUB, "repository_id": REPO, "folder_id": FOLDER}),
    ("list_subfolders", {"hub_id": HUB, "repository_id": REPO, "folder_id": FOLDER}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args", OPERATIONS)
async def test_every_native_operation_uses_closed_get_and_private_projection(transport, operation, args):
    result = await run(operation, **args)
    assert result["status"] == "success" and result["mutation_attempted"] is False
    serialized = json.dumps(result)
    assert "PRIVATE" not in serialized and "Opt-in" not in serialized and RAW["token"] not in serialized
    assert all(c.method == "GET" for c in transport[0])


@pytest.mark.asyncio
async def test_names_require_opt_in_and_type_settings_never_hydrate(transport):
    assert (await run("get_content_item", hub_id=HUB, repository_id=REPO, content_item_id=ITEM, include_names=True))["data"]["label"] == "Opt-in item"
    result = await run("get_content_type", hub_id=HUB, content_type_id=CONTENT_TYPE, include_names=True)
    assert set(result["data"]) == {"id", "resource_type", "status"}
    assert "PRIVATE" not in json.dumps(result)


@pytest.mark.asyncio
async def test_actual_picker_parent_and_family_refuse_before_http(transport):
    calls, _ = transport
    for context in ({}, {"hub_id": "other-hub"}, {"hub_id": HUB}):
        with pytest.raises(ValueError): await AmplienceNode.load_field_options("content_item_id", RAW, context)
    with pytest.raises(ValueError): await AmplienceNode.load_field_options("repository_id", {**RAW, "credential_type": "other_family"}, {"hub_id": HUB})
    assert not calls
    result = await run("get_hub", hub_id="other-hub")
    assert result["status"] == "error" and result["executed"] is False and not calls
    options = await AmplienceNode.load_field_options("content_item_id", RAW, {"hub_id": HUB, "repository_id": REPO})
    assert options["options"] == [{"value": ITEM, "label": ITEM, "metadata": {"hub_id": HUB, "repository_id": REPO}}]


@pytest.mark.asyncio
async def test_exact_hal_paging_never_follows_capabilities_or_guesses_basic(transport):
    calls, replies = transport
    replies["/content-repositories/" + REPO + "/content-items"] = (200, hal("content-items", [ITEM_ROW], 1, 20, 3, 41))
    result = await run("list_content_items", hub_id=HUB, repository_id=REPO, page=1)
    assert result["next_page"] == 2 and result["has_more"] is True and result["snapshot_stable"] is False
    request = next(c for c in calls if c.url.path.endswith("/content-items"))
    assert dict(request.url.params) == {"page": "1", "size": "20", "status": "ACTIVE"}
    replies["/content-repositories/" + REPO + "/content-items"] = (200, {"_embedded": {"wrong-key": [ITEM_ROW]}, "page": {"number": 1, "size": 20, "totalPages": 3, "totalElements": 41}})
    assert (await run("list_content_items", hub_id=HUB, repository_id=REPO, page=1))["status"] == "error"
    replies["/folders/" + FOLDER + "/folders"] = (200, hal("folders", [{"id": "child-fixture"}], 0, 20, 2, 21))
    result = await run("list_subfolders", hub_id=HUB, repository_id=REPO, folder_id=FOLDER)
    assert result["has_more"] is True and result["continuation_supported"] is False
    assert not next(c for c in calls if c.url.path.endswith("/" + FOLDER + "/folders")).url.params


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, hal("hubs", [], total_elements=0), hal("hubs", [{"id": "foreign-hub"}]), {"errors": [{"message": RAW["token"]}]}])
async def test_empty_foreign_or_error_envelope_does_not_prove_account(transport, payload):
    transport[1]["/hubs"] = (200, payload)
    evidence = await collect_evidence(node_type=TYPE, user_id=USER, credential_data=deepcopy(RAW))
    assert evidence.reachable is not True and not evidence.account_label and RAW["token"] not in json.dumps(asdict(evidence))


@pytest.mark.asyncio
async def test_actual_repository_and_item_parent_races_discard_metadata(transport):
    calls, replies = transport
    replies["/hubs/" + HUB + "/content-repositories"] = (200, hal("content-repositories", [{"id": "foreign-repository"}], size=100))
    result = await run("get_content_item", hub_id=HUB, repository_id=REPO, content_item_id=ITEM)
    assert result["status"] == "error" and not any(c.url.path.endswith("/content-items/" + ITEM) for c in calls)
    replies.clear(); calls.clear()
    def moved(request):
        count = sum(c.url.path.endswith("/content-items/" + ITEM) for c in calls)
        return 200, {**ITEM_ROW, "contentRepositoryId": REPO if count == 1 else "foreign-repository"}
    replies["/content-items/" + ITEM] = moved
    result = await run("get_content_item", hub_id=HUB, repository_id=REPO, content_item_id=ITEM)
    assert result["status"] == "error" and "data" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("createdDate", "PRIVATE-NOT-A-TIMESTAMP"), ("version", True), ("publishingStatus", "UNKNOWN"), ("contentRepositoryId", "foreign-repository")])
async def test_published_item_field_contracts_have_no_raw_fallback(transport, field, value):
    transport[1]["/content-items/" + ITEM] = (200, {**ITEM_ROW, field: value})
    result = await run("get_content_item", hub_id=HUB, repository_id=REPO, content_item_id=ITEM)
    assert result["status"] == "error" and "data" not in result and "PRIVATE" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [(401, {"errors": [{"invalidValue": RAW["token"]}]}), (429, b"PRIVATE"), (204, b""), httpx.ReadTimeout("synthetic")])
async def test_failure_preserves_status_privacy_and_no_retry(transport, reply):
    calls, replies = transport
    replies["/hubs"] = reply
    result = await run("check_connection")
    assert result["status"] == "error" and len(calls) == 1 and "data" not in result
    assert "PRIVATE" not in json.dumps(result) and RAW["token"] not in json.dumps(result)


def test_raw_family_and_expiry_are_validated_without_default_grant():
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    assert _credential({**RAW, "credential_type": "amplience_access_token", "expires_at": expiry}).expires_at == expiry
    for raw in ({**RAW, "credential_type": "other_family"}, {**RAW, "expires_at": expiry}, {**RAW, "credential_type": "amplience_access_token"}, {**RAW, "credential_type": "amplience_access_token", "expires_at": "2000-01-01T00:00:00Z"}, {**RAW, "refresh_token": "synthetic-refresh"}):
        with pytest.raises(ValueError) as error: _credential(raw)
        assert RAW["token"] not in str(error.value)
    assert _credential({**RAW, "token_version": 1, "updated_at": "2026-01-01T00:00:00Z"}).token == RAW["token"]


@pytest.mark.asyncio
async def test_provider_may_return_a_smaller_current_page_size(transport):
    # Published hub examples report size=20; membership asks for up to 100.
    # A smaller current page still proves membership using the returned IDs.
    transport[1]["/hubs"] = (200, hal("hubs", [HUB_ROW], size=20))
    assert (await run("check_connection"))["status"] == "success"
    assert (await run("list_hubs", size=10))["status"] == "error"


def test_supplied_token_permissions_cover_parent_catalogs_without_requesting_scopes():
    registry = AmplienceNode.scope_registry
    assert set(registry) == {operation for operation, _ in OPERATIONS}
    assert not registry.declared_scopes()
    for operation in ("list_content_items", "get_content_item", "list_folders", "get_folder", "list_subfolders"):
        requirement = registry.require(operation)
        assert "ACL: Hub - READ" in requirement.scopes
        assert "FN: CONTENT:FUNCTIONAL:REPOSITORY:READ" in requirement.scopes
        assert requirement.tier == "supplied"
