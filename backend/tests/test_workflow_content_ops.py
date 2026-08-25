"""Builder-authored workflow content: define_variable / add_test_run / run_test.

The first DSL ops that write OUTSIDE the graph blob (workflows.settings).
Pure parsing/merging lives in workflow_ops; the agentic executor dispatches
the DB write through PlatformOps. These tests pin the tag registrations, the
parse/merge semantics (including the FE authoring-shape contract), and the
executor's validation — a test run may only be authored for a trigger that
can actually stage (wired to an agent, not provider-wired).
"""

import pytest

from coder.workflow.workflow_ops import (
    append_rehearsal_run,
    parse_add_test_run,
    parse_define_variable,
    upsert_variable_definitions,
)
from coder.workflow.workflow_xml import ALL_TAGS, _BODY_TAGS, parse_xml


# ---------------------------------------------------------------------------
# Tag registration — miss one set and the op is silently invisible/rejected
# ---------------------------------------------------------------------------

def test_tags_registered_in_every_vocabulary():
    from coder.workflow.agentic.commands import AGENTIC_TAGS, WORKFLOW_CONTENT_TAGS
    from mcp_server import _UPDATE_WORKFLOW_TAGS

    for tag in ("define_variable", "add_test_run", "run_test"):
        assert tag in ALL_TAGS, f"{tag} missing from the parser vocabulary"
        assert tag in AGENTIC_TAGS, f"{tag} missing from the brain whitelist"
        assert tag in _UPDATE_WORKFLOW_TAGS, f"{tag} rejected by MCP update_workflow"
    assert WORKFLOW_CONTENT_TAGS == {"define_variable", "add_test_run"}
    # Body-bearing: value / staged message body. run_test is attribute-only.
    assert "define_variable" in _BODY_TAGS and "add_test_run" in _BODY_TAGS
    assert "run_test" not in _BODY_TAGS


def test_body_tag_with_bare_attribute_parses():
    """Regression: _BODY_TAG_PATTERN only accepted key="value" attrs, so the
    bare `per_user` broke the body match and the recovery path swallowed the
    closing tag into the value."""
    ops = parse_xml(
        '<define_variable name="repo" per_user>octo/repo</define_variable>'
    )
    assert len(ops) == 1
    assert ops[0].body == "octo/repo"
    assert ops[0].attrs.get("per_user") == ""


# ---------------------------------------------------------------------------
# define_variable parsing + merge
# ---------------------------------------------------------------------------

def _op(xml: str):
    ops = parse_xml(xml)
    assert len(ops) == 1, ops
    return ops[0]


def test_parse_define_variable_full():
    d, err = parse_define_variable(
        _op('<define_variable name="site_url" description="Site to watch" per_user>https://acme.dev</define_variable>')
    )
    assert err is None
    assert d == {
        "name": "site_url",
        "value": "https://acme.dev",
        "description": "Site to watch",
        "per_user": True,
    }


def test_parse_define_variable_declaration_only():
    d, err = parse_define_variable(_op('<define_variable name="tone"></define_variable>'))
    assert err is None
    assert d == {"name": "tone", "value": ""}


def test_parse_define_variable_rejects_unbindable_names():
    # The FE binding regex is a full-string {{vars.<name>}} match — a name it
    # cannot express must be refused at write time.
    for bad in ("has space", "9starts-with-digit", "dot.ted", ""):
        d, err = parse_define_variable(_op(f'<define_variable name="{bad}">v</define_variable>'))
        assert d is None and err, bad


def test_parse_define_variable_per_user_false_means_false():
    d, err = parse_define_variable(
        _op('<define_variable name="x" per_user="false">v</define_variable>')
    )
    assert err is None
    assert "per_user" not in d


def test_upsert_appends_and_replaces_by_name():
    existing = [
        {"name": "tone", "value": "friendly"},
        "garbage-row",
    ]
    merged = upsert_variable_definitions(
        existing,
        [
            {"name": "tone", "value": "formal", "per_user": True},
            {"name": "repo", "value": "octo/repo"},
        ],
    )
    assert merged[0] == {"name": "tone", "value": "formal", "per_user": True}
    assert merged[1] == "garbage-row"  # preserved untouched — dialog's problem
    assert merged[2] == {"name": "repo", "value": "octo/repo"}


def test_upsert_declaration_never_wipes_an_existing_value():
    merged = upsert_variable_definitions(
        [{"name": "repo", "value": "user/set-this"}],
        [{"name": "repo", "value": "", "per_user": True, "description": "d"}],
    )
    assert merged[0]["value"] == "user/set-this"
    assert merged[0]["per_user"] is True


# ---------------------------------------------------------------------------
# add_test_run parsing + authoring merge (FE useRehearsalAuthoring contract)
# ---------------------------------------------------------------------------

def test_parse_add_test_run_lead_composition():
    parsed, err = parse_add_test_run(
        _op('<add_test_run trigger="tg1" name="Booking inquiry" title="Rome trip" '
            'author="Casey Example" handle="+1 202 555 0100">Is the flat free?</add_test_run>')
    )
    assert err is None
    assert parsed["trigger_ref"] == "tg1"
    assert parsed["name"] == "Booking inquiry"
    assert parsed["lead"] == {
        "title": "Rome trip",
        "meta": "Casey Example",
        "body": "Is the flat free?",
        "author": "Casey Example",
        "handle": "+1 202 555 0100",
    }


def test_parse_add_test_run_requires_trigger_name_and_body():
    for xml in (
        '<add_test_run name="n">b</add_test_run>',
        '<add_test_run trigger="t">b</add_test_run>',
        '<add_test_run trigger="t" name="n"></add_test_run>',
    ):
        parsed, err = parse_add_test_run(_op(xml))
        assert parsed is None and err, xml


