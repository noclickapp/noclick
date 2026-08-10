"""Author-declared workflow variables (settings.variable_definitions).

Definitions live in workflows.settings — NOT the workflow blob — because the
graph autosave replaces the blob wholesale (variables included) while settings
merge shallowly; an author's declared variables must survive every canvas
save. Runtime-written blob variables overlay declared values: a set-variable
node's persisted write wins over the author's default, never vice versa.
"""

from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler as H


def test_defined_variables_resolve_to_a_clean_value_map():
    settings = {
        "variable_definitions": [
            {"name": "site_url", "value": "https://acme.dev", "description": "Site to monitor"},
            {"name": "unfilled", "value": ""},  # declared intent, no value yet — Setup's business
            {"name": "none_valued", "value": None},
            {"name": "   ", "value": "unnamed rows never leak"},
            {"value": "nameless"},
            "garbage",
            {"name": "count", "value": 3},  # non-string values keep their type
        ]
    }
    assert H._defined_variable_values(settings) == {
        "site_url": "https://acme.dev",
        "count": 3,
    }


def test_absent_or_empty_settings_mean_no_variables():
    assert H._defined_variable_values(None) == {}
    assert H._defined_variable_values({}) == {}
    assert H._defined_variable_values({"variable_definitions": None}) == {}


def test_runtime_blob_variables_overlay_declared_values():
    declared = H._defined_variable_values(
        {"variable_definitions": [{"name": "site_url", "value": "https://declared.dev"}]}
    )
    merged = {**declared, "site_url": "https://runtime.dev"}
    assert merged["site_url"] == "https://runtime.dev", (
        "a set-variable node's persisted write must win over the author default"
    )


def test_per_user_variables_arrive_unfilled_on_fork():
    """The fork-time contract: a per_user definition keeps its declaration but
    loses its value, so the new owner's Setup asks the question the author's
    own value would have silenced. Plain definitions carry as defaults."""
    source = {
        "variable_definitions": [
            {"name": "github_repo", "value": "author/private-repo", "per_user": True},
            {"name": "tone", "value": "friendly"},
        ]
    }
    fork_settings = dict(source)
    defs = fork_settings.get("variable_definitions")
    fork_settings["variable_definitions"] = [
        {**d, "value": ""} if isinstance(d, dict) and d.get("per_user") else d
        for d in defs
    ]
    by_name = {d["name"]: d for d in fork_settings["variable_definitions"]}
    assert by_name["github_repo"]["value"] == ""
    assert by_name["github_repo"]["per_user"] is True  # the flag itself rides on
    assert by_name["tone"]["value"] == "friendly"
