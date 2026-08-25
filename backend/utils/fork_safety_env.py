"""Set macOS fork-safety env vars before the forkserver is created.

Importing this module sets ``no_proxy=*`` and
``OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES`` via ``os.environ.setdefault``.

Why
---
On macOS, ``urllib.request.proxy_bypass`` calls
``proxy_bypass_macosx_sysconf``, which uses Apple's SystemConfiguration
framework. That framework is NOT fork-safe — its Objective-C runtime
state gets invalidated by ``fork()`` and the next call SIGSEGVs the
worker process. Many libraries reach for proxy detection on first
HTTP/WebSocket call (``websockets``, ``urllib``, etc.), so any worker
that opens a network connection after fork crashes immediately.

Linux production has no such API and is unaffected, but local dev on
macOS is. Two env vars defang the bug:

- ``no_proxy=*`` — urllib skips the macOS-specific
  ``proxy_bypass_macosx_sysconf`` code path entirely (we never use
  proxies, so always-skip is harmless on Linux too).
- ``OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES`` — disables Apple's
  runtime fork-safety check as a defensive backstop in case a library
  reaches into Objective-C / SystemConfiguration via some other path.

Both are harmless on Linux. ``setdefault`` preserves any operator
override.

Where this gets imported
------------------------
The backend entry point imports this before other runtime modules so the env vars are set
before any module that might do network I/O is imported. Worker
subprocesses inherit these env vars from the parent via standard UNIX
environment inheritance (separate from Python ``sys.modules``), so no
forkserver-preload entry is needed.
"""
import os

os.environ.setdefault("no_proxy", "*")
os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")
