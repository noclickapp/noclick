"""Native factory, connection evidence, operation and credential resolver seams.

Offline transports with synthetic credentials and a documented status response.
"""
import json
import logging
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from nodes import mastodon_node as native
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation
from nodes.core.credential_connect import validate_for_connect

NT = "automation-mastodon"
USER = "11111111-1111-4111-8111-111111111111"
CID = "22222222-2222-4222-8222-222222222222"
ACTOR = "actor_opaque-X"
SID = "status_opaque-Y"
KEY = {"credential_type": native.TYPE, "instance_origin": "https://social.example.test", "access_token": "synthetic-private-user-token"}
ACCOUNT = {"id": ACTOR, "created_at": "2022-03-01T00:00:00.000Z", "statuses_count": 4, "followers_count": 2, "following_count": 3, "last_status_at": None, "username": "synthetic", "acct": "synthetic", "display_name": "", "source": {"note": "omit-source", "email": "omit-email"}, "note": "omit-html", "roles": ["omit-role"], "url": "https://omit.example.test/profile"}
STATUS = {"id": SID, "account": deepcopy(ACCOUNT), "created_at": "2026-10-01T01:02:03.000Z", "edited_at": None, "visibility": "private", "language": None, "replies_count": 1, "reblogs_count": 2, "favourites_count": 3, "reblog": None, "content": "omit-content", "text": "omit-text", "spoiler_text": "omit-spoiler", "media_attachments": ["omit-media"], "poll": {"id": "omit-poll"}, "quote": "omit-quote", "application": "omit-app", "uri": "https://omit.example.test/status"}


def node(operation="verify_credentials", raw=KEY, **args):
    return NodeFactory.create_node(node_id="mastodon-fixture", node_type=NT, node_data={"config": {"operation": operation, **args}, "credentials": deepcopy(raw)}, sio=None, sid=None, user_id=USER)


@pytest.fixture(autouse=True)
def admission(monkeypatch):
    monkeypatch.setattr("utils.credential_approval.admit_node", AsyncMock(return_value=None))


@pytest.fixture
def transport(monkeypatch):
    calls, responses = [], []
    async def receive(request):
        assert request.url.host == "social.example.test" and request.url.scheme == "https"
        assert request.method == "GET" and request.content == b"" and not request.url.username and not request.url.password
        assert request.headers["Authorization"] == "Bearer " + KEY["access_token"]
        assert KEY["access_token"] not in str(request.url)
        calls.append(request)
        value = responses.pop(0)
        if callable(value):
            value = value(request)
        return value if isinstance(value, httpx.Response) else httpx.Response(200, json=value)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(receive)) as instance:
            yield instance
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls, responses


@pytest.mark.parametrize("args", [{"limit": "20"}, {"limit": True}, {"limit": 0}, {"limit": 41}, {"limit": 20.5}, {"limit": "20x"}, {"max_id": 1}, {"since_id": True}, {"min_id": "../foreign"}, {"include_names": "false"}, {"exclude_reblogs": False}, {"operation": "post_status"}, {"operation": "timeline"}, {"operation": "refresh_token"}])
def test_actual_factory_refuses_coercion_and_nonmetadata_scope(transport, args):
    with pytest.raises(ValueError):
        node(args.get("operation", "list_statuses"), account_id=ACTOR, **{key: value for key, value in args.items() if key != "operation"})
    assert not transport[0]


def test_actual_factory_normalizes_empty_optional_cursor_without_sending_it(transport):
    instance = node("list_statuses", account_id=ACTOR, max_id="")
    assert instance.config.config.max_id is None
    assert "max_id" not in native.page_params(instance.config.config)
    assert not transport[0]


@pytest.mark.asyncio
async def test_documented_status_response_preserves_nullable_fields_and_projects_metadata(transport):
    fixture = json.loads((Path(__file__).parent / "fixtures/mastodon/status_response.json").read_text())
    response = fixture["body"]
    actor = response["account"]["id"]
    transport[1].extend([response["account"], [response], response, response["account"]])
    result = await node("get_status", account_id=actor, status_id=response["id"]).execute({})
    assert result["data"] == {
        "actor_id": "1",
        "status": {
            "id": "1",
            "created_at": "2016-03-16T14:44:31.580Z",
            "visibility": "public",
            "replies_count": 7,
            "reblogs_count": 98,
            "favourites_count": 112,
            "language": "en",
        },
        "snapshot_consistent": False,
    }
    assert len(transport[0]) == 4


