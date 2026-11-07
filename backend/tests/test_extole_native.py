"""Extole regressions on staging; transport responses are synthetic unit fixtures."""
from copy import deepcopy
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import extole_node as provider
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation
USER = "11111111-1111-4111-8111-111111111111"
CID = "22222222-2222-4222-8222-222222222222"

NODE = "automation-extole"
GRANT = {"credential_type": "extole_access_token", "access_token": "synthetic-extole-secret"}
TOKEN = {"access_token": GRANT["access_token"], "client_id": "client-1", "identity_id": "private-identity",
         "type": "MANAGED", "scopes": ["CLIENT_ADMIN"], "expires_in": 3600}
PERSON = {"id": "person-1", "version": "v1", "identity_key_value": "private@example.invalid",
          "identity_id": "private-identity", "locale": {"country": "private-country"}}
CAMPAIGN = {"campaign_id": "campaign-1", "name": "Fixture campaign", "state": "NOT_LAUNCHED",
            "is_published": False, "tags": [], "version": 1,
            "components": [{"secret": "private-component"}], "incentive": {"secret": "private-incentive"}}
DATA = {"id": "data-1", "name": "fixture", "scope": "PRIVATE", "value": {"private": "synthetic-private-value"}}
REPORT = {"report_id": "report-1", "name": "Fixture", "display_name": "Fixture report",
          "report_type": "fixture-type", "completed_date": None, "formats": ["JSON"], "tags": [],
          "download_uri": "https://private.invalid/signed?secret=synthetic-url-secret", "parameters": {"private": "value"}}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    def handler(request):
        requests.append(request)
        assert request.headers["authorization"] == "Bearer " + GRANT["access_token"]
        assert "access_token" not in request.url.params
        assert request.url.host in {"api.extole.io", "events.extole.io"}
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, httpx.Response):
            return reply
        return httpx.Response(200, json=reply)
    def client(**kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False, follow_redirects=False)
    monkeypatch.setattr(provider, "guarded_async_client", client)
    return SimpleNamespace(requests=requests, replies=replies)


def node(operation, *, credentials=None, **arguments):
    return NodeFactory.create_node(node_id="fixture-extole", node_type=NODE,
        node_data={"config": {"operation": operation, **arguments}, "credentials": credentials or deepcopy(GRANT)},
        user_id=USER)


@pytest.mark.asyncio
async def test_native_dispatcher_token_identity_and_secret_projection(transport):
    transport.replies.append(TOKEN)
    result = await run_node_operation(node_type=NODE, operation="check_connection", arguments={},
                                      user_id=USER, credential_data=deepcopy(GRANT))
    assert result["data"]["client_id"] == "client-1"
    assert "access_token" not in result["data"] and "identity_id" not in result["data"]
    assert transport.requests[0].url.path == "/v4/tokens"


