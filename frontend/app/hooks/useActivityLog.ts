// Hook for fetching and listening to activity log entries from log nodes.
// Used by the Feed's Activity tab.

import { useState, useEffect, useCallback } from 'react';
import { sendEventWithCallback } from '~/lib/socket-sender';
import { onSocketEvent } from '~/lib/socket-receiver';

export interface ActivityLogEntry {
    id: string;
    workflow_id: string;
    execution_id: string;
    node_id: string;
    message: string;
    level: 'info' | 'success' | 'warning' | 'error';
    created_at: string;
    workflow_name: string;
}

export function useActivityLog() {
    const [entries, setEntries] = useState<ActivityLogEntry[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchLogs = useCallback(() => {
        setLoading(true);
        setError(null);
        sendEventWithCallback(
            { event_name: 'activity:list' as any, limit: 100 },
            (response: any) => {
                if (response.error) {
                    setError(response.error);
                } else {
                    const data = response.data || response;
                    setEntries(Array.isArray(data) ? data : []);
                }
                setLoading(false);
            },
        );
    }, []);

    useEffect(() => {
        fetchLogs();
    }, [fetchLogs]);

    // Real-time: new log entries
    useEffect(() => {
        const unsub = onSocketEvent('activity:log:created' as any, (data: any) => {
            setEntries(prev => [
                {
                    id: crypto.randomUUID(),
                    workflow_id: data.workflow_id,
                    execution_id: data.execution_id,
                    node_id: data.node_id,
                    message: data.message || '',
                    level: data.level || 'info',
                    created_at: new Date().toISOString(),
                    workflow_name: 'Workflow',
                },
                ...prev,
            ]);
        });
        return unsub;
    }, []);

    return { entries, loading, error, refresh: fetchLogs };
}
