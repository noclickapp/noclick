"""Process-wide Socket.IO server handle.

Set once at api startup so stateless HTTP routes — which have no request socket of
their own (the agent completion handler, future pool emits) — can reach the
shared server for downstream/relay emits without importing ``api`` (heavy + would
be circular). ``get_sio()`` is None until ``set_sio`` runs at startup; production
always sets it.
"""
from typing import Any, Optional

_sio: Optional[Any] = None


def set_sio(sio: Any) -> None:
    global _sio
    _sio = sio


def get_sio() -> Optional[Any]:
    return _sio
