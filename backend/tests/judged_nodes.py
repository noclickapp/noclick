"""The node types (and source files) a contract test over every node (or every file) judges.

Every registered type, unless ``NOCLICK_JUDGED_NODE_TYPES`` names some (comma-separated): an
integration's pull request judges only the types its own files declare
(scripts/select_integration_tests.py names them), against everything else as staging has it.
Listing the types imports nothing and looking one up imports its integration, so a narrowed run
never imports the other twelve hundred. A name the registry doesn't hold is an error, never an
empty (and so passing) run.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Iterable

from nodes.core import registry

ENV = "NOCLICK_JUDGED_NODE_TYPES"
FILES_ENV = "NOCLICK_JUDGED_FILES"  # the files a pull request changes, relative to the repository's root
ROOT = Path(__file__).resolve().parents[2]


def _named() -> frozenset[str] | None:
    names = frozenset(name.strip() for name in os.environ.get(ENV, "").split(",") if name.strip())
    if not names:
        return None
    unknown = sorted(name for name in names if name not in registry.NODE_REGISTRY)
    if unknown:
        raise ValueError(f"{ENV} names node types the registry doesn't hold: {', '.join(unknown)}")
    return names


def narrowed() -> bool:
    """Whether this run judges only some node types."""
    return _named() is not None


def judged_types(types: Iterable[str] | None = None) -> list[str]:
    """``types`` (every registered type by default) that this run judges, in their order."""
    named = _named()
    every = list(registry.NODE_REGISTRY if types is None else types)
    return every if named is None else [t for t in every if t in named]


def judged_classes() -> list[tuple[str, type]]:
    """``(type, class)`` for each judged type, importing only those integrations."""
    return [(node_type, registry.NODE_REGISTRY[node_type]) for node_type in judged_types()]


def judged_files(items: Iterable[Any], path: Callable[[Any], Path] = lambda item: item) -> list:
    """``items`` (files, or what ``path`` reads a file from) a scan of every source file judges: every one, unless
    ``NOCLICK_JUDGED_FILES`` names the files an integration's pull request changes, a rule of each file being
    answered for the rest as staging has them."""
    named = {(ROOT / name).resolve() for name in os.environ.get(FILES_ENV, "").split(",") if name.strip()}
    items = list(items)
    return items if not named else [item for item in items if Path(path(item)).resolve() in named]


def files_narrowed() -> bool:
    """Whether this run's scans judge only some files."""
    return bool(os.environ.get(FILES_ENV, "").strip())
