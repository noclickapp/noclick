"""Tests for the shared workflow operation executor (workflow_ops.py)."""

import pytest

from coder.workflow.workflow_xml import XmlOp
from coder.workflow.workflow_ops import (
    deep_merge_config,
    set_node_disabled,
    set_mock_output,
    merge_credentials,
    node_has_credential,
    apply_config_patch,
    update_node_settings,
    execute_node_op,
    is_node_op,
)


# ---------------------------------------------------------------------------
# deep_merge_config
# ---------------------------------------------------------------------------

class TestDeepMergeConfig:
    def test_simple_merge(self):
        result = deep_merge_config({"a": 1, "b": 2}, {"b": 3, "c": 4})
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_does_not_mutate_base(self):
        base = {"a": 1}
        deep_merge_config(base, {"a": 2})
        assert base == {"a": 1}

    def test_nested_merge(self):
        base = {"a": {"x": 1, "y": 2}, "b": 3}
        result = deep_merge_config(base, {"a": {"y": 99, "z": 100}})
        assert result == {"a": {"x": 1, "y": 99, "z": 100}, "b": 3}

    def test_overwrite_non_dict_with_dict(self):
        result = deep_merge_config({"a": "string"}, {"a": {"nested": True}})
        assert result == {"a": {"nested": True}}

    def test_overwrite_dict_with_scalar(self):
        result = deep_merge_config({"a": {"x": 1}}, {"a": 42})
        assert result == {"a": 42}

    def test_empty_updates(self):
        result = deep_merge_config({"a": 1}, {})
        assert result == {"a": 1}

    def test_empty_base(self):
        result = deep_merge_config({}, {"a": 1})
        assert result == {"a": 1}


# ---------------------------------------------------------------------------
# set_node_disabled
# ---------------------------------------------------------------------------

class TestSetNodeDisabled:
    def test_disable(self):
        config = {}
        set_node_disabled(config, True)
        assert config["disabled"] is True

    def test_enable(self):
        config = {"disabled": True, "operation": "send_email_message"}
        set_node_disabled(config, False)
        assert config["disabled"] is False
        assert config["operation"] == "send_email_message"


# ---------------------------------------------------------------------------
# set_mock_output
# ---------------------------------------------------------------------------

class TestSetMockOutput:
    def test_set_valid_json(self):
        config = {}
        err = set_mock_output(config, '{"status": 200}')
        assert err is None
        assert config["mockedOutput"] == {"status": 200}

    def test_set_json_array(self):
        config = {}
        err = set_mock_output(config, '[1, 2, 3]')
        assert err is None
        assert config["mockedOutput"] == [1, 2, 3]

    def test_invalid_json_returns_error(self):
        config = {}
        err = set_mock_output(config, "not json {")
        assert err is not None
        assert "Invalid JSON" in err
        assert "mockedOutput" not in config

    def test_clear(self):
        config = {"mockedOutput": {"old": True}}
        err = set_mock_output(config, None)
        assert err is None
        assert "mockedOutput" not in config

    def test_clear_noop_when_absent(self):
        config = {"operation": "send_email_message"}
        err = set_mock_output(config, None)
        assert err is None
        assert "mockedOutput" not in config


# ---------------------------------------------------------------------------
# merge_credentials
# ---------------------------------------------------------------------------

class TestMergeCredentials:
    def test_add_new(self):
        config = {}
        merge_credentials(config, {"google_oauth": "cred_123"})
        assert config["credentialIds"] == {"google_oauth": "cred_123"}

    def test_merge_preserves_existing(self):
        config = {"credentialIds": {"google_oauth": "cred_123"}}
        merge_credentials(config, {"slack_oauth": "cred_456"})
        assert config["credentialIds"] == {
            "google_oauth": "cred_123",
            "slack_oauth": "cred_456",
        }

    def test_overwrite_existing_provider(self):
        config = {"credentialIds": {"google_oauth": "old"}}
        merge_credentials(config, {"google_oauth": "new"})
        assert config["credentialIds"]["google_oauth"] == "new"

    def test_handles_non_dict_credentialIds(self):
        config = {"credentialIds": "corrupted"}
        merge_credentials(config, {"google_oauth": "cred_123"})
        assert config["credentialIds"] == {"google_oauth": "cred_123"}


# ---------------------------------------------------------------------------
# node_has_credential
# ---------------------------------------------------------------------------