def test_append_rehearsal_run_matches_fe_shape():
    lead = {"title": "T", "meta": "M", "body": "B"}
    authoring, slug = append_rehearsal_run(
        {"edits": {"k": {"body": "edited"}}},  # foreign keys survive
        "automation-telegram", "Booking inquiry", lead, "sales-inbound-lead",
    )
    assert slug == "booking-inquiry"
    assert authoring["runs"]["automation-telegram"] == [
        {"slug": "booking-inquiry", "backendKey": "sales-inbound-lead", "lead": lead}
    ]
    assert authoring["names"]["automation-telegram:booking-inquiry"] == "Booking inquiry"
    assert authoring["edits"] == {"k": {"body": "edited"}}


def test_append_rehearsal_run_replaces_same_name_and_dedupes_slugs():
    a1, s1 = append_rehearsal_run(None, "t", "Run", {"title": "1", "meta": "m", "body": "b"}, "k")
    # Same name → replaced in place, not stacked (builder re-runs are common).
    a2, s2 = append_rehearsal_run(a1, "t", "Run", {"title": "2", "meta": "m", "body": "b"}, "k")
    assert s1 == s2 == "run"
    assert len(a2["runs"]["t"]) == 1
    assert a2["runs"]["t"][0]["lead"]["title"] == "2"
    # Different name colliding on slug → suffixed.
    a3, s3 = append_rehearsal_run(a2, "t", "run", {"title": "3", "meta": "m", "body": "b"}, "k")
    assert s3 == "run-2" and len(a3["runs"]["t"]) == 2


def test_base_scenario_key_for_type():
    from nodes.agent.rehearsal_scenarios import (
        GENERIC_KEY_PREFIX,
        SCENARIO_TRIGGER_NODE_TYPES,
        base_scenario_key_for_type,
    )
    key = base_scenario_key_for_type("automation-gmail")
    assert SCENARIO_TRIGGER_NODE_TYPES.get(key) == "automation-gmail"
    assert base_scenario_key_for_type("automation-cal-com") == (
        f"{GENERIC_KEY_PREFIX}automation-cal-com"
    )


# ---------------------------------------------------------------------------
# Agentic executor — validation + PlatformOps dispatch
# ---------------------------------------------------------------------------

class _FakePlatform:
    def __init__(self):
        self.defined = None
        self.runs = []

    async def upsert_variable_definitions(self, definitions):
        self.defined = definitions
        return {"success": True}

    async def add_rehearsal_run(self, node_type, name, lead, base_key):
        self.runs.append((node_type, name, lead, base_key))
        return {"success": True, "slug": "authored-slug"}


def _graph_with_stageable_trigger():
    from coder.workflow.graph_state import GraphState

    gs = GraphState()
    gs.add_node("tg1", "automation-telegram", "Telegram")
    gs.add_node("agent_1", "agent", "Agent")
    gs.add_edge("tg1", "agent_1")
    return gs


@pytest.mark.asyncio
async def test_executor_defines_variables_and_mirrors_into_snapshot():
    from coder.workflow.agentic.commands import execute_workflow_content_ops

    gs = _graph_with_stageable_trigger()
    platform = _FakePlatform()
    ops = parse_xml(
        '<define_variable name="repo" description="d" per_user>octo/repo</define_variable>'
    )
    results, authored = await execute_workflow_content_ops(ops, platform, gs)
    assert platform.defined and platform.defined[0]["name"] == "repo"
    assert authored == []
    assert any("Defined variable 'repo'" in r for r in results)
    # The snapshot mirror makes later turns see the declaration.
    assert gs.variable_definitions[0]["name"] == "repo"
    assert '<variable name="repo"' in gs.to_xml()


@pytest.mark.asyncio
async def test_executor_authors_run_for_stageable_trigger_only():
    from coder.workflow.agentic.commands import execute_workflow_content_ops

    gs = _graph_with_stageable_trigger()
    platform = _FakePlatform()
    ops = parse_xml(
        '<add_test_run trigger="tg1" name="Ping" title="t">hello</add_test_run>'
    )
    results, authored = await execute_workflow_content_ops(ops, platform, gs)
    assert authored == [
        {"node_type": "automation-telegram", "name": "Ping", "slug": "authored-slug"}
    ]
    node_type, name, lead, base_key = platform.runs[0]
    assert node_type == "automation-telegram" and name == "Ping"
    assert lead["body"] == "hello"

    # An unknown node and a non-stageable one both refuse loudly.
    for ref in ("nope", "agent_1"):
        results, authored = await execute_workflow_content_ops(
            parse_xml(f'<add_test_run trigger="{ref}" name="N">b</add_test_run>'),
            platform, gs,
        )
        assert authored == []
        assert results and results[0].startswith("ERROR"), (ref, results)


@pytest.mark.asyncio
async def test_executor_surfaces_platform_errors():
    from coder.workflow.agentic.commands import execute_workflow_content_ops

    class _Failing(_FakePlatform):
        async def upsert_variable_definitions(self, definitions):
            return {"error": "Only the workflow owner can change workflow settings"}

    gs = _graph_with_stageable_trigger()
    results, _ = await execute_workflow_content_ops(
        parse_xml('<define_variable name="x">v</define_variable>'), _Failing(), gs,
    )
    assert results == [
        "ERROR: define_variable — Only the workflow owner can change workflow settings"
    ]
    assert gs.variable_definitions == []  # mirror untouched on failure
