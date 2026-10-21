// NodeDefinitions for renderers that need a node's Icon, colour, size and label without its ReactFlow wiring
// (the phone's ForkCanvas, the read-only and preview canvases). Loads only the requested types' modules.
import { getNodeDefinition, loadNodeDefinitions } from './nodes/nodeDefinitions';
import type { NodeDefinition } from './nodes/types';

// `type → NodeDefinition | null`, so callers can draw a default card for a type with no definition.
export async function loadNodeDefsFor(types: string[]): Promise<Record<string, NodeDefinition | null>> {
    await loadNodeDefinitions(types);
    return Object.fromEntries([...new Set(types)].map((type) => [type, getNodeDefinition(type) ?? null]));
}
