"""What changed between two saves of a workflow's graph: the nodes added and
removed, and the ones whose config changed and how, for whoever reports on it."""

from typing import Any, Dict, List, Optional


def _get_node_label(node: Dict[str, Any]) -> str:
    """Get a human-readable label for a node."""
    # Stored workflow nodes hold the label flat on node["config"]
    # (no "data" key — that's the live ReactFlow shape).
    label = node.get('config', {}).get('label') or node.get('type') or 'unknown'
    return label


def _truncate_value(value: Any, max_len: int = 30) -> str:
    """Truncate a value for display."""
    s = str(value)
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s


def _detect_config_changes(old_config: Dict[str, Any], new_config: Dict[str, Any]) -> List[str]:
    """Detect specific changes between two node configs."""
    changes = []

    # Check for credential changes (credentialId or credentialIds)
    for cred_key in ['credentialId', 'credentialIds']:
        old_cred = old_config.get(cred_key)
        new_cred = new_config.get(cred_key)
        if old_cred != new_cred:
            if not old_cred and new_cred:
                changes.append(f"added {cred_key}: {_truncate_value(new_cred)}")
            elif old_cred and not new_cred:
                changes.append(f"removed {cred_key}")
            else:
                changes.append(f"{cred_key}: {_truncate_value(old_cred)} → {_truncate_value(new_cred)}")

    # Check for other config field changes
    all_keys = set(old_config.keys()) | set(new_config.keys())
    changed_fields = []
    # Fields to ignore in change detection
    ignored_fields = {'credentialId', 'credentialIds', '_outputStoredLocally', 'output'}
    for key in all_keys:
        if key in ignored_fields:
            continue  # Skip credentials (handled above) and internal fields
        old_val = old_config.get(key)
        new_val = new_config.get(key)
        if old_val != new_val:
            # Show value change for simple types
            if isinstance(old_val, (str, int, float, bool, type(None))) and isinstance(new_val, (str, int, float, bool, type(None))):
                old_display = _truncate_value(old_val) if old_val is not None else "∅"
                new_display = _truncate_value(new_val) if new_val is not None else "∅"
                changed_fields.append(f"{key}: {old_display} → {new_display}")
            else:
                changed_fields.append(key)

    if changed_fields:
        if len(changed_fields) <= 2:
            changes.extend(changed_fields)
        else:
            # Show first 2 detailed, then count
            changes.extend(changed_fields[:2])
            changes.append(f"+{len(changed_fields) - 2} more fields")

    return changes


def compute_workflow_delta(
    old_workflow: Optional[Dict[str, Any]],
    new_workflow: Optional[Dict[str, Any]],
    deleted_node_ids: Optional[List[str]] = None
) -> Optional[Dict[str, Any]]:
    """
    Compute the delta between two workflow states.

    Args:
        old_workflow: Previous workflow data (nodes, edges)
        new_workflow: New workflow data (nodes, edges)
        deleted_node_ids: Explicitly deleted node IDs (from request)

    Returns:
        Dict with delta info if meaningful changes, None otherwise.
        Delta includes: added/deleted/modified counts, node labels, and change details
    """
    if not new_workflow:
        return None

    # Skip entries missing an id — corrupted client payloads shouldn't
    # take down the slack-notification path. The actual save layer
    # (workflow_handler.update_workflow) already persists the row; this
    # is just the diff computation for the audit notification.
    old_nodes = {n['id']: n for n in (old_workflow or {}).get('nodes', []) if n.get('id')}
    new_nodes = {n['id']: n for n in new_workflow.get('nodes', []) if n.get('id')}

    old_ids = set(old_nodes.keys())
    new_ids = set(new_nodes.keys())

    # Compute changes
    added_ids = new_ids - old_ids
    deleted_ids = old_ids - new_ids
    if deleted_node_ids:
        deleted_ids = deleted_ids | set(deleted_node_ids)

    # Get labels for added/deleted nodes
    added_labels = [_get_node_label(new_nodes[nid]) for nid in added_ids]
    deleted_labels = [_get_node_label(old_nodes[nid]) for nid in deleted_ids if nid in old_nodes]

    # Check for config changes in existing nodes with detailed change info
    modified_details = []  # List of (label, [changes])
    for node_id in old_ids & new_ids:
        old_config = old_nodes[node_id].get('config', {})
        new_config = new_nodes[node_id].get('config', {})
        if old_config != new_config:
            label = _get_node_label(new_nodes[node_id])
            changes = _detect_config_changes(old_config, new_config)
            # Only include if there are actual reportable changes
            if changes:
                modified_details.append((label, changes))

    # Only return delta if there are meaningful changes
    if not added_ids and not deleted_ids and not modified_details:
        return None

    return {
        'added': len(added_ids),
        'deleted': len(deleted_ids),
        'modified': len(modified_details),
        'added_labels': added_labels,
        'deleted_labels': deleted_labels,
        'modified_details': modified_details,
    }
