"""Auto-answering a resource pick that has only one possible answer.

Every question asked before an agent has done anything lowers the odds it ever
runs, and "choose from this list of one" is the emptiest of them. The schema
stamps ``auto_select_sole_option`` onto required independent pickers so the
frontend fills them silently when the account has exactly one candidate.

The value of this feature is entirely in its limits. Filling a field with the
only possible value takes nothing away; filling one with an ARBITRARY value
silently attaches an agent to the wrong channel, which is far worse than asking.
These tests pin the limits, not the feature.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nodes.core.registry import NODE_REGISTRY

# Read the GENERATED schema files rather than calling get_config_schema(): those
# files are what the frontend renders from, and several nodes (Zendesk, Discord,
# PagerDuty, Google Translate) add pickers in their own get_config_schema
# override, after the base pass has run. Testing the live call would have passed
# while the artifact users actually see was missing 74 fields.
SCHEMA_DIR = Path(__file__).resolve().parents[2] / "frontend/app/schemas/nodes"


def _dynamic_fields(node_cls):
    """Every (config class, field, x-dynamic-options, required) in a node."""
    for node_type, cls in NODE_REGISTRY.items():
        if cls is node_cls:
            path = SCHEMA_DIR / f"{node_type.replace('automation-', '')}.json"
            break
    else:
        return
    if not path.exists():
        return
    schema = json.loads(path.read_text())
    for defn_name, defn in (schema.get("$defs", {}) or {}).items():
        if not isinstance(defn, dict):
            continue
        required = set(defn.get("required") or [])
        for field, spec in (defn.get("properties", {}) or {}).items():
            dyn = spec.get("x-dynamic-options") if isinstance(spec, dict) else None
            if isinstance(dyn, dict):
                yield defn_name, field, dyn, field in required


ALL_NODES = sorted(NODE_REGISTRY.items())


@pytest.mark.parametrize("node_type,node_cls", ALL_NODES)
def test_sole_option_autofill_never_lands_on_a_dependent_field(node_type, node_cls):
    """A dependent field has nothing to resolve until its parent is chosen.

    Auto-filling a Sheets tab before a spreadsheet exists would either fill from
    an empty list or fill from the WRONG spreadsheet's tabs.
    """
    offenders = [
        f"{defn}.{field}"
        for defn, field, dyn, _ in _dynamic_fields(node_cls)
        if dyn.get("auto_select_sole_option") and dyn.get("depends_on")
    ]
    assert not offenders, (
        f"{node_type}: these depend on another field but are marked for "
        f"sole-option autofill: {offenders}. They cannot be resolved before "
        f"their parent is set."
    )


@pytest.mark.parametrize("node_type,node_cls", ALL_NODES)
def test_sole_option_autofill_never_lands_on_an_optional_field(node_type, node_cls):
    """An empty optional field MEANS something; a required one does not.

    Leaving an optional filter blank says "no filter". Auto-filling it with the
    account's only project silently narrows what the node does, and nobody asked
    for that. A required field has to be answered regardless, so answering it
    with the only possible value costs the user nothing.
    """
    offenders = [
        f"{defn}.{field}"
        for defn, field, dyn, required in _dynamic_fields(node_cls)
        if dyn.get("auto_select_sole_option") and not required
    ]
    assert not offenders, (
        f"{node_type}: these are optional but marked for sole-option autofill: "
        f"{offenders}. Auto-filling an optional field changes behaviour the user "
        f"did not ask for."
    )


@pytest.mark.parametrize("node_type,node_cls", ALL_NODES)
def test_every_required_independent_picker_auto_answers(node_type, node_cls):
    """The whole catalogue gets this, including nodes nobody has written yet.

    Stamped centrally in `_mark_sole_option_autofill` rather than declared per
    field, so a new node cannot ship without it and no backfill can go stale.
    """
    missing = [
        f"{defn}.{field}"
        for defn, field, dyn, required in _dynamic_fields(node_cls)
        if required and not dyn.get("depends_on") and not dyn.get("auto_select_sole_option")
    ]
    assert not missing, (
        f"{node_type}: required independent pickers not marked for sole-option "
        f"autofill: {missing}. This is stamped automatically — if it is absent, "
        f"the central pass in nodes/core/base.py has regressed."
    )


def test_the_catalogue_actually_benefits():
    """A guard that silently stops applying is the failure mode to fear here."""
    stamped = sum(
        1
        for _, node_cls in ALL_NODES
        for _, _, dyn, _ in _dynamic_fields(node_cls)
        if dyn.get("auto_select_sole_option")
    )
    assert stamped > 1000, (
        f"only {stamped} fields carry sole-option autofill; the central stamping "
        f"pass has probably stopped matching."
    )
