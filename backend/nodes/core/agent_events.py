"""Shared shaping behind every trigger's ``resolve_agent_event``.

A fired trigger's output is a delivery envelope around a provider payload,
and the payload itself carries transport fields (tokens, authorization
blocks, block-kit duplicates of the text) that mean nothing to the agent
reading it. The default hook in ``WorkflowNode`` and the per-provider
overrides shape their text with these helpers so the turn the model reads
and the record the chat surface stores are both bounded and free of
plumbing. The frontend mirror is ``runStory.ts:sanitizeEventPayload``.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Bytes of pretty-printed JSON the model turn carries before it is cut.
DEFAULT_EVENT_CHARS = 4000

# Per-string ceiling in the record persisted for the chat surface — a
# pasted log inside one field must not swallow the conversation row.
DISPLAY_STRING_CHARS = 2000
DISPLAY_RECORD_CHARS = 24_000

# Routing ids the delivery plumbing adds around a fired payload — never
# content, whichever shape the payload takes.
ROUTING_KEYS = frozenset(
    {
        "schedule_id",
        "workflow_id",
        "user_id",
        "node_id",
        "execution_id",
        "webhook_id",
        "triggered_at",
        "source",
        "timing_ms",
    }
)

# One object-valued wrapper is unwrapped when present, in this order. Its
# scalar siblings (``type: "slack"``, ``status``, ``action``) describe the
# wrapper and become the envelope; with no wrapper, a payload's own scalars
# are its content (GitHub's ``action``, a provider's ``type``) and stay.
_WRAPPER_KEYS = ("payload", "data", "body", "event", "message")


def prune_empty(value: Any, *, max_str: Optional[int] = None) -> Any:
    """Drop ``None``/``""``/empty containers and ``_``-prefixed keys
    recursively; optionally clip long strings. Pure."""
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and k.startswith("_"):
                continue
            pv = prune_empty(v, max_str=max_str)
            if pv is None or pv == "" or pv == [] or pv == {}:
                continue
            out[k] = pv
        return out
    if isinstance(value, (list, tuple)):
        items = [prune_empty(v, max_str=max_str) for v in value]
        return [v for v in items if not (v is None or v == "" or v == [] or v == {})]
    if isinstance(value, str) and max_str is not None and len(value) > max_str:
        return value[:max_str] + f"… [{len(value) - max_str} more chars]"
    return value


def unwrap_trigger_output(output: Any) -> Tuple[Any, Dict[str, Any]]:
    """``(payload, envelope)`` of a fired trigger's output.

    The payload is the first object wrapper (``payload``/``data``/``body``/
    ``event``/``message``) when one exists, its scalar siblings forming the
    envelope; else the output minus routing ids and ``_``-prefixed plumbing,
    with an empty envelope. A non-dict output is its own payload.
    """
    if not isinstance(output, dict):
        return output, {}
    for key in _WRAPPER_KEYS:
        inner = output.get(key)
        if isinstance(inner, dict):
            envelope = {
                k: v
                for k, v in output.items()
                if k != key and not isinstance(v, (dict, list))
                and not (isinstance(k, str) and k.startswith("_"))
            }
            return inner, envelope
    payload = {
        k: v
        for k, v in output.items()
        if k not in ROUTING_KEYS and not (isinstance(k, str) and k.startswith("_"))
    }
    return payload, {}


def compact_json(value: Any, *, limit: int = DEFAULT_EVENT_CHARS) -> str:
    """Pruned, pretty-printed JSON cut at ``limit`` with a note saying so —
    a model that sees a cut knows the full payload is on the trigger node."""
    pruned = prune_empty(value)
    try:
        text = json.dumps(pruned, indent=2, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(pruned)
    if len(text) <= limit:
        return text
    return (
        text[:limit]
        + f"\n… [truncated {len(text) - limit} more chars; the trigger node's "
        "output holds the full payload]"
    )


def event_kind(envelope: Dict[str, Any], payload: Any = None) -> Optional[str]:
    """The event's own name: the envelope's provider event type or selected
    operation (its ``type`` is NoClick's node type, not an event), else the
    payload's own event/type field (kept in the payload too — the header is
    a signpost, never the only copy)."""
    for source, keys in (
        (envelope, ("event_type", "event", "action", "operation")),
        (payload if isinstance(payload, dict) else {}, ("event_type", "event", "type", "action")),
    ):
        for key in keys:
            v = source.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return None


def default_agent_event(output: Any, *, limit: int = DEFAULT_EVENT_CHARS) -> Dict[str, Any]:
    """The base ``resolve_agent_event``: the unwrapped payload as bounded
    JSON, headed by the event's name when the envelope carries one."""
    payload, envelope = unwrap_trigger_output(output)
    body = compact_json(payload, limit=limit)
    kind = event_kind(envelope, payload)
    text = f"Event: {kind}\n{body}" if kind else body
    return {"text": text, "conversation_key": None}


