"""
Tests for agentic builder command utilities: summarize_output, has_output in
graph state, read_config value display, and graph utility functions.
"""

import pytest
from coder.workflow.agentic.commands import summarize_output
from coder.workflow.graph_state import GraphState, NodeState
from coder.workflow.workflow_ops import find_predecessors


# ============================================================================
# summarize_output
# ============================================================================

class TestSummarizeOutput:
    def test_primitives(self):
        assert summarize_output(None) == "null"
        assert summarize_output(True) == "true"
        assert summarize_output(42) == "42"
        assert summarize_output(3.14) == "3.14"

    def test_short_string(self):
        result = summarize_output("hello")
        assert result == "'hello'"

    def test_long_string_truncated(self):
        long_str = "x" * 200
        result = summarize_output(long_str)
        assert "chars" in result
        assert len(result) < 200

    def test_empty_collections(self):
        assert summarize_output([]) == "[]"
        assert summarize_output({}) == "{}"

    def test_array_shows_length_and_item_schema(self):
        result = summarize_output([{"id": 1, "name": "a"}, {"id": 2, "name": "b"}])
        assert "array[2]" in result
        assert "id" in result
        assert "name" in result

    def test_nested_object(self):
        data = {"messages": [{"id": "abc", "snippet": "hello"}], "count": 5}
        result = summarize_output(data)
        assert "messages" in result
        assert "array[1]" in result
        assert "count" in result
        assert "5" in result

    def test_max_depth_limits_recursion(self):
        deep = {"a": {"b": {"c": {"d": {"e": "deep"}}}}}
        result = summarize_output(deep, max_depth=2)
        # At depth 2, inner objects should be summarized as "object(N keys)"
        assert "object" in result

    def test_large_object_caps_keys(self):
        data = {f"key_{i}": i for i in range(30)}
        result = summarize_output(data)
        assert "+10 more keys" in result


# ============================================================================
# has_output in GraphState.to_xml
# ============================================================================

class TestHasOutputInSnapshot:
    def test_has_output_true_shows_in_xml(self):
        state = GraphState()
        node = NodeState(id="n1", type="automation-gmail", label="Gmail", goal="read",
                         has_output=True)
        state.nodes["n1"] = node
        xml = state.to_xml()
        assert 'has_output="true"' in xml

    def test_has_output_false_omitted_from_xml(self):
        state = GraphState()
        node = NodeState(id="n1", type="automation-gmail", label="Gmail", goal="read",
                         has_output=False)
        state.nodes["n1"] = node
        xml = state.to_xml()
        assert "has_output" not in xml


# ============================================================================
# read_config shows actual values
# ============================================================================

class TestReadConfig:
    def test_shows_actual_values(self):
        from coder.workflow.agentic.commands import execute_read_config
        from coder.workflow.workflow_xml import XmlOp

        state = GraphState()
        node = NodeState(id="n1", type="automation-slack", label="Slack", goal="send",
                         config={"channel": "#general", "message": "hello world"})
        state.nodes["n1"] = node

        ops = [XmlOp(tag="read_config", attrs={"node": "n1"}, body=None)]
        results = execute_read_config(ops, state)
        result_text = results[0]
        assert "#general" in result_text
        assert "hello world" in result_text
        # Should NOT show "chars" for short values
        assert "chars" not in result_text

    def test_long_values_truncated_with_hint(self):
        from coder.workflow.agentic.commands import execute_read_config
        from coder.workflow.workflow_xml import XmlOp

        state = GraphState()
        long_val = "x" * 300
        node = NodeState(id="n1", type="automation-slack", label="Slack", goal="send",
                         config={"jsx_source": long_val})
        state.nodes["n1"] = node

        ops = [XmlOp(tag="read_config", attrs={"node": "n1"}, body=None)]
        results = execute_read_config(ops, state)
        result_text = results[0]
        assert "chars" in result_text
        assert 'field="jsx_source"' in result_text


# ============================================================================
# Patch mode in field ops
# ============================================================================

