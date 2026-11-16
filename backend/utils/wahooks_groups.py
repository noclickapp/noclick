"""WhatsApp groups on a QR-linked connection, through WAHooks' group routes, with NoClick's one WAHooks key. Callers
gate access: a connection id comes here only from a credential the caller may use.

- ``POST /connections/{id}/groups`` ``{name, participants?}`` creates one: the group, and ``notAdded`` per person.
- ``GET .../groups/{group}`` reads one (``?refresh=true`` skips WAHooks' copy, kept up to 60 s and dropped on any
  group event); ``PATCH`` renames it.
- ``POST .../participants/add`` and ``/remove`` answer per person: ``added``, ``removed``, ``already_member``,
  ``not_member``, or ``failed`` with WhatsApp's ``code``.
- ``POST .../leave``; ``GET .../invite-link`` and ``POST .../invite-link/revoke`` (an admin's).

A group is ``{id, name, description, owner, createdAt, participantCount, participants: [{id, phone, lid, name, role
(superadmin|admin|member), isMe}], announcementOnly, locked, isCommunity}``. A member may be named by ``id`` or
``lid`` (a sender named by @lid is the same person), and ``phone`` is null where WhatsApp hides the number. A
failure raises ``GroupError``, whose message says plainly what happened and what to do.
"""

import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

import httpx

from utils.phone_numbers import normalize_e164, readable

logger = logging.getLogger(__name__)

FETCH_TIMEOUT_S = 20.0
MAX_PARTICIPANTS = 256
# Members a group's turn names; the rest are counted.
TURN_MEMBERS = 30

_STATUS_WHY = {
    400: "WhatsApp refused it",
    403: ("this WhatsApp account isn't in that group, or isn't one of its admins (adding or removing people, "
          "renaming a locked group and its invite link take an admin)"),
    404: "this WhatsApp account has no such group (WhatsApp deletes a group once its last member leaves)",
    409: ("the WhatsApp connection isn't connected right now: its phone has to be linked again by scanning this "
          "credential's QR code"),
    429: "WhatsApp is limiting how fast this account changes groups: wait a minute, then try again",
    502: "WhatsApp couldn't be reached: try again shortly",
}
# Why one person wasn't added, by the code WhatsApp gave.
_NOT_ADDED_WHY = {
    403: "their privacy settings let only their contacts add them to groups: send them the group's invite link",
    404: "that number isn't on WhatsApp",
    408: "they left this group recently, so WhatsApp won't add them back yet: send them the group's invite link",
}


class GroupError(Exception):
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def group_jid(value: Any) -> str:
    """A group's id as WAHooks takes it (``<digits>@g.us``; bare digits are taken as one)."""
    raw = str(value or "").strip()
    local, at, server = raw.partition("@")
    if not at and local and all(c.isdigit() or c == "-" for c in local):
        server = "g.us"
    if server != "g.us" or not local:
        raise ValueError(f"{raw!r} isn't a WhatsApp group id: a group's id ends in @g.us, as a message from the "
                         "group names it.")
    return f"{local}@g.us"


def participant_ids(values: Any) -> List[str]:
    """People as WAHooks takes them: a phone number in international form (digits) or a ``@c.us``/``@lid`` id."""
    if isinstance(values, str):
        values = values.replace("\n", ",").split(",")
    out: List[str] = []
    for value in values or ():
        raw = str(value or "").strip()
        if not raw:
            continue
        local, at, server = raw.partition("@")
        if at:
            if not local or server not in ("c.us", "s.whatsapp.net", "lid"):
                raise ValueError(f"{raw!r} isn't a person's WhatsApp id (one ends in @c.us or @lid).")
            out.append(f"{local.split(':', 1)[0]}@c.us" if server == "s.whatsapp.net" else raw)
            continue
        number = normalize_e164(raw if raw.startswith(("+", "00")) else f"+{raw}")
        if number is None:
            raise ValueError(f"{raw!r} isn't a phone number in international form (with its country code, "
                             "e.g. +12025550100).")
        out.append(number.lstrip("+"))
    out = list(dict.fromkeys(out))
    if len(out) > MAX_PARTICIPANTS:
        raise ValueError(f"A group change takes at most {MAX_PARTICIPANTS} people at once; this named {len(out)}.")
    return out


def _path(connection_id: str, group_id: Optional[str] = None, *rest: str) -> str:
    parts = ["connections", quote(connection_id, safe=""), "groups"]
    if group_id:
        parts.append(quote(group_id, safe="@"))
    return "/" + "/".join([*parts, *rest])