@pytest.mark.asyncio
async def test_search_requires_criterion_preserves_duplicates_empty_and_paging(transport):
    with pytest.raises(ValueError):
        node("search_participants")
    transport.replies.extend([[PERSON, {**PERSON, "id": "person-2"}], []])
    result = await node("search_participants", person_keys=["partner_user_id:fixture"], limit=2).execute({})
    assert [row["id"] for row in result["data"]] == ["person-1", "person-2"]
    assert result["pagination"]["next_offset"] == 2
    assert "identity_key_value" not in str(result)
    assert transport.requests[0].url.params["person_keys"] == "partner_user_id:fixture"
    empty = await node("search_participants", identity_key_value="fixture", offset=2, limit=2).execute({})
    assert empty["data"] == [] and empty["pagination"]["next_offset"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,response,method,path", [
    ("get_participant", {"person_id": "person-1"}, PERSON, "GET", "/v5/persons/person-1"),
    ("create_participant", {"identity_key_value": "fixture@example.invalid"}, PERSON, "POST", "/v5/persons"),
    ("update_participant", {"person_id": "person-1", "identity_key_value": "fixture@example.invalid"}, PERSON, "PUT", "/v5/persons/person-1"),
    ("list_participant_data", {"person_id": "person-1"}, {"fixture": DATA}, "GET", "/v5/persons/person-1/data"),
    ("get_participant_data", {"person_id": "person-1", "name": "fixture"}, DATA, "GET", "/v5/persons/person-1/data/fixture"),
    ("create_participant_data", {"person_id": "person-1", "name": "fixture", "value": {}}, DATA, "POST", "/v5/persons/person-1/data"),
    ("update_participant_data", {"person_id": "person-1", "name": "fixture", "value": {}}, DATA, "PUT", "/v5/persons/person-1/data/fixture"),
    ("delete_participant_data", {"person_id": "person-1", "name": "fixture"}, DATA, "DELETE", "/v5/persons/person-1/data/fixture"),
    ("list_referral_relationships", {"person_id": "person-1"}, [], "GET", "/v5/persons/person-1/relationships"),
    ("list_participant_journeys", {"person_id": "person-1"}, [], "GET", "/v5/persons/person-1/journeys"),
    ("list_campaign_summaries", {}, [], "GET", "/v2/campaign-summaries"),
    ("get_campaign_summary", {"campaign_id": "campaign-1"}, CAMPAIGN, "GET", "/v2/campaign-summaries/campaign-1"),
    ("get_campaign_metadata", {"campaign_id": "campaign-1"}, CAMPAIGN, "GET", "/v2/campaigns/campaign-1"),
    ("create_campaign_draft", {"name": "Fixture"}, CAMPAIGN, "POST", "/v2/campaigns"),
    ("list_report_types", {}, [], "GET", "/v6/report-types"),
    ("list_reports", {}, [], "GET", "/v4/reports"),
    ("get_report", {"report_id": "report-1"}, REPORT, "GET", "/v4/reports/report-1"),
    ("create_report", {"name": "Fixture", "report_type": "fixture-type"}, REPORT, "POST", "/v4/reports"),
    ("update_report", {"report_id": "report-1", "tags": []}, REPORT, "PUT", "/v4/reports/report-1"),
    ("delete_report", {"report_id": "report-1"}, REPORT, "DELETE", "/v4/reports/report-1"),
    ("get_opt_out_status", {"email": "fixture@example.invalid"}, {"email": "fixture@example.invalid", "optout": False}, "GET", "/v4/optouts"),
])
async def test_native_operation_paths_methods_and_private_projections(transport, operation, arguments, response, method, path):
    transport.replies.append(response)
    result = await node(operation, **arguments).execute({})
    request = transport.requests[-1]
    assert request.method == method and request.url.path == path
    assert result["http_status"] == 200
    from nodes.agent.node_op_tools import extract_resource_id_from_output, resource_creators
    for creator, _resource, path in resource_creators(NODE):
        if creator == operation:
            expected = response.get("id") or response.get("campaign_id") or response.get("report_id")
            assert extract_resource_id_from_output(result, path) == expected
    for secret in ("private@example.invalid", "synthetic-private-value", "private-component", "private-incentive", "synthetic-url-secret"):
        assert secret not in str(result)
    if operation == "create_participant_data":
        assert json.loads(request.content) == {"name": "fixture", "value": {}, "scope": "PRIVATE"}
    if operation == "create_report":
        assert result["execution"] == "asynchronous"
        assert result["data"]["completed_date"] is None and "status" not in result["data"]
        assert json.loads(request.content)["parameters"] == {}
    if operation == "get_opt_out_status":
        assert result["data"] == {"optout": False}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["update_campaign_metadata", "delete_campaign_draft"])
