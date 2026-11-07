"""Discover opt-in integration nodes without importing unregistered legacy modules.

A top-level WorkflowNode subclass in nodes/*_node.py opts in by declaring its own
integration_type string. Import errors and duplicate types are startup errors.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import re
from pathlib import Path

from nodes.core.base import WorkflowNode


def discover_nodes(directory: Path, package: str = "nodes") -> dict[str, type[WorkflowNode]]:
    entries: dict[str, type[WorkflowNode]] = {}
    for path in sorted(directory.glob("*_node.py")):
        source = path.read_text()
        if "integration_type" not in source:
            continue
        tree = ast.parse(source, filename=str(path))
        declarations = [
            cls.name for cls in tree.body if isinstance(cls, ast.ClassDef)
            and any(
                isinstance(statement, (ast.Assign, ast.AnnAssign))
                and any(isinstance(target, ast.Name) and target.id == "integration_type" for target in (
                    statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                ))
                for statement in cls.body
            )
        ]
        if not declarations:
            continue
        module = importlib.import_module(f"{package}.{path.stem}")
        for name in declarations:
            cls = vars(module).get(name)
            if not inspect.isclass(cls) or cls.__module__ != module.__name__:
                raise ValueError(f"Invalid integration class in {module.__name__}.{name}")
            if not issubclass(cls, WorkflowNode):
                continue  # Config models may have a field with the same name.
            integration_type = vars(cls).get('integration_type')
            if not isinstance(integration_type, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", integration_type):
                raise ValueError(f"Invalid integration_type declaration in {module.__name__}.{name}")
            if integration_type in entries:
                raise ValueError(f"Duplicate node type: {integration_type}")
            entries[integration_type] = cls
    return entries


def merge_node_entries(explicit, discovered):
    duplicates = explicit.keys() & discovered.keys()
    if duplicates:
        raise ValueError(f"Duplicate node types: {', '.join(sorted(duplicates))}")
    return {**explicit, **discovered}
