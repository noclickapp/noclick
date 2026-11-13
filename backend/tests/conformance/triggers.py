"""Trigger checks: a webhook trigger is fed every event its contract documents, a poll trigger's new-item detection its
list response, and both go on through resolve_agent_event. Every field the node's own code reads from an event or a
listed item must be one the event's or response's schema has.

Events come from the spec's `webhooks` (OpenAPI 3.1) and operations' `callbacks`, and from the catalog's optional
events.json for a contract that documents none. A delivery is signed the way the provider's docs describe, declared as
the catalog entry's `webhook_signature` (or the spec's root `x-webhook-signature`), with the docs page as its source.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import os
import re
import sys
import time
import typing
from functools import lru_cache
from pathlib import Path

FAKE_SECRET = "conformance-webhook-secret"
WEBHOOK_URL = "https://conformance.hooks.example.test/webhook/conformance"
EVENT_ID = "conformance-event-1"
ALGORITHMS = {"sha1", "sha256", "sha512"}
ENCODINGS = {"hex", "base64"}
PLACEHOLDER = re.compile(rb"\{(body|timestamp|id|url)\}")
NODES = Path(__file__).resolve().parents[2] / "nodes"
SHARED = (NODES / "core", NODES / "agent")


def _harness():
    from tests.conformance import harness
    return harness


# --- what the node's own code reads -------------------------------------------------------------------------------

@lru_cache(maxsize=4096)
def _real(path):
    return os.path.realpath(path)


def node_files(node_cls):
    """Source files whose reads count: the node's module, its package (a node in its own folder) and the provider's
    own base classes. Shared plumbing (nodes/core, nodes/agent: the default agent event's envelope unwrapping) never
    counts."""
    files = set()
    for klass in node_cls.__mro__:
        module = sys.modules.get(klass.__module__)
        path = getattr(module, "__file__", None)
        if not path:
            continue
        real = Path(_real(path))
        if NODES not in real.parents or any(s == real.parent or s in real.parents for s in SHARED):
            continue
        files.add(str(real))
        if real.parent != NODES:
            files.update(str(Path(_real(str(p)))) for p in real.parent.rglob("*.py"))
    return frozenset(files)


class Reads:
    """Every key the node's own code asked of a tracked object, and those its schema doesn't have."""

    def __init__(self, files):
        self.files = files
        self.count = 0
        self.unknown = {}

    def note(self, owner, key):
        caller = sys._getframe(2).f_code.co_filename
        if caller not in self.files and _real(caller) not in self.files:
            return
        self.count += 1
        allowed = owner._allowed
        if allowed is None or key in allowed or (isinstance(key, str) and key.startswith("_")):
            return
        self.unknown.setdefault(f"{owner._path}.{key}" if owner._path else str(key), owner._label)


class TrackedDict(dict):
    """A dict that tells Reads what is read from it; copies are plain dicts."""

    __slots__ = ("_reads", "_allowed", "_path", "_label")

    def get(self, key, default=None):
        self._reads.note(self, key)
        return dict.get(self, key, default)

    def __getitem__(self, key):
        self._reads.note(self, key)
        return dict.__getitem__(self, key)

    def __copy__(self):
        return dict(self)

    def __deepcopy__(self, memo):
        return copy.deepcopy(dict(self), memo)

    def __reduce__(self):
        return dict, (dict(self),)


def _members(doc, schema, depth=0):
    """The schema and every allOf/anyOf/oneOf member under it, resolved."""
    resolve = _harness().resolve
    try:
        schema = resolve(doc, schema) if isinstance(schema, dict) else {}
    except Exception:
        return []
    if not isinstance(schema, dict) or depth > 20:
        return []
    found = [schema]
    for key in ("allOf", "anyOf", "oneOf"):
        for member in schema.get(key) or []:
            found += _members(doc, member, depth + 1)
    return found


def shape(doc, schema):
    """(allowed keys, or None when the schema names none or takes any key; key -> its schema)."""
    props, extra, open_ = {}, None, False
    for member in _members(doc, schema):
        props.update(member.get("properties") or {})
        additional = member.get("additionalProperties")
        if isinstance(additional, dict) and additional:
            extra = additional
        if member.get("patternProperties"):
            open_ = True
    allowed = None if (open_ or extra is not None or not props) else frozenset(props)
    return allowed, (lambda key: props.get(key) or extra or {})


def items_of(doc, schema):
    for member in _members(doc, schema):
        if isinstance(member.get("items"), dict):
            return member["items"]
    return {}


def track(value, doc, schema, reads, label, path="", authored=False):
    """Track reads of `value` against `schema`. A provider-authored value (the docs' or spec's own example) also
    vouches for the fields it shows: a published schema that leaves out what the provider's documented payload carries
    (Clover's list responses) never blames a node for reading it."""
    if isinstance(value, dict):
        allowed, child = shape(doc, schema)
        if allowed is not None and authored:
            allowed = allowed | frozenset(value)
        out = TrackedDict()
        for key, item in value.items():
            dict.__setitem__(out, key, track(item, doc, child(key), reads, label,
                                             f"{path}.{key}" if path else str(key), authored))
        out._reads, out._allowed, out._path, out._label = reads, allowed, path, label
        return out
    if isinstance(value, list):
        item_schema = items_of(doc, schema)
        return [track(item, doc, item_schema, reads, label, f"{path}[]", authored) for item in value]
    return value


def example_schema(value):
    """A documented example with no schema in the contract: its own keys are the event's fields."""
    if isinstance(value, dict):
        return {"type": "object", "properties": {k: example_schema(v) for k, v in value.items()}}
    if isinstance(value, list):
        return {"type": "array", "items": example_schema(value[0]) if value else {}}
    return {}


def track_response(response, reads, label, source=None):
    """Hand the node tracked JSON from a response the contract answered with (its schema rides the response; a Postman
    saved example has none, so its own fields are the response's)."""
    doc, schema = response.extensions.get("conformance_schema") or ({}, {"type": "object"})
    authored = source in ("docs", "spec_example", "postman_example")
    original = response.json

    def tracked_json(**kwargs):
        return track(original(**kwargs), doc, schema, reads, label, authored=authored)

    response.json = tracked_json


# --- the events a contract documents ------------------------------------------------------------------------------

def _json_media(content):
    return sorted(content, key=lambda m: not (m == "application/json" or m.endswith("+json")))


def _header_example(doc, parameter):
    resolve = _harness().resolve
    parameter = resolve(doc, parameter)
    if parameter.get("in") != "header":
        return None
    schema = resolve(doc, parameter.get("schema") or {})
    for value in (parameter.get("example"), schema.get("const"), schema.get("example"), schema.get("default")):
        if isinstance(value, (str, int)):
            return str(value)
    enum = schema.get("enum") or []
    return str(enum[0]) if len(enum) == 1 else None


def _path_item_events(doc, name, item, where):
    harness = _harness()
    item = harness.resolve(doc, item)
    events = []
    for method in ("post", "put"):
        operation = item.get(method)
        if not isinstance(operation, dict):
            continue
        operation = harness.resolve(doc, operation)
        headers = {}
        for parameter in (item.get("parameters") or []) + (operation.get("parameters") or []):
            value = _header_example(doc, parameter)
            if value is not None:
                headers[harness.resolve(doc, parameter)["name"].lower()] = value
        body = harness.resolve(doc, operation.get("requestBody") or {})
        content = body.get("content") or {}
        if not content:
            continue
        media = _json_media(content)[0]
        definition = content[media]
        schema = harness.resolve(doc, definition.get("schema") or {})
        bodies = []
        if "example" in definition:
            bodies.append(("spec_example", definition["example"]))
        for example in (definition.get("examples") or {}).values():
            example = harness.resolve(doc, example)
            if "value" in example:
                bodies.append(("spec_example", example["value"]))
        if not bodies and "example" in schema:
            bodies.append(("spec_example", schema["example"]))
        if not bodies:
            for example in schema.get("examples") or []:
                bodies.append(("spec_example", example))
        if not bodies:
            try:
                bodies.append(("generated", harness.sample(doc, schema, examples=True, full=True)))
            except Exception as exc:
                events.append({"name": name, "where": where, "error": "cannot generate a payload: " + harness.reason(exc)})
                continue
        for source, value in bodies:
            events.append({"name": name, "where": where, "source": source, "body": value, "headers": dict(headers),
                           "doc": doc, "schema": schema})
    return events


def contract_events(contracts, documented):
    """Every event the contracts document (webhooks, callbacks), then the catalog's documented ones (events.json)."""
    harness = _harness()
    events, schemas = [], {}
    for contract in contracts:
        doc = getattr(contract, "doc", None)
        if not isinstance(doc, dict) or harness.is_postman(doc):
            continue
        for name, item in (doc.get("webhooks") or {}).items():
            found = _path_item_events(doc, name, item, f"webhooks.{name}")
            events += found
            for event in found:
                schemas.setdefault(name, (doc, event.get("schema")))
        for path, item in (doc.get("paths") or {}).items():
            item = harness.resolve(doc, item)
            for method, operation in item.items():
                if method not in harness.METHODS or not isinstance(operation, dict):
                    continue
                for callback, expressions in (operation.get("callbacks") or {}).items():
                    expressions = harness.resolve(doc, expressions)
                    for expression, callback_item in expressions.items():
                        found = _path_item_events(doc, callback, callback_item,
                                                  f"callbacks.{callback} of {method.upper()} {path}")
                        events += found
                        for event in found:
                            schemas.setdefault(callback, (doc, event.get("schema")))
    for name, entry in (documented or {}).items():
        webhook = entry.get("webhook", name)
        doc, schema = schemas.get(webhook, ({}, None))
        if schema is None:
            doc, schema = {}, example_schema(entry.get("body"))
        events.append({"name": name, "where": "events.json", "source": "docs", "url": entry.get("source"),
                       "body": entry.get("body"), "headers": {k.lower(): str(v) for k, v in (entry.get("headers") or {}).items()},
                       "doc": doc, "schema": schema})
    return events


# --- signing a delivery as the provider's docs describe -----------------------------------------------------------

def signing_of(entry, contracts):
    """The catalog's (or spec's) declared signature scheme, checked; None when neither declares one."""
    harness = _harness()
    declared = entry.get("webhook_signature")
    origin = "manifest"
    if declared is None:
        for contract in contracts:
            doc = getattr(contract, "doc", None)
            if isinstance(doc, dict) and isinstance(doc.get("x-webhook-signature"), dict):
                declared, origin = doc["x-webhook-signature"], "spec"
                break
    if declared is None:
        return None
    if not isinstance(declared, dict):
        raise harness.FixtureError("webhook_signature must be an object")
    source = declared.get("source") or (declared.get("x-source") or {}).get("url")
    if not isinstance(source, str) or not source.startswith(("https://", "http://")):
        raise harness.FixtureError("webhook_signature needs the docs page that describes it (source)")
    scheme = declared.get("scheme", "hmac")
    if scheme == "hmac":
        if declared.get("algorithm") not in ALGORITHMS:
            raise harness.FixtureError(f"webhook_signature algorithm must be one of {sorted(ALGORITHMS)}")
        if declared.get("encoding", "hex") not in ENCODINGS:
            raise harness.FixtureError(f"webhook_signature encoding must be one of {sorted(ENCODINGS)}")
        if not isinstance(declared.get("header"), str) or not declared["header"]:
            raise harness.FixtureError("webhook_signature needs the header that carries the signature")
        if declared.get("secret_encoding", "utf-8") not in ("utf-8", "base64"):
            raise harness.FixtureError("webhook_signature secret_encoding must be utf-8 or base64")
    elif scheme == "unsupported":
        if not declared.get("reason"):
            raise harness.FixtureError("an unsupported webhook_signature needs its reason (e.g. RSA with the provider's key)")
    elif scheme != "none":
        raise harness.FixtureError("webhook_signature scheme must be hmac, none or unsupported")
    return {**declared, "scheme": scheme, "source": source, "origin": origin}


def secret_value(signing):
    """The secret the node holds, as the provider hands it out (e.g. Svix's whsec_ + base64)."""
    if signing and signing.get("secret_encoding") == "base64":
        return signing.get("secret_prefix", "") + base64.b64encode(FAKE_SECRET.encode()).decode()
    return FAKE_SECRET


def sign(signing, body, secret, url=WEBHOOK_URL):
    """The headers a provider sends with `body`, signed with `secret` per the declared scheme."""
    timestamp = str(int(time.time()))
    if signing.get("secret_encoding") == "base64":
        raw = secret[len(signing.get("secret_prefix", "")):] if secret.startswith(signing.get("secret_prefix", "")) else secret
        key = base64.b64decode(raw)
    else:
        key = secret.encode()
    values = {b"body": body, b"timestamp": timestamp.encode(), b"id": EVENT_ID.encode(), b"url": url.encode()}
    message = PLACEHOLDER.sub(lambda m: values[m.group(1)], signing.get("message", "{body}").encode())
    digest = hmac.new(key, message, getattr(hashlib, signing["algorithm"])).digest()
    signature = digest.hex() if signing.get("encoding", "hex") == "hex" else base64.b64encode(digest).decode()
    value = signing.get("format", "{signature}")
    value = value.replace("{signature}", signing.get("prefix", "") + signature)
    value = value.replace("{timestamp}", timestamp).replace("{id}", EVENT_ID)
    headers = {signing["header"].lower(): value}
    if signing.get("timestamp_header"):
        headers[signing["timestamp_header"].lower()] = timestamp
    if signing.get("id_header"):
        headers[signing["id_header"].lower()] = EVENT_ID
    return headers


# --- which family a trigger operation belongs to -----------------------------------------------------------------

def _models(annotation, seen=None):
    from pydantic import BaseModel
    seen = set() if seen is None else seen
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if annotation not in seen:
            seen.add(annotation)
            yield annotation
        return
    for arg in typing.get_args(annotation):
        yield from _models(arg, seen)


def op_config_class(model, operation):
    field = (getattr(model, "model_fields", {}) or {}).get("config")
    if field is None:
        return None
    for klass in _models(field.annotation):
        op_field = klass.model_fields.get("operation")
        if op_field is None:
            continue
        if op_field.default == operation or operation in typing.get_args(op_field.annotation):
            return klass
    return None


def _plumbing():
    from nodes.core.poll_trigger import PollTriggerConfigBase
    from nodes.core.webhook_trigger import WebhookTriggerConfigBase
    return frozenset(PollTriggerConfigBase.model_fields) | frozenset(WebhookTriggerConfigBase.model_fields) | {"webhook_url"}


PLUMBING = _plumbing()


def trigger_kind(node_cls, model, operation):
    """"poll" for a PollTriggerConfigBase operation, "webhook" for a trigger of an ExternalWebhookTriggerMixin node,
    else None (app-event subscriptions and other families stay a passthrough)."""
    from nodes.core.poll_trigger import PollTriggerConfigBase
    from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin
    klass = op_config_class(model, operation)
    if klass is not None and issubclass(klass, PollTriggerConfigBase):
        return "poll"
    if issubclass(node_cls, ExternalWebhookTriggerMixin):
        return "webhook"
    return None


# --- running them -------------------------------------------------------------------------------------------------

def agent_event_problem(event):
    if event is None:
        return None
    if not isinstance(event, dict) or not isinstance(event.get("text"), str) or not event["text"].strip():
        return f"resolve_agent_event returned {type(event).__name__} without text"
    return None


def unknown_reads(reads):
    return [f"reads {path}, which the {label} schema doesn't have" for path, label in sorted(reads.unknown.items())]


async def check_webhook(node_cls, node_type, model, raw, credential, events, signing, files):
    """Register, deliver each documented event the node's own way, unregister. Returns the trigger report."""
    harness = _harness()
    from unittest.mock import Mock
    trigger = {"kind": "webhook", "registration": None, "events": [], "failures": [], "advisory": [],
               "signature": signing["scheme"] if signing else "none declared"}
    config = {**raw, "webhook_url": WEBHOOK_URL}
    try:
        extra = await node_cls._register_external_webhook(
            webhook_url=WEBHOOK_URL, credential=dict(credential), config=dict(config), node_id="conformance")
        trigger["registration"] = "registered"
        for key in ("signing_secret", "external_webhook_id"):
            if (extra or {}).get(key) is not None:
                config[key] = extra[key]
    except NotImplementedError:
        trigger["registration"] = "registered by hand (no API registration)"
    except Exception as exc:
        trigger["registration"] = "failed"
        trigger["failures"].append("registration: " + harness.reason(exc))
    secret_field = (signing or {}).get("secret_field", "signing_secret")
    if not config.get(secret_field):
        config[secret_field] = secret_value(signing)
    secret = str(config[secret_field])
    if signing and signing["scheme"] == "unsupported":
        trigger["advisory"].append(f"signature not checkable offline: {signing['reason']}")
    if not events:
        trigger["failures"].append(
            "no webhook events to deliver: the contract has no webhooks or callbacks and the catalog no events.json")
    for event in events:
        record = {"event": event["name"], "where": event["where"], "source": event.get("source"), "outcome": None,
                  "failures": []}
        trigger["events"].append(record)
        if event.get("error"):
            record["failures"].append(event["error"])
            record["outcome"] = "not delivered"
            continue
        body = json.dumps(event["body"]).encode()
        headers = {**event["headers"], "content-type": "application/json"}
        if signing and signing["scheme"] == "hmac":
            headers.update(sign(signing, body, secret))
        try:
            if node_cls.handle_webhook_handshake(body, headers, config) is not None:
                record["outcome"] = "handshake"
                continue
            verified = node_cls.verify_webhook_signature(body, headers, config)
            if signing and signing["scheme"] == "hmac":
                if not verified:
                    record["failures"].append("verify_webhook_signature rejected it, signed as the docs describe")
                elif node_cls.verify_webhook_signature(body + b" ", headers, config):
                    record["failures"].append("verify_webhook_signature accepts it with a body its signature doesn't match")
            elif signing is None or signing["scheme"] == "none":
                if not verified:
                    record["failures"].append(
                        "verify_webhook_signature rejected it unsigned, and the catalog declares no webhook_signature "
                        "(declare the scheme the provider's docs describe)")
            if record["failures"]:
                record["outcome"] = "rejected"
                continue
            reads = Reads(files)
            payload = track(json.loads(body), event["doc"], event["schema"], reads, f"{event['name']} event",
                            authored=event.get("source") in ("spec_example", "docs"))
            payload["_webhook"] = {"id": "conformance", "method": "POST", "headers": headers, "query_params": {}}
            if await node_cls.handle_control_event(payload, config, pool=None, workflow_id=None, node_id="conformance"):
                record["outcome"] = "control event"
                continue
            if not node_cls.filter_trigger_payload(payload, config):
                record["outcome"] = "filtered out"
                continue
            if await node_cls.drop_trigger_event(payload, config):
                record["outcome"] = "dropped"
                continue
            transformed = await node_cls.transform_trigger_payload(
                payload, config, pool=None, workflow_id=None, node_id="conformance")
            if transformed is not None:
                payload = transformed
            output = node_cls.resolve_trigger_payload(payload, config)
            if output is None:
                node = node_cls(node_id="conformance", node_type=node_type,
                                node_data={"config": {**config, "_triggerPayload": payload}},
                                config=model.model_validate({"config": raw, "credentials": credential}), sio=Mock())
                output = await node.execute({})
            agent_event = node_cls.resolve_agent_event(output)
            problem = agent_event_problem(agent_event)
            if problem:
                record["failures"].append(problem)
            record["failures"] += unknown_reads(reads)
            record["reads"] = reads.count
            # A run that hands the agent nothing (a skipped run, an event for another trigger) never reached this
            # trigger: only an event that produces an agent turn counts toward "at least one event reaches it".
            record["outcome"] = "delivered" if agent_event is not None else "no agent event"
        except Exception as exc:
            record["failures"].append("run: " + harness.reason(exc))
            record["outcome"] = record["outcome"] or "errored"
    delivered = [e for e in trigger["events"] if e["outcome"] == "delivered"]
    for record in trigger["events"]:
        trigger["failures"] += [f"{record['event']}: {failure}" for failure in record["failures"]]
    if events and not delivered and not any(e["failures"] for e in trigger["events"]):
        outcomes = sorted({e["outcome"] for e in trigger["events"]})
        trigger["failures"].append(
            f"none of the {len(events)} documented events reached this trigger ({', '.join(outcomes)}); give it a "
            "documented config in inputs.json that subscribes to one")
    if config.get("external_webhook_id") or trigger["registration"] == "registered":
        try:
            await node_cls._unregister_external_webhook(credential=dict(credential), config=dict(config),
                                                       node_id="conformance")
        except NotImplementedError:
            pass
        except Exception as exc:
            trigger["failures"].append("unregistration: " + harness.reason(exc))
    return trigger


async def seen_nothing(node):
    """Seed a poll trigger's state as a poll that already ran and saw nothing, so its next poll emits every item."""
    state = {"seen_ids": []}

    async def update(mutator, *, max_retries=4, skip_result=None):
        new_state, result = mutator(dict(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result

    node._update_node_state = update


def check_poll(node_cls, node, output, reads):
    """After the poll ran on the documented list response: it found new items and an agent hears them."""
    harness = _harness()
    trigger = {"kind": "poll", "failures": [], "advisory": []}
    emitted = getattr(node, "_poll_emitted_count", None)
    trigger["emitted"] = emitted
    if emitted is None:
        trigger["failures"].append("the poll never ran new-item detection (_filter_unseen)")
    elif emitted == 0:
        trigger["failures"].append(
            "a poll that had seen nothing found no new item in the listed response (an id it can't read, or no list)")
    try:
        event = node_cls.resolve_agent_event(output)
        problem = agent_event_problem(event)
        if problem:
            trigger["failures"].append(problem)
        elif emitted and event is None:
            trigger["failures"].append(f"resolve_agent_event delivered nothing for {emitted} new item(s)")
    except Exception as exc:
        trigger["failures"].append("resolve_agent_event: " + harness.reason(exc))
    trigger["failures"] += unknown_reads(reads)
    trigger["reads"] = reads.count
    if not reads.count:
        trigger["advisory"].append("no read of the listed response was observed (parsed outside response.json())")
    return trigger