async def test_campaign_preflight_and_second_current_authority_check(transport, monkeypatch, operation):
    instance = node(operation, campaign_id="campaign-1", **({"tags": []} if operation.startswith("update") else {}))
    current = AsyncMock(wraps=instance._current)
    monkeypatch.setattr(instance, "_current", current)
    transport.replies.extend([CAMPAIGN, CAMPAIGN])
    result = await instance.execute({})
    assert result["data"]["campaign_id"] == "campaign-1"
    assert [r.method for r in transport.requests] == ["GET", "PUT" if operation.startswith("update") else "DELETE"]
    assert current.await_count == 2
    if operation.startswith("update"):
        assert json.loads(transport.requests[-1].content) == {"tags": []}


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"is_published": True}, {"state": "LIVE"}, {"campaign_id": "other"}])
async def test_published_or_mismatched_campaign_cannot_be_deleted(transport, change):
    transport.replies.append({**CAMPAIGN, **change})
    with pytest.raises(ValueError):
        await node("delete_campaign_draft", campaign_id="campaign-1").execute({})
    assert len(transport.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,receipt", [
    ("submit_event", {"event_id": "event-1", "person_id": "person-1"}),
    ("submit_async_event", {"event_id": "event-1"}),
])
async def test_events_use_distinct_origin_and_honest_receipts(transport, operation, receipt):
    transport.replies.append(receipt)
    result = await node(operation, event_name="fixture", data={"person_id": 42, "properties": {"amount": 0}}).execute({})
    request = transport.requests[-1]
    assert request.url.host == "events.extole.io" and request.method == "POST"
    assert request.url.path == ("/v6/events" if operation == "submit_event" else "/v6/async-events")
    assert result["data"]["reward_completion"] == result["data"]["notification_completion"] == "unknown"
    assert ("person_id" in result["data"]) is (operation == "submit_event")
    body = json.loads(request.content)
    assert body["data"]["person_id"] == 42 and body["data"]["amount"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [
    httpx.Response(200, json={}), httpx.Response(200, text="<html>private</html>"),
    httpx.Response(204), httpx.Response(201, json=TOKEN), httpx.Response(302, headers={"location": "https://evil.invalid"}),
    httpx.Response(429, json={"message": "synthetic-extole-secret private@example.invalid"}),
    ValueError("synthetic-extole-secret private@example.invalid"),
])
async def test_malformed_unexpected_success_redirect_and_error_privacy(transport, reply):
    transport.replies.append(reply)
    with pytest.raises(ValueError) as error:
        await node("check_connection").execute({})
    assert "synthetic-extole-secret" not in str(error.value)
    assert "private@example.invalid" not in str(error.value)
    assert len(transport.requests) == 1


def test_real_factory_and_preparsed_source_refuse_foreign_discriminator():
    data = {"config": {"operation": "check_connection"}, "credentials": {**GRANT, "credential_type": "slack_bot_token"},
            "credentialIds": {"extole_access_token": CID}, "credential_id": CID}
    with pytest.raises(ValueError):
        NodeFactory.create_node(node_id="bad", node_type=NODE, node_data=data)
    assert provider.ExtoleNode.validate_config(data)["valid"] is False


@pytest.mark.asyncio
async def test_preparsed_execute_refuses_raw_foreign_type_before_transport(transport):
    instance = node("check_connection")
    instance.node_data["credentials"]["credential_type"] = "slack_bot_token"
    with pytest.raises(ValueError):
        await instance.execute({})
    assert transport.requests == []








@pytest.mark.asyncio
async def test_client_binding_refuses_foreign_tenant_before_write(transport):
    transport.replies.append({**TOKEN, "client_id": "other-client"})
    with pytest.raises(ValueError):
        await node("create_participant", credentials={**GRANT, "expected_client_id": "client-1"},
                   identity_key_value="fixture@example.invalid").execute({})
    assert [r.url.path for r in transport.requests] == ["/v4/tokens"]


@pytest.mark.asyncio
async def test_real_native_run_pending_admission_never_requests(transport, monkeypatch):
    pending = {"status": "pending", "success": False, "message": "Owner approval pending"}
    monkeypatch.setattr("utils.credential_approval.admit_node", AsyncMock(return_value=pending))
    result = await run_node_operation(node_type=NODE, operation="submit_event",
        arguments={"event_name": "fixture"}, credential_data=GRANT, user_id=USER)
    assert result == pending and transport.requests == []




