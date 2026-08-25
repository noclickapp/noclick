"""Process-wide Socket.IO server handle.

Set once at API startup so HTTP routes without a request socket can reach the
shared server for relay emits without importing ``api`` (heavy and circular).
``get_sio()`` is None until ``set_sio`` runs at startup.
"""
from typing import Any, Optional

_sio: Optional[Any] = None


def set_sio(sio: Any) -> None:
    global _sio
    _sio = sio


def get_sio() -> Optional[Any]:
    return _sio
