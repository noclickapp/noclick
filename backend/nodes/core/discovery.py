"""Discover opt-in integration nodes without importing them.

A top-level WorkflowNode subclass in nodes/*_node.py opts in by declaring its own
integration_type string. A declaration the source settles (a string literal, or a
module-level string constant) is read without importing its module: the module
imports the first time its type is looked up (``Declaration.load``), so a process
pays only for the integrations it uses. Any other declaration (a pydantic field
named integration_type, an annotation alone) is imported and judged at once.
Invalid declarations and duplicate types are startup errors; an import error
surfaces at the type's first lookup, and the suite loads every type.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import re
from dataclasses import dataclass
from pathlib import Path

from nodes.core.base import WorkflowNode

_TYPE = re.compile(r"[a-z][a-z0-9-]*")


@dataclass(frozen=True)
class Declaration:
    """Where a node type's class lives, loaded at the type's first lookup: a self-registered
    integration read from its source, or (``self_declared`` False) an entry registry.py lists by hand."""

    integration_type: str
    module: str
    class_name: str
    self_declared: bool = True

    def load(self) -> type[WorkflowNode]:
        module = importlib.import_module(self.module)
        cls = vars(module).get(self.class_name)
        if (
            not inspect.isclass(cls)
            or cls.__module__ != module.__name__
            or not issubclass(cls, WorkflowNode)
            or (self.self_declared and vars(cls).get("integration_type") != self.integration_type)
        ):
            raise ValueError(f"Invalid integration class in {self.module}.{self.class_name}")
        return cls


# The one shape nearly every integration declares in: four spaces into a top-level
# class, a string literal or a module constant. Reading it takes a regex, where
# parsing the module takes ~50x longer; a source naming integration_type in any
# other way (a field, a one-line class, a dict key) is parsed (_parsed).
_NAMED = re.compile(r"(?<![\w.])integration_type\b")
_SIMPLE = re.compile(r"    integration_type\s*=\s*(?:(['\"])([^'\"\n]*)\1|([A-Z_][A-Z0-9_]*))\s*(?:#.*)?$", re.M)
_CLASS = re.compile(r"class\s+(\w+)")


def _constant(source: str, name: str) -> str | None:
    found = re.search(rf"^{name}\s*=\s*(['\"])([^'\"\n]*)\1\s*$", source, re.M)
    return found.group(2) if found else None


def _top_level(source: str, line_start: int) -> str:
    """The text of the column-0 line the line at ``line_start`` sits under."""
    while line_start > 0:
        line_start = source.rfind("\n", 0, line_start - 1) + 1
        if source[line_start] not in " \t#\r\n@)]}":
            return source[line_start:source.find("\n", line_start)]
    return ""


def _scanned(source: str) -> list[tuple[str, str]] | None:
    """``(class name, integration type)`` for each declaration in the simple shape, or None if any isn't."""
    found = []
    for name in _NAMED.finditer(source):
        line_start = name.start() - 4
        simple = _SIMPLE.match(source, line_start) if line_start >= 0 and (
            line_start == 0 or source[line_start - 1] == "\n") else None
        header = _CLASS.match(_top_level(source, line_start)) if simple else None
        value = (simple.group(2) if simple.group(1) else _constant(source, simple.group(3))) if header else None
        if value is None:
            return None
        found.append((header.group(1), value))
    return found


def _parsed(source: str, filename: str) -> list[tuple[str, str | None]]:
    """``(class name, integration type)`` for each declaration, None where the source can't settle it."""
    tree = ast.parse(source, filename=filename)
    constants = {
        target.id: statement.value.value
        for statement in tree.body if isinstance(statement, ast.Assign)
        and isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str)
        for target in statement.targets if isinstance(target, ast.Name)
    }
    found = []
    for cls in tree.body:
        if not isinstance(cls, ast.ClassDef):
            continue
        for statement in cls.body:
            if not isinstance(statement, (ast.Assign, ast.AnnAssign)) or not any(
                isinstance(target, ast.Name) and target.id == "integration_type" for target in (
                    statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                )
            ):
                continue
            value = statement.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                found.append((cls.name, value.value))
            elif isinstance(value, ast.Name):
                found.append((cls.name, constants.get(value.id)))
            else:
                found.append((cls.name, None))
    return found


def _judged(module_name: str, names: list[str]) -> list[type[WorkflowNode]]:
    """Import a module whose declarations its source can't settle and keep its node classes."""
    module = importlib.import_module(module_name)
    nodes = []
    for name in names:
        cls = vars(module).get(name)
        if not inspect.isclass(cls) or cls.__module__ != module.__name__:
            raise ValueError(f"Invalid integration class in {module.__name__}.{name}")
        if not issubclass(cls, WorkflowNode):
            continue  # Config models may have a field with the same name.
        integration_type = vars(cls).get("integration_type")
        if not isinstance(integration_type, str) or not _TYPE.fullmatch(integration_type):
            raise ValueError(f"Invalid integration_type declaration in {module.__name__}.{name}")
        nodes.append(cls)
    return nodes


def declare_nodes(directory: Path, package: str = "nodes") -> dict[str, Declaration | type[WorkflowNode]]:
    """Each integration type -> its Declaration, or its class where the module had to be imported to judge it."""
    entries: dict[str, Declaration | type[WorkflowNode]] = {}

    def add(integration_type: str, entry: Declaration | type[WorkflowNode]) -> None:
        if integration_type in entries:
            raise ValueError(f"Duplicate node type: {integration_type}")
        entries[integration_type] = entry

    for path in sorted(directory.glob("*_node.py")):
        source = path.read_text()
        if "integration_type" not in source:
            continue
        module_name = f"{package}.{path.stem}"
        declarations = _scanned(source)
        if declarations is None:
            declarations = _parsed(source, str(path))
        settled: list[tuple[str, str]] = []
        unsettled: list[str] = []
        for class_name, integration_type in declarations:
            if integration_type is None:
                unsettled.append(class_name)
            elif not _TYPE.fullmatch(integration_type):
                raise ValueError(f"Invalid integration_type declaration in {module_name}.{class_name}")
            else:
                settled.append((integration_type, class_name))
        if unsettled:
            for cls in _judged(module_name, [name for _, name in settled] + unsettled):
                add(vars(cls)["integration_type"], cls)
        else:
            for integration_type, name in settled:
                add(integration_type, Declaration(integration_type, module_name, name))
    return entries


def merge_node_entries(explicit, discovered):
    duplicates = explicit.keys() & discovered.keys()
    if duplicates:
        raise ValueError(f"Duplicate node types: {', '.join(sorted(duplicates))}")
    return {**explicit, **discovered}