class TestFieldOpsPatch:
    def test_patch_applies_diff(self):
        from coder.workflow.agentic.commands import execute_field_ops
        from coder.workflow.workflow_xml import XmlOp

        state = GraphState()
        node = NodeState(id="n1", type="automation-slack", label="Slack", goal="send",
                         config={"jsx_source": "line1\nline2\nline3\n"})
        state.nodes["n1"] = node

        patch = "@@ line1\n line1\n-line2\n+replaced\n"
        ops = [XmlOp(tag="field", attrs={"node": "n1", "name": "jsx_source"}, body=patch)]
        results = execute_field_ops(ops, state)
        assert "Patched" in results[0]
        assert "replaced" in node.config["jsx_source"]
        assert "line2" not in node.config["jsx_source"]

    def test_patch_git_style_hunk_header(self):
        """The brain (GLM) emits standard git diff headers `@@ -a,b +c,d @@`, not
        the simplified `@@ <anchor>` form. Regression for run 7cfb3698: these
        silently no-op'd through execute_field_ops, forcing a full rewrite."""
        from coder.workflow.agentic.commands import execute_field_ops
        from coder.workflow.workflow_xml import XmlOp

        state = GraphState()
        source = (
            "function App() {\n"
            "  const canvasRef = useRef(null);\n"
            "  const handleKey = (e) => {\n"
            "    if (e.code === 'Space') { flap(); }\n"
            "  };\n"
            "}"
        )
        node = NodeState(id="flappy-bird", type="interface-html-react", label="Flappy Bird",
                         goal="game", config={"jsx_source": source})
        state.nodes["flappy-bird"] = node

        # Wrong line numbers on purpose — must be ignored, located by context.
        patch = (
            "@@ -1,2 +1,3 @@\n"
            " function App() {\n"
            "+  const containerRef = useRef(null);\n"
            "   const canvasRef = useRef(null);\n"
            "@@ -4,1 +5,1 @@\n"
            "-    if (e.code === 'Space') { flap(); }\n"
            "+    if (e.code === 'Space' || e.key === ' ') { flap(); }\n"
        )
        ops = [XmlOp(tag="field", attrs={"node": "flappy-bird", "name": "jsx_source"}, body=patch)]
        results = execute_field_ops(ops, state)
        assert "Patched" in results[0], f"expected Patched, got: {results[0]}"
        patched = node.config["jsx_source"]
        assert "const containerRef = useRef(null);" in patched
        assert "e.key === ' '" in patched
        assert "const canvasRef = useRef(null);" in patched

    def test_patch_on_empty_field_errors(self):
        from coder.workflow.agentic.commands import execute_field_ops
        from coder.workflow.workflow_xml import XmlOp

        state = GraphState()
        node = NodeState(id="n1", type="automation-slack", label="Slack", goal="send",
                         config={})
        state.nodes["n1"] = node

        patch = "@@ line1\n-old\n+new\n"
        ops = [XmlOp(tag="field", attrs={"node": "n1", "name": "jsx_source"}, body=patch)]
        results = execute_field_ops(ops, state)
        assert "cannot patch" in results[0]

    def test_patch_no_match_reports_failure(self):
        from coder.workflow.agentic.commands import execute_field_ops
        from coder.workflow.workflow_xml import XmlOp

        state = GraphState()
        node = NodeState(id="n1", type="automation-slack", label="Slack", goal="send",
                         config={"jsx_source": "line1\nline2\nline3\n"})
        state.nodes["n1"] = node

        patch = "@@ nonexistent anchor\n-old\n+new\n"
        ops = [XmlOp(tag="field", attrs={"node": "n1", "name": "jsx_source"}, body=patch)]
        results = execute_field_ops(ops, state)
        assert "PATCH FAILED" in results[0]
        # Original value should be unchanged
        assert "line2" in node.config["jsx_source"]

    def test_patch_tolerates_blank_line_gaps(self):
        from coder.workflow.agentic.commands import execute_field_ops
        from coder.workflow.workflow_xml import XmlOp

        state = GraphState()
        # Source has a blank line between imports and function
        source = "import React from 'react';\nimport ReactDOM from 'react-dom/client';\n\nfunction App() {\n  return <div>hello</div>;\n}"
        node = NodeState(id="n1", type="interface-html-react", label="Test", goal="test",
                         config={"jsx_source": source})
        state.nodes["n1"] = node

        # Patch skips the blank line
        patch = "@@import React from 'react';\n import ReactDOM from 'react-dom/client';\n function App() {\n-  return <div>hello</div>;\n+  return <div>goodbye</div>;\n"
        ops = [XmlOp(tag="field", attrs={"node": "n1", "name": "jsx_source"}, body=patch)]
        results = execute_field_ops(ops, state)
        assert "Patched" in results[0]
        assert "goodbye" in node.config["jsx_source"]

    def test_non_patch_field_still_works(self):
        from coder.workflow.agentic.commands import execute_field_ops
        from coder.workflow.workflow_xml import XmlOp

        state = GraphState()
        node = NodeState(id="n1", type="automation-slack", label="Slack", goal="send",
                         config={})
        state.nodes["n1"] = node

        ops = [XmlOp(tag="field", attrs={"node": "n1", "name": "channel", "value": "#general"}, body=None)]
        results = execute_field_ops(ops, state)
        assert node.config["channel"] == "#general"


# ============================================================================
# Schema-aware coercion in execute_field_ops
# ============================================================================

class TestFieldOpsSchemaCoercion:
    """
    Regression test for the AI-builder loop on agent.show_in_interface.

    The builder repeatedly emitted ``<field name="show_in_interface" value="false" />``
    against an agent node; ``coerce_value`` JSON-decoded ``"false"`` to bool
    ``False``; Pydantic v2 rejected it because the field is
    ``enum('true','false')`` (a string). The builder couldn't recover and burned
    several turns. Now ``execute_field_ops`` consults the field schema and
    preserves the raw string for string-typed enum fields.
    """

    def test_string_enum_field_keeps_value_as_string(self):
        """value='false' on agent.show_in_interface must stay 'false' (str)."""
        from coder.workflow.agentic.commands import execute_field_ops
        from coder.workflow.workflow_xml import XmlOp

        state = GraphState()
        # agent default operation has show_in_interface: enum('true','false')
        node = NodeState(
            id="n1", type="agent", label="Agent", goal="chat",
            operation="default", config={},
        )
        state.nodes["n1"] = node

        ops = [XmlOp(
            tag="field",
            attrs={"node": "n1", "name": "show_in_interface", "value": "false"},
            body=None,
        )]
        execute_field_ops(ops, state)

        # Before the fix: config["show_in_interface"] was Python False
        # After the fix: it's the literal string "false"
        assert node.config["show_in_interface"] == "false"
        assert isinstance(node.config["show_in_interface"], str), (
            f"Expected str, got {type(node.config['show_in_interface']).__name__}"
        )

    def test_string_enum_field_via_body_also_preserved(self):
        """value-in-body form was the workaround the AI builder eventually used;
        confirm it still works the same way."""
        from coder.workflow.agentic.commands import execute_field_ops
        from coder.workflow.workflow_xml import XmlOp

        state = GraphState()
        node = NodeState(
            id="n1", type="agent", label="Agent", goal="chat",
            operation="default", config={},
        )
        state.nodes["n1"] = node

        ops = [XmlOp(
            tag="field",
            attrs={"node": "n1", "name": "show_in_interface"},
            body="false",
        )]
        execute_field_ops(ops, state)

        assert node.config["show_in_interface"] == "false"


