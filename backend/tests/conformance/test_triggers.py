"""A trigger is verified, not just present: webhook events and a poll's list response go through the node's own path."""
import copy
import hashlib
import hmac
import os
from typing import Annotated, Any, Literal, Optional, Union

import httpx
import pytest
from pydantic import BaseModel, ConfigDict, Field

from nodes.core.base import WorkflowNode
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from tests.conformance import harness, triggers
from tests.conformance.verdict import openapi_verdict

HERE = os.path.realpath(__file__)
SOURCE = "https://example.test/docs/webhooks"
ORDER = {"type": "order.created", "data": {"id": "ord_1", "total": 42}}

ORDER_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string"},
        "data": {"type": "object", "properties": {"id": {"type": "string"}, "total": {"type": "integer"}}},
    },
}
HOOK = {"type": "object", "properties": {"id": {"type": "string"}, "secret": {"type": "string"}}}
SIGNING = {"header": "X-Sig", "algorithm": "sha256", "encoding": "hex", "format": "t={timestamp},v1={signature}",
           "message": "{timestamp}.{body}", "source": SOURCE}


def webhook_doc(events=True):
    doc = {
        "openapi": "3.1.0",
        "info": {"title": "Shop", "version": "1"},
        "servers": [{"url": "https://example.test"}],
        "paths": {
            "/hooks": {"post": {
                "requestBody": {"required": True, "content": {"application/json": {"schema": {
                    "type": "object", "required": ["url"], "properties": {"url": {"type": "string"}}}}}},
                "responses": {"200": {"description": "ok", "content": {"application/json": {
                    "schema": HOOK, "example": {"id": "hook_1", "secret": "whsec-documented"}}}}},
            }},
            "/hooks/{id}": {"delete": {
                "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"204": {"description": "gone"}},
            }},
        },
    }
    if events:
        doc["webhooks"] = {"order.created": {"post": {"requestBody": {"content": {"application/json": {
            "schema": ORDER_SCHEMA, "example": ORDER}}}, "responses": {"200": {"description": "ok"}}}}}
    return doc


def install(monkeypatch, name, node, doc, entry, events=None):
    from nodes.core.registry import NODE_REGISTRY

    # The pipeline runs the harness with CONFORMANCE_WITNESS=full: the spec's own examples answer first.
    monkeypatch.setattr(harness, "FULL", True)

    monkeypatch.setitem(NODE_REGISTRY, f"test-{name}", node)
    monkeypatch.setitem(harness.PROVIDERS, name, (f"test-{name}", {"credential_type": "key", "token": "<token>"}))
    monkeypatch.setattr(harness, "spec_entry", lambda _: (None, entry))
    monkeypatch.setattr(harness, "load_specs", lambda _: [doc])
    monkeypatch.setattr(harness, "EVENTS", events or {})
    monkeypatch.setattr(triggers, "node_files", lambda cls: frozenset({HERE}))


class Key(BaseModel):
    credential_type: Literal["key"] = "key"
    token: str


def webhook_node(mutation=None):
    class OnOrder(WebhookTriggerConfigBase):
        model_config = ConfigDict(json_schema_extra={"x-is-trigger": True})
        operation: Literal["on_order"]

    class Config(BaseModel):
        config: Annotated[Union[OnOrder], Field(discriminator="operation")]
        credentials: Key

    class Shop(ExternalWebhookTriggerMixin, WorkflowNode):
        get_config_model = staticmethod(lambda: Config)

        @classmethod
        async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
            async with httpx.AsyncClient() as client:
                path = "/hookz" if mutation == "bad_registration" else "/hooks"
                response = await client.post(f"https://example.test{path}", json={"url": webhook_url})
            hook = response.json()
            return {"external_webhook_id": hook["id"], "signing_secret": hook["secret"]}

        @classmethod
        async def _unregister_external_webhook(cls, *, credential, config, node_id):
            async with httpx.AsyncClient() as client:
                await client.delete(f"https://example.test/hooks/{config['external_webhook_id']}")

        @classmethod
        def verify_webhook_signature(cls, body, headers, config):
            if mutation == "lax_signature":
                return True
            parts = dict(p.split("=", 1) for p in headers.get("x-sig", "").split(",") if "=" in p)
            signed = body if mutation == "wrong_signature" else parts.get("t", "").encode() + b"." + body
            expected = hmac.new(config["signing_secret"].encode(), signed, hashlib.sha256).hexdigest()
            return hmac.compare_digest(parts.get("v1", ""), expected)

        @classmethod
        def filter_trigger_payload(cls, payload, config):
            return mutation != "filtered"

        @classmethod
        def resolve_agent_event(cls, output):
            data = output["data"]
            if mutation == "raises":
                raise KeyError("customer")
            extra = f" for {data.get('customer')}" if mutation == "reads_unknown" else ""
            return {"text": f"Order {data['id']} ({data.get('total')}){extra}", "conversation_key": None}

        async def execute(self, inputs):
            return self.no_event_output("on_order")

    return Shop


