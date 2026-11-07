"""NationBuilder native routes, config validation and bounded response regressions.

Exercise staging factory/run/connect paths with a mocked provider transport and
the real public-target guard. No live API proof is implied.
"""
from copy import deepcopy
import asyncio
import json
import logging
import socket
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from nodes import nationbuilder_node as native
from nodes.core.connection_evidence import collect_evidence
from nodes.core.credential_connect import validate_for_connect
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from nodes.core.run_op import run_node_operation

NODE, FAMILY = native.NODE_TYPE, "nationbuilder_v2_token"
USER = str(UUID(int=1))
CREDS = {"credential_type": FAMILY, "nation_slug": "fixture-nation", "access_token": "synthetic_header.synthetic_payload.synthetic_signature"}
OPS = {"get_me", "list_signups", "get_signup", "create_signup", "update_signup", "list_tags", "get_tag", "create_tag", "update_tag", "delete_tag", "list_lists", "get_list", "create_list", "update_list", "delete_list", "list_list_signups", "list_signup_taggings", "tag_signup", "untag_signup", "add_list_signups", "remove_list_signups", "get_async_process"}
RECORDS = {
    "signups": {"id": "1", "type": "signups", "attributes": {"first_name": "Fixture", "last_name": "Person", "email": "private@example.invalid", "note": "private-note", "support_level": 1, "donations_amount_in_cents": 500, "custom_values": {"private": "hidden"}}, "relationships": {"private": {}}, "links": {"self": "https://private.invalid"}},
    "signup_tags": {"id": "2", "type": "signup_tags", "attributes": {"name": "Fixture tag", "taggings_count": 0, "imported": False}},
    "lists": {"id": "3", "type": "lists", "attributes": {"name": "Fixture list", "signups_count": 0, "description": "private description", "is_sharing_writable": True}},
    "signup_taggings": {"id": "4", "type": "signup_taggings", "attributes": {"signup_id": "1", "tag_id": "2"}},
}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
async def provider(monkeypatch):
    from utils import ssrf
    state = SimpleNamespace(requests=[], status=None, override=None, raw=None, media=None, timeout=False, after_response=None, empty=False, private_dns=False)
    original_client = ssrf.guarded_async_client
    async def public_dns(host, port, **kwargs):
        assert host == "fixture-nation.nationbuilder.com"
        assert kwargs == {"type": socket.SOCK_STREAM}
        address = "127.0.0.1" if state.private_dns else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port))]
    # Mock DNS answers beneath the real resolver so its public-IP check still runs.
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", public_dns)
    async def respond(request):
        assert request.url.scheme == "https" and request.url.host == "fixture-nation.nationbuilder.com"
        assert request.headers["authorization"] == "Bearer " + CREDS["access_token"]
        assert CREDS["access_token"] not in str(request.url) + request.content.decode()
        assert request.headers["accept"] == native.MEDIA
        state.requests.append(request)
        if state.timeout:
            raise httpx.ReadTimeout("private " + CREDS["access_token"], request=request)
        path = request.url.path.removeprefix("/api/v2/")
        parts = path.split("/")
        status = 200
        if parts[0] == "async_processes":
            raw = {"id": parts[1], "status": "completed", "message": "private process message"}
        elif len(parts) == 3 and parts[2] in {"add_signups", "remove_signups"}:
            assert request.method == "PATCH" and request.headers["content-type"] == native.MEDIA
            assert json.loads(request.content) == {"data": {"id": "3", "type": "lists", "signup_ids": ["1"]}}
            status, raw = 202, {"token": "process42"}
        elif request.method == "DELETE":
            raw = {"meta": {}}
        else:
            resource = "signups" if len(parts) == 3 and parts[2] == "signups" else parts[0]
            row = deepcopy(RECORDS[resource])
            if request.method in {"POST", "PATCH"}:
                assert request.headers["content-type"] == native.MEDIA
                body = json.loads(request.content)
                assert set(body) == {"data"} and body["data"]["type"] == resource
                assert set(body["data"]) == ({"type", "attributes"} if request.method == "POST" else {"id", "type", "attributes"})
                row["attributes"].update(body["data"]["attributes"])
                if request.method == "PATCH": assert body["data"]["id"] == row["id"]
                status, raw = (201 if request.method == "POST" else 200), {"data": row}
            elif len(parts) == 1 or len(parts) == 3:
                raw = {"data": [] if state.empty else [row], "links": {"next": "https://foreign.invalid/never-follow?secret=value"}}
            else:
                raw = {"data": row}
        if state.after_response: state.after_response()
        if state.override is not None: raw = deepcopy(state.override)
        content = state.raw if state.raw is not None else json.dumps(raw).encode()
        media = state.media or ("application/json" if path == "lists/3/signups" else native.MEDIA)
        return httpx.Response(state.status or status, content=content, headers={"content-type": media}, request=request)
    def guarded(**kwargs):
        assert kwargs == {"follow_redirects": False, "trust_env": False, "timeout": 25.0}
        return original_client(**kwargs, transport=httpx.MockTransport(respond))
    monkeypatch.setattr(native, "guarded_async_client", guarded)
    return state


