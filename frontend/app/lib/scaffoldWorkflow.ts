// A scaffold a public page built (an /agents agent, an MCP link), made into a real workflow once its visitor is signed
// in: the Automations page opens a bare one on the canvas for the builder to finish, the chat finishes a set-up one
// in its thread.
import type { ScaffoldIntent } from '~/lib/agentScaffold';
import { sendEventAsync } from '~/lib/socket-sender';
import { WorkflowCreateRequest } from '~/types/socket-events.generated';

export interface CreatedWorkflow {
    id: string;
    name: string;
    description: string;
}

export async function createScaffoldWorkflow(
    intent: Pick<ScaffoldIntent, 'name' | 'workflowData'>,
    { organizationId, folderId }: { organizationId: string | null | undefined; folderId?: string | null }
): Promise<CreatedWorkflow> {
    const visibility = organizationId ? 'organization' : 'personal';
    const response = await sendEventAsync(
        WorkflowCreateRequest.create({
            request_id: crypto.randomUUID(),
            name: intent.name || 'Untitled',
            description: '',
            workflow_data: { nodes: intent.workflowData.nodes, edges: intent.workflowData.edges },
            permissions: { public: [], shared_with: {} },
            visibility,
            organization_permission: visibility === 'organization' ? 'edit' : undefined,
            folder_id: folderId ?? null,
        }),
        undefined,
        30000
    );
    if (response.error) throw new Error(response.error);
    if (!response.workflow) throw new Error('Failed to create agent');
    return { id: response.workflow.id, name: response.workflow.name, description: response.workflow.description || '' };
}
