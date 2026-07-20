"""extract_resource_id_from_output feeds the agent-create auto-extend writeback
(and validates x-resource-id-path annotations). Regression: it must coerce
NUMERIC ids (PostHog/Monday/GitLab dashboards, cohorts, boards …) to str — it
previously returned only strings, so every int-id create silently failed to
write back."""

from nodes.agent.node_op_tools import extract_resource_id_from_output as extract


def test_string_id():
    assert extract({"data": {"id": "abc"}}, "data.id") == "abc"


def test_int_id_coerced_to_str():
    assert extract({"data": {"id": 1874837}}, "data.id") == "1874837"


def test_nested_path():
    assert extract({"data": {"issueCreate": {"issue": {"id": "iss_1"}}}}, "data.issueCreate.issue.id") == "iss_1"


def test_short_id_string_path():
    assert extract({"data": {"short_id": "CjbMSmgg"}}, "data.short_id") == "CjbMSmgg"


def test_missing_or_empty_returns_none():
    assert extract({"data": {}}, "data.id") is None
    assert extract({"data": {"id": ""}}, "data.id") is None
    assert extract({"data": {"id": None}}, "data.id") is None
    assert extract({}, "data.id") is None
    assert extract(None, "data.id") is None


def test_bool_rejected():
    # a boolean is never a resource id (avoids True -> "True")
    assert extract({"data": {"id": True}}, "data.id") is None


def test_non_dict_midpath_returns_none():
    assert extract({"data": "notadict"}, "data.id") is None
