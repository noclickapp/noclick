"""Discover real provider schemas, then execute them against selected accounts.

Only OAuth loading and external HTTP are replaced; registry, SDK tool rounds,
credential access, provider implementation and approval transactions are real.
"""
import base64
import json
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from coder.coordinator.tools import CoordinatorTools
from utils.credential_actions import CredentialActions
from tests.test_credential_approvals import USER, OTHER, OP, approval_db  # noqa: F401

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def use_test_database(approval_db, monkeypatch):
    # Provider execution also reads account tier for email branding. Every
    # database read must use this test's real pool, not a local dev database
    # or an uninitialized app-lifespan pool on CI.
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: approval_db[0])


def coordinator(pool):
    return CoordinatorTools(pool=pool, sio=None, user_id=USER, organization_id=None,
                            conversation_id=f"coordinator:{USER}")


async def mail_accounts(monkeypatch, ids):
    async def load(cid, *args):
        assert cid in ids
        return {"credential_type": "google_gmail_oauth", "access_token": f"token-{cid}", "refresh_token": "test",
                "expires_at": "2099-01-01T00:00:00Z", "email": f"{ids.index(cid)}@example.test"}
    monkeypatch.setattr("nodes.core.run_op.resolve_operation_credential", load)


async def test_identity_is_allowlisted_searchable_and_native_provider_first(approval_db):
    pool, _, (cid, _) = approval_db
    await pool.execute("UPDATE credentials SET credential_type='microsoft_outlook_oauth',metadata=$2 WHERE id=$1::uuid",
                       cid, {"email": "owner@example.test", "access_token": "NEVER_EXPORT", "nested": {"secret": "secret"}})
    actions = CredentialActions(pool=pool, user_id=USER)
    found = await actions.list_credentials(query="owner@example.test")
    assert found["credentials"][0]["identity"] == {"email": "owner@example.test"}
    assert "NEVER_EXPORT" not in json.dumps(found)
    ops = await actions.credential_operations(cid)
    assert ops["operations"][0]["node_type"] == "automation-outlook"
    search = await actions.search_credential_tools("read outlook email messages", credential_id=cid)
    assert search["operations"] and search["operations"][0]["tool_names"]


@respx.mock
async def test_outlook_operation_uses_its_selected_account_without_workflow(approval_db, monkeypatch):
    pool, _, (cid, _) = approval_db
    await pool.execute("UPDATE credentials SET credential_type='microsoft_outlook_oauth' WHERE id=$1::uuid", cid)
    monkeypatch.setattr("nodes.core.run_op.resolve_operation_credential", AsyncMock(return_value={
        "credential_type": "microsoft_outlook_oauth", "access_token": "outlook-token", "refresh_token": "test",
        "expires_at": "2099-01-01T00:00:00Z", "email": "owner@example.test"}))
    tools = coordinator(pool)
    loaded = await tools.execute("credential_operations", {"credential_id": cid,
        "node_type": "automation-outlook", "operation": "get_mailbox_settings"})
    remote = respx.get("https://graph.microsoft.com/v1.0/me/mailboxSettings").mock(
        return_value=httpx.Response(200, json={"timeZone": "UTC"}))
    result = await tools.execute(loaded["loaded_tools"][0], {"credential_id": cid, "arguments": {}})
    assert result["status"] == "success" and result["settings"]["timezone"] == "UTC"
    assert remote.calls.last.request.headers["authorization"] == "Bearer outlook-token"


@respx.mock
async def test_native_lookup_requires_credential_and_cannot_bypass_locked_reads(approval_db, monkeypatch):
    from utils.credential_operations import operation_catalog, operation_tool
    pool, repo, (cid, _) = approval_db
    await mail_accounts(monkeypatch, [cid])
    tools = coordinator(pool)
    for op in operation_catalog("google_gmail_oauth"):
        definitions, configs = operation_tool("google_gmail_oauth", op["node_type"], op["operation"])
        if any(c["tool_type"] == "node_op_lookup" for c in configs.values()):
            tools.credential_tools.registry.load(op["node_type"], op["operation"], definitions, configs)
            break
    else:
        pytest.fail("Expected a provider with dynamic ID lookup")
    lookup = next(t["function"] for t in tools.credential_tools.registry.tool_params() if "_lookup_" in t["function"]["name"])
    assert "credential_id" in lookup["parameters"]["required"]
    field = lookup["parameters"]["properties"]["arguments"]["properties"]["field"]["enum"][0]
    await repo.tighten(cid, USER, ["*"])
    result = await tools.execute(lookup["name"], {"credential_id": cid, "arguments": {"field": field}})
    assert result["status"] == "pending_approval" and not result["executed"]


