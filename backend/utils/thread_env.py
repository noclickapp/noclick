"""
Thread-safe environment variable management for cross-thread execution contexts.

This module provides thread-aware wrappers around os.environ that allow
different threads to have isolated environment variable overrides without
affecting each other or the global environment. Works in both sync and async contexts.

For async contexts, it uses contextvars for isolation between async tasks.
For sync/thread contexts, it uses thread-local storage.

Created because OpenHands creates new threads that break async_env(). We can
probably deprecate async_env.py now.

UPDATE: Because of OpenHands' queue thread pattern where there's a worker queue processor,
we can't use this either inside agent_handler. The robust fix is to use it in TrackingLLM.
"""

import os
import threading
import functools
from contextlib import contextmanager, asynccontextmanager
from contextvars import ContextVar
from typing import Dict, Optional, Any, Iterator, Tuple, Union, List, Callable

# Store original environ
_original_environ = dict(os.environ)

# Thread-local storage for environment stacks (for thread isolation)
_thread_local = threading.local()

# Context variable for async isolation (for async task isolation)
_async_context: ContextVar[Optional[Dict[str, str]]] = ContextVar('async_env_context', default=None)


def _get_thread_stack() -> List[Dict[str, str]]:
    """Get the environment stack for the current thread, creating if needed."""
    if not hasattr(_thread_local, 'env_stack'):
        _thread_local.env_stack = []
    return _thread_local.env_stack


