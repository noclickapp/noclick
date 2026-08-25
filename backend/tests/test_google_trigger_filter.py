"""Unit tests for Google Drive and Google Calendar granular trigger filtering.

Tests that the change-filtering logic in _trigger_on_drive_change and
_trigger_on_calendar_event correctly discriminates changes by operation.
The filter logic is extracted here as pure functions to avoid importing
the full node (which drags in heavy optional deps like litellm/agents).
"""

import json
import pathlib


# ============================================================
# Inline filter logic — mirrors what the node methods do
# ============================================================


_FOLDER_MIME = "application/vnd.google-apps.folder"


def _filter_drive_changes(
    operation: str,
    changes: list,
    *,
    watch_target_id: str = "",
    watch_target_kind: str = "",
    watch_parent_folder_id: str = "",
    ancestor_map: dict | None = None,
) -> list:
    """Mirrors the filtering block inside GoogleDriveNode._trigger_on_drive_change."""
    ancestor_map = ancestor_map or {}

    def _is_in_folder_tree(item_id: str, folder_id: str, parents: list[str]) -> bool:
        if item_id == folder_id:
            return True
        frontier = list(parents)
        seen = set(frontier)
        while frontier:
            parent_id = frontier.pop(0)
            if parent_id == folder_id:
                return True
            for next_parent in ancestor_map.get(parent_id, []):
                if next_parent not in seen:
                    seen.add(next_parent)
                    frontier.append(next_parent)
        return False

    if operation == "on_file_changed":
        changes = [
            c for c in changes
            if not c.get("removed") and not (c.get("file") or {}).get("trashed", False)
            and (c.get("file") or {}).get("mimeType") != _FOLDER_MIME
        ]
    elif operation == "on_file_removed":
        changes = [
            c for c in changes
            if (
                c.get("removed")
                and ((c.get("file") or {}).get("mimeType") != _FOLDER_MIME or not c.get("file"))
            ) or (
                (c.get("file") or {}).get("trashed", False)
                and (c.get("file") or {}).get("mimeType") != _FOLDER_MIME
            )
        ]
    elif operation == "on_folder_changed":
        changes = [
            c for c in changes
            if (c.get("file") or {}).get("mimeType") == _FOLDER_MIME
            and not c.get("removed")
            and not (c.get("file") or {}).get("trashed", False)
        ]
    elif operation == "on_folder_removed":
        changes = [
            c for c in changes
            if (
                (c.get("file") or {}).get("mimeType") == _FOLDER_MIME
                and (c.get("removed") or (c.get("file") or {}).get("trashed", False))
            ) or (
                c.get("removed") and not c.get("file")
            )
        ]
    else:
        changes = list(changes)  # on_drive_change: passthrough

    if watch_target_id and watch_target_kind == "file":
        changes = [c for c in changes if c.get("fileId") == watch_target_id]

    scope = watch_target_id if watch_target_kind == "folder" else watch_parent_folder_id
    if scope:
        scoped = []
        for c in changes:
            file_id = c.get("fileId") or ""
            parents = ((c.get("file") or {}).get("parents")) or []
            if _is_in_folder_tree(file_id, scope, parents):
                scoped.append(c)
        changes = scoped

    return changes


def _filter_calendar_events(operation: str, events: list) -> list:
    """Mirrors the filtering block inside GoogleCalendarNode._trigger_on_calendar_event."""
    if operation == "on_event_active":
        return [e for e in events if e.get("status") != "cancelled"]
    elif operation == "on_event_cancelled":
        return [e for e in events if e.get("status") == "cancelled"]
    return list(events)  # on_calendar_event: passthrough


# ============================================================
# Sample data
# ============================================================

_CHANGE_ACTIVE = {"fileId": "1", "removed": False, "file": {"id": "1", "name": "doc.txt", "mimeType": "text/plain", "trashed": False}}
_CHANGE_TRASHED = {"fileId": "2", "removed": False, "file": {"id": "2", "name": "old.txt", "mimeType": "text/plain", "trashed": True}}
_CHANGE_REMOVED = {"fileId": "3", "removed": True}  # permanently deleted — no file key

