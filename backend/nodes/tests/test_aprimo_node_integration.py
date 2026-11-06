"""UNRUN offline native factory/transport/parent/privacy regression source."""
import json

import httpx
import pytest

from nodes.aprimo_node import AprimoNode, OPERATIONS
from nodes.core.registry import NodeFactory

ROOT = "a" * 32
RECORD = "b" * 32
FIELD = "c" * 32
GROUP = "d" * 32
ACTOR = "11111111-1111-4111-8111-111111111111"
CID = "22222222-2222-4222-8222-222222222222"
CREDENTIAL = {"credential_type": "aprimo_bearer", "access_token": "fixture-literal-private-token", "tenant": "fixture-tenant", "classification_id": ROOT}


def root(**extras):
    return {"id": ROOT, "parentId": None, "isRoot": True, "name": "Private classification", "registeredFields": [{"fieldId": FIELD}], "registeredFieldGroups": [{"fieldGroupId": GROUP}], **extras}


def make(operation="get_classification", *, credential=None, saved=False, **arguments):
    data = {"config": {"operation": operation, **arguments}, "credentials": dict(credential or CREDENTIAL)}
    if saved:
        data["credentialIds"] = {"aprimo_bearer": CID}
    return NodeFactory.create_node("fixture", "automation-aprimo", data, user_id=ACTOR)


def transport(monkeypatch, handler):
    import nodes.aprimo_node as module
    seen = []
    def checked(request):
        seen.append(request)
        assert request.url.host == "fixture-tenant.dam.aprimo.com"
        assert request.url.path.startswith("/api/core/")
        assert request.headers["Authorization"].startswith("Bearer ")
        assert request.headers["API-VERSION"] == "1"
        assert request.headers["Accept"] == "application/json"
        assert "select-record" not in request.headers and "select-user" not in request.headers
        return handler(request)
    monkeypatch.setattr(module, "guarded_async_client", lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(checked), **kwargs))
    return seen


def test_actual_factory_native_schema_and_raw_types():
    assert make().config.config.operation == "get_classification"
    config_data = {"config": {"operation": "get_classification"}, "credentials": CREDENTIAL}
    assert AprimoNode.parse_config(config_data=config_data).config.operation == "get_classification"
    assert AprimoNode.validate_config(config_data=config_data)["valid"] is True
    schema = AprimoNode.get_config_schema()
    assert "x-credential-type" not in schema["$defs"]["AprimoBearerCredential"]
    actual = {v["properties"]["operation"]["const"] for v in schema["$defs"].values() if "operation" in v.get("properties", {})}
    assert actual == set(OPERATIONS) and len(actual) == 8
    for args in ({"take": True}, {"skip": "0"}, {"include_names": "false"}, {"record_id": 4}):
        operation = "get_record" if "record_id" in args else "list_records"
        data = {"config": {"operation": operation, **args}, "credentials": CREDENTIAL}
        assert AprimoNode.validate_config(config_data=data)["valid"] is False
        with pytest.raises(ValueError):
            AprimoNode.parse_config(config_data=data)


@pytest.mark.parametrize("credential", [
    {**CREDENTIAL, "access_token": 1}, {**CREDENTIAL, "access_token": "https://example.invalid/token"},
    {**CREDENTIAL, "tenant": "other.dam.aprimo.com"}, {**CREDENTIAL, "tenant": "fixture-tenant/path"},
    {**CREDENTIAL, "tenant": "fixture-tenant:443"}, {**CREDENTIAL, "credential_type": "other_token"},
])
def test_actual_factory_refuses_bad_credentials_without_secret_echo(credential):
    with pytest.raises(ValueError) as error:
        make(credential=credential)
    assert str(credential.get("access_token")) not in str(error.value)


@pytest.mark.asyncio
async def test_classification_projection_names_opt_in(monkeypatch):
    transport(monkeypatch, lambda r: httpx.Response(200, json=root(fields={"items": [{"value": "private"}]}, createdBy={"email": "private"}, _links={"self": {"href": "https://private"}})))
    plain = (await make().run({}))["data"]
    assert plain == {"id": ROOT, "parentId": None, "isRoot": True}
    assert (await make(include_names=True).run({}))["data"]["name"] == "Private classification"


@pytest.mark.asyncio
async def test_foreign_root_and_pending_references_refuse_before_http(monkeypatch):
    seen = transport(monkeypatch, lambda r: pytest.fail("Must not call HTTP"))
    with pytest.raises(ValueError, match="credential-bound"):
        await make(classification_id="e" * 32).run({})
    node = make("get_record", record_id="{{source.output.data.id}}")
    with pytest.raises(ValueError, match="Resolve"):
        await node.run({})
    assert seen == []


@pytest.mark.asyncio
async def test_exact_field_registration_and_post_read_removal(monkeypatch):
    calls = 0
    def handler(request):
        nonlocal calls
        if "/classification/" in request.url.path:
            calls += 1
            return httpx.Response(200, json=root(registeredFields=[] if calls > 1 else [{"fieldId": FIELD}]))
        return httpx.Response(200, json={"id": FIELD, "dataType": "Numeric", "scope": "RecordContentGlobal", "name": "Private Name", "defaultValue": "private", "isReadOnly": False})
    transport(monkeypatch, handler)
    with pytest.raises(ValueError, match="registration changed"):
        await make("get_field_definition", field_id=FIELD).run({})


