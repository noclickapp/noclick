import { useLazyTypes } from '~/hooks/useLazyTypes';
import { nodeSchemaStore } from '~/utils/nodeSchemas';

/** Loads the schemas of `types` and re-renders as they land; true once all have loaded. */
export function useNodeSchemas(types: Iterable<string | null | undefined>): boolean {
    return useLazyTypes(nodeSchemaStore, types);
}