class ThreadAwareEnviron(dict):
    """
    Environment dict that checks thread-local stack first.
    
    This class wraps os.environ to provide thread-safe environment variable
    management. Each thread can have its own stack of environment variable
    overrides that don't affect other threads or the global environment.
    """
    
    def __init__(self, original: Dict[str, str]) -> None:
        self._original = original
        super().__init__(original)
    
    def _get_merged(self) -> Dict[str, str]:
        """Get merged environment (original + thread overrides + async overrides)."""
        merged = dict(self._original)
        
        # Apply thread-local stack
        stack = _get_thread_stack()
        for env_dict in stack:
            merged.update(env_dict)
        
        # Apply async context if present (highest priority)
        async_ctx = _async_context.get()
        if async_ctx:
            merged.update(async_ctx)
        
        return merged
    
    def _get_value(self, key: str) -> Optional[str]:
        """Get value checking async context, then thread stack, then original."""
        # Check async context first (highest priority)
        async_ctx = _async_context.get()
        if async_ctx and key in async_ctx:
            return async_ctx[key]
        
        # Check thread stack (top to bottom)
        stack = _get_thread_stack()
        for env_dict in reversed(stack):
            if key in env_dict:
                return env_dict[key]
        
        return None
    
    def __getitem__(self, key: str) -> str:
        # Check async/thread contexts first
        value = self._get_value(key)
        if value is not None:
            return value
        return self._original[key]
    
    def __setitem__(self, key: str, value: str) -> None:
        """
        Set an environment variable.
        
        Updates async context if present, else thread context, else original.
        """
        # Check async context first
        async_ctx = _async_context.get()
        if async_ctx is not None:
            async_ctx[key] = value
            return
        
        # Check thread stack
        stack = _get_thread_stack()
        if stack:
            # Update the top context
            stack[-1][key] = value
        else:
            # Update original if no context
            self._original[key] = value
    
    def __delitem__(self, key: str) -> None:
        # Check async context first
        async_ctx = _async_context.get()
        if async_ctx and key in async_ctx:
            del async_ctx[key]
            return
        
        # Check thread stack
        stack = _get_thread_stack()
        if stack:
            # Try to delete from top of stack first
            for env_dict in reversed(stack):
                if key in env_dict:
                    del env_dict[key]
                    return
        # If not in contexts, delete from original
        if key in self._original:
            del self._original[key]
        else:
            raise KeyError(key)
    
    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        # Check async/thread contexts first
        value = self._get_value(key)
        if value is not None:
            return True
        return key in self._original
    
    def __iter__(self) -> Iterator[str]:
        return iter(self._get_merged())
    
    def __len__(self) -> int:
        return len(self._get_merged())
    
    def __repr__(self) -> str:
        return f"ThreadAwareEnviron({repr(self._get_merged())})"
    
    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        # Check async/thread contexts first
        value = self._get_value(key)
        if value is not None:
            return value
        return self._original.get(key, default)
    
    def pop(self, key: str, *args: Any) -> str:
        """Pop from async context first, then thread stack, then original."""
        # Check async context first
        async_ctx = _async_context.get()
        if async_ctx and key in async_ctx:
            return async_ctx.pop(key)
        
        # Check thread stack
        stack = _get_thread_stack()
        if stack:
            for env_dict in reversed(stack):
                if key in env_dict:
                    return env_dict.pop(key)
        
        # Not in contexts, try original
        if len(args) > 0:
            return self._original.pop(key, args[0])
        return self._original.pop(key)
    
    def setdefault(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Set default in original if not exists anywhere."""
        # Check if key exists in async/thread contexts
        value = self._get_value(key)
        if value is not None:
            return value
        
        # Check if key exists in original
        if key in self._original:
            return self._original[key]
        
        # Key doesn't exist anywhere, set in original
        self._original[key] = default
        return default
    
    def clear(self) -> None:
        """Clear the current context or original if no context."""
        # Check async context first
        async_ctx = _async_context.get()
        if async_ctx is not None:
            async_ctx.clear()
            return
        
        # Check thread stack
        stack = _get_thread_stack()
        if stack:
            # Clear the top context
            stack[-1].clear()
        else:
            # Clear original if no context
            self._original.clear()
    
    def copy(self) -> Dict[str, str]:
        return self._get_merged()
    
    def update(self, *args: Any, **kwargs: str) -> None:
        """Update environment variables."""
        # Check async context first
        async_ctx = _async_context.get()
        if async_ctx is not None:
            async_ctx.update(*args, **kwargs)
            return
        
        # Check thread stack
        stack = _get_thread_stack()
        if stack:
            # Update top context
            stack[-1].update(*args, **kwargs)
        else:
            # Update original if no context
            self._original.update(*args, **kwargs)
    
    def keys(self) -> Iterator[str]:
        return self._get_merged().keys()
    
    def values(self) -> Iterator[str]:
        return self._get_merged().values()
    
    def items(self) -> Iterator[Tuple[str, str]]:
        return self._get_merged().items()
    
    # For Python 3.9+ | operator support
    def __or__(self, other: Dict[str, str]) -> Dict[str, str]:
        return self._get_merged() | other
    
    def __ror__(self, other: Dict[str, str]) -> Dict[str, str]:
        return other | self._get_merged()
    
    def __ior__(self, other: Union[Dict[str, str], 'ThreadAwareEnviron']) -> 'ThreadAwareEnviron':
        # Check async context first
        async_ctx = _async_context.get()
        if async_ctx is not None:
            async_ctx.update(other)
        else:
            # Check thread stack
            stack = _get_thread_stack()
            if stack:
                stack[-1].update(other)
            else:
                self._original.update(other)
        return self


# Patch os.environ with our thread-aware version
_patched_environ = ThreadAwareEnviron(_original_environ)


def patch_environ() -> None:
    """Patch os.environ with the thread-aware version."""
    os.environ = _patched_environ


def unpatch_environ() -> None:
    """Restore the original os.environ."""
    os.environ = _original_environ


@contextmanager
def override_env(**env_vars: str):
    """
    Set environment variables for the current thread context.
    
    This context manager allows you to temporarily override environment
    variables within a thread context without affecting other threads
    or the global environment. Supports nesting with proper inheritance.
    
    Args:
        **env_vars: Environment variables to set for this context
        
    Example:
        with override_env(API_KEY='test_key', DEBUG='true'):
            # These env vars are only visible in this thread
            assert os.environ['API_KEY'] == 'test_key'
    """
    # If no env_vars provided, don't push anything to stack
    # This allows empty contexts to behave like normal environment
    if not env_vars:
        yield
        return
    
    stack = _get_thread_stack()
    
    # Create new environment dict inheriting from parent
    if stack:
        # Inherit from parent context
        new_env = dict(stack[-1])
        new_env.update(env_vars)
    else:
        # No parent, just use provided vars
        new_env = env_vars
    
    # Push to stack
    stack.append(new_env)
    
    try:
        yield
    finally:
        # Pop from stack
        stack.pop()


@asynccontextmanager
async def async_override_env(**env_vars: str):
    """
    Async version of override_env for use in async contexts.
    
    This uses contextvars to provide isolation between async tasks
    running on the same thread. Each async task gets its own environment
    overrides that don't affect other tasks.
    
    Args:
        **env_vars: Environment variables to set for this context
        
    Example:
        async with async_override_env(API_KEY='test_key', DEBUG='true'):
            # These env vars are only visible in this async task
            assert os.environ['API_KEY'] == 'test_key'
    """
    # If no env_vars provided, don't set context
    # This allows empty contexts to behave like normal environment
    if not env_vars:
        yield
        return
    
    # Get current async context
    current_ctx = _async_context.get()
    
    # Create new environment dict inheriting from parent
    if current_ctx is not None:
        # Inherit from parent async context
        new_ctx = dict(current_ctx)
        new_ctx.update(env_vars)
    else:
        # Check if there's a thread context to inherit from
        stack = _get_thread_stack()
        if stack:
            # Inherit from thread context
            new_ctx = dict(stack[-1])
            new_ctx.update(env_vars)
        else:
            # No parent, just use provided vars
            new_ctx = env_vars
    
    # Set the context var
    token = _async_context.set(new_ctx)
    
    try:
        yield
    finally:
        # Reset context var
        _async_context.reset(token)


def _capture_current_context() -> Tuple[Optional[List[Dict[str, str]]], Optional[Dict[str, str]]]:
    """
    Capture the current thread's environment context.
    
    Returns:
        Tuple of (thread_stack_copy, async_context_copy)
    """
    # Capture thread stack
    stack = _get_thread_stack()
    thread_stack_copy = list(stack) if stack else None
    
    # Capture async context
    async_ctx = _async_context.get()
    async_context_copy = dict(async_ctx) if async_ctx else None
    
    return thread_stack_copy, async_context_copy


def _restore_context_in_thread(thread_stack: Optional[List[Dict[str, str]]], 
                               async_ctx: Optional[Dict[str, str]]) -> None:
    """
    Restore captured context in the current thread.
    
    Args:
        thread_stack: The thread stack to restore
        async_ctx: The async context to restore
    """
    # Restore thread stack
    if thread_stack is not None:
        if not hasattr(_thread_local, 'env_stack'):
            _thread_local.env_stack = []
        _thread_local.env_stack.clear()
        _thread_local.env_stack.extend(thread_stack)
    
    # Restore async context
    if async_ctx is not None:
        _async_context.set(async_ctx)


def _context_preserving_wrapper(fn: Callable, 
                               thread_stack: Optional[List[Dict[str, str]]],
                               async_ctx: Optional[Dict[str, str]],
                               *args, **kwargs) -> Any:
    """
    Wrapper that restores context before executing a function.
    
    This is used to wrap functions submitted to ThreadPoolExecutor.
    """
    # Restore the captured context in this worker thread
    _restore_context_in_thread(thread_stack, async_ctx)
    
    try:
        # Execute the original function
        return fn(*args, **kwargs)
    finally:
        # Clean up the thread-local context to avoid leaks
        if hasattr(_thread_local, 'env_stack'):
            _thread_local.env_stack.clear()


# Store original ThreadPoolExecutor submit method before patching
from concurrent.futures import ThreadPoolExecutor
_original_threadpool_submit = ThreadPoolExecutor.submit


def _patched_threadpool_submit(self, fn: Callable, *args, **kwargs) -> Any:
    """
    Patched submit method for ThreadPoolExecutor that preserves context.
    
    This captures the current context and ensures it's restored in the worker thread.
    """
    # Capture current context
    thread_stack, async_ctx = _capture_current_context()
    
    # If there's any context to preserve, wrap the function
    if thread_stack or async_ctx:
        fn_with_context = functools.partial(
            _context_preserving_wrapper,
            fn,
            thread_stack,
            async_ctx
        )
        # Submit the wrapped function
        return _original_threadpool_submit(self, fn_with_context, *args, **kwargs)
    else:
        # No context to preserve, use original submit
        return _original_threadpool_submit(self, fn, *args, **kwargs)


def enable_context_propagation() -> None:
    """
    Enable automatic context propagation for ThreadPoolExecutor.
    
    This patches ThreadPoolExecutor.submit to automatically capture and restore
    context when submitting tasks to thread pools. This makes override_env work
    transparently with code that uses ThreadPoolExecutor (like OpenHands).
    """
    ThreadPoolExecutor.submit = _patched_threadpool_submit


def disable_context_propagation() -> None:
    """
    Disable automatic context propagation for ThreadPoolExecutor.
    
    This restores the original ThreadPoolExecutor.submit method.
    """
    ThreadPoolExecutor.submit = _original_threadpool_submit


# Auto-patch on import
patch_environ()

# Enable context propagation for ThreadPoolExecutor by default
enable_context_propagation()