# ============================================================================
# Graph utility functions (find_predecessors) + flat node-config shape
# ============================================================================

class TestFindPredecessors:
    def test_finds_direct_predecessor(self):
        edges = [{"source": "a", "target": "b"}]
        result = find_predecessors("b", edges, {"a", "b"})
        assert result == {"a"}

    def test_finds_transitive_predecessors(self):
        edges = [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}]
        result = find_predecessors("c", edges, {"a", "b", "c"})
        assert result == {"a", "b"}

    def test_ignores_unknown_nodes(self):
        edges = [{"source": "x", "target": "b"}]
        result = find_predecessors("b", edges, {"b"})  # "x" not in all_node_ids
        assert result == set()

    def test_no_predecessors(self):
        edges = [{"source": "a", "target": "b"}]
        result = find_predecessors("a", edges, {"a", "b"})
        assert result == set()


class TestNodeConfigShape:
    """Verify the flat node shape exposes config + output directly (no helper needed)."""

    def test_flat_format(self):
        node = {"config": {"channel": "#general", "output": {"ok": True}}}
        config = node["config"]
        assert config == {"channel": "#general", "output": {"ok": True}}
        assert config.get("output") == {"ok": True}

    def test_empty_node(self):
        node: dict = {}
        config = node.get("config", {}) or {}
        assert config == {}
        assert config.get("output") is None


# ============================================================================
# Credential-awareness regressions
#
# The brain kept asking the user to connect Reddit/Email accounts for
# operations that need no credentials, and asked for a recipient field the
# send-email node doesn't have. Three feedback gaps caused it: no positive
# "not required" signal, a search_credentials empty-result message that
# asserted a requirement for any type string, and an ask pipeline that
# accepted invalid asks silently.
# ============================================================================

class TestNodeRequiresCredentials:
    def test_credentials_optional_operation(self):
        from coder.workflow.operation_catalog import node_requires_credentials
        assert node_requires_credentials('automation-reddit', 'get_subreddit_posts', {}) is False

    def test_node_without_credentials(self):
        from coder.workflow.operation_catalog import node_requires_credentials
        assert node_requires_credentials('automation-send-email', 'send', {}) is False

    def test_oauth_node_requires(self):
        from coder.workflow.operation_catalog import node_requires_credentials
        assert node_requires_credentials('automation-gmail', None, {}) is True

    def test_unknown_node_type(self):
        from coder.workflow.operation_catalog import node_requires_credentials
        assert node_requires_credentials('automation-does-not-exist', 'x', {}) is False


class TestCredentialStatusLine:
    def test_not_required_for_optional_operation(self):
        from coder.workflow.operation_catalog import credential_status_line
        line = credential_status_line('automation-reddit', 'get_subreddit_posts', {}, 'reddit')
        assert line == '[credentials: not required for this operation]'

    def test_not_required_for_credential_free_node(self):
        from coder.workflow.operation_catalog import credential_status_line
        line = credential_status_line('automation-send-email', 'send', {}, 'email_sender')
        assert line == '[credentials: not required for this operation]'

    def test_needed_for_oauth_node(self):
        from coder.workflow.operation_catalog import credential_status_line
        line = credential_status_line('automation-gmail', None, {}, 'gmail_1')
        assert '[credentials needed: gmail]' in line
        assert 'google_gmail_oauth' in line

    def test_attached_shows_checkmark(self):
        from coder.workflow.operation_catalog import credential_status_line
        config = {'credentialIds': {'google_gmail_oauth': 'cred-1'}}
        line = credential_status_line('automation-gmail', None, config, 'gmail_1')
        assert line == '[credentials: gmail ✓]'

    def test_non_integration_node_gets_no_line(self):
        from coder.workflow.operation_catalog import credential_status_line
        assert credential_status_line('trigger-cron', 'default', {}, 'cron') is None

    def test_agent_node_gets_billing_aware_line(self):
        # Agents are no longer silent: platform-billed models get the positive
        # line; CLI harnesses get [credentials needed] (harness runs are BYOK —
        # no per-call cost capture, so platform keys can't fund them). Full
        # matrix in test_agent_harness_credentials.py.
        from coder.workflow.operation_catalog import credential_status_line
        default_llm = credential_status_line('agent', 'default', {}, 'summarizer')
        assert default_llm == (
            "[credentials: not required — this model runs on NoClick's "
            "platform key and is billed per use]"
        )
        harness = credential_status_line('agent', 'default', {'model': 'codex'}, 'summarizer')
        assert harness.startswith('[credentials needed:')

    def test_summary_and_snapshot_carry_the_line(self):
        from coder.workflow.agentic.commands import build_node_summary

        state = GraphState()
        node = NodeState(id='reddit', type='automation-reddit', label='Reddit', goal='fetch',
                         operation='get_subreddit_posts', config={'subreddit': 'wallstreetbets'})
        state.nodes['reddit'] = node

        assert '[credentials: not required for this operation]' in build_node_summary(node)
        assert '[credentials: not required for this operation]' in state.to_xml()


