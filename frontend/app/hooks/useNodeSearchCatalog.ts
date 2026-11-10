import { useEffect, useState } from 'react';
import { loadNodeSearchCatalog, nodeSearchCatalog, type NodeSearchCatalog } from '~/utils/nodeSearchCatalog';

/** The node search catalog (utils/nodeSearchCatalog), fetched once a session from the first `enabled` render; null
 *  until it lands. A failed fetch is logged and asked again on the next open, and search stays on names. */
export function useNodeSearchCatalog(enabled = true): NodeSearchCatalog | null {
    const [catalog, setCatalog] = useState(nodeSearchCatalog);
    useEffect(() => {
        if (!enabled || catalog) return;
        let live = true;
        loadNodeSearchCatalog().then(
            (loaded) => live && setCatalog(loaded),
            (error: unknown) => console.error('[nodeSearchCatalog]', error)
        );
        return () => {
            live = false;
        };
    }, [enabled, catalog]);
    return catalog;
}
