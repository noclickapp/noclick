"""Actionstep REST v1 routes, pinned to docs.actionstep.com/downloads/*.yaml.

The resource names are Actionstep's wire names; contacts are participants and
matters are actions. Writes use the documented resource envelope.
"""
OPERATIONS = {
    "list_matters": ("GET", "actions", False),
    "get_matter": ("GET", "actions", True),
    "list_contacts": ("GET", "participants", False),
    "get_contact": ("GET", "participants", True),
    "create_contact": ("POST", "participants", False),
    "update_contact": ("PUT", "participants", True),
    "list_tasks": ("GET", "tasks", False),
    "get_task": ("GET", "tasks", True),
    "create_task": ("POST", "tasks", False),
    "update_task": ("PUT", "tasks", True),
    "delete_task": ("DELETE", "tasks", True),
    "list_file_notes": ("GET", "filenotes", False),
    "get_file_note": ("GET", "filenotes", True),
    "create_file_note": ("POST", "filenotes", False),
    "update_file_note": ("PUT", "filenotes", True),
    "delete_file_note": ("DELETE", "filenotes", True),
    "list_time_entries": ("GET", "timeentries", False),
    "get_time_entry": ("GET", "timeentries", True),
    "list_matter_types": ("GET", "actiontypes", False),
}
