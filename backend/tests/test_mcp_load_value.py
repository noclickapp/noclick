"""Unit tests for load_value's discovery helper (_loadable_fields).

The full fetch path (routing to node.load_field_value for alarm/filesystem/
mcp-server) is exercised by the in-process smoke test; here we pin the schema-
driven discovery so a fresh agent's load_value(field_name='') lists the right
computed fields.
"""
from mcp_server import _loadable_fields


def _fields(node_type):
    return {f["field_name"] for f in _loadable_fields(node_type)}


def test_alarm_lists_active_alarms():
    fields = {f["field_name"]: f for f in _loadable_fields("alarm")}
    assert "active_alarms" in fields
    assert fields["active_alarms"]["widget"] == "alarm_viewer"


def test_filesystem_lists_file_browser():
    fields = {f["field_name"]: f for f in _loadable_fields("filesystem")}
    assert "file_browser" in fields
    assert fields["file_browser"]["widget"] == "file_browser"




def test_unknown_node_type_is_empty():
    assert _loadable_fields("not-a-real-node") == []
