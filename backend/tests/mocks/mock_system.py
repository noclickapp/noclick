"""
Reusable system patches for testing.

This module provides test-friendly mocks for system operations to avoid
external dependencies during testing while allowing precise control for testing edge cases.
"""

import asyncio
import os
import signal
import socket
from typing import Dict, List, Set, Callable, Any
from unittest.mock import MagicMock, AsyncMock
import logging

logger = logging.getLogger(__name__)


# Global state for port mocking
_mock_taken_ports: Set[int] = set()
_original_socket_methods = {}


class MockProcess:
    """Mock subprocess that can simulate different command outcomes."""
    
    def __init__(self, stdout_text="", stderr_text="", returncode=0, pid=12345):
        self.returncode = returncode
        self.pid = pid
        self.stdout = AsyncMock()
        self.stderr = AsyncMock()
        self._stdout_text = stdout_text
        self._stderr_text = stderr_text
    
    async def communicate(self):
        return (
            self._stdout_text.encode() if self._stdout_text else b"",
            self._stderr_text.encode() if self._stderr_text else b""
        )
    
    async def wait(self):
        return self.returncode
    
    def terminate(self):
        logger.debug(f"Mock process {self.pid} terminated")
    
    async def readline(self):
        # For monitoring process output (like vite startup)
        return b"Process output line\n"


class MockObserver:
    """Mock watchdog Observer for file watching."""
    
    def __init__(self):
        self.daemon = True
        self._scheduled_paths = []
    
    def schedule(self, handler, path, recursive=True):
        self._scheduled_paths.append(path)
        logger.debug(f"Mock observer scheduled for {path}")
    
    def start(self):
        logger.debug("Mock observer started")
    
    def stop(self):
        logger.debug("Mock observer stopped")
    
    def join(self, timeout=None):
        logger.debug("Mock observer joined")


def configure_mock_ports(taken_ports: List[int] = None, all_taken: bool = False):
    """
    Configure which ports should appear as taken for testing.
    
    Args:
        taken_ports: List of specific port numbers to mark as taken
        all_taken: If True, all ports will appear taken (for testing error cases)
    """
    global _mock_taken_ports
    
    if all_taken:
        # Mark a large range as taken to simulate "no free ports"
        _mock_taken_ports = set(range(1024, 65536))
    elif taken_ports:
        _mock_taken_ports = set(taken_ports)
    else:
        _mock_taken_ports = set()
    
    logger.debug(f"Mock ports configured: {len(_mock_taken_ports)} ports marked as taken")


def patch_subprocess_operations(command_responses: Dict[str, Dict[str, Any]] = None):
    """
    Patch subprocess operations with configurable responses.
    
    Args:
        command_responses: Dict mapping command names to response config
                         e.g., {"pnpm": {"stdout": "success", "returncode": 0}}
    """
    default_responses = {
        "pnpm": {"stdout": "Dependencies installed successfully", "returncode": 0},
        "npx": {"stdout": "Local: http://localhost:5174/", "returncode": 0},
        "rsync": {"stdout": "Files synced successfully", "returncode": 0},
        "tar": {"stdout": "Archive created successfully", "returncode": 0},
        "which": {"stdout": "/usr/local/bin/pnpm", "returncode": 0},
    }
    
    # Merge with custom responses if provided
    responses = {**default_responses, **(command_responses or {})}
    
    async def mock_subprocess_exec(*args, **kwargs):
        command = args[0] if args else "unknown"
        
        # Find matching response config
        config = responses.get(command, {"stdout": "Command executed", "returncode": 0})
        
        # Create mock process with configured response
        mock_proc = MockProcess(
            stdout_text=config.get("stdout", ""),
            stderr_text=config.get("stderr", ""),
            returncode=config.get("returncode", 0),
            pid=config.get("pid", 12345)
        )
        
        # Special handling for vite dev server simulation
        if command == "npx" and "vite" in args:
            mock_proc.stdout.readline = AsyncMock(return_value=b"Local: http://localhost:5174/\n")
        
        return mock_proc
    
    # Apply patch
    asyncio.create_subprocess_exec = mock_subprocess_exec