class TestKnownCredentialTypes:
    def test_real_type_known_invented_types_not(self):
        from coder.workflow.operation_catalog import known_credential_types
        kt = known_credential_types()
        assert 'google_gmail_oauth' in kt
        # These invented credential types do not exist.
        assert 'reddit' not in kt
        assert 'send_email' not in kt


class TestNoCredentialsGuidance:
    def test_unknown_type_and_no_needy_nodes(self):
        from coder.workflow.agentic.commands import _no_credentials_guidance

        state = GraphState()
        state.nodes['reddit'] = NodeState(
            id='reddit', type='automation-reddit', label='Reddit', goal='fetch',
            operation='get_subreddit_posts', config={})
        state.nodes['email_sender'] = NodeState(
            id='email_sender', type='automation-send-email', label='Email', goal='send',
            operation='send', config={})

        guidance = _no_credentials_guidance('reddit', state)
        assert "'reddit' is not a known credential type" in guidance
        assert 'do not ask the user to connect an account' in guidance

    def test_lists_nodes_that_actually_need_credentials(self):
        from coder.workflow.agentic.commands import _no_credentials_guidance

        state = GraphState()
        state.nodes['gmail_1'] = NodeState(
            id='gmail_1', type='automation-gmail', label='Gmail', goal='read', config={})

        guidance = _no_credentials_guidance('google_gmail_oauth', state)
        assert 'is not a known credential type' not in guidance
        assert 'gmail_1 (automation-gmail)' in guidance

    def test_node_with_attached_credentials_not_listed(self):
        from coder.workflow.agentic.commands import _no_credentials_guidance

        state = GraphState()
        state.nodes['gmail_1'] = NodeState(
            id='gmail_1', type='automation-gmail', label='Gmail', goal='read',
            config={'credentialIds': {'google_gmail_oauth': 'cred-1'}})

        guidance = _no_credentials_guidance('google_gmail_oauth', state)
        assert 'gmail_1' not in guidance
        assert 'do not ask the user to connect an account' in guidance

    def test_without_graph_state_points_at_flag(self):
        from coder.workflow.agentic.commands import _no_credentials_guidance
        assert '[credentials needed:' in _no_credentials_guidance('anything', None)


class TestExtractAskRequestsValidation:
    """Invalid asks are dropped with a rejection message instead of rendering
    a junk question to the user (credential picker for a credential-free node,
    text input for a nonexistent field)."""

    def _ask(self, node, field, label='Q?'):
        from coder.workflow.workflow_xml import XmlOp
        return XmlOp(tag='ask', attrs={'node': node, 'field': field, 'label': label}, body=None)

    def test_credential_ask_rejected_for_credential_free_operation(self):
        from coder.workflow.agentic.commands import extract_ask_requests

        state = GraphState()
        state.nodes['reddit'] = NodeState(
            id='reddit', type='automation-reddit', label='Reddit', goal='fetch',
            operation='get_subreddit_posts', config={})

        reqs, rejections = extract_ask_requests([self._ask('reddit', 'credential')], graph_state=state)
        assert reqs == []
        assert len(rejections) == 1
        assert 'does not require credentials' in rejections[0]

    def test_credential_ask_allowed_for_oauth_node(self):
        from coder.workflow.agentic.commands import extract_ask_requests

        state = GraphState()
        state.nodes['gmail_1'] = NodeState(
            id='gmail_1', type='automation-gmail', label='Gmail', goal='read', config={})

        reqs, rejections = extract_ask_requests([self._ask('gmail_1', 'credential')], graph_state=state)
        assert rejections == []
        assert len(reqs) == 1
        assert reqs[0]['type'] == 'credential'
        assert reqs[0]['credentialType'] == 'google_gmail_oauth'

    def test_field_ask_rejected_for_nonexistent_field(self):
        from coder.workflow.agentic.commands import extract_ask_requests

        state = GraphState()
        state.nodes['email_sender'] = NodeState(
            id='email_sender', type='automation-send-email', label='Email', goal='send',
            operation='send', config={})

        # The invalid ask uses "to", but send-email has no recipient field.
        reqs, rejections = extract_ask_requests([self._ask('email_sender', 'to')], graph_state=state)
        assert reqs == []
        assert len(rejections) == 1
        assert "'to' is not a config field" in rejections[0]
        assert 'subject' in rejections[0]  # valid-fields list helps the brain recover

    def test_field_ask_allowed_for_real_field(self):
        from coder.workflow.agentic.commands import extract_ask_requests

        state = GraphState()
        state.nodes['email_sender'] = NodeState(
            id='email_sender', type='automation-send-email', label='Email', goal='send',
            operation='send', config={})

        reqs, rejections = extract_ask_requests([self._ask('email_sender', 'subject')], graph_state=state)
        assert rejections == []
        assert len(reqs) == 1
        assert reqs[0]['fieldKey'] == 'subject'
        assert reqs[0].get('fieldSchema')

    def test_ask_rejected_for_unknown_node(self):
        from coder.workflow.agentic.commands import extract_ask_requests

        reqs, rejections = extract_ask_requests([self._ask('ghost', 'credential')], graph_state=GraphState())
        assert reqs == []
        assert "node 'ghost' not found" in rejections[0]

    def test_free_form_ask_passes_through(self):
        from coder.workflow.agentic.commands import extract_ask_requests
        from coder.workflow.workflow_xml import XmlOp

        op = XmlOp(tag='ask', attrs={'label': 'Tone?'}, body='Formal\nCasual')
        reqs, rejections = extract_ask_requests([op], graph_state=GraphState())
        assert rejections == []
        assert reqs[0]['type'] == 'selection'
        # Single-choice by default — the FE renders radios.
        assert reqs[0]['multiple'] is False

    def test_free_form_ask_multiple(self):
        from coder.workflow.agentic.commands import extract_ask_requests
        from coder.workflow.workflow_xml import XmlOp

        op = XmlOp(
            tag='ask',
            attrs={'label': 'Which alerts?', 'multiple': 'true'},
            body='Signups\nFailed payments\nRefunds',
        )
        reqs, rejections = extract_ask_requests([op], graph_state=GraphState())
        assert rejections == []
        assert reqs[0]['type'] == 'selection'
        assert reqs[0]['multiple'] is True
        assert [o['id'] for o in reqs[0]['options']] == ['Signups', 'Failed payments', 'Refunds']


