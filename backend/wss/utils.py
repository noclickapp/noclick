"""Common utilities for WS handlers."""
import os


def get_workspace_base() -> str:
    """
    Return a writable base directory for local workspace files.

    Returns:
        str: Path to the workspace base directory
    """
    # Local: containers (running as root) use /tmp, regular users their home.
    if os.getuid() == 0:
        return "/tmp"
    return os.path.expanduser("~/workspace")
