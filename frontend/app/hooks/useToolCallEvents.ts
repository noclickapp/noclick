// Hook for fetching agent tool-call events (the durable tool_call_events log).
// Powers the Feed's "Agents" tab — one entry per tool an agent invoked, scoped
// to the active workspace. Fetch-on-open (+ org change + manual refresh); tool
// calls are high-volume background writes with no live socket broadcast.

import { useState, useEffect, useCallback } from 'react';
import { sendEventWithCallback } from '~/lib/socket-sender';
import { useOrgContext } from '~/hooks/useOrgContext';

export interface ToolCallEntry {
    id: string;
    workflow_id: string | null;
    execution_id: string | null;
    conversation_id: string | null;
    agent_node_id: string | null;
    agent_node_label: string | null;
    agent_node_type: string | null;
    agent_model: string | null;
    tool_name: string;
    tool_type: string;
    provider_node_id: string | null;
    provider_node_label: string | null;
    provider_node_type: string | null;
    operation: string | null;
    credential_id: string | null;
    credential_name: string | null;
    credential_type: string | null;
    arguments: Record<string, any> | null;
    result_status: 'success' | 'error';
    error: string | null;
    result_preview: string | null;
    duration_ms: number | null;
    created_at: string;
    workflow_name: string | null;
}

export function useToolCallEvents() {
    const [orgContext] = useOrgContext();
    const [entries, setEntries] = useState<ToolCallEntry[]>([]);
    // Final agent response per run, keyed by execution_id (workflow runs only).
    const [responses, setResponses] = useState<Record<string, string>>({});
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchToolCalls = useCallback(() => {
        setLoading(true);
        setError(null);
        sendEventWithCallback(
            { event_name: 'tool_calls:list' as any, limit: 100 },
            (response: any) => {
                if (response.error) {
                    setError(response.error);
                } else {
                    const data = response.data ?? response;
                    const list = Array.isArray(data) ? data : (data?.entries ?? []);
                    setEntries(Array.isArray(list) ? list : []);
                    setResponses((!Array.isArray(data) && data?.responses) || {});
                }
                setLoading(false);
            },
        );
    }, []);

    // Fetch on mount and when org context changes
    useEffect(() => {
        fetchToolCalls();
    }, [fetchToolCalls, orgContext.id]);

    return { entries, responses, loading, error, refresh: fetchToolCalls };
}