@pytest.mark.parametrize("origin", ["http://social.example.test", "https://localhost", "https://127.0.0.1", "https://10.0.0.1", "https://[::1]", "https://host.internal", "https://social.example.test/api/v1", "https://user:secret@social.example.test", "https://social.example.test?x=1", "https://social.example.test#fragment", "https://social.example.test:0"])
def test_public_origin_admission_refuses_private_or_broader_authority(origin, transport):
    with pytest.raises(ValueError):
        node(raw={**KEY, "instance_origin": origin})
    assert not transport[0]


def test_actual_schema_closed_four_operations_required_origin_and_opaque_parent():
    schema = native.MastodonNode.get_config_schema()
    refs = schema["properties"]["config"]["oneOf"]
    assert [schema["$defs"][row["$ref"].split("/")[-1]]["properties"]["operation"]["const"] for row in refs] == ["verify_credentials", "get_account", "list_statuses", "get_status"]
    creds = schema["$defs"]["MastodonCredential"]
    assert creds["required"] == ["instance_origin", "access_token"]
    assert creds["properties"]["access_token"]["ui:widget"] == "password"
    assert "refresh_token" not in creds["properties"] and "instance_origin" not in creds.get("default", {})
    assert schema["$defs"]["GetStatus"]["required"] == ["account_id", "status_id"]
    assert schema["$defs"]["GetStatus"]["properties"]["status_id"]["x-dynamic-options"]["depends_on"] == "account_id"
    assert schema["$defs"]["ListStatuses"]["properties"]["limit"]["default"] == 20
    assert schema["$defs"]["ListStatuses"]["properties"]["limit"]["maximum"] == 40
    assert node("list_statuses", account_id=ACTOR, max_id="older-X", min_id="newer-Y", since_id=None).config.config.max_id == "older-X"


@pytest.mark.asyncio
async def test_visible_form_connect_retains_only_protected_current_actor(transport):
    transport[1].append(deepcopy(ACCOUNT))
    result = await validate_for_connect(credential_type=native.TYPE, credential_data={key: value for key, value in KEY.items() if key != "credential_type"}, user_id=USER)
    assert result.ok and result.credential_data["credential_type"] == native.TYPE
    assert result.evidence.reachable and result.evidence.account_label == ACTOR
    assert result.verified_metadata()["verified_as"] == ACTOR
    assert "omit" not in str(result.evidence) and "synthetic-private" not in str(result.evidence)
    assert [request.url.path for request in transport[0]] == ["/api/v1/accounts/verify_credentials"]


@pytest.mark.asyncio
async def test_foreign_factory_and_preparsed_discriminator_are_zero_io(transport):
    with pytest.raises(ValueError):
        NodeFactory.create_node(node_id="foreign", node_type=NT, node_data={"config": {"operation": "verify_credentials"}, "credentials": {**KEY, "credential_type": "foreign"}, "credentialIds": {native.TYPE: CID}}, sio=None, sid=None)
    instance = node()
    instance.node_data["credentials"]["credential_type"] = "foreign"
    with pytest.raises(ValueError):
        await instance.execute({})
    assert not transport[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args,sequence,paths", [
    ("verify_credentials", {}, [ACCOUNT], ["/accounts/verify_credentials"]),
    ("get_account", {"account_id": ACTOR}, [ACCOUNT, ACCOUNT, ACCOUNT], ["/accounts/verify_credentials", "/accounts/" + ACTOR, "/accounts/verify_credentials"]),
    ("list_statuses", {"account_id": ACTOR, "max_id": "older-X", "min_id": "newer-Y"}, [ACCOUNT, [STATUS], ACCOUNT], ["/accounts/verify_credentials", "/accounts/" + ACTOR + "/statuses", "/accounts/verify_credentials"]),
    ("get_status", {"account_id": ACTOR, "status_id": SID}, [ACCOUNT, [STATUS], STATUS, ACCOUNT], ["/accounts/verify_credentials", "/accounts/" + ACTOR + "/statuses", "/statuses/" + SID, "/accounts/verify_credentials"]),
])
async def test_actual_native_routes_protected_witnesses_and_private_projection(transport, operation, args, sequence, paths):
    transport[1].extend(deepcopy(sequence))
    result = await node(operation, **args).execute({})
    assert result["status"] == "success" and result["operation"] == operation
    assert [request.url.path.removeprefix("/api/v1") for request in transport[0]] == paths
    def assert_public_projection(value):
        if isinstance(value, dict):
            assert not {"source", "roles", "content", "uri", "media_attachments", "access_token"}.intersection(value)
            for child in value.values():
                assert_public_projection(child)
        elif isinstance(value, list):
            for child in value:
                assert_public_projection(child)
        elif isinstance(value, str):
            assert "omit" not in value and KEY["access_token"] not in value

    assert_public_projection(result)
    if operation == "list_statuses":
        query = dict(transport[0][1].url.params)
        assert query == {"limit": "20", "exclude_reblogs": "true", "exclude_replies": "true", "max_id": "older-X", "min_id": "newer-Y"}
        assert result["data"]["completion"] == "unknown" and result["data"]["items"][0]["edited_at"] is None
    if operation == "verify_credentials":
        assert result["data"] == {"id": ACTOR}


