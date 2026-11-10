"""Wire-level and poll regressions; resource values come from official examples."""
import copy
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import easybroker_archive_node as native
from nodes.core.registry import NodeFactory
from nodes.core.poll_trigger import poll_scope

DOC = json.loads(
    (Path(__file__).parent / "fixtures/easybroker-archive/documented.json").read_text()
)
KEY = "fixture-easybroker-key-42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(
        node_id="easybroker-test",
        node_type=native.NODE_TYPE,
        node_data={
            "config": config,
            "credentials": {"credential_type": native.FAMILY, "api_key": KEY},
        },
    )


def page(rows, number=1, next_page=None):
    return {
        "content": rows,
        "pagination": {
            "page": number,
            "limit": 20,
            "total": len(rows),
            "next_page": next_page,
        },
    }


def transport(monkeypatch, reply):
    requests = []

    def respond(request):
        requests.append(request)
        return reply(request) if callable(reply) else httpx.Response(200, json=reply)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
async def test_account_connection_and_deep_object_repeated_array_filters(monkeypatch):
    requests = transport(monkeypatch, page([DOC["contact"]]))
    result = await node(
        {
            "operation": "list_contacts",
            "search_statuses": ["Contacted", "New"],
            "search_updated_after": "2020-03-01T23:26:53.402Z",
        }
    ).execute({})
    assert result["items"][0]["id"] == 123
    req = requests[0]
    assert req.method == "GET" and req.url.host == "api.easybroker.com"
    assert req.headers["X-Authorization"] == KEY
    assert req.url.params.get_list("search[statuses][]") == ["Contacted", "New"]
    assert req.url.params["search[updated_after]"] == "2020-03-01T23:26:53.402000Z"
    assert native.EasyBrokerNode.connection_evidence.operation == "list_contacts"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation", [name for name in native.OPERATIONS if name.startswith("list_")]
)
async def test_lists_and_empty_accounts(monkeypatch, operation):
    requests = transport(monkeypatch, page([]))
    result = await node({"operation": operation}).execute({})
    assert (
        result["items"] == []
        and result["next_page"] is None
        and result["has_more"] is False
    )
    assert requests[0].url.path == "/v1" + native.OPERATIONS[operation][1]


@pytest.mark.asyncio
async def test_contact_patch_preserves_omission_and_explicit_empty_list(monkeypatch):
    requests = transport(monkeypatch, DOC["contact"])
    await node(
        {
            "operation": "update_contact",
            "contact_id": 123,
            "body": {"first_name": "John", "tags": []},
        }
    ).execute({})
    assert requests[0].method == "PATCH"
    assert requests[0].url.path == "/v1/contacts/123"
    assert json.loads(requests[0].content) == {"first_name": "John", "tags": []}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_contact_request_body_and_single_encoded_property_path(monkeypatch):
    requests = transport(monkeypatch, {"status": "successful"})
    await node(
        {
            "operation": "create_contact_request",
            "body": {
                "name": "John Smith",
                "property_id": "EB-XXXX01",
                "source": "mydomain.com",
            },
        }
    ).execute({})
    assert (
        requests[0].method == "POST" and requests[0].url.path == "/v1/contact_requests"
    )
    assert json.loads(requests[0].content)["source"] == "mydomain.com"
    requests = transport(monkeypatch, DOC["property"])
    await node({"operation": "get_property", "property_id": "CUSTOM/ID"}).execute({})
    assert requests[0].url.raw_path == b"/v1/properties/CUSTOM%2FID"


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [301, 401, 422, 429, 500])
async def test_errors_never_retry_or_expose_secret(monkeypatch, code):
    requests = transport(
        monkeypatch, lambda req: httpx.Response(code, json={"error": "Rejected " + KEY})
    )
    with pytest.raises(ValueError) as err:
        await node(
            {
                "operation": "create_contact_request",
                "body": {
                    "name": "John Smith",
                    "property_id": "EB-XXXX01",
                    "source": "mydomain.com",
                },
            }
        ).execute({})
    assert KEY not in str(err.value) and str(code) in str(err.value)
    assert len(requests) == 1