@respx.mock
async def test_two_accounts_one_native_tool_distinct_approval_and_fresh_access(approval_db, monkeypatch):
    pool, repo, ids = approval_db
    a, b = ids
    await mail_accounts(monkeypatch, ids)
    tools = coordinator(pool)
    result = await tools.execute("search_credential_tools", {"query": "send email message"})
    operation = next(op for op in result["operations"] if op["key"] == OP)
    assert {c["id"] for c in operation["credentials"]} == set(ids)
    name = operation["tool_names"][0]
    schema = next(t["function"]["parameters"] for t in tools.credential_tools.registry.tool_params()
                  if t["function"]["name"] == name)
    assert "credential_id" in schema["required"]
    assert {"to", "body", "subject"} <= set(schema["properties"]["arguments"]["required"])
    args = {"arguments": {"to": ["recipient@example.test"], "subject": "Test", "body": "Hi"}}
    remote = respx.post("https://gmail.googleapis.com/gmail/v1/users/me/messages/send").mock(
        return_value=httpx.Response(200, json={"id": "msg1"}))
    assert (await tools.execute(name, args))["success"] is False
    assert remote.call_count == 0
    await repo.tighten(a, USER, [OP])
    pending = await tools.execute(name, {"credential_id": a, **args})
    assert pending["status"] == "pending_approval" and remote.call_count == 0
    assert (await tools.execute(name, {"credential_id": b, **args}))["status"] == "success"
    assert remote.calls.last.request.headers["authorization"] == f"Bearer token-{b}"
    mime = base64.urlsafe_b64decode(json.loads(remote.calls.last.request.content)["raw"]).decode()
    assert "From: 1@example.test" in mime
    await repo.decide_from_human(pending["approval_id"], USER, "approved")
    # Approval may wake a fresh container: reconstruct definitions from the
    # durable approval, without secretly retaining a tool-bound account.
    tools = coordinator(pool)
    await tools.credential_tools.load_approval_tools({"status": "approved", "credential_id": a,
        "node_type": "automation-gmail", "operation": "send_email_message", "arguments": args["arguments"]})
    assert name in tools.credential_tools.registry.routes
    assert (await tools.execute(name, {"credential_id": a, **args}))["status"] == "success"
    assert remote.calls.last.request.headers["authorization"] == f"Bearer token-{a}"
    assert (await tools.execute(name, {"credential_id": a, **args}))["status"] == "pending_approval"
    # A cached tool definition grants no enduring account access.
    await pool.execute("UPDATE credentials SET owner_id=$2::uuid WHERE id=$1::uuid", b, OTHER)
    assert (await tools.execute(name, {"credential_id": b, **args}))["success"] is False
    assert remote.call_count == 2