class TestSearchCredentialsGuidanceWiring:
    @pytest.mark.asyncio
    async def test_empty_search_reports_no_requirement(self):
        from coder.workflow.agentic.commands import execute_platform_ops
        from coder.workflow.workflow_xml import XmlOp

        class _Platform:
            async def search_credentials(self, credential_type, query, limit):
                return []

        state = GraphState()
        state.nodes['reddit'] = NodeState(
            id='reddit', type='automation-reddit', label='Reddit', goal='fetch',
            operation='get_subreddit_posts', config={})

        ops = [XmlOp(tag='search_credentials', attrs={'type': 'reddit'}, body=None)]
        results = await execute_platform_ops(ops, _Platform(), graph_state=state)

        text = '\n'.join(results)
        assert "No credentials found of type 'reddit'" in text
        assert 'do not ask the user to connect an account' in text
        # The old misleading assertion is gone.
        assert 'The user needs to add credentials' not in text




class TestUserFieldsClearedOnFieldSet:
    """[needs user input: model] kept rendering in summaries and snapshots
    after the brain applied the user's answer via <field>."""

    def test_field_set_clears_pending_flag(self):
        from coder.workflow.agentic.commands import build_node_summary, execute_field_ops
        from coder.workflow.workflow_xml import XmlOp

        state = GraphState()
        node = NodeState(id='summarizer', type='agent', label='Agent', goal='summarize',
                         operation='default', config={}, user_fields=['model'])
        state.nodes['summarizer'] = node

        ops = [XmlOp(tag='field', attrs={'node': 'summarizer', 'name': 'model',
                                         'value': 'openrouter/minimax/minimax-m3'}, body=None)]
        execute_field_ops(ops, state)

        assert node.user_fields == []
        assert '[needs user input' not in build_node_summary(node)
        assert '[needs user input' not in state.to_xml()

    def test_unrelated_field_keeps_flag(self):
        from coder.workflow.agentic.commands import execute_field_ops
        from coder.workflow.workflow_xml import XmlOp

        state = GraphState()
        node = NodeState(id='summarizer', type='agent', label='Agent', goal='summarize',
                         operation='default', config={}, user_fields=['model'])
        state.nodes['summarizer'] = node

        ops = [XmlOp(tag='field', attrs={'node': 'summarizer', 'name': 'temperature',
                                         'value': '0.2'}, body=None)]
        execute_field_ops(ops, state)

        assert node.user_fields == ['model']


# ============================================================================
# Missing-required visibility regressions
#
# node drafter's response for the reddit node used unclosed <field> tags; every
# field was dropped, empty config skipped validation, nothing flagged the
# missing required `subreddit`, and the brain <done/>'d a workflow that
# couldn't run. The parser now recovers the tags (test_workflow_xml), and
# these pin the visibility layer: required-but-empty fields must show in
# summaries and the snapshot.
# ============================================================================