def test_manual_credential_defaults_and_placeholders():
    credential = native.EasyBrokerAPIKeyCredential(api_key=KEY)
    assert credential.credential_type == native.FAMILY
    for value in ["https://example.com/key", "<token>", "bad key"]:
        with pytest.raises(ValidationError):
            native.EasyBrokerAPIKeyCredential(api_key=value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,kind",
    [
        ("on_new_contact_request", "contact_request"),
        ("on_new_or_updated_contact", "contact"),
        ("on_new_or_updated_property", "property"),
    ],
)
async def test_documented_poll_baseline_dedup_updates_and_agent_event(
    monkeypatch, operation, kind
):
    record = copy.deepcopy(DOC[kind])
    current = [record]
    transport(monkeypatch, lambda req: httpx.Response(200, json=page(current)))
    n = node({"operation": operation})
    state = {}

    async def update(mutator, **kwargs):
        replacement, result = mutator(copy.deepcopy(state))
        if replacement is not None:
            state.clear()
            state.update(replacement)
        return result

    n._update_node_state = update
    assert (await n.execute({}))["items"] == []
    assert (await n.execute({}))["items"] == []
    new = copy.deepcopy(record)
    if kind == "contact_request":
        new["id"] += 1
    else:
        new["updated_at"] = "2025-03-01T23:26:53.402Z"
    current[:] = [new]
    result = await n.execute({})
    assert result["items"] == [new] and result["new_item_count"] == 1
    assert n.trigger_emitted_event(result)
    assert native.EasyBrokerNode.should_propagate_output(
        result, {"operation": operation}
    )
    event = native.EasyBrokerNode.resolve_agent_event(result)
    assert (
        "EasyBroker" in event["text"]
        and str(new.get("public_id", new.get("id"))) in event["text"]
    )
    assert (await n.execute({}))["items"] == []
    assert n.trigger_produced_no_event({})
    assert (
        native.EasyBrokerNode.resolve_agent_event({"operation": operation, "items": []})
        is None
    )


@pytest.mark.asyncio
async def test_poll_all_pages_retains_filters_and_bad_continuation_never_baselines(
    monkeypatch,
):
    record = DOC["contact_request"]
    second = {**record, "id": 124}

    def reply(req):
        if req.url.params["page"] == "1":
            return httpx.Response(
                200,
                json=page(
                    [record],
                    next_page=native.BASE + "/contact_requests?page=2&limit=50",
                ),
            )
        return httpx.Response(200, json=page([second], 2))

    requests = transport(monkeypatch, reply)
    n = node(
        {
            "operation": "on_new_contact_request",
            "property_id": "EB-XXXX01",
            "since": "2020-03-01T23:26:53.402Z",
        }
    )

    async def unseen(rows, identify):
        assert len({identify(row) for row in rows}) == 2
        return rows

    n._filter_unseen = unseen
    assert (await n.execute({}))["new_item_count"] == 2
    assert len(requests) == 2 and all(
        r.url.params["property_id"] == "EB-XXXX01" for r in requests
    )
    transport(
        monkeypatch,
        page([record], next_page="https://attacker.test/v1/contact_requests?page=2"),
    )
    with pytest.raises(ValueError, match="origin"):
        await n.execute({})
    a = poll_scope(
        native.EasyBrokerNode,
        {"operation": "on_new_contact_request", "property_id": "EB-XXXX01"},
    )
    b = poll_scope(
        native.EasyBrokerNode,
        {"operation": "on_new_contact_request", "property_id": "EB-OTHER"},
    )
    assert a and b and a != b


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,method,path",
    [
        ("create_property", "POST", "/v1/properties"),
        ("update_property", "PATCH", "/v1/properties/EB-XXX123"),
    ],
)
async def test_property_writes_use_documented_body_once(
    monkeypatch, operation, method, path
):
    requests = transport(monkeypatch, DOC["property"])
    config = {"operation": operation, "body": DOC["property_body"]}
    if method == "PATCH":
        config["property_id"] = "EB-XXX123"
    result = await node(config).execute({})
    assert result["data"]["public_id"] == DOC["property"]["public_id"]
    assert (
        len(requests) == 1
        and requests[0].method == method
        and requests[0].url.path == path
    )
    assert json.loads(requests[0].content) == DOC["property_body"]


def test_contact_request_documented_conditional_requirements():
    for body in [
        {"source": "mydomain.com"},
        {"source": "mydomain.com", "property_id": "EB-XXXX01"},
    ]:
        with pytest.raises(ValidationError):
            native.ContactRequestBody.model_validate(body)
    native.ContactRequestBody.model_validate(
        {
            "source": "mydomain.com",
            "name": "John Smith",
            "email": "mail@example.com",
            "message": "I'm interested in this property. Please contact me.",
        }
    )
