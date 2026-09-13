"""SQLite for the database-backed stores, new enough for every harness's
schema wherever a move runs.

OpenClaw's tables are ``STRICT`` (SQLite 3.37+), and the Python inside a
harness sandbox links whatever libsqlite3 its base image ships — Debian
bullseye's 3.34 answers ``near "STRICT": syntax error`` and calls the whole
database malformed, so every pair touching OpenClaw fell back (2026-09-13
E2E). The stdlib module is used when its library is new enough; otherwise
``pysqlite3`` (the ``pysqlite3-binary`` wheel, a statically linked modern
SQLite that every harness image installs) is the same DB-API module under
another name. Neither is an ``InterchangeError``: a runtime without a usable
SQLite is a build defect, and the crash names the fix.
"""

from __future__ import annotations

import sqlite3 as _stdlib
from pathlib import Path
from typing import Any, List, Tuple, Union

try:
    import pysqlite3 as _bundled
except ImportError:  # the stdlib's library is new enough on most hosts
    _bundled = None

MIN_SQLITE: Tuple[int, int, int] = (3, 37, 0)  # STRICT tables
PYSQLITE3_BINARY = "0.5.4.post2"  # the wheel the harness images pin (SQLite 3.51)

# Every module that could answer, so an ``except`` clause catches either.
Error: Tuple[type, ...] = tuple(m.Error for m in (_stdlib, _bundled) if m is not None)

_module: Any = None


def _candidates() -> List[Any]:
    return [m for m in (_stdlib, _bundled) if m is not None]


def module() -> Any:
    """The DB-API module the formats use — resolved on first use so an
    unusable runtime fails the move it was asked for, not the import."""
    global _module
    if _module is None:
        chosen = next((m for m in _candidates() if m.sqlite_version_info >= MIN_SQLITE), None)
        if chosen is None:
            have = ", ".join(f"{m.__name__} links SQLite {m.sqlite_version}" for m in _candidates())
            wanted = ".".join(map(str, MIN_SQLITE))
            raise RuntimeError(
                f"no SQLite {wanted}+ for the interchange ({have}); install pysqlite3-binary=={PYSQLITE3_BINARY}"
            )
        _module = chosen
    return _module


def connect(path: Union[str, Path], *, readonly: bool = False, timeout: float = 30) -> Any:
    if readonly:
        return module().connect(f"file:{path}?mode=ro", uri=True)
    return module().connect(str(path), timeout=timeout)


__all__ = ["Error", "MIN_SQLITE", "PYSQLITE3_BINARY", "connect", "module"]
