"""Disable websocket per-message-deflate compression by monkey-patching ``websockets``.

Importing this module monkey-patches
``websockets.extensions.permessage_deflate.enable_server_permessage_deflate``
so uvicorn never installs a server-side compression extension factory.
Clients connect without negotiating compression and no zlib runs on the
send path.

Why
---
``permessage_deflate.encode`` runs synchronous CPU-bound zlib work inside
the websocket send path, so a large emit stream can block the main asyncio
loop. The protocol stack provides no clean off-loop hook for that work.

Trade-off
---------
Disabling compression trades additional network bytes for bounded main-loop
responsiveness: unrelated socket events no longer queue behind synchronous
compression of one emit stream.

Where this gets imported
------------------------
The backend entry point imports this before uvicorn boots. Worker subprocesses don't run uvicorn, so
they don't need the patch — and so this module is NOT in the
forkserver preload.

To restore compression after the work is moved off the main loop
(e.g. via a custom executor), delete this module or patch it to pass
through to the original function.
"""
import websockets.extensions.permessage_deflate as _pmd

_pmd.enable_server_permessage_deflate = (
    lambda extensions: extensions if extensions is not None else []
)
