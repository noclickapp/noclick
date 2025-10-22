"""Path utilities for tests."""

from pathlib import Path


def find_project_root(marker: str = ".git") -> Path:
    """
    Find the project root by walking up the directory tree.

    Args:
        marker: Directory or file name that marks the project root (default: .git)

    Returns:
        Path to the project root

    Raises:
        RuntimeError: If the project root cannot be found
    """
    # Start from the current file's directory
    current = Path(__file__).resolve().parent

    # Walk up the directory tree to find the project root
    while current != current.parent:  # Stop at filesystem root
        if (current / marker).exists():
            return current
        current = current.parent

    # If we reach here, we didn't find the marker
    raise RuntimeError(f"Could not find project root (no {marker} directory found)")
