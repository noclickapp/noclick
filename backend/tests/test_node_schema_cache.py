"""Node JSON Schema generation is cached, and the cache cannot be corrupted.

``TypeAdapter.json_schema()`` regenerates the entire document on every call.
``_cached_type_adapter`` had already removed the *core*-schema rebuild, which
made this look solved, but the JSON schema itself was still rebuilt per call,
synchronously on the event loop. Registry-wide schema generation must be
cached so a contended loop does not amplify repeated CPU work.

Caching it is only safe because callers own what they get back: node subclasses
layer edits on top of ``super().get_config_schema()`` (Slack stamps tier markers
into ``$defs``; Google Calendar *pops* a legacy operation out of the
discriminator mapping), and call sites mutate freely. These tests pin the cache
and the copy-on-read that makes it safe.
"""

from nodes.core.base import _cached_base_schema_json
from nodes.core.registry import NODE_REGISTRY


def test_schema_is_built_once_per_class():
    cls = NODE_REGISTRY["automation-slack"]

    cls.get_config_schema()  # ensure built
    before = _cached_base_schema_json.cache_info()
    for _ in range(5):
        cls.get_config_schema()
    after = _cached_base_schema_json.cache_info()

    assert after.hits - before.hits == 5, "repeated calls must hit the cache"
    assert after.misses == before.misses, "no rebuild once the class is cached"


def test_caller_mutation_does_not_leak_into_the_cache():
    cls = NODE_REGISTRY["automation-slack"]

    first = cls.get_config_schema()
    assert first["$defs"], "precondition: node has $defs"
    first["properties"]["__poison__"] = True
    first["$defs"].clear()  # nested mutation, not just top level

    second = cls.get_config_schema()
    assert "__poison__" not in second["properties"], "caller edit leaked into the cache"
    assert second["$defs"], "nested caller edit leaked into the cache"


def test_each_call_returns_an_independent_object():
    cls = NODE_REGISTRY["automation-slack"]
    a, b = cls.get_config_schema(), cls.get_config_schema()

    assert a == b, "copies must be equal"
    assert a is not b, "callers must not share one schema object"
    assert a["properties"] is not b["properties"], "copy must be deep, not shallow"


def test_subclass_override_is_applied_to_every_copy():
    # SlackNode.get_config_schema() stamps x-requires-tier into $defs on top of
    # the cached base document. It must land on every call, not just the first.
    cls = NODE_REGISTRY["automation-slack"]

    for _ in range(3):
        schema = cls.get_config_schema()
        tiered = [
            d for d in schema.get("$defs", {}).values()
            if isinstance(d, dict) and "x-requires-tier" in d
        ]
        assert tiered, "Slack tier markers missing from a cached-path schema"


def test_destructive_subclass_override_is_stable_across_calls():
    # GoogleCalendarNode *removes* a legacy operation from the discriminator
    # mapping. Applied to a shared dict this would compound; against a fresh
    # copy each call it must be identical every time.
    cls = NODE_REGISTRY["automation-google-calendar"]

    def mapping():
        config = (cls.get_config_schema().get("properties") or {}).get("config") or {}
        return (config.get("discriminator") or {}).get("mapping") or {}

    first = mapping()
    assert first, "precondition: node has a discriminator mapping"
    assert "on_event_active" not in first, "legacy op should be stripped"
    assert mapping() == first == mapping(), "override must be stable across calls"


def test_every_registered_node_still_produces_a_schema():
    # Guards the cache builder against a node whose schema now raises (which
    # would silently degrade to {} for the whole registry).
    empty = [
        key for key, cls in NODE_REGISTRY.items()
        if cls.get_config_model() and not cls.get_config_schema()
    ]
    assert not empty, f"nodes with a config model but no schema: {empty}"
