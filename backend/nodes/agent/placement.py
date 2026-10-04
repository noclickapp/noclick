"""Where an agent's sandboxes run, and the named volumes they mount.

An edition that places agents sets the runtime config key ``_sandboxRegion``
on the agent node (the sandbox provider's own region name); both sandbox
runtimes read it when they boot. Unset, the provider places them anywhere.
``_sandboxVolumes`` is ``{mount path: volume name}`` (the volume backend's
names): both runtimes mount each one read-write beside the workspace.
``_noShell`` (true) takes the in-process agent's shell away: no sandbox and no
``execute_bash``. ``_sandboxNetwork`` is the hosts its sandboxes' code may
reach (``*.d`` covers ``d`` and the names under it; none: no network beyond
what the agent itself needs, which the runtime adds); unset, anywhere. A
runtime that can't enforce it never takes it.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

SANDBOX_REGION_KEY = "_sandboxRegion"
SANDBOX_VOLUMES_KEY = "_sandboxVolumes"
NO_SHELL_KEY = "_noShell"
SANDBOX_NETWORK_KEY = "_sandboxNetwork"


def _runtime_value(node: Any, key: str) -> Any:
    data = getattr(node, "node_data", None) or {}
    config = data.get("config") if isinstance(data.get("config"), dict) else {}
    return config.get(key) or data.get(key)


def sandbox_region_of(node: Any) -> Optional[str]:
    region = _runtime_value(node, SANDBOX_REGION_KEY)
    return region if isinstance(region, str) and region else None


def sandbox_volumes_of(node: Any) -> Dict[str, str]:
    volumes = _runtime_value(node, SANDBOX_VOLUMES_KEY)
    if not isinstance(volumes, dict):
        return {}
    return {str(path): str(name) for path, name in sorted(volumes.items()) if path and name}


def shell_of(node: Any) -> bool:
    """Whether the in-process agent has its shell (``execute_bash``)."""
    return _runtime_value(node, NO_SHELL_KEY) is not True


def sandbox_network_of(node: Any) -> Optional[Tuple[str, ...]]:
    """The hosts its sandboxes may reach, or None (anywhere). An empty list is
    a limit too, so it isn't read through ``_runtime_value``'s truthiness."""
    data = getattr(node, "node_data", None) or {}
    config = data.get("config") if isinstance(data.get("config"), dict) else {}
    network = config.get(SANDBOX_NETWORK_KEY, data.get(SANDBOX_NETWORK_KEY))
    return tuple(str(host) for host in network) if isinstance(network, list) else None
