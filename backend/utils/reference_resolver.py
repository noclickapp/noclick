# Shared utility for resolving {{nodeId.path.to.field}} references in workflow
# config values. Used by both setup_execution_handler and workflow_execution_handler.

import re
from typing import Any, Dict


# Pre-compiled patterns
_REF_PATTERN = re.compile(r'\{\{([^}]+)\}\}')
_ARRAY_INDEX_PATTERN = re.compile(r'^([^\[]*)((?:\[\d+\])*)$')
_INDEX_EXTRACT_PATTERN = re.compile(r'\[(\d+)\]')


def resolve_references(value: Any, node_outputs: Dict[str, Any]) -> Any:
    """Recursively resolve {{nodeId.path}} references in config values.

    Handles strings (full-match preserves type, partial-match stringifies),
    dicts, and lists. Primitives pass through unchanged.
    """
    if isinstance(value, str):
        full_match = _REF_PATTERN.fullmatch(value.strip())
        if full_match:
            return resolve_single_reference(full_match.group(1), node_outputs)

        def replace_ref(match: re.Match) -> str:
            resolved = resolve_single_reference(match.group(1), node_outputs)
            return '' if resolved is None else str(resolved)

        return _REF_PATTERN.sub(replace_ref, value)
    elif isinstance(value, dict):
        return {k: resolve_references(v, node_outputs) for k, v in value.items()}
    elif isinstance(value, list):
        return [resolve_references(item, node_outputs) for item in value]
    return value


def _navigate_value(value: Any, path: str) -> Any:
    """Navigate a resolved value through a dotted path.

    Supports nested '[]' (fan-out / map to a list) and '[N]' numeric indices.
    Returns None for any missing key, out-of-range index, or type mismatch.
    """
    if '[]' in path:
        idx = path.index('[]')
        before = path[:idx].rstrip('.')
        after = path[idx + 2:].lstrip('.')
        arr = _navigate_value(value, before) if before else value
        if not isinstance(arr, list):
            return None
        if not after:
            return arr
        return [_navigate_value(item, after) for item in arr]

    current = value
    for part in path.split('.'):
        if not part:
            continue
        key_match = _ARRAY_INDEX_PATTERN.match(part)
        if not key_match:
            return None
        key_name = key_match.group(1)
        indices_str = key_match.group(2)
        if key_name:
            if isinstance(current, dict) and key_name in current:
                current = current[key_name]
            else:
                return None
        if indices_str:
            for idx_match in _INDEX_EXTRACT_PATTERN.finditer(indices_str):
                idx = int(idx_match.group(1))
                if isinstance(current, list) and 0 <= idx < len(current):
                    current = current[idx]
                else:
                    return None
    return current


def resolve_single_reference(ref_path: str, node_outputs: Dict[str, Any]) -> Any:
    """Resolve a single reference path like 'nodeId.field' or 'nodeId.data[0].name'.

    Supports:
      - Dot-separated key access: nodeId.key1.key2
      - Array index access: nodeId.items[0].name
      - Array map: nodeId.items[].name -> [el['name'], ...] (a list value, NOT a
        loop; implicit auto-iteration was removed — only explicit iteration nodes loop)
      - Entire node output: nodeId (no path)
    """
    # '[]' maps over the array and returns the resulting list value (no looping).
    if '[]' in ref_path:
        idx = ref_path.index('[]')
        source_path = ref_path[:idx].rstrip('.')
        remainder = ref_path[idx + 2:].lstrip('.')
        array_value = resolve_single_reference(source_path, node_outputs)
        if not isinstance(array_value, list):
            return None
        if not remainder:
            return array_value
        return [_navigate_value(item, remainder) for item in array_value]

    parts = ref_path.split('.')
    if not parts:
        return None

    node_id = parts[0]
    path = parts[1:]

    if node_id not in node_outputs:
        return None

    current = node_outputs[node_id]
    if not path:
        return current

    for part in path:
        key_match = _ARRAY_INDEX_PATTERN.match(part)
        if not key_match:
            return None

        key_name = key_match.group(1)
        indices_str = key_match.group(2)

        if key_name:
            if isinstance(current, dict) and key_name in current:
                current = current[key_name]
            else:
                return None

        if indices_str:
            for idx_match in _INDEX_EXTRACT_PATTERN.finditer(indices_str):
                idx = int(idx_match.group(1))
                if isinstance(current, list) and 0 <= idx < len(current):
                    current = current[idx]
                else:
                    return None

    return current
