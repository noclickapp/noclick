"""One async implementation, two surfaces.

Every public method is written once as ``async def`` and decorated with
``@synced``: ``obj.method(...)`` blocks and returns the result, while
``await obj.method.aio(...)`` is the native coroutine. Blocking calls run on a
private event loop in a daemon thread, so they work anywhere, including inside
Jupyter or another already-running loop. The caller's ``contextvars`` (the
current user) travel with the call.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import functools
import inspect
import threading
import types
from typing import Any, AsyncIterator, Callable, Coroutine, Iterator, Optional


class _LoopThread:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None

    def _ensure(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is None or self._thread is None or not self._thread.is_alive():
                loop = asyncio.new_event_loop()
                ready = threading.Event()

                def _run() -> None:
                    asyncio.set_event_loop(loop)
                    loop.call_soon(ready.set)
                    loop.run_forever()

                thread = threading.Thread(target=_run, name="noclick-loop", daemon=True)
                thread.start()
                ready.wait()
                self._loop, self._thread = loop, thread
            return self._loop

    def in_loop_thread(self) -> bool:
        return self._thread is not None and threading.current_thread() is self._thread

    def run(self, coro: Coroutine[Any, Any, Any]) -> Any:
        if self.in_loop_thread():
            coro.close()
            raise RuntimeError(
                "A blocking noclick call was made from inside its own event loop; "
                "use the `.aio` form (await obj.method.aio(...)) there."
            )
        loop = self._ensure()
        ctx = contextvars.copy_context()
        outcome: concurrent.futures.Future = concurrent.futures.Future()
        started: dict = {}

        def _start() -> None:
            task = ctx.run(loop.create_task, coro)
            started["task"] = task

            def _done(t: asyncio.Task) -> None:
                if t.cancelled():
                    outcome.cancel()
                elif t.exception() is not None:
                    outcome.set_exception(t.exception())
                else:
                    outcome.set_result(t.result())

            task.add_done_callback(_done)

        loop.call_soon_threadsafe(_start)
        try:
            return outcome.result()
        except KeyboardInterrupt:
            task = started.get("task")
            if task is not None:
                loop.call_soon_threadsafe(task.cancel)
            raise


_LOOP = _LoopThread()


def run_sync(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run ``coro`` to completion on the SDK loop and return its result."""
    return _LOOP.run(coro)


def _iterate_sync(agen: AsyncIterator[Any]) -> Iterator[Any]:
    async def _next() -> Any:
        return await agen.__anext__()

    async def _close() -> None:
        await agen.aclose()  # type: ignore[attr-defined]

    finished = False
    try:
        while True:
            try:
                item = run_sync(_next())
            except StopAsyncIteration:
                finished = True
                return
            yield item
    finally:
        if not finished:
            run_sync(_close())


class BoundMethod:
    """What ``obj.method`` evaluates to: call it to block, or use ``.aio``."""

    def __init__(self, bound: Callable[..., Any], fn: Callable[..., Any], is_gen: bool) -> None:
        self.aio = bound
        self._is_gen = is_gen
        self.__wrapped__ = bound
        self.__name__ = fn.__name__
        self.__qualname__ = fn.__qualname__
        self.__doc__ = fn.__doc__

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if self._is_gen:
            return _iterate_sync(self.aio(*args, **kwargs))
        return run_sync(self.aio(*args, **kwargs))

    def __repr__(self) -> str:
        return f"<noclick method {self.__qualname__}>"


class _Synced:
    def __init__(self, fn: Callable[..., Any], kind: str) -> None:
        self._fn = fn
        self._kind = kind
        self._is_gen = inspect.isasyncgenfunction(fn)
        if not (self._is_gen or inspect.iscoroutinefunction(fn)):
            raise TypeError(f"@synced needs an async function, got {fn!r}")
        functools.update_wrapper(self, fn)

    def __get__(self, obj: Any, objtype: Optional[type] = None) -> Any:
        if self._kind == "class":
            bound = types.MethodType(self._fn, objtype if objtype is not None else type(obj))
        elif self._kind == "static":
            bound = self._fn
        elif obj is None:
            return self
        else:
            bound = types.MethodType(self._fn, obj)
        return BoundMethod(bound, self._fn, self._is_gen)

    @property
    def aio(self) -> Callable[..., Any]:
        return self._fn

    def __call__(self, *args: Any, **kwargs: Any) -> Any:  # Class.method(obj, ...) or a module function
        return BoundMethod(self._fn, self._fn, self._is_gen)(*args, **kwargs)

    def __repr__(self) -> str:
        return f"<noclick function {self._fn.__qualname__}>"


def synced(fn: Any) -> Any:
    """Expose an async method (or classmethod/staticmethod) as blocking + ``.aio``."""
    if isinstance(fn, classmethod):
        return _Synced(fn.__func__, "class")
    if isinstance(fn, staticmethod):
        return _Synced(fn.__func__, "static")
    return _Synced(fn, "instance")
