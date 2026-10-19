"""Memory an agent keeps across its conversations, when a platform offers it.

A platform sets two runtime keys on the agent node per turn.
``AGENT_MEMORY_KEY`` (whatever the platform needs back, e.g. the layer; the
same on every turn of a thread, since it rides the tool config a warm CLI
sandbox is fingerprinted by) offers the memory tools, whose calls go to the
``AGENT_MEMORY`` capability. ``MEMORY_CATALOG_KEY`` (text: the entries' names
and descriptions) is composed into the turn's message by the agent node, so
the agent knows what it has without the system prompt changing. Reads are the
platform's own data, so a rehearsal runs them; writes are fabricated there.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

AGENT_MEMORY_KEY = "_agentMemory"
MEMORY_CATALOG_KEY = "_memoryCatalog"
MEMORY_READ_TOOL_TYPE = "memory_read"
MEMORY_WRITE_TOOL_TYPE = "memory_write"
PREFIX = "memory__"

_NAME = {"type": "string", "description": "The entry's name: lowercase letters, digits and . _ - (up to 64)."}
_VERSION = {"type": "integer", "description": "The version you read; the change lands only if it's still at it."}
# Which memory, when the platform gives the agent others besides its own.
_MEMORY = {"type": "string", "description": "Another memory you have, by its name; leave it out for your own."}


def _param(name: str, description: str, properties: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {"type": "function", "function": {
        "name": f"{PREFIX}{name}", "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required},
    }}


_READS = [
    _param("search", "Search your memory, notes you keep across conversations: the entries holding any of these "
                     "words, best first, with their content.",
           {"query": {"type": "string", "description": "Words to look for."},
            "memory": {**_MEMORY, "description": "Search only this memory of yours, by its name; leave it out to "
                                                 "search all of them."}},
           ["query"]),
    _param("read", "Read one entry of your memory in full, with the version to pass back when you change it.",
           {"name": _NAME, "memory": _MEMORY}, ["name"]),
]
_WRITES = [
    _param("save", "Remember something for later conversations: create an entry, or replace one you read (pass "
                   "its version). Keep one topic per entry and write a description saying what it holds and when "
                   "to read it; that line is what you see every turn. When the user asks you to remember or keep "
                   "something, save it exactly as they gave it, even a code or a number, before you reply. Don't "
                   "save other secrets or what you can look up.",
           {"name": _NAME,
            "content": {"type": "string", "description": "The note, in Markdown (up to 20,000 characters)."},
            "description": {"type": "string",
                            "description": "One line, up to 200 characters: required for a new entry."},
            "version": {**_VERSION, "description": "The version you read, or 0 for a new entry; the save lands only "
                                                   "if it's still at it."},
            "memory": _MEMORY},
           ["name", "content"]),
    _param("delete", "Forget an entry of your memory.", {"name": _NAME, "version": _VERSION, "memory": _MEMORY},
           ["name"]),
]


def memory_params(spec: Dict[str, Any]) -> List[Tuple[Dict[str, Any], str]]:
    """``(tool param, tool type)`` for a turn's spec: the reads always, the
    writes unless the platform made this thread's memory read-only."""
    params = [(p, MEMORY_READ_TOOL_TYPE) for p in _READS]
    if spec.get("writes", True):
        params += [(p, MEMORY_WRITE_TOOL_TYPE) for p in _WRITES]
    return params


def _config(node: Any) -> Dict[str, Any]:
    data = getattr(node, "node_data", None) or {}
    return data.get("config") if isinstance(data.get("config"), dict) else {}


def agent_memory_of(node: Any) -> Optional[Dict[str, Any]]:
    """The turn's memory spec, when a platform offers memory."""
    spec = _config(node).get(AGENT_MEMORY_KEY)
    return spec if isinstance(spec, dict) and spec else None


def conversation_compactor(node: Any, *, conversation_id: Optional[str], user_id: Optional[str],
                           user_email: Optional[str] = None, organization_id: Optional[str] = None) -> Any:
    """The turn's context filter: a ``Compactor`` keeping its checkpoint where
    the platform keeps this agent's memory (``CONVERSATION_CHECKPOINTS``); None
    for a turn without memory or a conversation, or one the platform keeps no
    checkpoint for. Summaries run on the default model, billed as the turn is; the turn's watchers hear
    ``status`` ``compacting`` and ``compacted`` around them."""
    from utils.capabilities import CONVERSATION_CHECKPOINTS, capability

    spec, provider = agent_memory_of(node), capability(CONVERSATION_CHECKPOINTS)
    if spec is None or provider is None or not conversation_id:
        return None
    from coder.openai_agent.compaction import Compactor
    from nodes.agent.config.llm import DEFAULT_LLM_AGENT_MODEL
    from utils.database_pool import get_native_pool

    store = provider(get_native_pool(), spec=spec, conversation_id=conversation_id)
    if store is None:
        return None

    def notify(status: str) -> None:
        from datetime import datetime, timezone

        from utils.turn_events import publish

        publish(conversation_id, {"type": "status", "status": status,
                                  "created_at": datetime.now(timezone.utc).isoformat()})

    return Compactor(store, model=DEFAULT_LLM_AGENT_MODEL, user_id=user_id, user_email=user_email,
                     organization_id=organization_id, notify=notify)


def memory_catalog_of(node_config: Any) -> Optional[str]:
    """The catalog text a platform put on the turn."""
    text = node_config.get(MEMORY_CATALOG_KEY) if isinstance(node_config, dict) else None
    return text.strip() if isinstance(text, str) and text.strip() else None


async def memory_impl(pool, spec: Optional[Dict[str, Any]], arguments: Dict[str, Any]) -> Dict[str, Any]:
    from utils.capabilities import AGENT_MEMORY, capability

    provider = capability(AGENT_MEMORY)
    if provider is None or not spec:
        return {"success": False, "error": "Memory isn't available here."}
    return await provider(pool, spec=spec, arguments=arguments)


async def execute_memory_tool(node: Any, arguments: Dict[str, Any], tool_info: Dict[str, Any]) -> Dict[str, Any]:
    from utils.database_pool import get_native_pool

    return await memory_impl(get_native_pool(), tool_info.get("spec"), arguments)