async def run(op, args=None, **kwargs):
    return await run_node_operation(node_type=NODE, operation=op, arguments=args or {}, user_id=USER, credential_data=kwargs.pop("credential_data", CREDS), **kwargs)


CASES = [("get_me", {}, "GET", "/signups/me"), ("list_signups", {}, "GET", "/signups"), ("get_signup", {"signup_id": "1"}, "GET", "/signups/1"), ("create_signup", {"first_name": "Ordinary", "email": "ordinary@example.invalid"}, "POST", "/signups"), ("update_signup", {"signup_id": "1", "last_name": "Updated"}, "PATCH", "/signups/1"), ("list_tags", {}, "GET", "/signup_tags"), ("get_tag", {"tag_id": "2"}, "GET", "/signup_tags/2"), ("create_tag", {"name": "Owned fixture"}, "POST", "/signup_tags"), ("update_tag", {"tag_id": "2", "name": "Owned updated"}, "PATCH", "/signup_tags/2"), ("delete_tag", {"tag_id": "2"}, "DELETE", "/signup_tags/2"), ("list_lists", {}, "GET", "/lists"), ("get_list", {"list_id": "3"}, "GET", "/lists/3"), ("create_list", {"name": "Owned list"}, "POST", "/lists"), ("update_list", {"list_id": "3", "name": "Updated list"}, "PATCH", "/lists/3"), ("delete_list", {"list_id": "3"}, "DELETE", "/lists/3"), ("list_list_signups", {"list_id": "3"}, "GET", "/lists/3/signups"), ("list_signup_taggings", {"signup_id": "1"}, "GET", "/signup_taggings"), ("tag_signup", {"signup_id": "1", "tag_id": "2"}, "POST", "/signup_taggings"), ("untag_signup", {"signup_id": "1", "tag_id": "2", "tagging_id": "4"}, "DELETE", "/signup_taggings/4"), ("add_list_signups", {"list_id": "3", "signup_ids": ["1"]}, "PATCH", "/lists/3/add_signups"), ("remove_list_signups", {"list_id": "3", "signup_ids": ["1"]}, "PATCH", "/lists/3/remove_signups"), ("get_async_process", {"process_id": "process42"}, "GET", "/async_processes/process42")]


@pytest.mark.asyncio
@pytest.mark.parametrize("op,args,method,path", CASES)
async def test_actual_factory_and_all_native_routes(provider, op, args, method, path):
    from coder.workflow.operation_catalog import get_operation_config_class, node_accepted_credential_types
    assert NODE_REGISTRY[NODE] is native.NationBuilderNode
    assert get_operation_config_class(NODE, op) is not None and node_accepted_credential_types(NODE) == {FAMILY}
    node = NodeFactory.create_node(node_id="fixture", node_type=NODE, node_data={"config": {"operation": op, **args}, "credentials": CREDS}, user_id=USER)
    assert isinstance(node, native.NationBuilderNode)
    output = await node.run({})
    assert output["status"] == "success" and provider.requests[-1].method == method
    assert provider.requests[-1].url.path == "/api/v2" + path
    serialized = json.dumps(output)
    for private in (CREDS["access_token"], "private@example.invalid", "private-note", "donations_amount", "support_level", "custom_values", "private process message", "private.invalid", "is_sharing_writable"):
        assert private not in serialized
    if op in {"add_list_signups", "remove_list_signups"}:
        assert output["data"]["accepted"] is True and output["data"]["completed"] is False and output["data"]["process_id"] == "process42"
    if method in {"POST", "PATCH", "DELETE"}:
        assert output["data"]["readback_verified"] is False


@pytest.mark.asyncio
async def test_exact_page_contract_empty_terminal_and_no_link_follow(provider):
    result = await run("list_signups", {"page_number": 2, "page_size": 10, "last_name_prefix": "Fi"})
    assert dict(provider.requests[-1].url.params) == {"fields[signups]": ",".join(native.FIELDS["signups"]), "page[number]": "2", "page[size]": "10", "filter[last_name][prefix]": "Fi"}
    assert result["data"]["next_page_number"] == 3 and result["data"]["pagination_complete"] is False
    assert len(provider.requests) == 1
    provider.empty = True
    result = await run("list_signups", {"page_number": 3})
    assert result["data"]["items"] == [] and result["data"]["next_page_number"] is None and result["data"]["pagination_complete"] is True


