"""Turn-local, on-demand native tools: one registry for everything a turn loads.

A connection's operations (``load``, over the shared operation catalog) and the
tools a platform installs mid-turn (``install``: the coordinator's
``COORDINATOR_PLATFORM_TOOLS``). Definitions belong to operations, never to
accounts: every credential tool's invocation names a credential, which
CredentialActions re-authorizes before the shared runner. Only the most
recently loaded of each kind stay in model context; dispatch keeps earlier
definitions for calls already in flight in the same tool batch.
"""
from collections import OrderedDict
from copy import deepcopy
import hashlib
import re

MAX_VISIBLE_TOOLS = 12
# A platform's installs: room for one API area's operations at once.
MAX_VISIBLE_INSTALLED = 40


class DiscoveredTools:
    def __init__(self):
        # Credential tools: name -> (node_type, operation, is_lookup).
        self.routes = {}
        # Installed tools: name -> whoever installed them, which runs them.
        self.installed = {}
        self.visible = OrderedDict()

    def load(self, node_type, operation, tools, configs):
        names = []
        label = re.sub(r"[^a-zA-Z0-9_-]", "_", operation)
        suffix = hashlib.sha256(f"{node_type}.{operation}".encode()).hexdigest()[:10]
        lookup_name = f"credential_lookup_{label[:33]}_{suffix}"
        for tool in tools:
            fn = tool["function"]
            config = configs[fn["name"]]
            is_lookup = config["tool_type"] == "node_op_lookup"
            name = lookup_name if is_lookup else f"credential_{label[:40]}_{suffix}"
            arguments = deepcopy(fn["parameters"])
            if config.get("lookup_tool"):
                def relabel(value):
                    if isinstance(value, str):
                        return value.replace(config["lookup_tool"], lookup_name)
                    if isinstance(value, list):
                        return [relabel(v) for v in value]
                    if isinstance(value, dict):
                        return {k: relabel(v) for k, v in value.items()}
                    return value
                arguments = relabel(arguments)
            parameters = {
                "type": "object", "properties": {
                    "credential_id": {"type": "string", "description":
                        "Required connection ID from search_credential_tools or list_credentials. "
                        "Choose the account the user requested; ask when the choice is ambiguous."},
                    "arguments": arguments,
                }, "required": ["credential_id", "arguments"], "additionalProperties": False,
            }
            # Local schema refs are rooted at the entire tool, not arguments.
            for defs in ("$defs", "definitions"):
                if defs in arguments:
                    parameters[defs] = arguments.pop(defs)
            self.routes[name] = (node_type, operation, is_lookup)
            self._show(name, {"type": "function", "function": {
                "name": name, "description": f"{node_type}: {fn.get('description', operation)} "
                "Uses the selected credential's approval rules. Pending approval means it has not run.",
                "parameters": parameters,
            }}, self.routes, MAX_VISIBLE_TOOLS)
            names.append(name)
        return names

    def install(self, definitions, owner):
        """Function params ``owner`` runs (``await owner.call(name, arguments, call_id=...)``), callable for the
        rest of the turn."""
        names = []
        for definition in definitions:
            name = definition["function"]["name"]
            if name in self.routes:
                raise ValueError(f"{name} is already a credential tool")
            self.installed[name] = owner
            self._show(name, definition, self.installed, MAX_VISIBLE_INSTALLED)
            names.append(name)
        return names

    def _show(self, name, definition, kind, limit):
        self.visible[name] = definition
        self.visible.move_to_end(name)
        for old in [n for n in self.visible if n in kind][:-limit]:
            del self.visible[old]

    def tool_params(self):
        return list(self.visible.values())
