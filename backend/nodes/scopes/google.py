"""Google Workspace operation → OAuth scope requirements.

Eight nodes share one module because they share one scope vocabulary: Google
issues a single token per credential whose granted scopes span every API the
project enables, so ``drive`` requested by the Docs node is the same string the
Drive node requests. One registry per node keyed on the operation name, since
none of these nodes has a central request helper to key endpoints on.

Requirements were derived from Google's API **discovery documents** (e.g.
``https://www.googleapis.com/discovery/v1/apis/drive/v3/rest``), which carry the
authoritative per-method ``scopes`` array — the same data the published method
reference renders as "Authorization scopes". Each operation was mapped to the
concrete API method(s) its handler calls, then to that method's scope list.

Two Google-specific facts shape the tables:

- **Scopes nest.** Google publishes readonly/write pairs (``drive.readonly`` vs
  ``drive``, ``tasks.readonly`` vs ``tasks``, ``documents.readonly`` vs
  ``documents``), and the broad scope subsumes the narrow one. These nodes
  request only the broad scope of each pair, so the narrowest scope that both
  authorizes a call AND is actually granted is the broad one — declaring
  ``drive.readonly`` for a read would be a phantom "missing scope" for a
  permission the token already holds. Where a genuinely narrower scope exists
  and is requested, it is used: the Forms node's response reads take
  ``forms.responses.readonly``, not ``forms.body``.
- **Reads never claim write scopes and writes never claim readonly ones.** The
  grouping below is by required scope precisely so that is checkable by eye.

Not represented here: ``load_field_options`` dropdown loaders. Docs, Slides,
Forms and Sheets all list their documents through Drive ``files.list``, which is
why those nodes request a Drive scope beyond their own API's — Sheets narrows it
to ``drive.metadata.readonly``, the other three request full ``drive``. Loaders
are not operations, so they have no registry key; the scopes they need are
covered by the requested list either way.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

CALENDAR = "https://www.googleapis.com/auth/calendar"
CONTACTS = "https://www.googleapis.com/auth/contacts"
DOCUMENTS = "https://www.googleapis.com/auth/documents"
DRIVE = "https://www.googleapis.com/auth/drive"
FORMS_BODY = "https://www.googleapis.com/auth/forms.body"
FORMS_RESPONSES_READONLY = "https://www.googleapis.com/auth/forms.responses.readonly"
PRESENTATIONS = "https://www.googleapis.com/auth/presentations"
SPREADSHEETS = "https://www.googleapis.com/auth/spreadsheets"
TASKS = "https://www.googleapis.com/auth/tasks"


def _table(groups: dict[str, tuple[str, ...]]) -> dict[str, ScopeRequirement]:
    """``{scope: operations needing it}`` → ``{operation: requirement}``.

    Grouped by scope rather than listed per operation so a reviewer can see at a
    glance that no write operation sits under a readonly scope.
    """
    return {
        operation: ScopeRequirement(scopes=(scope,))
        for scope, operations in groups.items()
        for operation in operations
    }


# ---------------------------------------------------------------------------
# Drive — drive/v3 throughout, including the change-feed triggers.
# ---------------------------------------------------------------------------
# Every method the node calls accepts `drive`, and several accept nothing else:
# `files.emptyTrash` and the whole `drives.*` (shared drive) resource are
# `drive`-only, so no narrowing of this node is possible without dropping
# operations. Triggers poll `changes.list` and manage `changes.watch` /
# `channels.stop`, all of which `drive` covers.
GOOGLE_DRIVE_SCOPES = ScopeRegistry(
    provider="google-drive",
    requirements=_table(
        {
            DRIVE: (
                # files
                "list_files",
                "search_files",
                "get_file_metadata",
                "update_file_metadata",
                "download_file",
                "export_google_workspace_file",
                "upload_file",
                "copy_file",
                "move_file",
                "delete_file",
                "create_folder",
                "move_file_to_trash",
                "restore_file_from_trash",
                "empty_drive_trash",
                # permissions
                "share_file",
                "list_file_permissions",
                "get_file_permission",
                "update_file_permission",
                "remove_file_permission",
                # comments and replies
                "create_file_comment",
                "list_file_comments",
                "get_file_comment",
                "update_file_comment",
                "delete_file_comment",
                "create_comment_reply",
                "list_comment_replies",
                "get_comment_reply",
                "update_comment_reply",
                "delete_comment_reply",
                # revisions
                "list_file_revisions",
                "get_file_revision",
                "update_file_revision",
                "delete_file_revision",
                # shared drives
                "list_shared_drives",
                "get_shared_drive",
                "create_shared_drive",
                "delete_shared_drive",
                "hide_shared_drive",
                "unhide_shared_drive",
                # account
                "get_drive_storage_info",
                # triggers (changes.watch + changes.list + channels.stop)
                "on_drive_change",
                "on_file_changed",
                "on_file_removed",
                "on_folder_changed",
                "on_folder_removed",
            ),
        }
    ),
)


# ---------------------------------------------------------------------------
# Sheets — sheets/v4 throughout; the `on_new_row` trigger polls values.get.
# ---------------------------------------------------------------------------
# The node also requests `drive.metadata.readonly`, used only by the spreadsheet
# dropdown loader (Drive `files.list`), which is not an operation.
GOOGLE_SHEETS_SCOPES = ScopeRegistry(
    provider="google-sheets",
    requirements=_table(
        {
            SPREADSHEETS: (
                # values
                "read_sheet_data",
                "read_multiple_sheet_ranges",
                "write_sheet_data",
                "write_to_multiple_sheet_ranges",
                "append_rows_to_sheet",
                "clear_sheet_range",
                "clear_multiple_sheet_ranges",
                # spreadsheet / sheet structure (spreadsheets.batchUpdate)
                "create_new_spreadsheet",
                "fetch_spreadsheet_metadata",
                "add_spreadsheet_sheet",
                "delete_spreadsheet_sheet",
                "rename_spreadsheet_sheet",
                "duplicate_sheet_in_spreadsheet",
                "copy_sheet_to_spreadsheet",
                "find_and_replace_in_spreadsheet",
                "insert_sheet_rows",
                "delete_sheet_rows",
                "insert_sheet_columns",
                "delete_sheet_columns",
                # formatting / presentation (also spreadsheets.batchUpdate, so
                # the existing read-write `spreadsheets` scope already covers them)
                "format_cells",
                "update_sheet_properties",
                "auto_resize_dimensions",
                "set_dimension_size",
                "merge_cells",
                "unmerge_cells",
                "format_borders",
                "add_alternating_colors",
                "set_basic_filter",
                "clear_basic_filter",
                "add_conditional_format_rule",
                "sort_range",
                "set_data_validation",
                "clear_data_validation",
                "delete_conditional_format_rules",
                "clear_alternating_colors",
                "add_table",
                "update_conditional_format_rule",
                "update_alternating_colors",
                "update_table",
                "update_spreadsheet_properties",
                "add_named_range",
                "update_named_range",
                "delete_named_range",
                "add_protected_range",
                "update_protected_range",
                "delete_protected_range",
                "set_cell_notes",
                "insert_smart_chips",
                "insert_pivot_table",
                "copy_paste_range",
                "cut_paste_range",
                "paste_data",
                "auto_fill",
                "split_text_to_columns",
                "trim_whitespace",
                "remove_duplicate_rows",
                "randomize_range",
                "insert_cells",
                "delete_cells",
                "move_rows_or_columns",
                "append_rows_or_columns",
                "add_chart",
                "update_chart",
                "move_chart",
                "set_chart_border",
                "delete_chart",
                "append_cells",
                "save_filter_view",
                "update_filter_view",
                "duplicate_filter_view",
                "delete_filter_view",
                "group_rows_or_columns",
                "collapse_group",
                "ungroup_rows_or_columns",
                "add_slicer",
                "update_slicer",
                "create_developer_metadata",
                "update_developer_metadata",
                "delete_developer_metadata",
                "add_data_source",
                "repoint_data_source",
                "delete_data_source",
                "refresh_data_source",
                "cancel_data_source_refresh",
                "delete_table",
                # trigger
                "on_new_row",
            ),
        }
    ),
)


# ---------------------------------------------------------------------------
# Calendar — calendar/v3 throughout.
# ---------------------------------------------------------------------------
# The triggers open an `events.watch` channel and read `events.list`; the write
# operations span events, calendars and calendarList. `calendar` is the only
# scope that covers all three resources, so per-resource narrowing (
# `calendar.events`, `calendar.calendars`, `calendar.freebusy`) would need
# several new scopes rather than one.
GOOGLE_CALENDAR_SCOPES = ScopeRegistry(
    provider="google-calendar",
    requirements=_table(
        {
            CALENDAR: (
                # events
                "list_calendar_events",
                "fetch_calendar_event",
                "create_calendar_event",
                "create_event_from_text",
                "update_calendar_event",
                "delete_calendar_event",
                "move_event_to_calendar",
                "fetch_recurring_event_instances",
                # calendars
                "list_user_calendars",
                "fetch_calendar_metadata",
                "create_new_calendar",
                "clear_calendar_events",
                # freebusy
                "query_calendar_availability",
                # triggers (events.watch + events.list + channels.stop)
                "on_calendar_event",
                "on_event_created",
                "on_event_updated",
                "on_event_cancelled",
                "on_event_tentative",
                # Retired from the operation picker but still dispatchable for
                # workflows saved before it was hidden.
                "on_event_active",
            ),
        }
    ),
)


# ---------------------------------------------------------------------------
# Docs — docs/v1, except the document picker which lists via Drive.
# ---------------------------------------------------------------------------
GOOGLE_DOCS_SCOPES = ScopeRegistry(
    provider="google-docs",
    requirements=_table(
        {
            DOCUMENTS: (
                "fetch_document_content",
                "create_new_document",
                "append_text_to_document",
                "insert_text_in_document",
                "replace_document_text",
            ),
            # Drive `files.list` filtered to the Docs mime type.
            DRIVE: ("list_google_drive_documents",),
        }
    ),
)


# ---------------------------------------------------------------------------
# Slides — slides/v1, except the presentation picker which lists via Drive.
# ---------------------------------------------------------------------------
GOOGLE_SLIDES_SCOPES = ScopeRegistry(
    provider="google-slides",
    requirements=_table(
        {
            PRESENTATIONS: (
                "get_presentation_metadata",
                "create_new_presentation",
                "add_presentation_slide",
                "delete_presentation_slide",
                "get_slide_page",
                "get_slide_thumbnail",
            ),
            # Drive `files.list` filtered to the Slides mime type.
            DRIVE: ("list_google_drive_presentations",),
        }
    ),
)


# ---------------------------------------------------------------------------
# Forms — forms/v1, except the form picker which lists via Drive.
# ---------------------------------------------------------------------------
# The only node here whose scopes genuinely split read from write: responses are
# readable with `forms.responses.readonly` alone, and `forms.body` does NOT
# grant them. The trigger polls `forms.responses.list`, so it takes the response
# scope rather than the body one.
GOOGLE_FORMS_SCOPES = ScopeRegistry(
    provider="google-forms",
    requirements=_table(
        {
            FORMS_BODY: (
                "create_new_form",
                "get_form_metadata",
                "update_form_metadata",
            ),
            FORMS_RESPONSES_READONLY: (
                "list_form_responses",
                "get_form_response",
                "on_form_response",
            ),
            # Drive `files.list` filtered to the Forms mime type.
            DRIVE: ("list_google_drive_forms",),
        }
    ),
)


# ---------------------------------------------------------------------------
# Tasks — tasks/v1 throughout.
# ---------------------------------------------------------------------------
GOOGLE_TASKS_SCOPES = ScopeRegistry(
    provider="google-tasks",
    requirements=_table(
        {
            TASKS: (
                # task lists
                "list_all_task_lists",
                "fetch_task_list",
                "create_new_task_list",
                "update_task_list_metadata",
                "delete_task_list",
                # tasks
                "list_tasks_in_list",
                "fetch_task_from_list",
                "create_new_task",
                "update_task_in_list",
                "delete_task_from_list",
                "move_task_to_position",
                "clear_completed_tasks",
            ),
        }
    ),
)


# ---------------------------------------------------------------------------
# Contacts — People API v1, `people.*` and `contactGroups.*`.
# ---------------------------------------------------------------------------
# Only the user's own contacts are touched. `otherContacts.*` and the directory
# methods need scopes of their own (`contacts.other.readonly`,
# `directory.readonly`) and no operation calls them.
GOOGLE_CONTACTS_SCOPES = ScopeRegistry(
    provider="google-contacts",
    requirements=_table(
        {
            CONTACTS: (
                # contacts
                "list_contacts",
                "get_contact",
                "search_contacts",
                "create_contact",
                "update_contact",
                "delete_contact",
                # contact groups
                "list_contact_groups",
                "get_contact_group",
                "create_contact_group",
                "update_contact_group",
                "delete_contact_group",
            ),
        }
    ),
)
