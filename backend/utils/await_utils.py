# Tested on Python 3.10
import asyncio
import weakref
from asyncio import AbstractEventLoop, run
from typing import (
    Coroutine, Generator, Iterable, Protocol, TypeVar, Awaitable, Iterator, ParamSpec, Callable, Optional, Type,
    AsyncContextManager, Tuple
)
from contextlib import contextmanager, ExitStack
import threading
import time
import contextvars
import types
from concurrent.futures import ThreadPoolExecutor, Future
import random
import functools

try:
    from asyncio import get_running_loop # python >= 3.7
except ImportError:
    pass

__all__ = ("run",)

class TaskFactory(Protocol):
    def __call__(
            self,
            __loop: AbstractEventLoop,
            __factory: Coroutine[None, None, object] | Generator[None, None, object],
            /,
    ) -> asyncio.futures.Future[object]: ...

def _patch_loop(loop: AbstractEventLoop) -> weakref.WeakSet[asyncio.Task]:
    """
    Keep a thread safe variable tasks up to date with any tasks that are
    created for the given loop. This then lets you cancel them as _all_tasks
    waas intended for.

    {get, set}_task_factory are patched so other users aren't allowed to overwrite
    our factory function.
    """
    tasks: weakref.WeakSet = weakref.WeakSet()

    task_factory: list[TaskFactory | None] = [None]

    def _set_task_factory(factory: TaskFactory | None) -> None:
        task_factory[0] = factory

    def _get_task_factory() -> TaskFactory | None:
        return task_factory[0]

    def _safe_task_factory(
            loop: AbstractEventLoop,
            coro: Coroutine[None, None, object] | Generator[None, None, object],
    ) -> asyncio.futures.Future[object]:
        local_task_factory = task_factory[0]
        if local_task_factory is None:
            task = asyncio.Task(coro, loop=loop)
            if task._source_traceback:
                del task._source_traceback[-1]
        else:
            task = local_task_factory(loop, coro)
        tasks.add(task)
        return task
    
    loop.set_task_factory(_safe_task_factory)
    loop.set_task_factory = _set_task_factory
    loop.get_task_factory = _get_task_factory

    return tasks

def _cancel_all_tasks(
        loop: AbstractEventLoop,
        tasks: Iterable[asyncio.futures.Future[object]],
) -> None:
    to_cancel = [task for task in tasks if not task.done()]

    if not to_cancel:
        return

    for task in to_cancel:
        task.cancel()

    loop.run_until_complete(asyncio.gather(*to_cancel, return_exceptions=True))

    for task in to_cancel:
        if task.cancelled():
            continue
        if task.exception() is not None:
            loop.call_exception_handler({
                "message": "unhandled exception during asyncio.run() shutdown",
                "exception": task.exception(),
                "task": task,
            })

