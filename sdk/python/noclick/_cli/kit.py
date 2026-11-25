"""What a part of the ``noclick`` command registers its commands with (``register(kit)``)."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Sequence


@dataclass
class Kit:
    """``command(group, name, run, summary, auth=, parents=)`` adds a command whose ``run(args)`` returns its exit
    status; ``group(name, summary)`` a group of subcommands (``groups`` holds every one by name, so a part adds to
    another's); ``as_json`` and ``user`` are the parents for ``--json`` and ``--user``; ``commands`` is the top
    level."""

    commands: Any
    command: Callable[..., argparse.ArgumentParser]
    group: Callable[[str, str], Any]
    as_json: argparse.ArgumentParser
    user: argparse.ArgumentParser
    groups: Dict[str, Any] = field(default_factory=dict)


def parts() -> Sequence[Any]:
    """Every part's module, in name order."""
    import importlib
    import pkgutil

    from . import parts as package

    return [importlib.import_module(f"{package.__name__}.{info.name}")
            for info in sorted(pkgutil.iter_modules(package.__path__), key=lambda i: i.name)]
