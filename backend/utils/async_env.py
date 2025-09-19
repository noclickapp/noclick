"""
Async-safe environment variable management for parallel execution contexts.

This module provides a context-aware wrapper around os.environ that allows
different async tasks to have isolated environment variable overrides without
affecting each other or the global environment.
"""

import os
from contextvars import ContextVar
from contextlib import asynccontextmanager
from typing import Dict, Optional, Any, Iterator, Tuple, Union

# Store original environ and create context var
_original_environ = dict(os.environ)
_env_context: ContextVar[Optional[Dict[str, str]]] = ContextVar('env_context', default=None)


class ContextAwareEnviron(dict):
    """
    Environment dict that checks context variables first.
    
    This class wraps os.environ to provide async-safe environment variable
    management. Each async context can have its own set of environment
    variable overrides that don't affect other contexts or the global environment.
    """
    
    def __init__(self, original: Dict[str, str]) -> None:
        self._original = original
        super().__init__(original)
    
    def _get_merged(self) -> Dict[str, str]:
        """Get merged environment (original + context overrides)"""
        ctx = _env_context.get()
        if ctx:
            merged = dict(self._original)
            merged.update(ctx)
            return merged
        return dict(self._original)
    
    def __getitem__(self, key: str) -> str:
        ctx = _env_context.get()
        if ctx and key in ctx:
            return ctx[key]
        return self._original[key]
    
    def __setitem__(self, key: str, value: str) -> None:
        """
        Set an environment variable.
        
        Note: If in a context with overrides, this will only affect the
        original environment if the key is not overridden in the context.
        """
        ctx = _env_context.get()
        if ctx is not None and key in ctx:
            # Update the context instead of original
            ctx[key] = value
        else:
            self._original[key] = value
    
    def __delitem__(self, key: str) -> None:
        ctx = _env_context.get()
        if ctx and key in ctx:
            # Remove from context
            del ctx[key]
        else:
            del self._original[key]
    
    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        ctx = _env_context.get()
        if ctx and key in ctx:
            return True
        return key in self._original
    
    def __iter__(self) -> Iterator[str]:
        return iter(self._get_merged())
    
    def __len__(self) -> int:
        return len(self._get_merged())
    
    def __repr__(self) -> str:
        return f"ContextAwareEnviron({repr(self._get_merged())})"
    
    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        ctx = _env_context.get()
        if ctx and key in ctx:
            return ctx[key]
        return self._original.get(key, default)
    
    def pop(self, key: str, *args: Any) -> str:
        """Pop from context first, then original"""
        ctx = _env_context.get()
        if ctx and key in ctx:
            return ctx.pop(key)
        
        if len(args) > 0:
            return self._original.pop(key, args[0])
        return self._original.pop(key)
    
    def setdefault(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Set default in original if not exists anywhere"""
        ctx = _env_context.get()
        
        # Check if key exists in context
        if ctx is not None and key in ctx:
            return ctx[key]
        
        # Check if key exists in original
        if key in self._original:
            return self._original[key]
        
        # Key doesn't exist anywhere, set in original
        self._original[key] = default
        return default
    
    def clear(self) -> None:
        """Clear the environment (context if active, otherwise original)"""
        ctx = _env_context.get()
        if ctx is not None:
            ctx.clear()
        else:
            self._original.clear()
    
    def copy(self) -> Dict[str, str]:
        return self._get_merged()
    
    def update(self, *args: Any, **kwargs: str) -> None:
        """Update environment variables"""
        ctx = _env_context.get()
        if ctx is not None:
            # Update context if active
            ctx.update(*args, **kwargs)
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
    
    def __ior__(self, other: Union[Dict[str, str], 'ContextAwareEnviron']) -> 'ContextAwareEnviron':
        ctx = _env_context.get()
        if ctx is not None:
            ctx.update(other)
        else:
            self._original.update(other)
        return self


# Patch os.environ with our context-aware version
_patched_environ = ContextAwareEnviron(_original_environ)


def patch_environ() -> None:
    """Patch os.environ with the context-aware version."""
    os.environ = _patched_environ


def unpatch_environ() -> None:
    """Restore the original os.environ."""
    os.environ = _original_environ


@asynccontextmanager
async def async_env(**env_vars: str):
    """
    Set environment variables for the current async context.
    
    This context manager allows you to temporarily override environment
    variables within an async context without affecting other concurrent
    tasks or the global environment.
    
    Args:
        **env_vars: Environment variables to set for this context
        
    Example:
        async with async_env(API_KEY='test_key', DEBUG='true'):
            # These env vars are only visible in this context
            assert os.environ['API_KEY'] == 'test_key'
    """
    # Create a new dict that includes context overrides
    current_ctx = _env_context.get()
    if current_ctx is not None:
        # Inherit from parent context
        new_ctx = dict(current_ctx)
        new_ctx.update(env_vars)
    else:
        new_ctx = env_vars
    
    token = _env_context.set(new_ctx)
    try:
        yield
    finally:
        _env_context.reset(token)


# Auto-patch on import
patch_environ()