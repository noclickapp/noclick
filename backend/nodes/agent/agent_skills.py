"""Skills an in-process agent can follow, when a platform offers them.

A coding harness finds its skills where it reads them (a platform writes them
into its sandbox); NoClick's own loop reads them through a tool instead. A
platform sets two runtime keys on the agent node per turn:
``AGENT_SKILLS_KEY`` (whatever the platform needs back to read them) offers
``skill__read``, whose calls go to the ``AGENT_SKILLS`` capability, and
``SKILL_CATALOG_KEY`` (text: each skill's name and description, and the
whole of any skill to follow every turn) is composed into the turn's message
by the agent node, as the memory catalog is. Reads are the platform's own
data, so a rehearsal runs them.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

AGENT_SKILLS_KEY = "_agentSkills"
SKILL_CATALOG_KEY = "_skillCatalog"
SKILL_READ_TOOL_TYPE = "skill_read"
READ_TOOL = "skill__read"

_READ = {"type": "function", "function": {
    "name": READ_TOOL,
    "description": "Read one of your skills before you follow it: its SKILL.md (its instructions), or another of its "
                   "files by path (a script, a template, a reference). To run one of its scripts, write it into your shell "
                   "and run it there.",
    "parameters": {"type": "object", "properties": {
        "name": {"type": "string", "description": "The skill's name, as your skills list it."},
        "path": {"type": "string", "description": "A file in the skill's folder; leave it out for SKILL.md."},
    }, "required": ["name"]},
}}


def skill_params(spec: Dict[str, Any]) -> List[Tuple[Dict[str, Any], str]]:
    return [(_READ, SKILL_READ_TOOL_TYPE)]


def _config(node: Any) -> Dict[str, Any]:
    data = getattr(node, "node_data", None) or {}
    return data.get("config") if isinstance(data.get("config"), dict) else {}


def agent_skills_of(node: Any) -> Optional[Dict[str, Any]]:
    """The turn's skills spec, when a platform offers skills to read."""
    spec = _config(node).get(AGENT_SKILLS_KEY)
    return spec if isinstance(spec, dict) and spec else None


def skill_catalog_of(node_config: Any) -> Optional[str]:
    """The catalog text a platform put on the turn."""
    text = node_config.get(SKILL_CATALOG_KEY) if isinstance(node_config, dict) else None
    return text.strip() if isinstance(text, str) and text.strip() else None


async def skill_impl(pool, spec: Optional[Dict[str, Any]], arguments: Dict[str, Any]) -> Dict[str, Any]:
    from utils.capabilities import AGENT_SKILLS, capability

    provider = capability(AGENT_SKILLS)
    if provider is None or not spec:
        return {"success": False, "error": "Skills aren't available here."}
    return await provider(pool, spec=spec, arguments=arguments)


async def execute_skill_tool(node: Any, arguments: Dict[str, Any], tool_info: Dict[str, Any]) -> Dict[str, Any]:
    from utils.database_pool import get_native_pool

    return await skill_impl(get_native_pool(), tool_info.get("spec"), arguments)