@pytest.mark.asyncio
async def test_parent_picker_requires_explicit_parent_and_strict_page(transport):
    with pytest.raises(ValueError):
        await provider.ExtoleNode.load_field_options("data_name", GRANT, context={})
    with pytest.raises(ValueError):
        await provider.ExtoleNode.load_field_options("report_id", GRANT, page_token="https://evil.invalid")
    assert transport.requests == []


@pytest.mark.asyncio
async def test_query_and_header_diagnostics_are_private_and_task_scope_restores(transport, caplog):
    transport.replies.append({"email": "fixture@example.invalid", "optout": False})
    with caplog.at_level(logging.INFO, logger="httpx"):
        await node("get_opt_out_status", email="fixture@example.invalid").execute({})
        logging.getLogger("httpx").info("outside diagnostic")
    assert "fixture@example.invalid" not in caplog.text
    assert "synthetic-extole-secret" not in caplog.text
    assert "outside diagnostic" in caplog.text


@pytest.mark.asyncio
async def test_actual_collector_pending_admission_does_not_claim_account_or_reachability(transport, monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    monkeypatch.setattr("utils.credential_approval.admit_node", AsyncMock(return_value={
        "status": "pending", "success": False, "message": "Owner approval pending"}))
    result = await collect_evidence(node_type=NODE, user_id=USER, credential_data=GRANT)
    assert result.reachable is None and result.account_label is None and result.samples == []
    assert transport.requests == []


@pytest.mark.asyncio
async def test_actual_collector_uses_protected_client_identity_without_requiring_campaign_scope(transport):
    from nodes.core.connection_evidence import collect_evidence
    transport.replies.append(TOKEN)
    result = await collect_evidence(node_type=NODE, user_id=USER, credential_data=GRANT)
    assert result.reachable is True
    assert provider.ExtoleNode.connection_evidence.proves == "account"
    assert result.account_label == "client-1" and result.samples == []
    assert [r.url.path for r in transport.requests] == ["/v4/tokens"]




def test_native_creator_schema_paths_and_credential_title():
    from nodes.agent.node_op_tools import resource_creators
    schema = provider.ExtoleNodeConfig.model_json_schema()
    assert schema["$defs"]["ExtoleAccessTokenCredential"]["title"] == "Extole Access Token"
    entries = resource_creators(NODE)
    paths = {op: path for op, _resource, path in entries}
    assert paths["create_participant"] == "data.id"
    assert paths["create_campaign_draft"] == "data.campaign_id"
    assert paths["create_report"] == "data.report_id"
    assert provider.ExtoleNode.get_config_model() is provider.ExtoleNodeConfig


def test_real_factory_preserves_canvas_tool_metadata_without_forwarding_it():
    instance = node("get_participant", person_id="person-1",
                    agent_tool_operations=["get_participant"])
    assert instance.node_data["config"]["agent_tool_operations"] == ["get_participant"]
    assert "agent_tool_operations" not in instance._config.config.model_dump()


@pytest.mark.parametrize("arguments", [{"limit": True}, {"limit": 0}, {"offset": False}, {"person_id": "../other"}])
def test_numeric_and_path_validation(arguments):
    operation = "list_reports" if "person_id" not in arguments else "get_participant"
    with pytest.raises(ValueError):
        node(operation, **arguments)


@pytest.mark.asyncio
async def test_expired_token_fails_before_transport_on_execute_and_lookup(transport):
    expired = {**GRANT, "expires_at": "2000-01-01T00:00:00Z"}
    with pytest.raises(ValueError, match="expired"):
        await node("check_connection", credentials=expired).execute({})
    with pytest.raises(ValueError, match="expired"):
        await provider.ExtoleNode.load_field_options("campaign_id", expired)
    assert transport.requests == []


@pytest.mark.asyncio
async def test_freshen_token_matches_staging_hook_and_preserves_client_binding():
    grant = {**GRANT, "expected_client_id": "client-1"}
    current = await provider.ExtoleNode.freshen_credential(grant, pool=None, user_id=USER, credential_id="stored-id")
    assert current["access_token"] == GRANT["access_token"]
    assert current["expected_client_id"] == "client-1"
