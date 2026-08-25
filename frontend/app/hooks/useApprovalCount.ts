// Global listener for approval feed pending count.
// Runs at Dashboard level so the NavBar badge updates in real-time
// regardless of whether the Feed tab is mounted.
// Re-fetches when the active org context changes so the count
// reflects the current workspace.

import { useEffect } from 'react';
import { sendEventWithCallback } from '~/lib/socket-sender';
import { onSocketEvent } from '~/lib/socket-receiver';
import { getLocalComponentValtio } from '~/state';
import { useOrgContext } from '~/hooks/useOrgContext';
import type { ApprovalRequestCreatedEvent, ApprovalRequestResolvedEvent } from '~/types/socket-events.generated';

const VALTIO_PATH = 'noclick-ui';
const VALTIO_KEY = 'approvalPendingCount';

function writePendingCount(count: number) {
    const proxy = getLocalComponentValtio(VALTIO_PATH);
    if (!proxy.state) proxy.state = {};
    proxy.state[VALTIO_KEY] = count;
}

function readPendingCount(): number {
    const proxy = getLocalComponentValtio(VALTIO_PATH);
    const value = proxy.state?.[VALTIO_KEY];
    return typeof value === 'number' ? value : 0;
}

export function useApprovalCount() {
    const [orgContext] = useOrgContext();

    useEffect(() => {
        // Fetch count (scoped to current workspace by backend)
        sendEventWithCallback(
            { event_name: 'approval:list' as any },
            (response: any) => {
                if (!response.error) {
                    const data = response.data || response;
                    const pending = data.pending || [];
                    writePendingCount(pending.length);
                }
            },
        );

        // Listen for new approval requests
        const unsubCreated = onSocketEvent('approval:request:created', (_data: ApprovalRequestCreatedEvent) => {
            writePendingCount(readPendingCount() + 1);
        });

        // Listen for resolved approval requests
        const unsubResolved = onSocketEvent('approval:request:resolved', (_data: ApprovalRequestResolvedEvent) => {
            writePendingCount(Math.max(0, readPendingCount() - 1));
        });

        return () => {
            unsubCreated();
            unsubResolved();
        };
    }, [orgContext.id]);
}
