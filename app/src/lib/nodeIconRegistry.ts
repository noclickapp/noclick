// Client-side singleton holding serialized node-icon metadata (type → label +
// iconColor + pre-rendered iconHtml), populated once from the host's loader.
//
// WHY: the app's always-mounted surfaces (command palette, workflow-list
// rows, chat event views, credential icons) need each node's brand icon + label,
// but importing the node registry to get them drags the full node-
// component graph into the page's initial bundle. The registry is only
// loaded with the (lazy) editor; these light surfaces read icons from this
// singleton instead. The host's loader serializes the data server-side
// and sets it during render, before any consumer mounts.
//
// It's a plain module singleton (not React context) so non-component utilities
// (credential icons) can read it synchronously too. The data is static
// (identical for every user), so a shared singleton is correct.
import type { SerializedNodeMeta } from '@/lib/nodeCatalogTypes';

let _nodeIconData: Record<string, SerializedNodeMeta> = {};

/** Populate the registry from the host loader's serialized data. Idempotent. */
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

/** The current serialized icon map. Passed into pure visual surfaces such as
 * a workflow's graph preview so those components do not need to reach into this
 * singleton themselves (and public routes can inject their server-built map). */
export function getNodeIconData(): Readonly<Record<string, SerializedNodeMeta>> {
    return _nodeIconData;
}

/** All node types currently known to the icon registry. */
export function getKnownNodeIconTypes(): string[] {
    return Object.keys(_nodeIconData);
}

/**
 * Light mirror of the schemas' trigger check, backed by the serialized
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
    // (interface-config-form is its pre-merge legacy alias, inlined here.)
    if (type === 'interface-form' || type === 'interface-config-form') return true;
    if (!operation) return false;
    return _nodeIconData[type]?.triggerOps?.includes(operation) ?? false;
}
