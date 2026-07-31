// Client-side singleton holding serialized node-icon metadata (type → label +
// iconColor + pre-rendered iconHtml), populated once from the dashboard loader.
//
// WHY: the authed app's always-mounted surfaces (command palette, workflow-list
// rows, chat event views, credential icons) need each node's brand icon + label,
// but importing the node registry to get them dragged the full ~4.7MB node-
// component graph into the dashboard's initial bundle. The registry is now only
// loaded with the (lazy) editor; these light surfaces read icons from this
// singleton instead. The dashboard loader serializes the data server-side (via
// lib/nodeCatalog.server) and sets it during render, before any consumer mounts.
//
// It's a plain module singleton (not React context) so non-component utilities
// (e.g. utils/credentialIcons) can read it synchronously too. The data is static
// (identical for every user), so a shared singleton is correct.
import type { SerializedNodeMeta } from '~/lib/nodeCatalogTypes';

let _nodeIconData: Record<string, SerializedNodeMeta> = {};

/** Populate the registry from the dashboard loader's serialized data. Idempotent. */
export function setNodeIconData(data: Record<string, SerializedNodeMeta>): void {
    // Merge rather than replace so a route that provides a partial set never
    // clobbers a fuller one already loaded this session.
    if (data && data !== _nodeIconData) {
        _nodeIconData = Object.keys(_nodeIconData).length ? { ..._nodeIconData, ...data } : data;
    }
}

/** Serialized icon metadata for one node type (undefined if not loaded/unknown). */
export function getNodeIconMeta(type: string): SerializedNodeMeta | undefined {
    return _nodeIconData[type];
}

/** All node types currently known to the icon registry. */
export function getKnownNodeIconTypes(): string[] {
    return Object.keys(_nodeIconData);
}

/**
 * Light mirror of nodeSchemas.isTriggerSource, backed by the serialized
 * `triggerOps` metadata instead of the full schema-JSON bundle — safe to call
 * from always-mounted surfaces (e.g. the workflow-browser store). Returns false
 * when the registry isn't populated yet.
 */
export function isTriggerSourceLite(
    type: string | undefined,
    operation: string | undefined,
): boolean {
    if (!type) return false;
    if (type.startsWith('trigger-')) return true;
    // The unified form node mints a public form URL whose submissions start runs.
    if (type === 'interface-form') return true;
    if (!operation) return false;
    return _nodeIconData[type]?.triggerOps?.includes(operation) ?? false;
}