class TestMissingRequiredFields:
    def test_empty_config_lists_required(self):
        from coder.workflow.operation_catalog import missing_required_fields
        assert missing_required_fields('automation-reddit', 'get_subreddit_posts', {}) == ['subreddit']
        assert missing_required_fields('automation-send-email', 'send', {}) == ['subject', 'body']

    def test_filled_and_empty_string_values(self):
        from coder.workflow.operation_catalog import missing_required_fields
        assert missing_required_fields(
            'automation-reddit', 'get_subreddit_posts', {'subreddit': 'wallstreetbets'}) == []
        # node drafter sometimes emits value="" when it doesn't know — counts as missing.
        assert missing_required_fields(
            'automation-reddit', 'get_subreddit_posts', {'subreddit': ''}) == ['subreddit']

    def test_user_input_fields_excluded(self):
        from coder.workflow.operation_catalog import missing_required_fields
        assert missing_required_fields(
            'automation-reddit', 'get_subreddit_posts', {}, user_fields=['subreddit']) == []

    def test_summary_and_snapshot_flag_missing_required(self):
        from coder.workflow.agentic.commands import build_node_summary

        state = GraphState()
        node = state.add_node('reddit', 'automation-reddit', 'Reddit', goal='fetch wsb posts')
        node.operation = 'get_subreddit_posts'

        assert '[missing required: subreddit]' in build_node_summary(node, state)
        assert '[missing required: subreddit]' in state.to_xml()

    def test_tool_provider_nodes_not_flagged(self):
        from coder.workflow.agentic.commands import build_node_summary

        state = GraphState()
        provider = state.add_node('linear1', 'automation-linear', 'Linear', goal='tools')
        provider.operation = 'create_issue'
        agent = state.add_node('agent1', 'agent', 'Agent', goal='assist')
        agent.operation = 'default'
        agent.config = {'message': 'do things'}
        state.add_edge('linear1', 'agent1', source_handle='top', target_handle='bottom')

        assert '[missing required' not in build_node_summary(provider, state)
        # The provider's create_issue op has required fields but providers
        # never execute it — the whole snapshot must stay clean.
        assert '[missing required' not in state.to_xml()




class TestFilterPrematureFieldOps:
    """Regression for the 'agent tools never set' bug: when the brain adds a
    tool-provider node and sets its allowlist in the SAME turn, the allowlist
    must survive the premature-field strip (node drafting never authors it)."""

    @staticmethod
    def _ops(*specs):
        from coder.workflow.workflow_xml import XmlOp
        return [XmlOp(tag=tag, attrs=attrs, body=None) for tag, attrs in specs]

    def test_keeps_allowlisted_fields_on_same_turn_node(self):
        from coder.workflow.agentic.commands import (
            filter_premature_field_ops, SAME_TURN_FIELD_ALLOWLIST,
        )
        # Every exempt field set on a node added this same turn must survive.
        for field_name in SAME_TURN_FIELD_ALLOWLIST:
            ops = self._ops(
                ('add_node', {'name': 'gmail-tools', 'type': 'automation-gmail'}),
                ('add_edge', {'from': 'gmail-tools', 'to': 'agent', 'type': 'tools'}),
                ('field', {'node': 'gmail-tools', 'name': field_name, 'value': '["x"]'}),
            )
            kept, dropped = filter_premature_field_ops(ops)
            field_ops = [o for o in kept if o.tag == 'field']
            assert len(field_ops) == 1, f"{field_name} should survive the strip"
            assert field_ops[0].attrs['name'] == field_name
            assert dropped == []

    def test_drops_non_exempt_field_on_same_turn_node(self):
        from coder.workflow.agentic.commands import filter_premature_field_ops
        # prompt is an operation-schema field node drafting fills — must be dropped;
        # agent_env_requested is exempt and must stay. show_in_interface is no
        # longer exempt: a same-turn hide broke the closing <run_test/> demo
        # (the Test Run screen lives in the agent chat), so it drops too.
        ops = self._ops(
            ('add_node', {'name': 'support-agent', 'type': 'agent'}),
            ('field', {'node': 'support-agent', 'name': 'prompt', 'value': 'hi'}),
            ('field', {'node': 'support-agent', 'name': 'agent_env_requested', 'value': '["K"]'}),
            ('field', {'node': 'support-agent', 'name': 'show_in_interface', 'value': 'false'}),
        )
        kept, dropped = filter_premature_field_ops(ops)
        kept_field_names = {o.attrs['name'] for o in kept if o.tag == 'field'}
        assert kept_field_names == {'agent_env_requested'}
        # The drops are fed back to the brain, never silent.
        assert len(dropped) == 2
        assert 'prompt' in dropped[0] and 'support-agent' in dropped[0]
        assert 'show_in_interface' in dropped[1]

    def test_keeps_all_fields_on_preexisting_node(self):
        from coder.workflow.agentic.commands import filter_premature_field_ops
        # The edited node is NOT added this turn — the brain is editing an
        # existing node, so keep every field override regardless of name.
        ops = self._ops(
            ('add_node', {'name': 'newnode', 'type': 'agent'}),
            ('field', {'node': 'existing-agent', 'name': 'prompt', 'value': 'hi'}),
            ('field', {'node': 'existing-agent', 'name': 'temperature', 'value': '0.5'}),
        )
        kept, dropped = filter_premature_field_ops(ops)
        kept_field_names = {o.attrs['name'] for o in kept if o.tag == 'field'}
        assert kept_field_names == {'prompt', 'temperature'}
        assert dropped == []

    def test_passthrough_when_no_nodes_added(self):
        from coder.workflow.agentic.commands import filter_premature_field_ops
        ops = self._ops(('field', {'node': 'n1', 'name': 'prompt', 'value': 'hi'}))
        assert filter_premature_field_ops(ops) == (ops, [])

    def test_exact_failed_run_scenario(self):
        """The real Message-1/Turn-2 batch from run 4f26775a-…: both providers'
        allowlists survive; the bogus `prompt` field (not a real agent field)
        is correctly left to node drafting, and the agent's show_in_interface is
        dropped (no longer same-turn exempt — the chat hosts the Test Run
        screen; user-requested hides re-issue next turn)."""
        from coder.workflow.agentic.commands import filter_premature_field_ops
        ops = self._ops(
            ('add_node', {'name': 'gmail-trigger', 'type': 'automation-gmail'}),
            ('add_node', {'name': 'support-agent', 'type': 'agent'}),
            ('add_node', {'name': 'gmail-tools', 'type': 'automation-gmail'}),
            ('add_node', {'name': 'drive-tools', 'type': 'automation-google-drive'}),
            ('add_edge', {'from': 'gmail-tools', 'to': 'support-agent', 'type': 'tools'}),
            ('add_edge', {'from': 'drive-tools', 'to': 'support-agent', 'type': 'tools'}),
            ('field', {'node': 'gmail-tools', 'name': 'agent_tool_operations', 'value': '["send_email"]'}),
            ('field', {'node': 'drive-tools', 'name': 'agent_tool_operations', 'value': '["search_files"]'}),
            ('field', {'node': 'support-agent', 'name': 'show_in_interface', 'value': 'true'}),
            ('field', {'node': 'support-agent', 'name': 'prompt', 'value': '...'}),
        )
        kept, dropped = filter_premature_field_ops(ops)
        surviving = {(o.attrs['node'], o.attrs['name']) for o in kept if o.tag == 'field'}
        assert surviving == {
            ('gmail-tools', 'agent_tool_operations'),
            ('drive-tools', 'agent_tool_operations'),
        }
        assert len(dropped) == 2
        assert any('show_in_interface' in d for d in dropped)
        assert any('prompt' in d for d in dropped)