@pytest.mark.asyncio
async def test_unknown_registration_is_not_empty_or_global_lookup(monkeypatch):
    seen = transport(monkeypatch, lambda r: httpx.Response(200, json=root(registeredFields=None)))
    output = (await make("list_registered_fields").run({}))["data"]
    assert output["registration_unknown"] and output["completion_unknown"] and output["items"] == []
    with pytest.raises(ValueError, match="not currently registered"):
        await make("get_field_definition", field_id=FIELD).run({})
    assert all("/classification/" in request.url.path for request in seen)


@pytest.mark.asyncio
async def test_get_collection_skip_take_is_not_search_page_contract(monkeypatch):
    def handler(request):
        if "/classification/" in request.url.path:
            return httpx.Response(200, json=root())
        assert request.method == "GET" and request.url.params["filter"] == f"DirectClassification.Id = '{ROOT}'"
        assert dict(request.url.params) == {"skip": "3", "take": "1", "filter": f"DirectClassification.Id = '{ROOT}'"}
        return httpx.Response(200, json={"offset": 3, "limit": 1, "totalCount": 8, "items": [{"id": RECORD, "status": "Released", "files": {"uri": "https://private"}, "fields": {"items": [{"value": "private"}]}}]})
    transport(monkeypatch, handler)
    output = (await make("list_records", skip=3, take=1).run({}))["data"]
    assert output["offset"] == 3 and output["limit"] == 1 and "page" not in output
    assert output["completion_unknown"] and output["total_count_accuracy"] == "unspecified"
    assert "total_count_is_approximate" not in output
    assert output["items"] == [{"id": RECORD, "status": "Released"}]


@pytest.mark.asyncio
async def test_parameterized_read_search_no_arbitrary_expression_or_logging(monkeypatch):
    term = "quote' OR private = 'value"
    def handler(request):
        if "/classification/" in request.url.path:
            return httpx.Response(200, json=root())
        body = json.loads(request.content)
        assert request.method == "POST" and request.url.path.endswith("/search/records")
        assert body == {"searchExpression": {"expression": "DirectClassification.Id = @Root AND Status = @Status AND Title CONTAINS @Title", "namedParameters": {"Root": ROOT, "Status": "Released", "Title": term}}, "logRequest": False}
        assert dict(request.url.params) == {"page": "2", "pageSize": "1"}
        return httpx.Response(200, json={"page": 2, "pageSize": 1, "totalCount": 20, "items": [{"id": RECORD, "title": "private"}]})
    transport(monkeypatch, handler)
    result = (await make("search_records", page=2, page_size=1, status="Released", title_contains=term).run({}))["data"]
    assert result["items"] == [{"id": RECORD}] and "offset" not in result


@pytest.mark.asyncio
async def test_global_record_route_requires_exact_current_membership(monkeypatch):
    seen = transport(monkeypatch, lambda r: httpx.Response(200, json=root() if "/classification/" in r.url.path else {"items": []}))
    with pytest.raises(ValueError, match="membership is unproven"):
        await make("get_record", record_id=RECORD).run({})
    assert all(not request.url.path.endswith("/record/" + RECORD) for request in seen)


@pytest.mark.asyncio
async def test_exact_record_readback_rechecks_membership_and_omits_content(monkeypatch):
    memberships = 0
    def handler(request):
        nonlocal memberships
        if "/classification/" in request.url.path:
            return httpx.Response(200, json=root())
        if "/search/records" in request.url.path:
            memberships += 1
            assert json.loads(request.content)["searchExpression"]["namedParameters"] == {"Root": ROOT, "Record": RECORD}
            return httpx.Response(200, json={"items": [{"id": RECORD}]})
        return httpx.Response(200, json={"id": RECORD, "status": "Released", "contentType": "Asset", "title": "Private title", "textContent": "private", "preview": {"uri": "https://private"}})
    transport(monkeypatch, handler)
    output = (await make("get_record", record_id=RECORD).run({}))["data"]
    assert memberships == 2 and output == {"id": RECORD, "status": "Released", "contentType": "Asset"}


@pytest.mark.asyncio
async def test_escaped_token_reflection_refuses_output(monkeypatch):
    credential = {**CREDENTIAL, "access_token": 'fixture-token-with-"quote'}
    transport(monkeypatch, lambda r: httpx.Response(200, json=root(name=credential["access_token"])))
    with pytest.raises(ValueError, match="reflected a credential"):
        await make(credential=credential).run({})


@pytest.mark.parametrize("status", [201, 301, 401, 403, 404, 429, 504])
@pytest.mark.asyncio
async def test_errors_do_not_follow_redirect_retry_or_reflect_private_html(monkeypatch, status):
    seen = transport(monkeypatch, lambda r: httpx.Response(status, text=CREDENTIAL["access_token"], headers={"Location": "https://outsider.invalid"}))
    with pytest.raises(ValueError) as error:
        await make().run({})
    assert len(seen) == 1 and CREDENTIAL["access_token"] not in str(error.value)
