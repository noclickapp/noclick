"""Process identity helpers for self-hosted telemetry and audit events.

Identity comes only from operator configuration or the local host. Importing
this module never performs network I/O or sends installation metadata to a
third party.
"""

from __future__ import annotations

import os
import socket


_INSTANCE_ID = os.getenv("NOCLICK_INSTANCE_ID") or socket.gethostname()
_PROCESS_PID = os.getpid()


def instance_id() -> str:
    """Return the stable identifier configured for this backend instance."""
    return _INSTANCE_ID


def process_pid() -> int:
    """Return this process id, cached when the module is imported."""
    return _PROCESS_PID
