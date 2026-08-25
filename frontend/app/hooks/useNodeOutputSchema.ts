// Hook for fetching the expected output schema AND the LLM-curated list of
// "suggested references" for a workflow node. The schema is the type-only
// tree, the suggestions are the short ordered list shown in the Suggested
// tab — non-technical users get a drop-target list without trawling JSON.

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { sendEventAsync } from '~/lib/socket-sender';
import type { Node } from '@xyflow/react';
import type { SuggestedRef } from '~/components/workflow/SuggestedRefsTab';
import type { JsonObject, JsonValue } from '~/components/workflow/nodes/types';
import { isJsonObject } from '~/utils/jsonValue';

interface UseNodeOutputSchemaOptions {
    nodeType: string | undefined;
    nodeOperation: string | undefined;
    enabled?: boolean; // Whether to fetch (default: true when both nodeType and nodeOperation are set)
}

interface UseNodeOutputSchemaReturn {
    schema: JsonObject | null;
    suggestedRefs: SuggestedRef[] | null;
    isLoading: boolean;
    error: string | null;
    refetch: () => Promise<void>;
}

interface CachedSchemaEntry {
    schema: JsonObject | null;
    suggestedRefs: SuggestedRef[] | null;
}

// Module-level cache, shared across every consumer. Entries with populated
// suggestedRefs short-circuit fully; entries with null suggestedRefs are
// treated as a miss for the suggestions (schema is still reused) so the
// hook re-fetches on the next mount in case the server has since curated.
const schemaCache = new Map<string, CachedSchemaEntry>();

const getCacheKey = (nodeType: string, nodeOperation: string) =>
    `${nodeType}:${nodeOperation}`;

/** A cache entry is "complete" once suggestions have landed. Schema-only
    entries are kept around to populate the UI immediately, but the hook
    keeps re-fetching until suggestions arrive. */
const isCacheComplete = (entry: CachedSchemaEntry | undefined): entry is CachedSchemaEntry =>
    !!entry && entry.suggestedRefs !== null;

async function fetchSchemaResponse(
    nodeType: string,
    nodeOperation: string,
    requestIdSuffix: string,
): Promise<CachedSchemaEntry | null> {
    const response = await sendEventAsync<{
        success?: boolean;
        schema?: Record<string, unknown> | null;
        suggested_refs?: SuggestedRef[] | null;
    }>({
        event_name: 'workflow:node:schema',
        request_id: `node-schema-${requestIdSuffix}`,
        node_type: nodeType,
        node_operation: nodeOperation,
    });
    if (!response?.success) return null;
    const entry: CachedSchemaEntry = {
        schema: isJsonObject(response.schema) ? response.schema : null,
        suggestedRefs: (response.suggested_refs as SuggestedRef[] | null) ?? null,
    };
    schemaCache.set(getCacheKey(nodeType, nodeOperation), entry);
    return entry;
}

export function useNodeOutputSchema({
    nodeType,
    nodeOperation,
    enabled = true,
}: UseNodeOutputSchemaOptions): UseNodeOutputSchemaReturn {
    const [schema, setSchema] = useState<JsonObject | null>(null);
    const [suggestedRefs, setSuggestedRefs] = useState<SuggestedRef[] | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const fetch = useCallback(async () => {
        if (!nodeType || !nodeOperation) return;
        setIsLoading(true);
        setError(null);
        try {
            const entry = await fetchSchemaResponse(nodeType, nodeOperation, String(Date.now()));
            if (entry) {
                setSchema(entry.schema);
                setSuggestedRefs(entry.suggestedRefs);
            } else {
                setError('Failed to fetch schema');
            }
        } catch (err) {
            const errorMsg = err instanceof Error ? err.message : 'Failed to fetch schema';
            console.error('[useNodeOutputSchema] Fetch error:', errorMsg);
            setError(errorMsg);
        } finally {
            setIsLoading(false);
        }
    }, [nodeType, nodeOperation]);

    useEffect(() => {
        setError(null);
        if (!enabled || !nodeType || !nodeOperation) {
            setSchema(null);
            setSuggestedRefs(null);
            return;
        }

        // Complete cache hit → render synchronously, no fetch.
        const cached = schemaCache.get(getCacheKey(nodeType, nodeOperation));
        if (isCacheComplete(cached)) {
            setSchema(cached.schema);
            setSuggestedRefs(cached.suggestedRefs);
            return;
        }

        fetch();
    }, [enabled, nodeType, nodeOperation, fetch]);

    return { schema, suggestedRefs, isLoading, error, refetch: fetch };
}

// Operation lives at the top of node.data, not nested under config.
const getNodeOperation = (nodeData: Record<string, unknown>) =>
    nodeData.operation as string | undefined;

/**
 * Hook to fetch expected output schemas for multiple input nodes.
 * Returns a Map of nodeId -> schema for nodes that don't have actual output data.
 * Used by ReferenceAutocompleteProvider to validate and suggest references.
 */
export function useInputNodeSchemas(inputNodes: Node[]): Map<string, JsonValue> {
    const [schemas, setSchemas] = useState<Map<string, JsonValue>>(new Map());

    // Determine which nodes need schema fetching (no output data)
    const nodesToFetch = useMemo(() => {
        return inputNodes.filter(node => {
            const hasOutput = node.data?.mockedOutput !== undefined || node.data?.output !== undefined;
            return !hasOutput && node.type;
        });
    }, [inputNodes]);

    // The fetch effect must key on the CONTENT of the set to fetch, not the array
    // reference. `nodesToFetch` is a fresh array on every `inputNodes` change, and
    // a running workflow churns `nodes` continuously — so a reference dep re-runs
    // this effect every commit, and the `setSchemas` storm trips React's
    // "Maximum update depth". The schema only depends on (id, type, operation), so
    // collapse those into a stable string and read the live array via a ref.
    const fetchKey = useMemo(
        () => nodesToFetch.map(n => `${n.id}:${n.type ?? ''}:${getNodeOperation(n.data || {}) ?? ''}`).join('|'),
        [nodesToFetch],
    );
    const nodesToFetchRef = useRef(nodesToFetch);
    nodesToFetchRef.current = nodesToFetch;

    useEffect(() => {
        const toFetch = nodesToFetchRef.current;
        if (toFetch.length === 0) {
            setSchemas(prev => (prev.size === 0 ? prev : new Map()));
            return;
        }

        let cancelled = false;
        (async () => {
            const next = new Map<string, JsonValue>();
            for (const node of toFetch) {
                const nodeType = node.type;
                const nodeOperation = getNodeOperation(node.data || {});
                if (!nodeType || !nodeOperation) continue;

                const cacheKey = getCacheKey(nodeType, nodeOperation);
                const cached = schemaCache.get(cacheKey);
                if (cached) {
                    if (cached.schema) next.set(node.id, cached.schema);
                    continue;
                }

                try {
                    const entry = await fetchSchemaResponse(nodeType, nodeOperation, `${node.id}-${Date.now()}`);
                    if (entry?.schema) next.set(node.id, entry.schema);
                } catch (err) {
                    console.error(`[useInputNodeSchemas] Failed to fetch schema for ${node.id}:`, err);
                }
            }
            if (!cancelled) setSchemas(next);
        })();

        return () => { cancelled = true; };
    }, [fetchKey]);

    return schemas;
}