class TestNodeHasCredential:
    def test_true_when_credential_attached(self):
        assert node_has_credential({"credentialIds": {"slack_oauth": "cred_1"}}) is True

    def test_false_when_no_credentialIds_key(self):
        assert node_has_credential({"channel": "#general"}) is False

    def test_false_when_credentialIds_empty(self):
        assert node_has_credential({"credentialIds": {}}) is False

    def test_false_when_all_ids_empty(self):
        assert node_has_credential({"credentialIds": {"slack_oauth": ""}}) is False

    def test_false_on_none_or_non_dict(self):
        assert node_has_credential(None) is False
        assert node_has_credential({"credentialIds": "corrupted"}) is False


# ---------------------------------------------------------------------------
# apply_config_patch
# ---------------------------------------------------------------------------

class TestApplyConfigPatch:
    def test_basic_patch(self):
        config = {"function_body": "line1\nline2\nline3"}
        patch_text = "*** Begin Patch\n@@ line2\n-line2\n+line2_modified\n*** End Patch"
        err = apply_config_patch(config, "function_body", patch_text)
        assert err is None
        assert "line2_modified" in config["function_body"]
        assert "line1" in config["function_body"]

    def test_missing_field_returns_error(self):
        config = {"operation": "send_email_message"}
        err = apply_config_patch(config, "nonexistent", "patch content")
        assert err is not None
        assert "not found" in err

    def test_git_style_hunk_header(self):
        """Standard git unified-diff headers (@@ -a,b +c,d @@) — the format LLMs
        actually emit — must apply, not just the simplified '@@ <anchor>' form.
        Regression for run 7cfb3698: the brain's patch silently no-op'd because
        the line-number header was mis-parsed as an old line, forcing a full rewrite."""
        config = {"jsx_source": (
            "function App() {\n"
            "  const canvasRef = useRef(null);\n"
            "  const handleKey = (e) => {\n"
            "    if (e.code === 'Space') { flap(); }\n"
            "  };\n"
            "}"
        )}
        # Line numbers are deliberately wrong — they must be ignored, and the hunk
        # located by its context/±lines instead.
        patch_text = (
            "@@ -1,2 +1,3 @@\n"
            " function App() {\n"
            "+  const containerRef = useRef(null);\n"
            "   const canvasRef = useRef(null);\n"
            "@@ -3,1 +4,1 @@\n"
            "-    if (e.code === 'Space') { flap(); }\n"
            "+    if (e.code === 'Space' || e.key === ' ') { flap(); }\n"
        )
        err = apply_config_patch(config, "jsx_source", patch_text)
        assert err is None, f"git-style patch should apply, got: {err}"
        assert "const containerRef = useRef(null);" in config["jsx_source"]
        assert "e.key === ' '" in config["jsx_source"]
        assert "const canvasRef = useRef(null);" in config["jsx_source"]


# ---------------------------------------------------------------------------
# is_node_op
# ---------------------------------------------------------------------------

class TestIsNodeOp:
    def test_node_ops_recognized(self):
        for tag in ["disable_node", "enable_node", "mock_node", "unmock_node",
                     "set_credentials", "patch_config", "patch"]:
            assert is_node_op(tag) is True, f"{tag} should be a node op"

    def test_graph_ops_not_recognized(self):
        for tag in ["add_node", "add_edge", "remove_node", "remove_edge"]:
            assert is_node_op(tag) is False, f"{tag} should not be a node op"

    def test_builder_specific_not_recognized(self):
        for tag in ["field", "done", "input", "update_goal"]:
            assert is_node_op(tag) is False, f"{tag} should not be a node op"

    def test_update_settings_is_node_op(self):
        assert is_node_op("update_settings") is True

    def test_update_config_not_in_dispatcher(self):
        # update_config is handled differently by each system
        assert is_node_op("update_config") is False


# ---------------------------------------------------------------------------
# execute_node_op (dispatcher)
# ---------------------------------------------------------------------------

