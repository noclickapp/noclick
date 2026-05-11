// Lazy node-definition loader for renderers that need NodeDefinitions (Icon,
// iconColor, dimensions, label) without going through the full eager registry.
// Used by ForkCanvas / FlowCanvas (mobile path) / forkflow route to keep the
// initial mobile bundle small.
//
// The type → module mapping is discovered at runtime via `import.meta.glob`:
// on first call we load every node module in parallel, read each one's
// exported `NodeDefinition.type`, and build a `type → def` cache. Subsequent
// calls are O(1) and never hit the loaders again. The one-time cost is taken
// on first canvas mount; in exchange there's no hand-maintained type → path
// list to keep in sync with `nodes/nodeRegistry.ts`.

import type { NodeDefinition } from './nodes/types';

// Vite's import.meta.glob — matches every Node component under ./nodes (and
// its interface/ subfolder). Each module exports one or more NodeDefinitions.
const moduleLoaders = import.meta.glob<Record<string, unknown>>([
    './nodes/*Node.tsx',
    './nodes/interface/*Node.tsx',
]);

let _typeCachePromise: Promise<Map<string, NodeDefinition>> | null = null;

function buildTypeCache(): Promise<Map<string, NodeDefinition>> {
    if (_typeCachePromise) return _typeCachePromise;
    _typeCachePromise = (async () => {
        const cache = new Map<string, NodeDefinition>();
        await Promise.all(
            Object.entries(moduleLoaders).map(async ([path, loader]) => {
                try {
                    const mod = await loader();
                    for (const value of Object.values(mod)) {
                        if (
                            value &&
                            typeof value === 'object' &&
                            'type' in value &&
                            typeof (value as NodeDefinition).type === 'string'
                        ) {
                            const def = value as NodeDefinition;
                            if (!cache.has(def.type)) cache.set(def.type, def);
                        }
                    }
                } catch (err) {
                    console.error('[nodeRegistryLazy] failed to load', path, err);
                }
            }),
        );
        return cache;
    })();
    return _typeCachePromise;
}

// Load NodeDefinitions for the given types. Returns a `type → NodeDefinition |
// null` map so callers can fall back to a default renderer for unknown types.
export async function loadNodeDefsFor(
    types: string[],
): Promise<Record<string, NodeDefinition | null>> {
    const cache = await buildTypeCache();
    const result: Record<string, NodeDefinition | null> = {};
    for (const type of new Set(types)) {
        result[type] = cache.get(type) ?? null;
    }
    return result;
}