@pytest.mark.asyncio
@pytest.mark.parametrize("rows,link", [([], False), ([STATUS], True)])
async def test_actual_agent_page_completion_stays_unknown_and_link_is_not_followed(transport, rows, link):
    headers = {"link": '<https://private.invalid/omit?token=omit>; rel="next"'} if link else {}
    transport[1].extend([ACCOUNT, httpx.Response(200, json=rows, headers=headers), ACCOUNT])
    result = await run_node_operation(node_type=NT, operation="list_statuses", arguments={"account_id": ACTOR}, credential_data=KEY, user_id=USER)
    data = result["data"]
    assert data["returned_count"] == len(rows) and data["completion"] == "unknown" and data["snapshot_consistent"] is False
    assert data["link_header_present"] is link and "total" not in data and "next_page_token" not in data
    assert "omit" not in str(result) and len(transport[0]) == 3


@pytest.mark.asyncio
async def test_names_are_opt_in_and_dates_remain_provider_strings(transport):
    transport[1].extend([ACCOUNT, {**ACCOUNT, "last_status_at": "2026-10-01"}, ACCOUNT])
    result = await node("get_account", account_id=ACTOR, include_names=True).execute({})
    assert result["data"]["account"]["display_name"] == "" and result["data"]["account"]["last_status_at"] == "2026-10-01"
    assert "omit" not in str(result)


