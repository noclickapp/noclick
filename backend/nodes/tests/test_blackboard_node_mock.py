"""Offline wire tests; fixture values are synthetic, routes follow Learn 4001.4.0."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import blackboard_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-blackboard-token"
CREDENTIAL = {"credential_type": "blackboard_access_token", "site_url": "https://school.blackboard.com", "access_token": TOKEN}
CASES = json.loads((Path(__file__).parent / "fixtures/blackboard/wire_cases.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="blackboard-fixture", node_type="automation-blackboard",
        node_data={"config": config, "credentials": CREDENTIAL if credential is None else credential})


def transport(monkeypatch, handler):
    requests = []
    def respond(request):
        requests.append(request)
        return handler(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        assert "trusted_exact_urls" not in kwargs
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["operation"])
async def test_all_operations_through_real_factory(monkeypatch, case):
    payload = {"results": [{"id": "_123_1", "name": "Mathematics"}], "paging": {"nextPage": "/learn/api/public/v3/courses?offset=100&limit=100"}} if case["operation"].startswith("list_") else {"id": "_123_1", "courseId": "_123_1", "userId": "_456_1"}
    calls = transport(monkeypatch, lambda req: httpx.Response(case["status"], **({"json": payload} if case["status"] != 204 else {})))
    result = await node({"operation": case["operation"], **case["config"]}).execute({})
    assert result["status"] == "success" and result["http_status"] == case["status"]
    assert len(calls) == 1
    req = calls[0]
    assert req.method == case["method"] and req.url.path == case["path"]
    assert req.url.host == "school.blackboard.com" and req.url.scheme == "https"
    assert req.headers["Authorization"] == "Bearer " + TOKEN
    assert dict(req.url.params) == case["params"]
    assert (json.loads(req.content) if req.content else None) == case["body"]
    if case["status"] == 204:
        assert result["deletion_acknowledged"] is True
        assert "data" not in result
    else:
        assert result["data"] == payload


@pytest.mark.asyncio
async def test_empty_course_page_is_valid_connection_evidence(monkeypatch):
    calls = transport(monkeypatch, lambda req: httpx.Response(200, json={"results": []}))
    spec = native.BlackboardNode.connection_evidence
    result = await node({"operation": spec.operation}).execute({})
    assert result["data"]["results"] == [] and result["status"] == "success"
    assert len(calls) == 1 and calls[0].url.path == "/learn/api/public/v3/courses"
    assert spec.proves == "account"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404, 429, 500])
async def test_errors_do_not_follow_redirects_or_leak_token(monkeypatch, status):
    calls = transport(monkeypatch, lambda req: httpx.Response(status, headers={"Location": "https://other.example/"}, json={"message": "Rejected " + TOKEN}))
    with pytest.raises(ValueError) as exc:
        await node({"operation": "list_courses"}).execute({})
    assert str(status) in str(exc.value) and TOKEN not in str(exc.value)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_redacts_nested_response_secrets(monkeypatch):
    transport(monkeypatch, lambda req: httpx.Response(200, json={"id": "_123_1", "password": "never-return", "nested": {"access_token": TOKEN, "text": TOKEN}}))
    result = await node({"operation": "get_user", "user_id": "_123_1"}).execute({})
    assert TOKEN not in str(result) and "never-return" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [[], {}, {"results": {}}, {"results": ["bad-row"]}])
async def test_rejects_invalid_list_envelopes(monkeypatch, payload):
    transport(monkeypatch, lambda req: httpx.Response(200, json=payload))
    with pytest.raises(ValueError, match="invalid JSON"):
        await node({"operation": "list_courses"}).execute({})


@pytest.mark.asyncio
async def test_write_timeout_is_unknown_and_not_retried(monkeypatch):
    def timeout(req):
        raise httpx.ReadTimeout("request timed out", request=req)
    calls = transport(monkeypatch, timeout)
    with pytest.raises(ValueError, match="write outcome is unknown"):
        await node({"operation": "create_course", "course_code": "math101", "name": "Math"}).execute({})
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_guard_blocks_private_dns_before_sending_credentials(monkeypatch):
    import asyncio
    import socket
    from utils.ssrf import SSRFError

    monkeypatch.setenv("OUTBOUND_ALLOW_PRIVATE_IPS", "0")
    monkeypatch.delenv("HTTP_NODE_ALLOW_PRIVATE_IPS", raising=False)
    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    with pytest.raises(SSRFError, match="non-public"):
        await node({"operation": "list_courses"}).execute({})


@pytest.mark.parametrize("url", ["http://school.blackboard.com", "https://127.0.0.1", "https://[::1]", "https://school.blackboard.com/path", "https://school.blackboard.com?x=y", "https://user:secret@school.blackboard.com", "https://school.blackboard.com:8000", "https://school.blackboard.com/#fragment", "https://school.blackboard.com\n"])
def test_credential_rejects_invalid_site_origins(url):
    with pytest.raises(ValidationError):
        native.BlackboardAccessTokenCredential.model_validate({**CREDENTIAL, "site_url": url})


@pytest.mark.parametrize("token", ["Bearer some-token", "https://example.com", "token\nheader", ""])
def test_credential_rejects_bad_tokens(token):
    with pytest.raises(ValidationError):
        native.BlackboardAccessTokenCredential.model_validate({**CREDENTIAL, "access_token": token})


def test_manual_credential_default_and_custom_institution_domain():
    credential = native.BlackboardAccessTokenCredential(site_url="https://LEARN.university.edu/", access_token=TOKEN)
    assert credential.credential_type == "blackboard_access_token"
    assert credential.site_url == "https://learn.university.edu"
    assert native.BlackboardNode.get_config_schema()["$defs"]["BlackboardAccessTokenCredential"]["title"] == "Blackboard Access Token"


@pytest.mark.parametrize("config", [
    {"operation": "get_course", "course_id": "../users"},
    {"operation": "get_user", "user_id": "%2Fusers"},
    {"operation": "update_course", "course_id": "_123_1"},
    {"operation": "update_membership", "course_id": "_123_1", "user_id": "_456_1"},
    {"operation": "update_announcement", "course_id": "_123_1", "announcement_id": "_789_1"},
    {"operation": "list_courses", "limit": 0},
    {"operation": "list_courses", "offset": -1},
    {"operation": "create_membership", "course_id": "_123_1", "user_id": "_456_1", "course_role": "Administrator"},
])
def test_config_rejects_invalid_inputs(config):
    with pytest.raises(ValueError):
        node(config)


POLL_CONTRACT = json.loads((Path(__file__).parent / "fixtures/blackboard/poll_contract.json").read_text())
POLL_ROWS = {
    "on_new_user": {"id": "_123_1", "userName": "jsmith", "name": {"given": "John", "family": "Smith"}},
    "on_new_or_updated_course": {"id": "_123_1", "courseId": "math101", "name": "Mathematics", "modified": "2026-11-01T00:00:00Z"},
    "on_new_membership": {"id": "_789_1", "userId": "_456_1", "courseId": "_123_1", "courseRoleId": "Student"},
    "on_new_or_updated_announcement": {"id": "_123_1", "title": "Welcome", "creatorUserId": "_456_1", "body": POLL_CONTRACT["schemas"]["on_new_or_updated_announcement"]["properties"]["body"]["example"], "modified": "2026-11-01T00:00:00Z"},
}


def poll_node(operation, state, course_id="_123_1"):
    config = {"operation": operation}
    if operation in {"on_new_membership", "on_new_or_updated_announcement"}:
        config["course_id"] = course_id
    instance = node(config)

    async def update(mutator, **kwargs):
        new_state, result = mutator(dict(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result

    instance._update_node_state = update
    return instance


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", POLL_ROWS)
async def test_poll_baselines_emits_new_items_once_and_shapes_agent_turn(monkeypatch, operation):
    # Fields follow the pinned Learn 4001.4.0 response schemas; IDs are synthetic.
    state, rows = {}, [dict(POLL_ROWS[operation])]
    calls = transport(monkeypatch, lambda req: httpx.Response(200, json={"results": rows}))
    instance = poll_node(operation, state)
    assert (await instance.execute({}))["count"] == 0
    assert instance.trigger_produced_no_event({})
    new = {**rows[0], "id": "_999_1", "userId": "_999_1"} if operation == "on_new_membership" else {**rows[0], "id": "_999_1"}
    rows.append(new)
    output = await instance.execute({})
    assert output["items"] == [new] and output["count"] == 1
    assert instance.trigger_emitted_event(output)
    event = instance.resolve_agent_event(output)
    assert "Blackboard" in event["text"] and "_999_1" in event["text"]
    if "course_id" in output:
        assert "courseId=_123_1" in event["text"]
    assert (await instance.execute({}))["count"] == 0
    action, sort, _, _ = native.POLL_OPERATIONS[operation]
    assert calls[0].url.path == native.OPERATIONS[action][1].format(course_id="_123_1")
    assert dict(calls[0].url.params) == {"limit": "100", "offset": "0", "sort": sort + "(desc)"}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["on_new_or_updated_course", "on_new_or_updated_announcement"])
async def test_poll_detects_updated_record_once(monkeypatch, operation):
    state, row = {}, dict(POLL_ROWS[operation])
    transport(monkeypatch, lambda req: httpx.Response(200, json={"results": [row]}))
    instance = poll_node(operation, state)
    await instance.execute({})
    row["modified"] = "2026-11-02T00:00:00Z"
    assert (await instance.execute({}))["items"] == [row]
    assert (await instance.execute({}))["count"] == 0


@pytest.mark.asyncio
async def test_poll_paginates_on_bound_origin_and_does_not_follow_next_url(monkeypatch):
    def respond(req):
        if req.url.params["offset"] == "0":
            return httpx.Response(200, json={"results": [POLL_ROWS["on_new_user"]], "paging": {"nextPage": "https://untrusted.example/steal"}})
        return httpx.Response(200, json={"results": [{"id": "_999_1", "userName": "second"}]})
    calls = transport(monkeypatch, respond)
    output = await poll_node("on_new_user", {"seen_ids": []}).execute({})
    assert output["count"] == 2
    assert [r.url.params["offset"] for r in calls] == ["0", "100"]
    assert all(r.url.host == "school.blackboard.com" for r in calls)


@pytest.mark.asyncio
async def test_poll_repoint_baselines_new_course(monkeypatch):
    state = {}
    transport(monkeypatch, lambda req: httpx.Response(200, json={"results": [POLL_ROWS["on_new_membership"]]}))
    await poll_node("on_new_membership", state).execute({})
    output = await poll_node("on_new_membership", state, course_id="_999_1").execute({})
    assert output["count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [[], {}, {"results": {}}, {"results": ["bad"]}])
async def test_poll_rejects_invalid_list_without_advancing_state(monkeypatch, payload):
    state = {}
    transport(monkeypatch, lambda req: httpx.Response(200, json=payload))
    with pytest.raises(ValueError, match="invalid list"):
        await poll_node("on_new_user", state).execute({})
    assert state == {}


@pytest.mark.asyncio
async def test_poll_fails_at_page_cap_without_advancing_state(monkeypatch):
    state = {}
    calls = transport(monkeypatch, lambda req: httpx.Response(200, json={"results": [POLL_ROWS["on_new_user"]], "paging": {"nextPage": "?offset=100"}}))
    with pytest.raises(ValueError, match="5,000"):
        await poll_node("on_new_user", state).execute({})
    assert len(calls) == 50 and state == {}


def test_poll_operations_are_trigger_operations():
    schema = native.BlackboardNode.get_config_schema()
    for name in ("OnNewUser", "OnNewOrUpdatedCourse", "OnNewMembership", "OnNewOrUpdatedAnnouncement"):
        assert schema["$defs"][name]["properties"]["operation"]["x-is-trigger"] is True
    with pytest.raises(ValidationError):
        native.OnNewMembership(course_id="../bad")


@pytest.mark.parametrize("operation", POLL_ROWS)
def test_poll_rows_match_the_pinned_provider_response_schema(operation):
    import jsonschema
    jsonschema.validate(POLL_ROWS[operation], POLL_CONTRACT["schemas"][operation])
