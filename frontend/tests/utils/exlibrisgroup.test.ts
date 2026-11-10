import { beforeAll, expect, it } from 'vitest';
import {
    loadNodeSchemas,
    getNodeCredentialInfo,
    getAgentToolOperations,
} from '~/utils/nodeSchemas';
import {
    credentialRequirements,
    methodFromRequirement,
} from '~/components/credential/credentialMethods';
import { ExLibrisNode } from '~/components/workflow/nodes/integrations/exlibrisgroup';

beforeAll(async () => {
    await loadNodeSchemas(['automation-exlibrisgroup']);
});
it('discovers Ex Libris, its manual API key and task-list tools', () => {
    expect(ExLibrisNode.category).toBe('industry');
    expect(getNodeCredentialInfo(ExLibrisNode.type)?.acceptedTypes).toEqual([
        'exlibrisgroup_api_key',
    ]);
    expect(
        credentialRequirements(ExLibrisNode.type).map(methodFromRequirement)
    ).toEqual([
        expect.objectContaining({
            credential_type: 'exlibrisgroup_api_key',
            method_kind: 'api_key',
            is_oauth: false,
        }),
    ]);
    expect(
        getAgentToolOperations(ExLibrisNode.type).map((op) => op.operation)
    ).toEqual(
        expect.arrayContaining([
            'list_authority_control_tasks',
            'dismiss_authority_control_task',
            'create_printout',
            'mark_lending_requests_reported',
        ])
    );
});
