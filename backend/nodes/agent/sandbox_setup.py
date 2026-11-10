"""An agent's sandbox setup: commands its sandbox runs as it starts, after its checkouts and before the harness
(a CLI installed, a config file written from a secret its environment holds). Bound per turn under ``_sandboxSetup``
by the edition that defines the agent; a hosted CLI sandbox runs them in order with ``bash``, and one that fails
stops the start, naming its step."""
from __future__ import annotations

from typing import Any, List

SANDBOX_SETUP_KEY = "_sandboxSetup"


def setup_of(node: Any) -> List[str]:
    """The setup commands a run's sandbox runs as it starts (``_sandboxSetup``), in order."""
    data = getattr(node, "node_data", None) or {}
    config = data.get("config") if isinstance(data.get("config"), dict) else {}
    commands = config.get(SANDBOX_SETUP_KEY) or data.get(SANDBOX_SETUP_KEY)
    return [c for c in commands if isinstance(c, str)] if isinstance(commands, list) else []
