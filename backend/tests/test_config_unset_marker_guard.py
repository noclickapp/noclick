"""Registry-wide guard: no node config field can crash on an unset marker.

The runtime cleans "" → None before parsing, and `runtime_config_view` drops
markers that a DEFAULTED field rejects (falling back to the default). This
walks every registered node's operation models and probes each such field
with both markers, asserting the runtime view leaves nothing the field's
annotation would reject — the Gmail validation cc="" incident class is
structurally impossible for every current and future node (a new node with a
crashable field fails this test the day it's added).
"""
from __future__ import annotations

from pydantic import TypeAdapter

from nodes.core.base import (
    _config_target_and_members,
    _rejected_unset_fields,
    runtime_config_view,
)
from nodes.core.registry import NODE_REGISTRY

_ABSENT = object()


def _member_models(node_class):
    model = node_class.get_config_model()
    if model is None:
        return []
    # {'config': {}} routes resolution to the inner operation union for
    # NodeConfig wrappers; flat models resolve to themselves.
    _, members = _config_target_and_members({"config": {}}, model)
    return members


def test_no_defaulted_field_crashes_on_unset_markers():
    checked = 0
    offenders = []
    for node_type, node_class in sorted(NODE_REGISTRY.items()):
        try:
            members = _member_models(node_class)
        except Exception:
            continue
        for member in members:
            rejects_none, rejects_empty = _rejected_unset_fields(member)
            for marker, fields in ((None, rejects_none), ("", rejects_empty)):
                for name in fields:
                    probe = {name: marker}
                    op_field = member.model_fields.get("operation")
                    if op_field is not None:
                        probe["operation"] = op_field.default
                    viewed = runtime_config_view(probe, member)
                    survived = viewed.get(name, _ABSENT)
                    if survived is not _ABSENT:
                        try:
                            TypeAdapter(member.model_fields[name].annotation).validate_python(survived)
                        except Exception:
                            offenders.append(f"{node_type} {member.__name__}.{name} = {survived!r}")
                    checked += 1
    assert not offenders, f"{len(offenders)} fields still crash on unset markers: {offenders[:10]}"
    # Census 2026-07-29 found ~2.9k such fields — a collapse in this count
    # means the walk broke, not that the problem vanished.
    assert checked > 2000, f"guard only probed {checked} fields — member resolution broke?"
