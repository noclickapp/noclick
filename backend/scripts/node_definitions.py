"""The canvas's words for each node type, read from its NodeDefinition source.

A node type's label, description, category and keywords live in its frontend
definition (frontend/app/components/workflow/nodes: the LEGACY_NODE_DEFINITION_FILES
list in nodeDefinitions.ts, and integrations/<slug>.tsx). The generator copies them
into the type's backend catalog file (nodes/core/catalog.py) so search can name an
app the way the canvas does without the backend reading TypeScript. Each value must
be a literal in the definition; anything else is an error, never a guess.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional

NODES_DIR = Path(__file__).resolve().parents[2] / "frontend" / "app" / "components" / "workflow" / "nodes"
FIELDS = ("label", "description", "category", "keywords")

_LEGACY_FILE = re.compile(r"\[\s*'([a-z0-9-]+)'\s*,\s*'([A-Za-z0-9/_]+)'\s*\]")
_TYPE = re.compile(r"""\btype\s*:\s*(['"])([a-z0-9-]+)\1""")
_KEY = re.compile(r"([A-Za-z_$][\w$]*)\s*:")


def definition_files(nodes_dir: Path = NODES_DIR) -> Dict[str, Path]:
    """Each node type the canvas defines -> the file its NodeDefinition is in."""
    files = {
        node_type: nodes_dir / f"{file}.tsx"
        for node_type, file in _LEGACY_FILE.findall((nodes_dir / "nodeDefinitions.ts").read_text())
    }
    for path in sorted((nodes_dir / "integrations").glob("*.tsx")):
        files.setdefault(f"automation-{path.stem}", path)
    return files


def _string(source: str, i: int) -> tuple[str, int]:
    """The string literal starting at ``source[i]`` and the index after it."""
    quote = source[i]
    out = []
    i += 1
    while source[i] != quote:
        if quote == "`" and source.startswith("${", i):
            raise ValueError("template literal with a substitution")
        if source[i] == "\\":
            escaped = source[i + 1]
            out.append({"n": "\n", "t": "\t"}.get(escaped, escaped))
            i += 2
            continue
        out.append(source[i])
        i += 1
    return "".join(out), i + 1


def _skip(source: str, i: int) -> int:
    """Past whitespace and comments."""
    while True:
        while i < len(source) and source[i].isspace():
            i += 1
        if source.startswith("//", i):
            i = source.index("\n", i)
        elif source.startswith("/*", i):
            i = source.index("*/", i) + 2
        else:
            return i


def _literal(source: str, i: int) -> tuple[Any, int]:
    """A string literal or an array of them at ``source[i]``; ValueError for anything else."""
    i = _skip(source, i)
    if source[i] in "'\"`":
        return _string(source, i)
    if source[i] == "[":
        items, i = [], _skip(source, i + 1)
        while source[i] != "]":
            item, i = _literal(source, i)
            if not isinstance(item, str):
                raise ValueError("nested array")
            items.append(item)
            i = _skip(source, i)
            if source[i] == ",":
                i = _skip(source, i + 1)
        return items, i + 1
    raise ValueError(f"not a literal: {source[i:i + 40]!r}")


def _object_start(source: str, i: int) -> int:
    """The index of the ``{`` opening the object literal that contains ``source[i]``."""
    depth = 0
    while i > 0:
        i -= 1
        if source[i] == "}":
            depth += 1
        elif source[i] == "{":
            if depth == 0:
                return i
            depth -= 1
    raise ValueError("no enclosing object")


def _top_level_fields(source: str, start: int) -> Dict[str, int]:
    """Each key of the object literal opening at ``source[start]`` -> where its value starts."""
    fields: Dict[str, int] = {}
    depth, i = 0, start
    while True:
        c = source[i]
        if c in "'\"`":
            _, i = _string(source, i)
            continue
        if source.startswith("//", i) or source.startswith("/*", i):
            i = _skip(source, i)
            continue
        if c in "{[(":
            depth += 1
        elif c in "}])":
            depth -= 1
            if depth == 0:
                return fields
        elif depth == 1 and (c.isalpha() or c in "_$") and source[i - 1] in "{,\n \t":
            key = _KEY.match(source, i)
            if key and key.group(1) not in fields:
                fields[key.group(1)] = key.end()
                i = key.end()
                continue
        i += 1


def definition_facts(node_type: str, path: Path) -> Dict[str, Optional[Any]]:
    """``label``, ``description``, ``category`` and ``keywords`` of ``node_type``'s definition in ``path``."""
    source = path.read_text()
    for match in _TYPE.finditer(source):
        if match.group(2) != node_type:
            continue
        fields = _top_level_fields(source, _object_start(source, match.start()))
        if "label" not in fields:
            continue
        out: Dict[str, Optional[Any]] = {}
        for name in FIELDS:
            if name not in fields:
                out[name] = None
                continue
            try:
                out[name] = _literal(source, fields[name])[0]
            except ValueError as e:
                raise ValueError(f"{path.name}: {node_type}'s {name} must be a literal ({e})") from None
        return out
    raise ValueError(f"{path.name}: no NodeDefinition of type {node_type}")


def every_definition_facts(nodes_dir: Path = NODES_DIR) -> Dict[str, Dict[str, Optional[Any]]]:
    return {node_type: definition_facts(node_type, path) for node_type, path in definition_files(nodes_dir).items()}
