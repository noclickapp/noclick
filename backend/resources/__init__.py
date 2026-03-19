# Documentation resources and prompts registry.
# Each .py file in this package can define:
#   RESOURCES = [{"name": "...", "title": "...", "content": "..."}]
#   PROMPTS   = [{"name": "...", "description": "...", "resource": "resource-name"}]
#
# Both are auto-discovered on first access. To add new docs:
#   1. Create a new .py file in this directory
#   2. Define RESOURCES and/or PROMPTS
#   3. Automatically available everywhere (MCP, internal builder, <read> command)
#
# Used by:
#   - MCP server: registers as MCP resources (noclick://docs/*) and prompts
#   - Internal agentic builder: <read topic="name" /> command

from __future__ import annotations

import importlib
import pkgutil
from typing import Dict, List, Optional

_resources: Dict[str, tuple[str, str]] = {}  # name → (title, content)
_prompts: List[dict] = []  # [{"name", "description", "resource"}]
_loaded = False


def _ensure_loaded() -> None:
    """Auto-discover and load all resource modules in this package."""
    global _loaded
    if _loaded:
        return
    _loaded = True

    package_path = __path__  # type: ignore[name-defined]
    for _importer, modname, _ispkg in pkgutil.iter_modules(package_path):
        if modname.startswith('_'):
            continue
        module = importlib.import_module(f'.{modname}', package=__name__)

        entries = getattr(module, 'RESOURCES', None)
        if entries and isinstance(entries, list):
            for entry in entries:
                name = entry.get('name', '')
                if name:
                    _resources[name] = (entry.get('title', ''), entry.get('content', ''))

        prompts = getattr(module, 'PROMPTS', None)
        if prompts and isinstance(prompts, list):
            _prompts.extend(prompts)


def get(name: str) -> Optional[str]:
    """Get resource content by name. Returns None if not found."""
    _ensure_loaded()
    entry = _resources.get(name)
    return entry[1] if entry else None


def list_all() -> List[dict]:
    """List all registered resources with name and title."""
    _ensure_loaded()
    return [{"name": k, "title": v[0]} for k, v in _resources.items()]


def list_prompts() -> List[dict]:
    """List all registered prompts."""
    _ensure_loaded()
    return list(_prompts)