class TestExecuteNodeOp:
    def test_disable_node(self):
        config = {"operation": "send_email_message"}
        err = execute_node_op(XmlOp(tag="disable_node"), config)
        assert err is None
        assert config["disabled"] is True

    def test_enable_node(self):
        config = {"disabled": True}
        err = execute_node_op(XmlOp(tag="enable_node"), config)
        assert err is None
        assert config["disabled"] is False

    def test_mock_node_with_body(self):
        config = {}
        err = execute_node_op(
            XmlOp(tag="mock_node", body='{"result": 42}'),
            config,
        )
        assert err is None
        assert config["mockedOutput"] == {"result": 42}

    def test_mock_node_with_output_attr(self):
        config = {}
        err = execute_node_op(
            XmlOp(tag="mock_node", attrs={"output": '{"key": "val"}'}),
            config,
        )
        assert err is None
        assert config["mockedOutput"] == {"key": "val"}

    def test_mock_node_no_output_returns_error(self):
        config = {}
        err = execute_node_op(XmlOp(tag="mock_node"), config)
        assert err is not None
        assert "requires output" in err

    def test_mock_node_invalid_json_returns_error(self):
        config = {}
        err = execute_node_op(
            XmlOp(tag="mock_node", body="not json"),
            config,
        )
        assert err is not None
        assert "Invalid JSON" in err

    def test_unmock_node(self):
        config = {"mockedOutput": {"old": True}}
        err = execute_node_op(XmlOp(tag="unmock_node"), config)
        assert err is None
        assert "mockedOutput" not in config

    def test_set_credentials(self):
        config = {}
        err = execute_node_op(
            XmlOp(tag="set_credentials", attrs={
                "id": "node_1", "google_oauth": "cred_abc",
            }),
            config,
        )
        assert err is None
        assert config["credentialIds"] == {"google_oauth": "cred_abc"}

    def test_set_credentials_multiple(self):
        config = {}
        err = execute_node_op(
            XmlOp(tag="set_credentials", attrs={
                "id": "node_1",
                "google_oauth": "cred_1",
                "slack_oauth": "cred_2",
            }),
            config,
        )
        assert err is None
        assert config["credentialIds"]["google_oauth"] == "cred_1"
        assert config["credentialIds"]["slack_oauth"] == "cred_2"

    def test_set_credentials_no_pairs_returns_error(self):
        config = {}
        err = execute_node_op(
            XmlOp(tag="set_credentials", attrs={"id": "node_1"}),
            config,
        )
        assert err is not None
        assert "requires" in err

    def test_patch_config(self):
        config = {"function_body": "line1\nold_line\nline3"}
        err = execute_node_op(
            XmlOp(
                tag="patch_config",
                attrs={"id": "node_1", "field": "function_body"},
                body="*** Begin Patch\n@@ old_line\n-old_line\n+new_line\n*** End Patch",
            ),
            config,
        )
        assert err is None
        assert "new_line" in config["function_body"]

    def test_patch_missing_field_attr_returns_error(self):
        config = {"function_body": "content"}
        err = execute_node_op(
            XmlOp(tag="patch_config", attrs={"id": "node_1"}),
            config,
        )
        assert err is not None
        assert "requires" in err

    def test_patch_tag_uses_name_attr(self):
        """The builder uses <patch name="..."> instead of field="..."."""
        config = {"code": "line1\nold\nline3"}
        err = execute_node_op(
            XmlOp(
                tag="patch",
                attrs={"name": "code"},
                body="*** Begin Patch\n@@ old\n-old\n+new\n*** End Patch",
            ),
            config,
        )
        assert err is None
        assert "new" in config["code"]

    def test_update_settings_via_execute_node_op(self):
        config = {}
        err = execute_node_op(
            XmlOp(tag="update_settings", attrs={"id": "node_1", "retryOnFail": "true", "maxTries": "3"}),
            config,
        )
        assert err is None
        assert config["_settings"]["retryOnFail"] == "true"
        assert config["_settings"]["maxTries"] == "3"

    def test_update_settings_no_fields_returns_error(self):
        config = {}
        err = execute_node_op(
            XmlOp(tag="update_settings", attrs={"id": "node_1"}),
            config,
        )
        assert err is not None
        assert "requires" in err

    def test_unknown_op(self):
        config = {}
        err = execute_node_op(XmlOp(tag="fly_to_moon"), config)
        assert err is not None
        assert "Unknown" in err


# ---------------------------------------------------------------------------
# update_node_settings
# ---------------------------------------------------------------------------

