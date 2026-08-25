// Hook for managing approval feed state — fetches pending/resolved approvals
// from the backend and listens for real-time updates via socket events.

import { useState, useEffect, useCallback } from 'react';
import { sendEventWithCallback } from '~/lib/socket-sender';
import { onSocketEvent } from '~/lib/socket-receiver';
import { getLocalComponentValtio } from '~/state';
import { useOrgContext } from '~/hooks/useOrgContext';
import type { ApprovalRequestCreatedEvent, ApprovalRequestResolvedEvent } from '~/types/socket-events.generated';

// Shared pending count — written by useApprovalFeed, read by NavBar via useApprovalPendingCount
const VALTIO_PATH = 'noclick-ui';
const VALTIO_KEY = 'approvalPendingCount';

function writePendingCount(count: number) {
    const proxy = getLocalComponentValtio(VALTIO_PATH);
    if (!proxy.state) proxy.state = {};
    proxy.state[VALTIO_KEY] = count;
}

export interface ApprovalFormField {
    name: string;
    type: 'string' | 'number' | 'boolean' | 'select' | 'schedule' | 'list' | 'media';
    label: string;
    description?: string;
    required?: boolean;
    options?: string[];
    default?: string;
}

export interface ApprovalRequest {
    id: string;
    workflow_id: string;
    execution_id: string;
    node_id: string;
    title: string;
    fields: ApprovalFormField[];
    values: Record<string, any>;
    status: 'pending' | 'approved' | 'rejected';
    created_at: string;
    workflow_name: string;
    decided_by?: string;
    decided_by_email?: string;
    decided_at?: string;
}

interface ApprovalFeedState {
    pending: ApprovalRequest[];
    resolved: ApprovalRequest[];
    loading: boolean;
    error: string | null;
}

export function useApprovalFeed() {
    const [orgContext] = useOrgContext();
    const [state, setState] = useState<ApprovalFeedState>({
        pending: [],
        resolved: [],
        loading: true,
        error: null,
    });

    const fetchApprovals = useCallback(() => {
        setState(prev => ({ ...prev, loading: true, error: null }));
        sendEventWithCallback(
            { event_name: 'approval:list' as any },
            (response: any) => {
                if (response.error) {
                    setState(prev => ({ ...prev, loading: false, error: response.error }));
                } else {
                    const data = response.data || response;
                    const pendingList = data.pending || [];
                    setState({
                        pending: pendingList,
                        resolved: data.resolved || [],
                        loading: false,
                        error: null,
                    });
                    writePendingCount(pendingList.length);
                }
            },
        );
    }, []);

    const respond = useCallback((approvalId: string, decision: 'approved' | 'rejected', values?: Record<string, any>) => {
        // Optimistically remove from pending
        setState(prev => {
            const next = prev.pending.filter(a => a.id !== approvalId);
            writePendingCount(next.length);
            return { ...prev, pending: next };
        });

        sendEventWithCallback(
            { event_name: 'approval:respond' as any, approval_id: approvalId, decision, values },
            (response: any) => {
                if (response.error) {
                    fetchApprovals();
                }
            },
        );
    }, [fetchApprovals]);

    // Fetch on mount and when org context changes
    useEffect(() => {
        fetchApprovals();
    }, [fetchApprovals, orgContext.id]);

    // Listen for real-time events
    useEffect(() => {
        const unsubCreated = onSocketEvent('approval:request:created', (data: ApprovalRequestCreatedEvent) => {
            setState(prev => {
                // Dedupe by approval_id — a server-truth fetch may have
                // already added this row before the live event arrives.
                // Re-sync the count anyway: useApprovalCount (mounted at
                // Dashboard level) handles the same socket event with a
                // raw +1, so if we skip we have to overwrite its value
                // with our (correct) list length.
                if (prev.pending.some(a => a.id === data.approval_id)) {
                    writePendingCount(prev.pending.length);
                    return prev;
                }
                const next = [
                    {
                        // Backend id (approval_requests.id) — matches what the
                        // resolved event carries, so we can correlate and
                        // remove from pending without ghosting.
                        id: data.approval_id,
                        workflow_id: data.workflow_id,
                        execution_id: data.execution_id,
                        node_id: data.node_id,
                        title: data.title || '',
                        fields: (data as any).fields || [],
                        values: (data as any).values || {},
                        status: 'pending' as const,
                        created_at: new Date().toISOString(),
                        workflow_name: 'Workflow',
                    },
                    ...prev.pending,
                ];
                writePendingCount(next.length);
                return { ...prev, pending: next };
            });
        });

        const unsubResolved = onSocketEvent('approval:request:resolved', (data: ApprovalRequestResolvedEvent) => {
            setState(prev => {
                const next = prev.pending.filter(a => a.id !== data.approval_id);
                if (next.length === prev.pending.length) {
                    // Already removed (or never present). Re-sync the
                    // count to overwrite useApprovalCount's raw -1.
                    writePendingCount(prev.pending.length);
                    return prev;
                }
                writePendingCount(next.length);
                return { ...prev, pending: next };
            });
            // The resolved event is authoritative; no need to refetch from
            // the server (the previous unconditional fetchApprovals here
            // could re-add a just-resolved row if read-after-write hadn't
            // propagated yet).
        });

        return () => {
            unsubCreated();
            unsubResolved();
        };
    }, []);

    return {
        pending: state.pending,
        resolved: state.resolved,
        loading: state.loading,
        error: state.error,
        respond,
        refresh: fetchApprovals,
    };
}