@respx.mock
async def test_streamed_sdk_sees_discovered_tool_on_next_round_and_chooses_account(approval_db, monkeypatch):
    from agents.models.interface import Model
    from openai.types.responses import Response, ResponseCompletedEvent, ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText
    from coder.openai_agent import Agent
    from coder.openai_agent.config import AgentConfiguration
    from wss.sender.schema import ContentItem

    pool, _, ids = approval_db
    await mail_accounts(monkeypatch, ids)
    tools = coordinator(pool)
    seen = []
    class ModelDouble(Model):
        async def get_response(self, *args, **kwargs):
            raise AssertionError("Expected streaming")

        async def stream_response(self, system_instructions, input, model_settings, tools, *args, **kwargs):
            definitions = tools
            seen.append(definitions)
            n = len(seen)
            if n == 1:
                assert not any(t.name.startswith("credential_send_") for t in definitions)
                name, arguments = "search_credential_tools", {"query": "send email message"}
            elif n == 2:
                native = next(t for t in definitions if t.name.startswith("credential_send_email_message_"))
                assert "credential_id" in native.params_json_schema["required"]
                name, arguments = native.name, {"credential_id": ids[1], "arguments": {
                    "to": ["recipient@example.test"], "subject": "Hello", "body": "Hi"}}
            else:
                assert n == 3
                output = [ResponseOutputMessage(id="final", type="message", role="assistant", status="completed",
                    content=[ResponseOutputText(type="output_text", text="Done", annotations=[])])]
            if n < 3:
                output = [ResponseFunctionToolCall(type="function_call", name=name, call_id=f"call-{n}", arguments=json.dumps(arguments))]
            response = Response.model_construct(id=f"r{n}", created_at=0, model="test", object="response", output=output,
                                                status="completed", usage=None)
            yield ResponseCompletedEvent(type="response.completed", response=response, sequence_number=0)

    async def execute(name, arguments):
        result = await tools.execute(name, arguments)
        agent.set_discovered_tools(tools.credential_tools.registry.tool_params())
        return result

    agent = await Agent.create(emit_message=AsyncMock(), user_id=USER,
        config=AgentConfiguration.from_kwargs(model="gpt-4o", enable_cmd=False, enable_editor=False, enable_mcp=False,
                                              custom_tools=tools.tool_params()), custom_tool_executor=execute)
    agent._sdk_agent.model = ModelDouble()
    agent._billing_hooks = None
    remote = respx.post("https://gmail.googleapis.com/gmail/v1/users/me/messages/send").mock(
        return_value=httpx.Response(200, json={"id": "msg2"}))
    try:
        await agent({"content_items": [ContentItem(type="text", text="Send using my second email account.")]})
    finally:
        await agent.cleanup()
    assert len(seen) == 3 and remote.call_count == 1
    assert remote.calls.last.request.headers["authorization"] == f"Bearer token-{ids[1]}"


async def test_tool_definitions_are_bounded_and_runtime_errors_are_not_argument_errors(approval_db, monkeypatch):
    pool, _, (cid, _) = approval_db
    tools = coordinator(pool)
    for offset in range(0, 18, 3):
        await tools.credential_tools.search_credential_tools("", credential_id=cid, offset=offset)
    assert len(tools.credential_tools.registry.tool_params()) == 12
    async def broken():
        raise TypeError("provider runtime failed")
    tools._tools["broken"] = broken
    audit = []
    monkeypatch.setattr("coder.coordinator.tools.record_tool_call", lambda **kw: audit.append(kw))
    assert (await tools.execute("broken", {}))["error"] == "provider runtime failed"
    tools._tools["broken"] = AsyncMock(return_value={"status": "error", "error": "provider refused"})
    await tools.execute("broken", {})
    assert [r["result_status"] for r in audit] == ["error", "error"]


async def test_empty_search_discovers_setup_without_loading_unconnected_tools(monkeypatch):
    from utils import capabilities

    monkeypatch.setitem(capabilities._providers, capabilities.PHONE_NUMBERS, object())
    actions = CredentialActions(pool=None, user_id=USER)
    monkeypatch.setattr(actions, "_credentials", AsyncMock(return_value=[]))
    result = await actions.search_credential_tools("make outbound phone call call phone number")
    assert not result["operations"] and not actions.registry.routes
    phone = next(o for o in result["setup_options"] if o["node_type"] == "automation-phone")
    assert phone["operation"] == "place_call"
    assert phone["connections"] == [{"credential_type": "phone_number", "name": "Phone Number", "tool": "request_phone_number"}]
    assert "not a calling credential" in result["instructions"]
    mail = await actions.search_credential_tools("Gmail send email message")
    gmail = next(o for o in mail["setup_options"] if o["node_type"] == "automation-gmail")
    assert gmail["connections"][0]["tool"] == "connect_credential"
    # A local instance cannot sell a number. Suggestions never load a tool or
    # confer access to an account, and an exhausted page doesn't restart setup.
    monkeypatch.delitem(capabilities._providers, capabilities.PHONE_NUMBERS)
    result = await actions.search_credential_tools("place phone call")
    assert all(c["tool"] != "request_phone_number" for o in result["setup_options"] for c in o["connections"])
    assert "setup_options" not in await actions.search_credential_tools("place call", offset=3)


async def test_scoped_search_does_not_suggest_switching_credentials(approval_db):
    pool, _, (cid, _) = approval_db
    actions = CredentialActions(pool=pool, user_id=USER)
    result = await actions.search_credential_tools("qzxnotanoperation", credential_id=cid)
    assert result["operations"] == [] and "setup_options" not in result