class TestUpdateNodeSettings:
    def test_set_retry_on_fail(self):
        config = {}
        err = update_node_settings(config, {"retryOnFail": "true"})
        assert err is None
        assert config["_settings"]["retryOnFail"] == "true"

    def test_set_retry_on_fail_false(self):
        config = {}
        err = update_node_settings(config, {"retryOnFail": "false"})
        assert err is None
        assert config["_settings"]["retryOnFail"] == "false"

    def test_bool_coercion_true_variants(self):
        for v in ("true", "True", "TRUE", "1", "yes", "Yes"):
            config = {}
            err = update_node_settings(config, {"retryOnFail": v})
            assert err is None, f"Expected success for {v!r}"
            assert config["_settings"]["retryOnFail"] == "true"

    def test_bool_coercion_false_variants(self):
        for v in ("false", "False", "FALSE", "0", "no", "No"):
            config = {}
            err = update_node_settings(config, {"alwaysOutputData": v})
            assert err is None, f"Expected success for {v!r}"
            assert config["_settings"]["alwaysOutputData"] == "false"

    def test_bool_invalid_value_returns_error(self):
        config = {}
        err = update_node_settings(config, {"retryOnFail": "maybe"})
        assert err is not None
        assert "true" in err and "false" in err

    def test_set_max_tries_valid_range(self):
        for n in range(2, 6):
            config = {}
            err = update_node_settings(config, {"maxTries": str(n)})
            assert err is None
            assert config["_settings"]["maxTries"] == str(n)

    def test_max_tries_below_range_returns_error(self):
        config = {}
        err = update_node_settings(config, {"maxTries": "1"})
        assert err is not None
        assert "2" in err and "5" in err

    def test_max_tries_above_range_returns_error(self):
        config = {}
        err = update_node_settings(config, {"maxTries": "6"})
        assert err is not None

    def test_max_tries_non_numeric_returns_error(self):
        config = {}
        err = update_node_settings(config, {"maxTries": "three"})
        assert err is not None
        assert "integer" in err

    def test_set_wait_between_tries_valid(self):
        config = {}
        err = update_node_settings(config, {"waitBetweenTries": "500"})
        assert err is None
        assert config["_settings"]["waitBetweenTries"] == "500"

    def test_wait_between_tries_boundaries(self):
        for v in ("0", "5000"):
            config = {}
            err = update_node_settings(config, {"waitBetweenTries": v})
            assert err is None

    def test_wait_between_tries_out_of_range_returns_error(self):
        config = {}
        err = update_node_settings(config, {"waitBetweenTries": "5001"})
        assert err is not None

    def test_on_error_valid_values(self):
        for v in ("stopWorkflow", "continueRegularOutput", "continueErrorOutput"):
            config = {}
            err = update_node_settings(config, {"onError": v})
            assert err is None
            assert config["_settings"]["onError"] == v

    def test_on_error_invalid_value_returns_error(self):
        config = {}
        err = update_node_settings(config, {"onError": "explode"})
        assert err is not None
        assert "stopWorkflow" in err

    def test_set_notes(self):
        config = {}
        err = update_node_settings(config, {"notes": "This node handles retries."})
        assert err is None
        assert config["_settings"]["notes"] == "This node handles retries."

    def test_execute_once(self):
        config = {}
        err = update_node_settings(config, {"executeOnce": "true"})
        assert err is None
        assert config["_settings"]["executeOnce"] == "true"

    def test_partial_update_preserves_existing(self):
        config = {"_settings": {"retryOnFail": "true", "maxTries": "3", "notes": "old"}}
        err = update_node_settings(config, {"notes": "updated"})
        assert err is None
        assert config["_settings"]["retryOnFail"] == "true"
        assert config["_settings"]["maxTries"] == "3"
        assert config["_settings"]["notes"] == "updated"

    def test_unknown_field_returns_error(self):
        config = {}
        err = update_node_settings(config, {"unknownField": "value"})
        assert err is not None
        assert "Unknown" in err

    def test_multiple_fields_at_once(self):
        config = {}
        err = update_node_settings(config, {
            "retryOnFail": "true",
            "maxTries": "4",
            "waitBetweenTries": "2000",
            "onError": "continueRegularOutput",
            "alwaysOutputData": "false",
            "executeOnce": "false",
            "notes": "full config test",
        })
        assert err is None
        s = config["_settings"]
        assert s["retryOnFail"] == "true"
        assert s["maxTries"] == "4"
        assert s["waitBetweenTries"] == "2000"
        assert s["onError"] == "continueRegularOutput"
        assert s["alwaysOutputData"] == "false"
        assert s["executeOnce"] == "false"
        assert s["notes"] == "full config test"

    def test_settings_created_when_absent(self):
        """Config without _settings key gets _settings dict created."""
        config = {"operation": "send_email_message"}
        err = update_node_settings(config, {"retryOnFail": "false"})
        assert err is None
        assert "_settings" in config

    def test_handles_corrupted_settings_value(self):
        """Non-dict _settings is replaced with a fresh dict."""
        config = {"_settings": "corrupted"}
        err = update_node_settings(config, {"retryOnFail": "true"})
        assert err is None
        assert isinstance(config["_settings"], dict)
        assert config["_settings"]["retryOnFail"] == "true"
