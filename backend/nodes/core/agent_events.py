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


def bullet_lines(pairs: Iterable[Tuple[str, Any]]) -> List[str]:
    """``[(label, value)]`` → ``"- label: value"`` lines, skipping empties."""
    lines = []
    for label, value in pairs:
        if value is None or value == "" or value == [] or value == {}:
            continue
        lines.append(f"- {label}: {value}")
    return lines
