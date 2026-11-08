"""Fixed operations from https://docs.smokeball.com/openapi.json v1.0."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    scopes: tuple[str, ...]

OPERATIONS = {
    "get_firm": Operation("GET", "/firm", ("firm/read",)),
    "list_staff": Operation("GET", "/staff", ("staff/read",)),
    "list_matter_types": Operation("GET", "/mattertypes", ("mattertypes/read",)),
    "list_contacts": Operation("GET", "/contacts", ("contacts/read",)),
    "get_contact": Operation("GET", "/contacts/{contact_id}", ("contacts/read",)),
    "create_contact": Operation("POST", "/contacts", ("contacts/write",)),
    "update_contact": Operation("PUT", "/contacts/{contact_id}", ("contacts/write",)),
    "list_matters": Operation("GET", "/matters", ("matters/read",)),
    "get_matter": Operation("GET", "/matters/{matter_id}", ("matters/read",)),
    "create_matter": Operation("POST", "/matters", ("matters/write",)),
    "update_matter": Operation("PUT", "/matters/{matter_id}", ("matters/write",)),
    "list_tasks": Operation("GET", "/tasks", ("tasks/read",)),
    "get_task": Operation("GET", "/tasks/{task_id}", ("tasks/read",)),
    "create_task": Operation("POST", "/tasks", ("tasks/write",)),
    "update_task": Operation("PUT", "/tasks/{task_id}", ("tasks/write",)),
    "list_events": Operation("GET", "/events", ("events/read",)),
    "get_event": Operation("GET", "/events/{event_id}", ("events/read",)),
    "create_event": Operation("POST", "/events", ("events/write",)),
    "list_memos": Operation("GET", "/matters/{matter_id}/memos", ("matters/read", "memos/read")),
    "create_memo": Operation("POST", "/matters/{matter_id}/memos", ("matters/write", "memos/write")),
}