def compact_for_display(output: Any) -> Any:
    """The record persisted beside a trigger turn for the chat surface:
    pruned, strings clipped, and bounded as a whole — the frontend derives
    its native frame from it, so it keeps the provider's own keys."""
    record = prune_empty(output, max_str=DISPLAY_STRING_CHARS)
    for clip in (DISPLAY_STRING_CHARS, 400, 80):
        record = prune_empty(record, max_str=clip)
        try:
            size = len(json.dumps(record, ensure_ascii=False, default=str))
        except (TypeError, ValueError):
            return {"_truncated": True}
        if size <= DISPLAY_RECORD_CHARS:
            return record
    if isinstance(record, dict):
        scalars = {k: v for k, v in record.items() if not isinstance(v, (dict, list))}
        return {**scalars, "_truncated": True}
    return {"_truncated": True}


def first_line(text: str, limit: int = 100) -> str:
    """A conversation title from an event's text: its first non-empty line."""
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line[:limit]
    return ""


_SLACK_MARKUP: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"<@([\w-]+)\|([^>]+)>"), r"@\2"),
    (re.compile(r"<@([\w-]+)>"), r"@\1"),
    (re.compile(r"<#([\w-]+)\|([^>]+)>"), r"#\2"),
    (re.compile(r"<#([\w-]+)>"), r"#\1"),
    (re.compile(r"<!subteam\^[\w-]+\|@?([^>]+)>"), r"@\1"),
    (re.compile(r"<!(here|channel|everyone)(?:\|[^>]*)?>"), r"@\1"),
    (re.compile(r"<mailto:([^|>]+)\|[^>]+>"), r"\1"),
    (re.compile(r"<((?:https?|mailto):[^|>]+)\|([^>]+)>"), r"\2 (\1)"),
    (re.compile(r"<([^|>]+)\|([^>]+)>"), r"\2"),
    (re.compile(r"<((?:https?|mailto):[^>]+)>"), r"\1"),
]


def humanize_slack_markup(text: str, *, drop_user_id: Optional[str] = None) -> str:
    """Slack message markup → what a person reads: ``<@U1|dana>`` → @dana,
    ``<#C1|general>`` → #general, ``<!here>`` → @here, ``<url|label>`` →
    label (url) so the agent keeps the link, entities unescaped. The
    receiving bot's own mention is the wake-up, not content — dropped when
    its user id is known."""
    if drop_user_id:
        text = re.sub(rf"<@{re.escape(drop_user_id)}(?:\|[^>]*)?>\s*", "", text)
    for pattern, repl in _SLACK_MARKUP:
        text = pattern.sub(repl, text)
    return (
        text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").strip()
    )


