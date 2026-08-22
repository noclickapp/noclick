// Tracks what the user is currently looking at (tab, workflow, selected node/block).
// Used by the headless builder and NoClick chat to make context-aware routing decisions.
//
// Backed by a Valtio proxy hoisted to globalThis so HMR — which serves the
// same source file under different `?t=` query strings (each a distinct
// browser ESM record) — doesn't fragment the singleton. Without the hoist,
// a setter called on one module instance wouldn't notify subscribers on
// another. In production the bundle is loaded once anyway, so the indirection
// is a single dictionary lookup with no behavioral difference.

import { proxy, subscribe } from 'valtio';

export interface BuilderContext {
    /** Dashboard-level tab: 'flow' | 'feed' | 'debug' | 'analytics' | 'settings' */
    dashboardTab: string | null;
    /** Current workflow ID (persists after canvas unmount) */
    workflowId: string | null;
    /** Current workflow name */
    workflowName: string | null;
    /** Inner workflow tab: 'canvas' | 'interface' | 'logs' | 'setup' | 'resources' */
    innerTab: string | null;
    /** Selected node on canvas */
    selectedNodeId: string | null;
    /** Selected block on interface grid */
    selectedInterfaceBlockId: string | null;
    /** Whether FlowCanvas is actively mounted */
    isCanvasMounted: boolean;
}

const INITIAL: BuilderContext = {
    dashboardTab: null,
    workflowId: null,
    workflowName: null,
    innerTab: null,
    selectedNodeId: null,
    selectedInterfaceBlockId: null,
    isCanvasMounted: false,
};

const GLOBAL_KEY = '__ncBuilderContextProxy';

function getOrCreateStore(): BuilderContext {
    if (typeof window === 'undefined') {
        // SSR — every request gets a fresh proxy. No HMR concerns server-side.
        return proxy({ ...INITIAL });
    }
    const w = window as unknown as { [GLOBAL_KEY]?: BuilderContext };
    if (!w[GLOBAL_KEY]) w[GLOBAL_KEY] = proxy({ ...INITIAL });
    return w[GLOBAL_KEY];
}

export const builderContextStore: BuilderContext = getOrCreateStore();

export function getBuilderContext(): Readonly<BuilderContext> {
    return builderContextStore;
}

export function updateBuilderContext(partial: Partial<BuilderContext>): void {
    // Direct assignment on the proxy — Valtio diff-detects per key and only
    // notifies subscribers when something actually changed.
    const updateKey = <K extends keyof BuilderContext>(key: K) => {
        const next = partial[key];
        if (next !== undefined && builderContextStore[key] !== next) {
            builderContextStore[key] = next;
        }
    };
    for (const key of Object.keys(partial) as (keyof BuilderContext)[]) {
        updateKey(key);
    }
}

/**
 * Subscribe to context changes. Returns an unsubscribe function. Kept for
 * non-React consumers (e.g. the WorkflowContext composition hook); React
 * components should `useSnapshot(builderContextStore)` directly.
 */
export function subscribeBuilderContext(listener: () => void): () => void {
    return subscribe(builderContextStore, listener);
}