_FOLDER_ACTIVE = {"fileId": "4", "removed": False, "file": {"id": "4", "name": "MyFolder", "mimeType": _FOLDER_MIME, "trashed": False}}
_FOLDER_TRASHED = {"fileId": "5", "removed": False, "file": {"id": "5", "name": "OldFolder", "mimeType": _FOLDER_MIME, "trashed": True}}
_FOLDER_REMOVED = {"fileId": "6", "removed": True}  # permanently deleted folder — no file key
_CHANGE_ACTIVE_SCOPED = {"fileId": "7", "removed": False, "file": {"id": "7", "name": "nested.txt", "mimeType": "text/plain", "trashed": False, "parents": ["parent-a"]}}
_CHANGE_ACTIVE_OTHER_SCOPE = {"fileId": "8", "removed": False, "file": {"id": "8", "name": "other.txt", "mimeType": "text/plain", "trashed": False, "parents": ["parent-b"]}}
_CHANGE_ACTIVE_NESTED_DESCENDANT = {"fileId": "9", "removed": False, "file": {"id": "9", "name": "deep.txt", "mimeType": "text/plain", "trashed": False, "parents": ["folder-child"]}}
_FOLDER_ACTIVE_CHILD = {"fileId": "10", "removed": False, "file": {"id": "10", "name": "Child Folder", "mimeType": _FOLDER_MIME, "trashed": False, "parents": ["parent-a"]}}
_FOLDER_ACTIVE_GRANDCHILD = {"fileId": "11", "removed": False, "file": {"id": "11", "name": "Grandchild Folder", "mimeType": _FOLDER_MIME, "trashed": False, "parents": ["10"]}}

_ANCESTOR_MAP = {
    "folder-child": ["parent-a"],
    "10": ["parent-a"],
    "11": ["10"],
}

_ALL_DRIVE_CHANGES = [_CHANGE_ACTIVE, _CHANGE_TRASHED, _CHANGE_REMOVED]
_ALL_FOLDER_CHANGES = [_FOLDER_ACTIVE, _FOLDER_TRASHED, _FOLDER_REMOVED]

_EVENT_CONFIRMED = {"id": "ev1", "status": "confirmed", "summary": "Team sync"}
_EVENT_TENTATIVE = {"id": "ev2", "status": "tentativelyAccepted", "summary": "Maybe meeting"}
_EVENT_CANCELLED = {"id": "ev3", "status": "cancelled", "summary": "Old event"}

_ALL_CALENDAR_EVENTS = [_EVENT_CONFIRMED, _EVENT_TENTATIVE, _EVENT_CANCELLED]


# ============================================================
# Google Drive filter tests
# ============================================================


def test_drive_passthrough_returns_all_changes():
    result = _filter_drive_changes("on_drive_change", _ALL_DRIVE_CHANGES)
    assert len(result) == 3


def test_drive_on_file_changed_excludes_trashed_and_removed():
    result = _filter_drive_changes("on_file_changed", _ALL_DRIVE_CHANGES + [_FOLDER_ACTIVE])
    assert result == [_CHANGE_ACTIVE]


def test_drive_on_file_changed_empty_when_only_removals():
    result = _filter_drive_changes("on_file_changed", [_CHANGE_TRASHED, _CHANGE_REMOVED])
    assert result == []


def test_drive_on_file_removed_returns_trashed_and_removed():
    result = _filter_drive_changes("on_file_removed", _ALL_DRIVE_CHANGES)
    assert set(c["fileId"] for c in result) == {"2", "3"}


def test_drive_on_file_removed_empty_when_only_active():
    result = _filter_drive_changes("on_file_removed", [_CHANGE_ACTIVE])
    assert result == []


def test_drive_on_file_changed_passes_active_without_file_key():
    """Changes with no 'file' key and removed=False are treated as active."""
    change = {"fileId": "99", "removed": False}
    result = _filter_drive_changes("on_file_changed", [change])
    assert result == [change]


def test_drive_on_file_removed_missing_file_key_with_removed_flag():
    """A permanently deleted change may not have a 'file' key."""
    change = {"fileId": "99", "removed": True}
    result = _filter_drive_changes("on_file_removed", [change])
    assert result == [change]


def test_drive_watch_file_id_targets_single_file():
    result = _filter_drive_changes(
        "on_file_changed",
        [_CHANGE_ACTIVE_SCOPED, _CHANGE_ACTIVE_OTHER_SCOPE],
        watch_target_id="7",
        watch_target_kind="file",
    )
    assert result == [_CHANGE_ACTIVE_SCOPED]


def test_drive_folder_target_matches_descendant_files_recursively():
    result = _filter_drive_changes(
        "on_file_changed",
        [_CHANGE_ACTIVE_SCOPED, _CHANGE_ACTIVE_NESTED_DESCENDANT, _CHANGE_ACTIVE_OTHER_SCOPE],
        watch_target_id="parent-a",
        watch_target_kind="folder",
        ancestor_map=_ANCESTOR_MAP,
    )
    assert result == [_CHANGE_ACTIVE_SCOPED, _CHANGE_ACTIVE_NESTED_DESCENDANT]