# ============================================================================
# Field-bound <ask> schema resolution (operation-independent picker)
# ============================================================================

class TestResolveAskFieldSchema:
    """The picker for a field-bound <ask> must resolve `x-dynamic-options`
    independently of the node's *selected* operation — provider nodes carry
    `default`, and their dynamic fields live in their other operations'
    schemas. Ambiguity is rejected, never silently degraded to a textbox."""

    def _node(self, operation=None, config=None):
        return NodeState(
            id="sheets", type="automation-google-sheets", label="Sheets",
            goal="x", operation=operation, config=config or {},
        )

    def test_provider_resolves_dynamic_options_via_allowlist(self):
        from coder.workflow.agentic.commands import _resolve_ask_field_schema
        node = self._node(config={"agent_tool_operations": ["append_rows_to_sheet"]})
        op, schema, err = _resolve_ask_field_schema(node, "spreadsheet_id")
        assert err is None
        assert op == "append_rows_to_sheet"
        assert "x-dynamic-options" in schema

    def test_provider_resolves_without_allowlist_by_scanning_ops(self):
        # "even before adding tools" — agent_tool_operations not set yet. All
        # google-sheets ops share the same spreadsheet_id loader, so scanning
        # every operation is unambiguous.
        from coder.workflow.agentic.commands import _resolve_ask_field_schema
        op, schema, err = _resolve_ask_field_schema(self._node(), "spreadsheet_id")
        assert err is None
        assert schema is not None and "x-dynamic-options" in schema

    def test_default_operation_treated_as_provider(self):
        # Some loaders persist the literal 'default' rather than None.
        from coder.workflow.agentic.commands import _resolve_ask_field_schema
        node = self._node(operation="default",
                          config={"agent_tool_operations": ["read_sheet_data"]})
        op, schema, err = _resolve_ask_field_schema(node, "spreadsheet_id")
        assert err is None and op == "read_sheet_data"
        assert "x-dynamic-options" in schema

    def test_invalid_field_rejected(self):
        from coder.workflow.agentic.commands import _resolve_ask_field_schema
        node = self._node(config={"agent_tool_operations": ["append_rows_to_sheet"]})
        op, schema, err = _resolve_ask_field_schema(node, "definitely_not_a_field")
        assert schema is None
        assert err and "not a config field" in err

    def test_explicit_operation_override(self):
        from coder.workflow.agentic.commands import _resolve_ask_field_schema
        op, schema, err = _resolve_ask_field_schema(
            self._node(), "spreadsheet_id", explicit_operation="read_sheet_data")
        assert err is None and op == "read_sheet_data"
        assert "x-dynamic-options" in schema

    def test_explicit_operation_unknown_rejected(self):
        from coder.workflow.agentic.commands import _resolve_ask_field_schema
        op, schema, err = _resolve_ask_field_schema(
            self._node(), "spreadsheet_id", explicit_operation="no_such_op")
        assert schema is None and err and "no operation" in err

    def test_concrete_operation_resolves(self):
        from coder.workflow.agentic.commands import _resolve_ask_field_schema
        node = self._node(operation="append_rows_to_sheet")
        op, schema, err = _resolve_ask_field_schema(node, "spreadsheet_id")
        assert err is None and op == "append_rows_to_sheet"
        assert "x-dynamic-options" in schema

    def test_concrete_operation_invalid_field_rejected(self):
        from coder.workflow.agentic.commands import _resolve_ask_field_schema
        node = self._node(operation="append_rows_to_sheet")
        op, schema, err = _resolve_ask_field_schema(node, "nope")
        assert schema is None and err and "append_rows_to_sheet" in err

    def test_signature_ignores_cosmetic_differences(self):
        # append's spreadsheet_id (title "Spreadsheet") vs copy_sheet's
        # (title "Source Spreadsheet", different placeholder) must NOT be
        # ambiguous — same loader, only cosmetics differ.
        from coder.workflow.agentic.commands import _field_value_signature
        a = {"title": "Spreadsheet",
             "x-dynamic-options": {"field_name": "spreadsheet_id", "placeholder": "Select..."}}
        b = {"title": "Source Spreadsheet",
             "x-dynamic-options": {"field_name": "spreadsheet_id", "placeholder": "Pick source..."}}
        assert _field_value_signature(a) == _field_value_signature(b)

    def test_signature_distinguishes_enums(self):
        from coder.workflow.agentic.commands import _field_value_signature
        assert _field_value_signature({"enum": ["a", "b"]}) \
            != _field_value_signature({"enum": ["a", "b", "c"]})

    def test_ambiguous_field_rejected(self, monkeypatch):
        # Synthetic node type: the same field resolves to *different* loaders on
        # two operations → reject (don't guess which dropdown to show).
        from types import SimpleNamespace
        import coder.workflow.agentic.commands as cmds
        ops = [SimpleNamespace(name="op_a"), SimpleNamespace(name="op_b")]
        schemas = {
            "op_a": {"properties": {"target": {"type": "string",
                     "x-dynamic-options": {"field_name": "loader_a"}}}},
            "op_b": {"properties": {"target": {"type": "string",
                     "x-dynamic-options": {"field_name": "loader_b"}}}},
        }
        monkeypatch.setattr(cmds, "get_operations_for_node_type", lambda nt: ops)
        monkeypatch.setattr(cmds, "get_operation_schema", lambda nt, op: schemas.get(op))
        node = NodeState(id="x", type="fake-type", label="F", goal="g", operation=None, config={})
        op, schema, err = cmds._resolve_ask_field_schema(node, "target")
        assert schema is None
        assert err and "different option sources" in err

    def test_ambiguity_resolved_by_allowlist(self, monkeypatch):
        # The allowlist narrows candidates to the agent's actual op → unambiguous.
        from types import SimpleNamespace
        import coder.workflow.agentic.commands as cmds
        ops = [SimpleNamespace(name="op_a"), SimpleNamespace(name="op_b")]
        schemas = {
            "op_a": {"properties": {"target": {"type": "string",
                     "x-dynamic-options": {"field_name": "loader_a"}}}},
            "op_b": {"properties": {"target": {"type": "string",
                     "x-dynamic-options": {"field_name": "loader_b"}}}},
        }
        monkeypatch.setattr(cmds, "get_operations_for_node_type", lambda nt: ops)
        monkeypatch.setattr(cmds, "get_operation_schema", lambda nt, op: schemas.get(op))
        node = NodeState(id="x", type="fake-type", label="F", goal="g", operation=None,
                         config={"agent_tool_operations": ["op_a"]})
        op, schema, err = cmds._resolve_ask_field_schema(node, "target")
        assert err is None and op == "op_a"
        assert schema["x-dynamic-options"]["field_name"] == "loader_a"