@pytest.mark.parametrize("mutation, expected", [
    (None, None),
    ("reads_unknown", "reads data.customer, which the order.created event schema doesn't have"),
    ("lax_signature", "accepts it with a body its signature doesn't match"),
    ("wrong_signature", "rejected it, signed as the docs describe"),
    ("raises", "run: "),
    ("filtered", "none of the 1 documented events reached this trigger"),
    ("no_events", "no webhook events to deliver"),
    ("bad_registration", "No spec operation for POST https://example.test/hookz"),
])
async def test_webhook_trigger_is_fed_each_documented_event(monkeypatch, mutation, expected):
    doc = webhook_doc(events=mutation != "no_events")
    install(monkeypatch, "shop", webhook_node(mutation), doc, {"webhook_signature": SIGNING})
    report = await harness.run_provider("shop")
    [op] = report["operations"]
    trigger = op["trigger"]
    assert trigger["kind"] == "webhook" and trigger["signature"] == "hmac"
    found = trigger["failures"] + op["failures"]
    if expected is None:
        assert found == [] and op["passed"]
        assert trigger["registration"] == "registered"
        assert [e["outcome"] for e in trigger["events"]] == ["delivered"]
        # Registration and teardown are ordinary requests the contract checks.
        assert [r["spec_operation"] for r in op["requests"]] == ["POST /hooks", "DELETE /hooks/{id}"]
    else:
        assert any(expected in f for f in found), found
        assert not op["passed"]
    verdict = openapi_verdict(report, "/nonexistent", audit=False)
    assert verdict["triggers"] == {"on_order": "passed" if expected is None else "failed"}
    assert verdict["ready"] is (expected is None)


async def test_signature_must_be_declared_or_the_node_must_take_unsigned_deliveries(monkeypatch):
    install(monkeypatch, "shop", webhook_node(), webhook_doc(), {})
    [op] = (await harness.run_provider("shop"))["operations"]
    assert any("declares no webhook_signature" in f for f in op["trigger"]["failures"])
    install(monkeypatch, "shop", webhook_node(), webhook_doc(), {"webhook_signature": {"header": "X-Sig"}})
    [op] = (await harness.run_provider("shop"))["operations"]
    assert op["fixture_errors"] == ["FixtureError: webhook_signature needs the docs page that describes it (source)"]


async def test_documented_events_stand_in_for_a_contract_without_webhooks(monkeypatch):
    events = {"order.created": {"body": ORDER, "source": SOURCE}}
    install(monkeypatch, "shop", webhook_node("reads_unknown"), webhook_doc(events=False),
            {"webhook_signature": SIGNING}, events=events)
    [op] = (await harness.run_provider("shop"))["operations"]
    # With no schema, the documented example's own keys are the event's fields.
    assert op["trigger"]["events"][0]["source"] == "docs"
    assert op["trigger"]["failures"] == [
        "order.created: reads data.customer, which the order.created event schema doesn't have"]


def test_sign_follows_the_declared_scheme():
    body = b'{"a": 1}'
    headers = triggers.sign(SIGNING, body, "s3cret")
    t, v1 = headers["x-sig"].split(",")
    expected = hmac.new(b"s3cret", t[2:].encode() + b"." + body, hashlib.sha256).hexdigest()
    assert v1 == "v1=" + expected
    svix = {"header": "svix-signature", "algorithm": "sha256", "encoding": "base64", "format": "v1,{signature}",
            "message": "{id}.{timestamp}.{body}", "timestamp_header": "svix-timestamp", "id_header": "svix-id",
            "secret_encoding": "base64", "secret_prefix": "whsec_", "source": SOURCE}
    secret = triggers.secret_value(svix)
    assert secret.startswith("whsec_")
    headers = triggers.sign(svix, body, secret)
    assert headers["svix-id"] == triggers.EVENT_ID and headers["svix-signature"].startswith("v1,")


TASKS = {"results": [{"id": "t1", "content": "Write the report"}], "next_cursor": None}


def poll_doc():
    item = {"type": "object", "properties": {"id": {"type": "string"}, "content": {"type": "string"}}}
    return {
        "openapi": "3.1.0",
        "info": {"title": "Tasks", "version": "1"},
        "servers": [{"url": "https://example.test"}],
        "paths": {"/tasks": {"get": {"responses": {"200": {"description": "ok", "content": {"application/json": {
            "schema": {"type": "object", "properties": {
                "results": {"type": "array", "items": item}, "next_cursor": {"type": ["string", "null"]}}},
            "example": TASKS}}}}}}},
    }