def test_drive_folder_target_does_not_include_folder_change_events():
    result = _filter_drive_changes(
        "on_file_changed",
        [_FOLDER_ACTIVE_CHILD],
        watch_target_id="parent-a",
        watch_target_kind="folder",
        ancestor_map=_ANCESTOR_MAP,
    )
    assert result == []


def test_drive_empty_changes_list():
    assert _filter_drive_changes("on_file_changed", []) == []
    assert _filter_drive_changes("on_file_removed", []) == []
    assert _filter_drive_changes("on_drive_change", []) == []
    assert _filter_drive_changes("on_folder_changed", []) == []
    assert _filter_drive_changes("on_folder_removed", []) == []


# ── on_folder_changed ────────────────────────────────────────

def test_drive_on_folder_changed_includes_active_folder():
    result = _filter_drive_changes("on_folder_changed", _ALL_FOLDER_CHANGES)
    assert _FOLDER_ACTIVE in result
    assert _FOLDER_TRASHED not in result
    assert _FOLDER_REMOVED not in result


def test_drive_on_folder_changed_excludes_non_folders():
    result = _filter_drive_changes("on_folder_changed", _ALL_DRIVE_CHANGES)
    assert result == []


def test_drive_on_folder_changed_excludes_trashed_folder():
    result = _filter_drive_changes("on_folder_changed", [_FOLDER_TRASHED])
    assert result == []


def test_drive_folder_trigger_scope_matches_descendant_subfolders_recursively():
    result = _filter_drive_changes(
        "on_folder_changed",
        [_FOLDER_ACTIVE_CHILD, _FOLDER_ACTIVE_GRANDCHILD, _FOLDER_ACTIVE],
        watch_parent_folder_id="parent-a",
        ancestor_map=_ANCESTOR_MAP,
    )
    assert result == [_FOLDER_ACTIVE_CHILD, _FOLDER_ACTIVE_GRANDCHILD]


# ── on_folder_removed ────────────────────────────────────────

def test_drive_on_folder_removed_includes_trashed_folder():
    result = _filter_drive_changes("on_folder_removed", [_FOLDER_TRASHED])
    assert result == [_FOLDER_TRASHED]


def test_drive_on_folder_removed_includes_permanently_deleted_folder():
    """Bug fix: permanently deleted items (removed=True, no file key) must appear."""
    result = _filter_drive_changes("on_folder_removed", [_FOLDER_REMOVED])
    assert result == [_FOLDER_REMOVED]


def test_drive_on_folder_removed_excludes_active_folder():
    result = _filter_drive_changes("on_folder_removed", [_FOLDER_ACTIVE])
    assert result == []


def test_drive_on_folder_removed_excludes_active_file():
    """Active (non-trashed) files must not appear in on_folder_removed."""
    result = _filter_drive_changes("on_folder_removed", [_CHANGE_ACTIVE])
    assert result == []


def test_drive_on_folder_removed_includes_all_deleted_types():
    """Both trashed-folder and permanently-deleted items show up."""
    result = _filter_drive_changes("on_folder_removed", _ALL_FOLDER_CHANGES)
    ids = {c["fileId"] for c in result}
    assert "5" in ids  # trashed folder
    assert "6" in ids  # permanently deleted
    assert "4" not in ids  # active folder excluded


def test_drive_on_folder_removed_trashed_file_excluded():
    """A trashed plain FILE must not appear (mimeType != folder)."""
    result = _filter_drive_changes("on_folder_removed", [_CHANGE_TRASHED])
    assert result == []


# ============================================================
# Google Calendar filter tests
# ============================================================


def test_calendar_passthrough_returns_all_events():
    result = _filter_calendar_events("on_calendar_event", _ALL_CALENDAR_EVENTS)
    assert len(result) == 3


def test_calendar_on_event_active_excludes_cancelled():
    result = _filter_calendar_events("on_event_active", _ALL_CALENDAR_EVENTS)
    assert _EVENT_CANCELLED not in result
    assert _EVENT_CONFIRMED in result
    assert _EVENT_TENTATIVE in result


def test_calendar_on_event_active_empty_when_only_cancelled():
    result = _filter_calendar_events("on_event_active", [_EVENT_CANCELLED])
    assert result == []


