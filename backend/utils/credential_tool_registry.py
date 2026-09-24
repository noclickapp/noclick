"""Turn-local, on-demand native tools over the shared operation catalog.

Definitions belong to operations, never to accounts. Every invocation must name
a credential, which CredentialActions re-authorizes before the shared runner.
Only the most recently discovered definitions stay in model context; dispatch
keeps earlier definitions for calls already in flight in the same tool batch.
"""
from collections import OrderedDict
from copy import deepcopy
import hashlib

MAX_VISIBLE_TOOLS = 12


class CredentialToolRegistry:
    def __init__(self):
        self.routes = {}
        self.visible = OrderedDict()

    def load(self, node_type, operation, tools, configs):
        names = []
        suffix = hashlib.sha256(f"{node_type}.{operation}".encode()).hexdigest()[:10]
        lookup_name = f"credential_lookup_{operation[:33]}_{suffix}"
        for tool in tools:
            fn = tool["function"]
            config = configs[fn["name"]]
            is_lookup = config["tool_type"] == "node_op_lookup"
            name = lookup_name if is_lookup else f"credential_{operation[:40]}_{suffix}"
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
            self.visible[name] = {"type": "function", "function": {
                "name": name, "description": f"{node_type}: {fn.get('description', operation)} "
                "Uses the selected credential's approval rules. Pending approval means it has not run.",
                "parameters": parameters,
            }}
            self.visible.move_to_end(name)
            while len(self.visible) > MAX_VISIBLE_TOOLS:
                self.visible.popitem(last=False)
            names.append(name)
        return names

    def tool_params(self):
        return list(self.visible.values())