def poll_node(mutation=None):
    class OnNewTask(PollTriggerConfigBase):
        model_config = ConfigDict(json_schema_extra={"x-is-trigger": True, "x-requires-webhook": True})
        operation: Literal["on_new_task"]

    class Config(BaseModel):
        config: Annotated[Union[OnNewTask], Field(discriminator="operation")]
        credentials: Key

    class Tasks(ScheduledPollTriggerMixin, WorkflowNode):
        get_config_model = staticmethod(lambda: Config)

        @classmethod
        def resolve_agent_event(cls, output):
            tasks = output.get("tasks") or []
            if not tasks:
                return None
            label = "title" if mutation == "reads_unknown" else "content"
            return {"text": "\n".join(f"- {t.get(label)}" for t in tasks), "conversation_key": None}

        async def execute(self, inputs):
            async with httpx.AsyncClient() as client:
                data = (await client.get("https://example.test/tasks")).json()
            key = "uid" if mutation == "bad_id" else "id"
            fresh = await self._filter_unseen(data.get("results") or [], lambda t: t.get(key))
            return {"tasks": fresh, "new_task_count": len(fresh)}

    return Tasks


@pytest.mark.parametrize("mutation, expected", [
    (None, None),
    ("reads_unknown", "reads results[].title, which the GET /tasks response schema doesn't have"),
    ("bad_id", "found no new item in the listed response"),
])
async def test_poll_trigger_runs_new_item_detection_on_its_list_response(monkeypatch, mutation, expected):
    install(monkeypatch, "tasks", poll_node(mutation), poll_doc(), {})
    report = await harness.run_provider("tasks")
    [op] = report["operations"]
    assert op["requests"][0]["spec_operation"] == "GET /tasks"
    assert op["requests"][0]["response_source"] == "spec_example"
    trigger = op["trigger"]
    if expected is None:
        assert trigger["failures"] == [] and trigger["emitted"] == 1 and op["passed"]
    else:
        assert any(expected in f for f in trigger["failures"]), trigger["failures"]
        assert not op["passed"]
    verdict = openapi_verdict(report, "/nonexistent", audit=False)
    assert verdict["triggers"] == {"on_new_task": "passed" if expected is None else "failed"}


def test_reads_count_only_the_nodes_own_code():
    reads = triggers.Reads(frozenset({HERE}))
    payload = triggers.track({"a": {"b": 1}}, {}, {"type": "object", "properties": {"a": {
        "type": "object", "properties": {"b": {"type": "integer"}}}}}, reads, "x event")
    assert payload["a"].get("b") == 1 and payload.get("_webhook") is None
    payload.get("missing")
    assert reads.unknown == {"missing": "x event"}
    # Plumbing outside the node (the default agent event's envelope unwrapping) never counts.
    from nodes.core.agent_events import default_agent_event
    default_agent_event(payload)
    assert reads.unknown == {"missing": "x event"}
    assert copy.deepcopy(payload) == {"a": {"b": 1}} and type(copy.deepcopy(payload)) is dict


def test_a_trigger_outside_both_families_stays_a_passthrough():
    report = {"provider": "p", "operations": [{"operation": "on_message", "skipped": "trigger passthrough"}]}
    verdict = openapi_verdict(report, "/nonexistent", audit=False)
    assert verdict["triggers"] == {"on_message": "not checked: not a webhook or poll trigger"}
    plain = openapi_verdict({"provider": "p", "operations": []}, "/nonexistent", audit=False)
    assert "triggers" not in plain


async def test_a_documented_payload_vouches_for_fields_its_schema_leaves_out(monkeypatch):
    # Clover's published list schemas omit fields its documented responses carry: reading those is no defect.
    doc = poll_doc()
    item = doc["paths"]["/tasks"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["properties"]["results"]["items"]
    del item["properties"]["content"]
    install(monkeypatch, "tasks", poll_node(), doc, {})
    [op] = (await harness.run_provider("tasks"))["operations"]
    assert op["trigger"]["failures"] == [] and op["passed"]
    install(monkeypatch, "tasks", poll_node("reads_unknown"), doc, {})
    [op] = (await harness.run_provider("tasks"))["operations"]
    assert op["trigger"]["failures"] == [
        "reads results[].title, which the GET /tasks response schema doesn't have"]


async def test_a_trigger_that_never_runs_is_still_reported_failed(monkeypatch):
    install(monkeypatch, "tasks", poll_node(), poll_doc(), {})
    monkeypatch.setattr(harness, "INPUTS", {"on_new_task": {"config": {"schedule": "every so often"},
                                                            "source": SOURCE}})
    report = await harness.run_provider("tasks")
    [op] = report["operations"]
    assert op["trigger"]["kind"] == "poll" and op["fixture_errors"]
    assert openapi_verdict(report, "/nonexistent", audit=False)["triggers"] == {"on_new_task": "failed"}
