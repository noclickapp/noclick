/**
 * Hook for handling MCP navigation requests at the dashboard level.
 *
 * This hook registers handlers for MCP operations that require navigation,
 * such as open_workflow and create_workflow. It runs at the dashboard level
 * so navigation works regardless of which tab/view is currently active.
 */

import { useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router';
import { onSocketEvent } from '~/lib/socket-receiver';
import { sendEvent } from '~/lib/socket-sender';

interface MCPRequest {
    request_id: string;
    request_type: string;
    params: Record<string, any>;
}

interface MCPResponse {
    event_name: 'workflow:mcp:response';
    request_id: string;
    data: any;
    error?: string | null;
}

export function useMCPNavigation() {
    const navigate = useNavigate();

    const sendResponse = useCallback((requestId: string, data: any, error?: string | null) => {
        const response: MCPResponse = {
            event_name: 'workflow:mcp:response',
            request_id: requestId,
            data,
            error: error || null,
        };
        sendEvent(response as any);
        // Also dispatch for event relay path (cross-container request-response)
        window.dispatchEvent(new CustomEvent('relay:mcp_response', {
            detail: { request_id: requestId, data, error: error || null },
        }));
    }, []);

    const handleOpenWorkflow = useCallback((requestId: string, params: { workflow_id: string }) => {
        const { workflow_id } = params;
        console.log('[MCPNavigation] Opening workflow:', workflow_id);

        // Navigate to the workflows tab with the workflow ID as a query param
        navigate(`/dashboard?tab=workflows&workflow=${workflow_id}`);
        sendResponse(requestId, { success: true });
    }, [navigate, sendResponse]);

    const handleCreateWorkflow = useCallback((requestId: string, params: { workflow_id: string }) => {
        const { workflow_id } = params;
        console.log('[MCPNavigation] Opening newly created workflow:', workflow_id);

        // Navigate to the workflows tab with the new workflow ID
        navigate(`/dashboard?tab=workflows&workflow=${workflow_id}`);
        sendResponse(requestId, { success: true });
    }, [navigate, sendResponse]);

    const handleMCPRequest = useCallback((request: MCPRequest) => {
        const { request_id, request_type, params } = request;

        // Only handle navigation-related requests at this level
        // Other requests are handled by useWorkflowMCPHandler in FlowCanvas
        switch (request_type) {
            case 'open_workflow':
                handleOpenWorkflow(request_id, params as { workflow_id: string });
                break;
            case 'create_workflow':
                // create_workflow backend sends this after creating the workflow
                handleCreateWorkflow(request_id, params as { workflow_id: string });
                break;
            // Don't handle other request types - let them fall through to FlowCanvas handler
            default:
                // Don't respond - let other handlers deal with it
                break;
        }
    }, [handleOpenWorkflow, handleCreateWorkflow]);

    useEffect(() => {
        const unsubscribe = onSocketEvent(
            'workflow:mcp:request' as any,
            handleMCPRequest as any
        );
        return unsubscribe;
    }, [handleMCPRequest]);
}