@pytest.mark.asyncio
async def test_foreign_account_refused_before_public_detail(transport):
    transport[1].append(ACCOUNT)
    with pytest.raises(ValueError):
        await node("get_account", account_id="third-party").execute({})
    assert len(transport[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", [[{**STATUS, "account": {"id": "third-party"}}], [{**STATUS, "reblog": STATUS}], [{**STATUS, "in_reply_to_account_id": "third-party"}], [STATUS, STATUS], {"statuses": [STATUS]}, [{**STATUS, "id": 1}], [{**STATUS, "favourites_count": True}]])
async def test_catalog_rejects_third_party_boosts_duplicate_ids_and_wrong_shapes(transport, rows):
    transport[1].extend([ACCOUNT, rows])
    with pytest.raises(native.OutcomeUnverified):
        await node("list_statuses", account_id=ACTOR).execute({})
    assert len(transport[0]) == 2


@pytest.mark.asyncio
async def test_documented_self_replies_are_accepted_without_reply_parent_output(transport):
    transport[1].extend([ACCOUNT, [{**STATUS, "in_reply_to_account_id": ACTOR, "in_reply_to_id": "omit-parent"}], ACCOUNT])
    result = await node("list_statuses", account_id=ACTOR).execute({})
    assert result["data"]["items"][0]["id"] == SID and "in_reply_to" not in str(result)


@pytest.mark.asyncio
async def test_selected_status_requires_current_page_and_independent_authorship(transport):
    transport[1].extend([ACCOUNT, []])
    with pytest.raises(native.OutcomeUnverified):
        await node("get_status", account_id=ACTOR, status_id=SID).execute({})
    assert len(transport[0]) == 2
    transport[1].extend([ACCOUNT, [STATUS], {**STATUS, "id": "other-status"}])
    with pytest.raises(native.OutcomeUnverified):
        await node("get_status", account_id=ACTOR, status_id=SID).execute({})
    assert len(transport[0]) == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("final", [{**ACCOUNT, "id": "changed-actor"}, httpx.Response(401, json={"error": "omit-token"})])
async def test_public_metadata_is_discarded_if_final_protected_actor_fails(transport, final):
    transport[1].extend([ACCOUNT, ACCOUNT, final])
    with pytest.raises((native.OutcomeUnverified, native.ApiError)):
        await node("get_account", account_id=ACTOR).execute({})
    assert len(transport[0]) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("status,category", [(401, "authentication"), (403, "permission"), (404, "resource"), (410, "resource"), (429, "other"), (500, "other"), (302, "other")])
async def test_safe_errors_never_echo_provider_error_body_or_retry(transport, status, category):
    transport[1].append(httpx.Response(status, json={"error": "omit-error " + KEY["access_token"]}, headers={"location": "https://omit.example.test"}))
    with pytest.raises(native.ApiError) as error:
        await node().execute({})
    assert error.value.category == category and "omit" not in str(error.value) and KEY["access_token"] not in str(error.value)
    assert len(transport[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body,ctype", [(b'{"id":"a","id":"b"}', "application/json"), (b'{"id":NaN}', "application/json"), (b'omit-private', "text/plain")])
async def test_json_shape_errors_do_not_echo_private_payload(transport, body, ctype):
    transport[1].append(httpx.Response(200, content=body, headers={"content-type": ctype}))
    with pytest.raises(native.OutcomeUnverified):
        await node().execute({})


@pytest.mark.asyncio
async def test_private_transport_logging_and_body_bound(transport, caplog):
    logger = logging.getLogger("httpx")
    def observed(request):
        logger.warning("%s %s", request.headers["Authorization"], "omit-private-resource")
        return ACCOUNT
    transport[1].append(observed)
    with caplog.at_level(logging.WARNING):
        await node().execute({})
        logger.warning("Ordinary unrelated message")
    assert "Mastodon transport activity" in caplog.text and "Ordinary unrelated message" in caplog.text
    assert KEY["access_token"] not in caplog.text and "omit-private" not in caplog.text
    transport[1].append(httpx.Response(200, content=b" " * (native.MAX_BODY + 1), headers={"content-type": "application/json"}))
    with pytest.raises(native.OutcomeUnverified):
        await node().execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("latest", [None, {**KEY, "access_token": "changed"}, {**KEY, "instance_origin": "https://other.example.test"}])
async def test_saved_credential_uses_staging_resolver_and_refuses_changes(monkeypatch, transport, latest):
    resolver = AsyncMock(side_effect=[deepcopy(KEY), latest])
    monkeypatch.setattr(native, "resolve_credential_with_owner_fallback", resolver)
    instance = node()
    instance.node_data.update({"credential_id": CID, "_approval_pool": object()})
    with pytest.raises(ValueError):
        await instance.execute({})
    assert not transport[0]
    assert resolver.await_args.kwargs == {"org_id": None, "workflow_id": None}


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["pending_approval", "rejected"])
async def test_actual_run_admission_is_zero_provider_io(monkeypatch, transport, decision):
    monkeypatch.setattr("utils.credential_approval.admit_node", AsyncMock(return_value={"status": decision, "message": "Owner review"}))
    assert (await node().run({}))["status"] == decision and not transport[0]


@pytest.mark.asyncio
async def test_picker_verifies_parent_and_uses_explicit_page(transport):
    transport[1].append(ACCOUNT)
    with pytest.raises(ValueError):
        await native.MastodonNode.load_field_options(field_name="status_id", credential_data=KEY, context={"account_id": "foreign"})
    transport[1].extend([ACCOUNT, [STATUS], ACCOUNT])
    result = await native.MastodonNode.load_field_options(field_name="status_id", credential_data=KEY, context={"account_id": ACTOR})
    assert result == {"options": [{"value": SID, "label": "Status " + SID + " · " + STATUS["created_at"]}], "next_page_token": None}
    with pytest.raises(ValueError):
        await native.MastodonNode.load_field_options(field_name="status_id", credential_data=KEY, context={"account_id": ACTOR}, page_token="https://private.invalid")
    assert len(transport[0]) == 4
