// Shared predicate for "is this a publishable fullscreen interface-html-react web app".
//
// interface-html-react's `fullscreen` config defaults to "true" in the JSON schema /
// Pydantic model, but the frontend does NOT materialize that default into data.config at
// node creation. So a freshly created / AI-built / pasted interface node usually has NO
// `fullscreen` key at all — which means fullscreen (the default). Only an explicit
// "false" (grid mode) is non-fullscreen. The old inline check (=== 'true' || === true)
// therefore silently missed every node where the default was never written, so the
// quick-publish banner + per-node Publish button never appeared.
//
// Used by the per-node Publish button (InterfaceNode), the top-bar Publish button
// (CanvasTopBar), the quick-publish banner detection (FlowCanvas → publish-state store), and
// the Interface-tab renderer (WorkflowInterface) so they all agree on which nodes/blocks
// are fullscreen web apps.

/** A `fullscreen` config value counts as fullscreen unless it's explicitly false. Absent
 *  => the schema default ("true") => fullscreen. */
export function isFullscreenValue(fullscreen: unknown): boolean {
    return fullscreen !== 'false' && fullscreen !== false;
}

/** Whether a canvas node is a publishable fullscreen interface-html-react web app. */
export function isFullscreenInterfaceNode(
    type: string | undefined,
    config: Record<string, unknown> | null | undefined,
): boolean {
    return type === 'interface-html-react' && isFullscreenValue(config?.fullscreen);
}

/** Whether an interface-html-react node actually has source to render — non-empty HTML
 *  `content` (HTML mode) or `jsx_source` (JSX/React mode). A freshly dropped node, or one the
 *  AI builder added but hasn't filled yet (builder before node drafting), has neither: publishing it
 *  would ship a blank page, so surfaces like the quick-publish CTA shouldn't offer it.
 *
 *  Takes the whole node `data` (not just `data.config`) because `content` is a shared-slot
 *  field: it's a registered top-level field (the sticky-note body), so a node loaded from the
 *  backend carries HTML-mode content at `data.content`, while an in-session edit keeps it at
 *  `data.config.content`. We check both so the result doesn't flip across a save/reload (see
 *  TOP_LEVEL_FIELDS + getNodeFieldValue in applyNodeUpdate.ts). `jsx_source` isn't registered,
 *  so it always lives in `data.config`. Checking all three rather than branching on `operation`
 *  also keeps it robust to the mode field being absent (defaults aren't materialized — see
 *  above). The caller only invokes this for type === 'interface-html-react', so the top-level
 *  `content` read can't collide with a sticky note. */
export function interfaceNodeHasContent(
    data: Record<string, unknown> | null | undefined,
): boolean {
    const config = (data?.config ?? {}) as Record<string, unknown>;
    const nonEmpty = (v: unknown) => typeof v === 'string' && v.trim().length > 0;
    return nonEmpty(config.jsx_source) || nonEmpty(config.content) || nonEmpty(data?.content);
}

/** The display name for an interface node — its canvas header title (InterfaceNode)
 *  AND its Interface sub-tab / grid-card title (WorkflowInterface) must agree on this.
 *  The node's own name (top-level metadata `data.label`, set by canvas rename / the AI
 *  builder) wins over a legacy nested `config.label`, then the generic block-type label,
 *  then the raw type. Keeping this in one place stops the tab from falling back to the
 *  block-type label ("HTML / React") while the canvas shows the node's real name. */
export function resolveInterfaceBlockLabel(
    dataLabel: string | undefined,
    configLabel: string | undefined,
    defLabel: string | undefined,
    fallback: string,
): string {
    return dataLabel ?? configLabel ?? defLabel ?? fallback;
}