def patch_process_management():
    """Patch process management operations to avoid actual process operations."""
    
    def mock_kill(pid, sig):
        logger.debug(f"Mock kill: pid={pid}, signal={sig}")
    
    def mock_killpg(pgid, sig):
        logger.debug(f"Mock killpg: pgid={pgid}, signal={sig}")
    
    # Store originals in case we need to restore
    _original_socket_methods['os_kill'] = getattr(os, 'kill', None)
    _original_socket_methods['os_killpg'] = getattr(os, 'killpg', None)
    
    os.kill = mock_kill
    os.killpg = mock_killpg
    
    # Ensure signal constants exist
    if not hasattr(signal, 'SIGTERM'):
        signal.SIGTERM = 15
    if not hasattr(signal, 'SIGKILL'):
        signal.SIGKILL = 9


def patch_network_operations():
    """
    Patch network operations with sophisticated port availability simulation.
    
    Use configure_mock_ports() to control which ports appear taken.
    """
    global _mock_taken_ports, _original_socket_methods
    
    # Store original methods
    _original_socket_methods['socket_init'] = socket.socket.__init__
    _original_socket_methods['socket_bind'] = socket.socket.bind
    
    def mock_socket_init(self, family=socket.AF_INET, type=socket.SOCK_STREAM, proto=0, fileno=None):
        # Initialize socket attributes without creating actual socket
        self.family = family
        self.type = type
        self._closed = False
    
    def mock_socket_bind(self, address):
        """Mock socket bind that respects configured taken ports."""
        if isinstance(address, tuple) and len(address) >= 2:
            host, port = address[0], address[1]
            
            if port in _mock_taken_ports:
                # Simulate port already in use
                raise OSError(f"[Errno 48] Address already in use: {address}")
        
        # Port is available - binding succeeds
        logger.debug(f"Mock socket bound to {address}")
    
    def mock_socket_close(self):
        self._closed = True
    
    def mock_socket_enter(self):
        return self
    
    def mock_socket_exit(self, *args):
        self.close()
    
    # Apply patches
    socket.socket.__init__ = mock_socket_init
    socket.socket.bind = mock_socket_bind
    socket.socket.close = mock_socket_close
    socket.socket.__enter__ = mock_socket_enter
    socket.socket.__exit__ = mock_socket_exit


def patch_file_watching():
    """Patch watchdog file watching to avoid actual file system monitoring."""
    try:
        from watchdog import observers
        observers.Observer = MockObserver
    except ImportError:
        # watchdog not available, create a placeholder
        logger.debug("watchdog not available, creating placeholder Observer")
        
        class MockWatchdogModule:
            Observer = MockObserver
        
        import sys
        if 'watchdog.observers' not in sys.modules:
            sys.modules['watchdog.observers'] = MockWatchdogModule()


def restore_system_patches():
    """Restore original system methods (useful for test cleanup)."""
    global _original_socket_methods
    
    # Restore socket methods
    if 'socket_init' in _original_socket_methods:
        socket.socket.__init__ = _original_socket_methods['socket_init']
    if 'socket_bind' in _original_socket_methods:
        socket.socket.bind = _original_socket_methods['socket_bind']
    
    # Restore os methods
    if 'os_kill' in _original_socket_methods and _original_socket_methods['os_kill']:
        os.kill = _original_socket_methods['os_kill']
    if 'os_killpg' in _original_socket_methods and _original_socket_methods['os_killpg']:
        os.killpg = _original_socket_methods['os_killpg']
    
    # Clear taken ports
    _mock_taken_ports.clear()
    
    logger.debug("System patches restored")


def patch_all_system_operations(
    taken_ports: List[int] = None,
    all_ports_taken: bool = False,
    command_responses: Dict[str, Dict[str, Any]] = None,
    patch_network: bool = False
):
    """
    Convenience function to apply common system patches.
    
    Args:
        taken_ports: List of ports to mark as taken
        all_ports_taken: Mark all ports as taken (for error testing)
        command_responses: Custom subprocess command responses
        patch_network: Whether to patch network operations (only for port testing)
    """
    if patch_network:
        configure_mock_ports(taken_ports, all_ports_taken)
        patch_network_operations()
    
    patch_subprocess_operations(command_responses)
    patch_process_management()
    patch_file_watching()
    
    logger.debug("System operations patched for testing")


# Test utilities for port mocking
def get_mock_taken_ports() -> Set[int]:
    """Get the current set of ports marked as taken (for test verification)."""
    return _mock_taken_ports.copy()


def is_port_mocked_as_taken(port: int) -> bool:
    """Check if a specific port is mocked as taken (for test verification)."""
    return port in _mock_taken_ports