@pytest.mark.asyncio
async def test_tagging_parent_mismatch_stops_delete(provider):
    provider.override = {"data": {**deepcopy(RECORDS["signup_taggings"]), "attributes": {"signup_id": "99", "tag_id": "2"}}}
    with pytest.raises(ValueError, match="belong"):
        await run("untag_signup", {"signup_id": "1", "tag_id": "2", "tagging_id": "4"})
    assert [r.method for r in provider.requests] == ["GET"]


@pytest.mark.asyncio
@pytest.mark.parametrize("op,args", [("delete_signup", {"signup_id": "1"}), ("send_message", {}), ("create_signup", {}), ("get_signup", {"signup_id": "../other"}), ("list_tags", {"page_size": 101}), ("add_list_signups", {"list_id": "3", "signup_ids": ["1", "1"]})])
async def test_invalid_inputs_and_undeclared_effects_stop_before_http(provider, op, args):
    with pytest.raises(ValueError): await run(op, args)
    assert provider.requests == []


@pytest.mark.parametrize("change", [{"nation_slug": "https://evil.invalid"}, {"nation_slug": "www"}, {"nation_slug": "fixture.nation"}, {"nation_slug": "Acme"}, {"access_token": "v1opaque"}, {"access_token": "Bearer a.b.c"}, {"access_token": "a.b.c\n"}, {"expires_at": "2026-10-06T12:00:00"}])
def test_credential_shape_never_exposes_input(change):
    with pytest.raises(ValueError) as error: native._credential({**CREDS, **change})
    assert CREDS["access_token"] not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 422, 429, 500])
async def test_status_privacy_and_no_automatic_retry(provider, status, caplog):
    provider.status = status
    with caplog.at_level(logging.DEBUG), pytest.raises(ValueError) as error: await run("get_me")
    assert len(provider.requests) == 1 and CREDS["access_token"] not in str(error.value) + caplog.text


@pytest.mark.asyncio
async def test_media_errors_duplicates_bounds_and_expiry(provider):
    provider.media = "text/html"
    with pytest.raises(ValueError): await run("get_me")
    provider.media, provider.raw = None, b'{"data":{},"data":{}}'
    with pytest.raises(ValueError): await run("get_me")
    provider.raw = b" " * (native.MAX_BYTES + 1)
    with pytest.raises(ValueError): await run("get_me")
    provider.raw, provider.override = None, {"code": "server_error", "message": CREDS["access_token"]}
    evidence = await collect_evidence(node_type=NODE, credential_data=CREDS, user_id=USER)
    assert evidence.reachable is None
    provider.requests.clear()
    with pytest.raises(ValueError): await run("get_me", credential_data={**CREDS, "expires_at": "2000-01-01T00:00:00Z"})
    assert provider.requests == []


@pytest.mark.asyncio
async def test_real_transport_rejects_private_dns_before_mock_provider(provider):
    provider.private_dns = True
    with pytest.raises(ValueError, match="public HTTPS"): await run("get_me")
    assert provider.requests == []


@pytest.mark.asyncio
async def test_actual_connect_collector_and_publication_free_pickers(provider):
    verdict = await validate_for_connect(credential_type=FAMILY, credential_data=CREDS, user_id=USER)
    assert verdict.ok and verdict.evidence.reachable is True and verdict.evidence.samples[0].label == "Fixture tag"
    options = await native.NationBuilderNode.load_field_options("tag_id", CREDS, page_token="2", search="Fi")
    assert options == {"options": [{"value": "2", "label": "Fixture tag"}], "next_page_token": "3"}
    assert provider.requests[-1].url.params["filter[name][prefix]"] == "Fi"
    provider.empty = True
    evidence = await collect_evidence(node_type=NODE, credential_data=CREDS, user_id=USER)
    assert evidence.reachable is True and evidence.samples == [] and evidence.account_label == "Fixture Person"
    assert provider.requests[-1].url.path.endswith("/signups/me")
    provider.status = 401
    verdict = await validate_for_connect(credential_type=FAMILY, credential_data=CREDS, user_id=USER)
    assert not verdict.ok and verdict.evidence.reachable is False


@pytest.mark.asyncio
async def test_resource_identity_and_delete_ack_not_guessed(provider):
    provider.override = {"data": {**deepcopy(RECORDS["signups"]), "id": "different"}}
    with pytest.raises(ValueError, match="different resource"): await run("get_signup", {"signup_id": "1"})
    provider.override = None
    original = provider.after_response
    def replace_delete():
        if provider.requests[-1].method == "DELETE": provider.override = {"meta": {"unexpected": True}}
    provider.after_response = replace_delete
    with pytest.raises(ValueError, match="deletion acknowledgment"): await run("delete_tag", {"tag_id": "2"})
    provider.after_response = original