@contextmanager
def _new_loop(
    task_factory: TaskFactory | None = None,
) -> Iterator[AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    tasks = _patch_loop(loop)

    if task_factory:
        loop.set_task_factory(task_factory)

    asyncio.set_event_loop(loop)

    try:
        yield loop
    finally:
        try:
            _cancel_all_tasks(loop, tasks)
        finally:
            asyncio.set_event_loop(None)
            loop.close()

@contextmanager
def _get_loop(
    always_create_new_loop: bool = False,
) -> Iterator[AbstractEventLoop]:
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError as re:
        if "There is no current event loop in thread" in str(re):
            with _new_loop() as loop:
                yield loop
            return
        else:
            raise

    @contextmanager
    def _restore_loop(
        loop: AbstractEventLoop,
    ) -> Iterator[None]:
        try:
            yield
        finally:
            asyncio.set_event_loop(loop)

    @contextmanager
    def _restore_running_loop() -> Iterator[None]:
        loop_from_events = asyncio.events._get_running_loop()
        asyncio.events._set_running_loop(None)
        try:
            yield
        finally:
            asyncio.events._set_running_loop(loop_from_events)

    with ExitStack() as stack:
        if loop.is_running():
            stack.enter_context(_restore_running_loop())
            stack.enter_context(_restore_loop(loop=loop))
            loop = stack.enter_context(_new_loop(loop.get_task_factory()))
        elif loop.is_closed():
            loop = stack.enter_context(_new_loop())
        elif always_create_new_loop:
            stack.enter_context(_restore_loop(loop=loop))
            loop = stack.enter_context(_new_loop())
        yield loop

T = TypeVar("T")
P = ParamSpec("P")


def await_sync(awaitable: Awaitable[T], always_create_new_loop: bool = False) -> T:
    with _get_loop(always_create_new_loop) as loop:
        return loop.run_until_complete(awaitable)

def is_jupyter_dispatch_queue() -> bool:
    cur_task = asyncio.current_task()
    return (
        cur_task is not None
        and cur_task.get_coro().__qualname__ == "Kernel.dispatch_queue"
    )

def async_run(coro: Coroutine[None, None, T]) -> T:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    
    if loop is not None and is_jupyter_dispatch_queue():
        ctx = contextvars.copy_context()
        func_call = functools.partial(ctx.run, asyncio.run, coro)
        if _CONVERT_TO_ASYNC_EXECUTOR is None:
            configure_conveyor_to_async_executor()
        
        return _CONVERT_TO_ASYNC_EXECUTOR.submit(func_call).result()
    
    if loop is not None:
        raise RuntimeError(
            "Trying to call async_run from inside a coroutine stack. Wrap blocking call from coroutine in "
            "asyncio.to_thread."
        )
    
    return asyncio.run(coro)

@contextmanager
def await_sync_contextmanager(
    context: AsyncContextManager[T],
) -> Iterator[T]:
    result = await_sync(context.__aenter__())
    exit_result = Tuple[
        Optional[Type[Exception]], Optional[Exception], Optional[types.TracebackType]
    ] = (None, None, None)
    try:
        yield result
    except Exception as e:
        exit_result = (type(e), e, None)
    finally:
        await_sync(context.__aexit__(*exit_result))

def await_sync_decorator(fn: Callable[P, Awaitable[T]]) -> Callable[P, T]:
    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        return await_sync(fn(*args, **kwargs))
    return wrapper

class _ThreadPoolExecutorWithJitter(ThreadPoolExecutor):
    def __init__(
            self,
            max_jitter: float | None = None,
            max_threads: float | None = None,
            max_workers: float | None = None,
            thread_name_prefix: str = "",
            initializer: Callable[[], object] | None = None,
            initargs: Tuple[object, ...] = (),
    ) -> None:
        self.max_jitter = max_jitter
        self.max_threads = max_threads
        super().__init__(
            max_workers=max_workers,
            thread_name_prefix=thread_name_prefix,
            initializer=initializer,
            initargs=initargs,
        )

    def submit(
            self: "_ThreadPoolExecutorWithJitter",
            func: Callable[P, T],
            *args: P.args,
            **kwargs: P.kwargs,
    ) -> Future[T]:
        nullable_max_jitter: float | None = self.max_jitter
        if nullable_max_jitter is not None:
            max_jitter: float = nullable_max_jitter
            
            def wrapper_with_jitter(method: Callable[[], T]) -> T:
                time.sleep(random.random() * max_jitter)
                return method()
            
            func = functools.partial(wrapper_with_jitter, func)
        
        return super().submit(func, *args, **kwargs)
    
_CONVERT_TO_ASYNC_EXECUTOR: Optional[_ThreadPoolExecutorWithJitter] = None

def configure_conveyor_to_async_executor(
        max_threads: Optional[int] = None,
        max_jitter: Optional[float] = None,
        thread_name_prefix: Optional[str] = "",
) -> None:
    global _CONVERT_TO_ASYNC_EXECUTOR
    _CONVERT_TO_ASYNC_EXECUTOR = _ThreadPoolExecutorWithJitter(
        max_threads=max_threads,
        max_jitter=max_jitter,
        thread_name_prefix=thread_name_prefix,
    )

async def convert_to_async(
        func: Callable[P, T] | Callable[P, Coroutine[None, None, T]],
        *args: P.args,
        **kwargs: P.kwargs,
) -> T:
    """
    Run a function synchronously on a separate thread and await the result.
    Supports both async and synchronous functions.
    """
    loop = asyncio.get_running_loop()
    if _CONVERT_TO_ASYNC_EXECUTOR is None:
        configure_conveyor_to_async_executor()
    ctx = contextvars.copy_context()
    if asyncio.iscoroutinefunction(func):
        def wrapped_coroutine(
                coroutine: Callable[P, Coroutine[None, None, T]],
                *args: P.args,
                **kwargs: P.kwargs,
        ) -> T:
            return await_sync(coroutine(*args, **kwargs))
        
        func = functools.partial(wrapped_coroutine, func)
    
    future = loop.run_in_executor(
        _CONVERT_TO_ASYNC_EXECUTOR,
        functools.partial(ctx.run, func, *args, **kwargs),
    )

    return await future


def make_awaitable(value: T = None) -> Awaitable[T]:
    result: asyncio.Future[T] = asyncio.Future()
    result.set_result(value)
    return result

class LoopDriver:
    def __init__(self) -> None:
        self._loop: AbstractEventLoop = asyncio.new_event_loop()

        def run_loop(loop: AbstractEventLoop) -> None:
            asyncio.set_event_loop(loop)
            try:
                loop.run_forever()
            finally:
                loop.close()
        
        self._thread = threading.Thread(target=run_loop, args=(self._loop,), daemon=True)
        self._thread.start()

    def __del__(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)

    def run_coro(self, coro: Coroutine[None, None, T]) -> T:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()
    
    def schedule_coro(self, coro: Coroutine[None, None, T]) -> Future[T]:
        return asyncio.run_coroutine_threadsafe(coro, self._loop)
    
_local = threading.local()

def schedule_in_another_thread(awaitable: Awaitable[T]) -> Future[T]:
    async def _f() -> T:
        return await awaitable
    
    driver = None
    
    try:
        driver = _local.loop_driver
    except AttributeError:
        driver = LoopDriver()
        _local.loop_driver = driver
    
    return driver.schedule_coro(_f())

def await_in_another_thread(awaitable: Awaitable[T]) -> T:
    future = schedule_in_another_thread(awaitable)
    return future.result()

def get_or_create_event_loop() -> Optional[AbstractEventLoop]:
    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        print("Event loop not found, creating new loop")
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return asyncio.get_event_loop()
        except RuntimeError:
            print("Failed to create new event loop")
            return None