def _plainly(status: int, detail: str) -> str:
    why = _STATUS_WHY.get(status) or f"WhatsApp answered {status}"
    said = f" ({detail})" if detail and detail.rstrip(".").lower() not in why.lower() else ""
    return f"{why[0].upper()}{why[1:]}{said}."


async def _call(method: str, path: str, *, body: Any = None, params: Optional[Dict[str, str]] = None,
                timeout: float = FETCH_TIMEOUT_S) -> Any:
    from utils.wahooks_connections import get_wahooks_api_key, wahooks_http

    api_key = get_wahooks_api_key()
    if not api_key:
        raise GroupError("WhatsApp QR service is not configured; set WAHOOKS_API_KEY on this backend.")
    try:
        async with wahooks_http(api_key, timeout=timeout) as client:
            response = await client.request(method, path, json=body, params=params)
    except httpx.HTTPError as e:
        raise GroupError(f"WhatsApp couldn't be reached ({type(e).__name__}): try again shortly.") from e
    try:
        data = response.json() if response.content else None
    except ValueError:
        data = None
    if response.is_success:
        return data
    detail = str(data.get("message") or data.get("error") or "") if isinstance(data, dict) else ""
    raise GroupError(_plainly(response.status_code, detail.strip()), response.status_code)


def _group(data: Any) -> Dict[str, Any]:
    if not (isinstance(data, dict) and isinstance(data.get("participants"), list)):
        raise GroupError("WAHooks answered without the group's members.")
    return data


async def get_group(connection_id: str, group_id: str, *, refresh: bool = False,
                    timeout: float = FETCH_TIMEOUT_S) -> Dict[str, Any]:
    return _group(await _call("GET", _path(connection_id, group_id), params={"refresh": "true"} if refresh else None,
                              timeout=timeout))


async def create_group(connection_id: str, name: str, participants: List[str]) -> Dict[str, Any]:
    return _group(await _call("POST", _path(connection_id),
                              body={"name": name, **({"participants": participants} if participants else {})}))


async def rename_group(connection_id: str, group_id: str, name: str) -> Dict[str, Any]:
    return await _call("PATCH", _path(connection_id, group_id), body={"name": name})


async def change_participants(connection_id: str, group_id: str, participants: List[str], *,
                              add: bool) -> List[Dict[str, Any]]:
    data = await _call("POST", _path(connection_id, group_id, "participants", "add" if add else "remove"),
                       body={"participants": participants})
    entries = data.get("participants") if isinstance(data, dict) else None
    return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []


async def leave_group(connection_id: str, group_id: str) -> None:
    await _call("POST", _path(connection_id, group_id, "leave"))


async def invite_link(connection_id: str, group_id: str, *, revoke: bool = False) -> str:
    if revoke:
        data = await _call("POST", _path(connection_id, group_id, "invite-link", "revoke"))
    else:
        data = await _call("GET", _path(connection_id, group_id, "invite-link"))
    link = data.get("link") if isinstance(data, dict) else None
    if not link:
        raise GroupError("WAHooks answered without the group's invite link.")
    return str(link)


# --------------------------------------------------------------------------- what an agent reads


def _key(jid: Any) -> str:
    local, _, server = str(jid or "").strip().partition("@")
    return f"{local.split(':', 1)[0]}@{'c.us' if server == 's.whatsapp.net' else server}" if local else ""


def is_member(participant: Dict[str, Any], jid: str) -> bool:
    """Whether ``participant`` is the person ``jid`` names, by their ``id`` or their ``lid``."""
    return bool(_key(jid)) and _key(jid) in {_key(participant.get("id")), _key(participant.get("lid"))}


def _admin(participant: Optional[Dict[str, Any]]) -> bool:
    return bool(participant) and participant.get("role") in ("admin", "superadmin")


def _phone(participant: Dict[str, Any]) -> Optional[str]:
    digits = "".join(c for c in str(participant.get("phone") or "") if c.isdigit())
    return (readable(digits) or f"+{digits}") if digits else None


def member(participant: Dict[str, Any]) -> Dict[str, Any]:
    """A member as an agent reads one. Their ``name`` is dropped where it's only their number."""
    phone = _phone(participant)
    name = str(participant.get("name") or "").strip() or None
    if name and phone and "".join(c for c in name if c.isdigit()) == "".join(c for c in phone if c.isdigit()):
        name = None
    return {"id": participant.get("id") or participant.get("lid"), "name": name, "phone": phone,
            "role": "admin" if _admin(participant) else "member"}


