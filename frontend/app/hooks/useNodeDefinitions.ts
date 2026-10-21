import { useLazyTypes } from '~/hooks/useLazyTypes';
import { nodeDefinitionStore } from '~/components/workflow/nodes/nodeDefinitions';

/** Loads the definitions (component, icon, label) of `types` and re-renders as they land; true once all have. */
export function useNodeDefinitions(types: Iterable<string | null | undefined>): boolean {
    return useLazyTypes(nodeDefinitionStore, types);
}
