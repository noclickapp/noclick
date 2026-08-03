"""Class-level node hooks must stay callable ON THE CLASS.

A family of ``WorkflowNode`` hooks is declared ``@classmethod`` because the
runtime has no instance when it calls them: the agent translates a fired
trigger with ``node_cls.resolve_agent_event(output)`` and the webhook receiver
authenticates a delivery with ``node_cls.verify_webhook_signature(body,
headers, config)``. An override written as a plain instance method still
imports, still type-checks, and still looks right in review — but at call time
Python binds the first real argument to ``self`` and the call dies with
``missing 1 required positional argument``.

That is not theoretical: on 2026-08-03 a PostHog ``on_rageclick`` trigger wired
into an agent killed the run with ``PostHogNode.resolve_agent_event() missing 1
required positional argument: 'output'``. Six nodes carried the same defect
(posthog, sentry, honeycomb, calendly, klaviyo, bamboohr) and
``CloudflareNode.verify_webhook_signature`` additionally took a different
arity, so every Cloudflare delivery raised inside the receiver.

The structural test walks the whole registry; the behavioural ones make the
exact call the runtime makes, so a future override can't drift in signature
without failing here.
"""

import inspect

import pytest

from nodes.core.base import WorkflowNode
from nodes.core.registry import NODE_REGISTRY

# Hooks the base declares as classmethods — the contract every override inherits.
CLASS_LEVEL_HOOKS = sorted(
    name
    for name, attr in vars(WorkflowNode).items()
    if isinstance(attr, classmethod) and not name.startswith("__")
)

REGISTERED = sorted(set(NODE_REGISTRY.values()), key=lambda c: c.__name__)


def test_base_declares_the_hooks_this_suite_guards():
    # Guards the guard: a rename that empties the list would silently pass.
    assert "resolve_agent_event" in CLASS_LEVEL_HOOKS
    assert "verify_webhook_signature" in CLASS_LEVEL_HOOKS


@pytest.mark.parametrize("node_cls", REGISTERED, ids=lambda c: c.__name__)
def test_class_level_hooks_are_bound_to_the_class(node_cls):
    """Every override of a base classmethod must itself be a classmethod with
    the base's parameter names — the runtime only ever has the class."""
    for hook in CLASS_LEVEL_HOOKS:
        own = vars(node_cls).get(hook)
        if own is None:
            continue  # inherited — the base is correct by construction
        assert isinstance(own, (classmethod, staticmethod)), (
            f"{node_cls.__name__}.{hook} is an instance method, but the runtime "
            f"calls it on the class — its first argument would bind to `self`. "
            f"Add @classmethod."
        )
        if isinstance(own, staticmethod):
            continue
        base_params = list(
            inspect.signature(getattr(WorkflowNode, hook)).parameters
        )
        params = list(inspect.signature(getattr(node_cls, hook)).parameters)
        assert params == base_params, (
            f"{node_cls.__name__}.{hook}{tuple(params)} does not match the base "
            f"hook{tuple(base_params)}; the caller passes positionally."
        )


TRIGGER_OUTPUT = {
    "status": "success",
    "action": "on_event",
    "data": {"event": "$rageclick", "distinct_id": "u1", "properties": {"$current_url": "/x"}},
}


@pytest.mark.parametrize("node_cls", REGISTERED, ids=lambda c: c.__name__)
def test_resolve_agent_event_survives_the_call_the_agent_makes(node_cls):
    """AgentNode._resolve_trigger_event calls this on the class with the fired
    trigger's output and reads ``text``/``conversation_key`` off the result."""
    event = node_cls.resolve_agent_event(TRIGGER_OUTPUT)
    if event is None:
        return  # declining to deliver is a valid answer
    assert isinstance(event, dict), f"{node_cls.__name__} returned {type(event)}"
    assert isinstance(event.get("text"), str) and event["text"], (
        f"{node_cls.__name__}.resolve_agent_event must return non-empty text"
    )
    ck = event.get("conversation_key")
    assert ck is None or isinstance(ck, str)


@pytest.mark.parametrize("node_cls", REGISTERED, ids=lambda c: c.__name__)
def test_verify_webhook_signature_survives_the_call_the_receiver_makes(node_cls):
    """_apply_trigger_node_hooks calls this on the class with (raw body,
    lowercased headers, config dict) and treats a raise as a 500."""
    verdict = node_cls.verify_webhook_signature(b"{}", {}, {})
    assert isinstance(verdict, bool), (
        f"{node_cls.__name__}.verify_webhook_signature returned {type(verdict)}"
    )