class TestExtractAskRequestsProvider:
    """End-to-end: a field-bound <ask> on a provider node (the real
    Telegram-receipt-bot failure shape) now ships the live spreadsheet picker."""

    def _state(self):
        state = GraphState()
        state.nodes["sheets"] = NodeState(
            id="sheets", type="automation-google-sheets", label="Sheets Tools",
            goal="append rows", operation=None,
            config={"agent_tool_operations": ["append_rows_to_sheet"],
                    "credentialIds": {"google_sheets_oauth": "cred-1"}},
        )
        return state

    def test_provider_field_ask_carries_dynamic_options(self):
        from coder.workflow.agentic.commands import extract_ask_requests
        from coder.workflow.workflow_xml import XmlOp
        ops = [XmlOp(tag="ask",
                     attrs={"node": "sheets", "field": "spreadsheet_id", "label": "Which sheet?"},
                     body=None)]
        requests, rejections = extract_ask_requests(ops, self._state())
        assert rejections == []
        cfg = [r for r in requests if r.get("fieldKey") == "spreadsheet_id"]
        assert len(cfg) == 1
        assert cfg[0]["type"] == "config"
        assert "x-dynamic-options" in (cfg[0].get("fieldSchema") or {})
        assert cfg[0]["credentialIds"] == {"google_sheets_oauth": "cred-1"}

    def test_provider_invalid_field_is_rejected_not_textbox(self):
        from coder.workflow.agentic.commands import extract_ask_requests
        from coder.workflow.workflow_xml import XmlOp
        ops = [XmlOp(tag="ask",
                     attrs={"node": "sheets", "field": "bogus_field", "label": "?"},
                     body=None)]
        requests, rejections = extract_ask_requests(ops, self._state())
        assert requests == []
        assert any("bogus_field" in r for r in rejections)