def _others(group: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Its members but the account itself, admins first."""
    others = [p for p in group.get("participants") or [] if isinstance(p, dict) and not p.get("isMe")]
    return sorted(others, key=lambda p: not _admin(p))


def _me(group: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return next((p for p in group.get("participants") or [] if isinstance(p, dict) and p.get("isMe")), None)


def summary(group: Dict[str, Any]) -> Dict[str, Any]:
    """A group as ``get_group`` answers it."""
    me = _me(group)
    return {"group_id": group.get("id"), "name": group.get("name"), "description": group.get("description"),
            "member_count": group.get("participantCount") or len(group.get("participants") or []),
            "you_are_admin": _admin(me) if me else None, "only_admins_send": bool(group.get("announcementOnly")),
            "only_admins_edit": bool(group.get("locked")), "is_community": bool(group.get("isCommunity")),
            "members": [member(p) for p in _others(group)]}


def turn_record(group: Dict[str, Any], sender: str = "") -> Dict[str, Any]:
    """What a group message's delivery keeps of its group (``payload["group"]``), for its turn to name: its other
    members, admins first (at most ``TURN_MEMBERS``), whether the account and the sender are admins."""
    others = _others(group)
    me = _me(group)
    writer = next((p for p in others if is_member(p, sender)), None) if sender else None
    return {"name": str(group.get("name") or "").strip() or None,
            "admin": _admin(me) if me else None, "sender_admin": _admin(writer) if writer else None,
            "members": [member(p) for p in others[:TURN_MEMBERS]], "more": max(0, len(others) - TURN_MEMBERS)}


def member_label(m: Dict[str, Any]) -> str:
    """A ``member`` as a sentence names them: name (number or hidden number, admin)."""
    marks = [m.get("phone") or "hidden number", *(["admin"] if m.get("role") == "admin" else [])]
    if m.get("name"):
        return f"{m['name']} ({', '.join(marks)})"
    who = m.get("phone") or "someone with a hidden number"
    return f"{who} (admin)" if m.get("role") == "admin" else who


def members_note(record: Optional[Dict[str, Any]]) -> str:
    """The sentences a group message's turn says of who's in the group (``turn_record``), or that they're unknown."""
    if not (isinstance(record, dict) and isinstance(record.get("members"), list)):
        return " Its members are unknown: the member list couldn't be read just now."
    shown, more = record["members"], int(record.get("more") or 0)
    count = len(shown) + more
    if not count:
        note = " No one else is in it."
    else:
        people = ", ".join(member_label(m) for m in shown) + (f", and {more} more" if more else "")
        note = f" It has {count} member{'s' if count != 1 else ''} besides you: {people}."
    if record.get("sender_admin"):
        note += " The sender is one of its admins."
    if record.get("admin") is True:
        note += " You're one of its admins."
    elif record.get("admin") is False:
        note += " You aren't one of its admins, so you can't add or remove people or share its invite link."
    return note


def _who(entry: Dict[str, Any]) -> str:
    return _phone(entry) or readable(entry.get("id")) or str(entry.get("id") or entry.get("lid") or "someone")


def people_results(entries: Iterable[Dict[str, Any]], *, add: bool) -> Tuple[List[Dict[str, Any]], str]:
    """Per person, what an add or a removal did, and one plain line saying it (who was, who wasn't and why)."""
    done_word, undone_word = ("added", "not added") if add else ("removed", "not removed")
    outcome_of = {"added": "added", "removed": "removed", "already_member": "already in the group",
                  "not_member": "not in the group"}
    people: List[Dict[str, Any]] = []
    for entry in entries:
        outcome = outcome_of.get(str(entry.get("status") or ""), undone_word)
        person = {"who": _who(entry), "id": entry.get("id") or entry.get("lid"), "outcome": outcome}
        if outcome == undone_word:
            code = entry.get("code")
            person["why"] = ((_NOT_ADDED_WHY.get(code) if add else None) or str(entry.get("reason") or "").strip()
                             or f"WhatsApp refused it{f' (code {code})' if code else ''}")
        people.append(person)
    groups: Dict[str, List[str]] = {}
    for p in people:
        groups.setdefault(p["outcome"], []).append(f"{p['who']} ({p['why']})" if "why" in p else p["who"])
    line = " ".join(f"{outcome[0].upper()}{outcome[1:]}: {'; '.join(names)}."
                    for outcome, names in sorted(groups.items(), key=lambda kv: kv[0] != done_word))
    return people, line or f"No one was {done_word}."
