"""The update notice: one line on stderr, at most once a day, when the registry has a newer ``noclick`` than this one.

It never delays a command. The registry is asked by a process of its own, started at most once a day and never
waited on, which writes what it heard to ``updates-pypi.json`` in the config directory (the npm CLI keeps its own,
``updates-npm.json``); a later command reads that file and says so. Nothing is said when either stream isn't a
terminal, in CI, under ``--json``, or with ``NOCLICK_NO_UPDATE_CHECK`` set. The npm CLI does the same against npm
(``src/cli/updates.ts``), in the same words.

    python -m noclick._cli.updates <cache file>     # ask PyPI, write the cache (what the notice starts)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

OFF_ENV = "NOCLICK_NO_UPDATE_CHECK"
DAY_S = 24 * 60 * 60
PYPI_URL = "https://pypi.org/pypi/noclick/json"
PIP = "pip install -U noclick"
FILE = "updates-pypi.json"


def newer(latest: str, current: str) -> bool:
    """Whether ``latest`` is a later release than ``current`` (a pre-release is never offered)."""
    def parts(version: str) -> Optional[tuple]:
        return tuple(int(n) for n in version.split(".")) if re.fullmatch(r"\d+(\.\d+)*", version) else None
    a, b = parts(latest), parts(current)
    return bool(a and b and a > b)


def words(latest: str, current: str, how: str) -> str:
    return f"A newer noclick is out: {latest} (you have {current}). Update: {how}"


def quiet(argv: Sequence[str], env: Mapping[str, str], terminals: bool) -> bool:
    """Whether nothing may be said: piped, in CI, under --json, or switched off."""
    return not terminals or bool(env.get("CI")) or bool(env.get(OFF_ENV)) or "--json" in argv


def _read(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _write(path: Path, data: Dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data) + "\n")
    except OSError:
        pass


def _within_a_day(at: Any, now: float) -> bool:
    return isinstance(at, (int, float)) and now - at < DAY_S


def _ask_registry(path: Path) -> None:
    """Start the process that asks PyPI, never waiting on it."""
    detached: Dict[str, Any] = ({"creationflags": 0x00000008} if os.name == "nt" else {"start_new_session": True})
    try:
        subprocess.Popen([sys.executable, "-m", "noclick._cli.updates", str(path)], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, **detached)
    except OSError:
        pass


def notice(argv: Sequence[str], *, current: str, how: str, env: Optional[Mapping[str, str]] = None,
           terminals: Optional[bool] = None, now: Optional[float] = None,
           ask: Optional[Callable[[Path], None]] = None) -> Optional[str]:
    """The line to say after a command, if any; asks the registry again when what it heard is a day old."""
    env = os.environ if env is None else env
    if terminals is None:
        terminals = sys.stdout.isatty() and sys.stderr.isatty()
    if quiet(argv, env, terminals):
        return None
    from ..cli import config_dir

    path = config_dir() / FILE
    now = time.time() if now is None else now
    seen = _read(path)
    if not _within_a_day(seen.get("checked_at"), now):
        seen["checked_at"] = now  # asked at most once a day, whether or not it answers
        _write(path, seen)
        (ask or _ask_registry)(path)
    latest = seen.get("latest")
    if not isinstance(latest, str) or not newer(latest, current) or _within_a_day(seen.get("told_at"), now):
        return None
    seen["told_at"] = now
    _write(path, seen)
    return words(latest, current, how)


def main(argv: Sequence[str]) -> int:
    import httpx

    path = Path(argv[0])
    try:
        latest = httpx.get(PYPI_URL, timeout=5, follow_redirects=True).json()["info"]["version"]
    except Exception:  # noqa: BLE001 - nothing heard is nothing to say
        return 0
    _write(path, {**_read(path), "latest": latest})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