def test_calendar_on_event_cancelled_returns_only_cancelled():
    result = _filter_calendar_events("on_event_cancelled", _ALL_CALENDAR_EVENTS)
    assert result == [_EVENT_CANCELLED]


def test_calendar_on_event_cancelled_empty_when_no_cancels():
    result = _filter_calendar_events("on_event_cancelled", [_EVENT_CONFIRMED, _EVENT_TENTATIVE])
    assert result == []


def test_calendar_on_event_active_includes_tentative():
    """tentativelyAccepted is not cancelled and should appear in on_event_active."""
    result = _filter_calendar_events("on_event_active", [_EVENT_TENTATIVE])
    assert result == [_EVENT_TENTATIVE]


def test_calendar_empty_events_list():
    assert _filter_calendar_events("on_event_active", []) == []
    assert _filter_calendar_events("on_event_cancelled", []) == []
    assert _filter_calendar_events("on_calendar_event", []) == []


# ============================================================
# Schema verification — x-is-trigger flag and operation const
# ============================================================

_FRONTEND_SCHEMAS = pathlib.Path(__file__).parents[2] / "frontend" / "app" / "schemas" / "nodes"


def test_drive_schema_has_all_trigger_operations():
    schema = json.loads((_FRONTEND_SCHEMAS / "google-drive.json").read_text())
    defs = schema.get("$defs", {})
    expected = [
        ("GoogleDriveOnChangeConfig", "on_drive_change"),
        ("GoogleDriveOnFileChangedConfig", "on_file_changed"),
        ("GoogleDriveOnFileRemovedConfig", "on_file_removed"),
        ("GoogleDriveOnFolderChangedConfig", "on_folder_changed"),
        ("GoogleDriveOnFolderRemovedConfig", "on_folder_removed"),
    ]
    for class_name, expected_op in expected:
        op_field = defs.get(class_name, {}).get("properties", {}).get("operation", {})
        assert op_field.get("x-is-trigger") is True, f"{class_name} missing x-is-trigger"
        assert op_field.get("const") == expected_op, f"{class_name} wrong const: {op_field.get('const')!r}"


def test_calendar_schema_has_all_trigger_operations():
    schema = json.loads((_FRONTEND_SCHEMAS / "google-calendar.json").read_text())
    defs = schema.get("$defs", {})
    expected = [
        ("GoogleCalendarOnEventConfig", "on_calendar_event"),
        ("GoogleCalendarOnEventCancelledConfig", "on_event_cancelled"),
        ("GoogleCalendarOnEventCreatedConfig", "on_event_created"),
        ("GoogleCalendarOnEventUpdatedConfig", "on_event_updated"),
        ("GoogleCalendarOnEventTentativeConfig", "on_event_tentative"),
    ]
    for class_name, expected_op in expected:
        op_field = defs.get(class_name, {}).get("properties", {}).get("operation", {})
        assert op_field.get("x-is-trigger") is True, f"{class_name} missing x-is-trigger"
        assert op_field.get("const") == expected_op, f"{class_name} wrong const: {op_field.get('const')!r}"


def test_drive_schema_discriminator_includes_all_ops():
    schema = json.loads((_FRONTEND_SCHEMAS / "google-drive.json").read_text())
    mapping = schema.get("properties", {}).get("config", {}).get("discriminator", {}).get("mapping", {})
    for op in ("on_file_changed", "on_file_removed", "on_folder_changed", "on_folder_removed"):
        assert op in mapping, f"{op} missing from Drive discriminator"


def test_drive_schema_exposes_specific_file_watchers():
    schema = json.loads((_FRONTEND_SCHEMAS / "google-drive.json").read_text())
    defs = schema.get("$defs", {})
    for class_name in ("GoogleDriveOnFileChangedConfig", "GoogleDriveOnFileRemovedConfig"):
        watch_target = defs[class_name]["properties"]["watch_target_id"]
        assert watch_target["x-dynamic-options"]["field_name"] == "watch_target_id"
        assert "watch_folder_id" not in defs[class_name]["properties"]
        assert "watch_file_id" not in defs[class_name]["properties"]


def test_calendar_schema_discriminator_includes_all_ops():
    schema = json.loads((_FRONTEND_SCHEMAS / "google-calendar.json").read_text())
    mapping = schema.get("properties", {}).get("config", {}).get("discriminator", {}).get("mapping", {})
    for op in ("on_event_cancelled", "on_event_created", "on_event_updated", "on_event_tentative"):
        assert op in mapping, f"{op} missing from Calendar discriminator"
    assert "on_event_active" not in mapping
