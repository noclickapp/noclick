"""Earlier values: what a secret or an app's setting held before it changed, kept 30 days."""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional

from ._object import parse_time


@dataclass(frozen=True)
class Version:
    """A value a secret or setting held before ``replaced_at``. ``op`` says what replaced it: ``changed`` (a new
    value) or ``deleted``. A secret's version never shows its value: ``keys`` names what a ``noclick.Secret`` held
    and ``environment`` is where an app's secret was set; a setting's shows its ``value``."""

    id: str
    name: str
    op: str
    replaced_at: Any
    environment: Optional[str] = None
    keys: Optional[List[str]] = None
    value: Optional[str] = None
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "Version":
        return cls(id=raw["id"], name=raw["name"], op=raw["op"], replaced_at=parse_time(raw.get("replaced_at")),
                   environment=raw.get("environment"), keys=raw.get("keys"), value=raw.get("value"), raw=raw)


def versions_of(raw: Any) -> List[Version]:
    return [Version._from(row) for row in (raw or {}).get("data") or []]


def version_id(version: Any) -> str:
    """A ``Version`` or its id."""
    if isinstance(version, Version):
        return version.id
    if isinstance(version, str):
        return version
    raise TypeError(f"A version is a noclick.Version or its id, not {type(version).__name__}")
