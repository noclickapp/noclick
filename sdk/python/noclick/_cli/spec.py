"""The ``noclick`` command surface as data, which both CLIs (Python's and TypeScript's) run from.

- ``spec/manifest.json``: the curated commands (``deploy``, ``logs``, ``db query`` ...), written by hand: each one's
  summary, arguments, flags and examples. Every curated command a CLI has is in it, and nothing else
  (``tests/test_cli_spec.py`` holds Python's parser to it).
- ``spec/operations.json``: every ``/v1`` operation, generated from the API's own description (the operations
  ``api_describe`` serves, under the same names, plus the ones only a key reaches), each ``noclick <area> <command>``.
  Never edited by hand: the backend's ``scripts/gen_cli_spec.py`` writes it.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Any, Dict, List, Optional, Tuple


def _read(name: str) -> Dict[str, Any]:
    return json.loads(resources.files("noclick._cli").joinpath("spec", name).read_text(encoding="utf-8"))


class Spec:
    def __init__(self, manifest: Dict[str, Any], operations: Dict[str, Any]):
        self.manifest = manifest
        self.operations: List[Dict[str, Any]] = operations["operations"]
        self._by_command = {(op["area"], op["command"]): op for op in self.operations}
        self._by_name = {op["name"]: op for op in self.operations}
        self._templates = [(op["method"], op["path"].strip("/").split("/"), op) for op in self.operations]

    @property
    def commands(self) -> List[Dict[str, Any]]:
        """The curated commands, as the manifest has them."""
        return self.manifest["commands"]

    def areas(self) -> Dict[str, List[Dict[str, Any]]]:
        found: Dict[str, List[Dict[str, Any]]] = {}
        for op in self.operations:
            found.setdefault(op["area"], []).append(op)
        return found

    def find(self, area: str, command: str) -> Optional[Dict[str, Any]]:
        return self._by_command.get((area, command))

    def named(self, name: str) -> Optional[Dict[str, Any]]:
        return self._by_name.get(name)

    def for_call(self, method: str, path: str) -> Optional[Dict[str, Any]]:
        """The operation a ``METHOD /v1/...`` call makes: its template, or a concrete path it matches."""
        method = method.upper()
        given = path.split("?")[0].strip("/").split("/")
        best: Optional[Tuple[int, Dict[str, Any]]] = None
        for verb, template, op in self._templates:
            if verb != method or len(template) != len(given):
                continue
            literal = 0
            for t, g in zip(template, given):
                if t.startswith("{"):
                    continue
                if t != g:
                    break
                literal += 1
            else:
                if best is None or literal > best[0]:
                    best = (literal, op)
        return best[1] if best else None

    def lookup(self, words: List[str]) -> Optional[Dict[str, Any]]:
        """An operation by ``<area> <command>``, its name, or ``METHOD /v1/...``."""
        if len(words) == 2 and words[0].upper() in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            return self.for_call(words[0], words[1])
        if len(words) == 2:
            return self.find(words[0], words[1])
        if len(words) == 1:
            return self.named(words[0].replace("-", "_"))
        return None


@lru_cache(maxsize=1)
def load() -> Spec:
    return Spec(_read("manifest.json"), _read("operations.json"))
