"""
Port detection utility for detecting the server port from command line arguments.

Works with both `python api.py --port 8001` and `uvicorn api:web_app --port 8001`.
"""

import sys


def detect_port_from_argv(default: int = 8000) -> int:
    """
    Detect port from command line arguments.

    Supports both formats:
    - --port 8001
    - --port=8001

    Args:
        default: Default port if not specified in argv

    Returns:
        Detected port number
    """
    port = default
    args = sys.argv[1:]

    for i, arg in enumerate(args):
        if arg == "--port" and i + 1 < len(args):
            try:
                port = int(args[i + 1])
            except ValueError:
                pass
        elif arg.startswith("--port="):
            try:
                port = int(arg.split("=")[1])
            except (ValueError, IndexError):
                pass

    return port
