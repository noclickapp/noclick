// Standalone source for CONNECTIONLESS_TYPES. Lifted out of nodeRegistry.ts so that
// node component files (e.g. InterfaceNode) can read it without transitively importing
// the heavy registry — the registry imports all 92 node components, which created a
// circular dependency when loading any one node file lazily (the file imports back to
// nodeRegistry, which is mid-evaluation).

import { NODE_SCHEMAS } from '~/utils/nodeSchemas';

export const CONNECTIONLESS_TYPES: ReadonlySet<string> = new Set(
    Object.entries(NODE_SCHEMAS || {})
        .filter(([, schema]) => (schema as any)?.['x-connectionless'])
        .map(([type]) => type)
);