def media_entry(
    *,
    url: Optional[str] = None,
    mime_type: Optional[str] = None,
    filename: Optional[str] = None,
    size_bytes: Optional[int] = None,
    duration_s: Optional[float] = None,
    voice: bool = False,
    resource_id: Optional[str] = None,
    record: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """One piece of media an event carried, in the shape a hook returns under
    ``"media"`` and ``nodes.core.media_digest`` understands: a fetchable URL
    and/or a workflow resource id, the MIME type, and — for a voice note —
    its duration. ``record`` is the provider's own dict for that media inside
    the output; the digest annotates it (``transcript``) so the persisted
    trigger record the chat surface frames carries what was said."""
    return {
        "url": url,
        "mime_type": mime_type or "",
        "filename": filename,
        "size_bytes": size_bytes,
        "duration_s": duration_s,
        "voice": voice,
        "resource_id": resource_id,
        "record": record,
    }


def phone_call_event(output: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A finished phone call, as the wired agent reads it: who called which
    number (or which number was called), and what was said. One conversation
    per (other party, our number). None when the output is not a call record."""
    caller = str(output.get("caller") or "").strip()
    number = str(output.get("to") or "").strip()
    if not caller:
        return None
    outbound = output.get("direction") == "outbound"
    transcript = output.get("transcript") or []
    lines = "\n".join(
        f"{'You' if t.get('role') != 'user' else ('They' if outbound else 'Caller')}: {t.get('text', '')}"
        for t in transcript if t.get("text")
    )
    seconds = output.get("seconds")
    length = f" after {int(round(float(seconds)))}s" if isinstance(seconds, (int, float)) and seconds else ""
    if outbound:
        text = (f"The call you placed from {caller} to {number} ended{length}. It is over: report what was learned; "
                f"do not place it again unless asked.")
        conversation_key, title = f"{number}:{caller}", f"Call to {number}"
    else:
        text = f"Phone call from {caller} to your number {number}{length}."
        conversation_key, title = f"{caller}:{number}", f"Call from {caller}"
    text += f"\n\nTranscript:\n{lines}" if lines else "\n\nNobody spoke on the call."
    return {"text": text, "conversation_key": conversation_key, "title": title}


DELIVERED_EVENT_KEY = "_deliveredEvent"


def delivered_event(agent_node_id: str, nodes: Any) -> Optional[Dict[str, Any]]:
    """An event the platform delivered straight to an agent — a finished
    outbound call coming back to the agent that placed it — carried on the
    agent's own run-scoped config as ``_deliveredEvent`` ({node_id,
    node_type, label, operation, output, conversation_key?}): the node it
    speaks for and that node's record, translated by the node class's
    ``resolve_agent_event`` like a fired trigger, so the same persistence and
    chat framing apply. None when this run delivered nothing."""
    me = next((n for n in nodes or [] if isinstance(n, dict) and n.get("id") == agent_node_id), None)
    config = me.get("config") if me else None
    if not isinstance(config, dict):
        config = (me.get("data") or {}).get("config") if me and isinstance(me.get("data"), dict) else None
    delivered = config.get(DELIVERED_EVENT_KEY) if isinstance(config, dict) else None
    if not isinstance(delivered, dict) or not isinstance(delivered.get("output"), dict):
        return None
    from nodes.core.registry import NODE_REGISTRY

    node_cls = NODE_REGISTRY.get(str(delivered.get("node_type") or ""))
    event = node_cls.resolve_agent_event(delivered["output"]) if node_cls else None
    if not event:
        return None
    return {
        "node_id": str(delivered.get("node_id") or agent_node_id),
        "node_type": str(delivered.get("node_type") or ""),
        "operation": delivered.get("operation"),
        "source": delivered.get("label") or delivered.get("node_type") or "event",
        "text": event.get("text") or "",
        "conversation_key": delivered.get("conversation_key") or event.get("conversation_key"),
        "title": event.get("title"),
        "media": event.get("media") or [],
        "output": delivered["output"],
    }


def bullet_lines(pairs: Iterable[Tuple[str, Any]]) -> List[str]:
    """``[(label, value)]`` → ``"- label: value"`` lines, skipping empties."""
    lines = []
    for label, value in pairs:
        if value is None or value == "" or value == [] or value == {}:
            continue
        lines.append(f"- {label}: {value}")
    return lines
