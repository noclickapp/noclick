// Housecall Pro must expose its operations and manual API key in the catalog.
// These checks pin the generated schema and definition at the shared frontend seams.
import { describe, expect, it } from 'vitest';
import {
    credentialRequirements,
    methodFromRequirement,
} from '~/components/credential/credentialMethods';
import { HousecallProNode } from '../../app/components/workflow/nodes/integrations/housecall-pro';
import {
    getAgentToolOperations,
    getTriggerOperations,
    getNodeCredentialInfo,
    loadNodeSchemas,
} from '../../app/utils/nodeSchemas';
import { humanizeCredentialLabel } from '../../app/utils/credentialLabels';

await loadNodeSchemas(['automation-housecall-pro']);
describe('Housecall Pro integration', () => {
    it('exposes the provider operations in the industry category', () => {
        expect(HousecallProNode.category).toBe('industry');
        expect(
            getAgentToolOperations('automation-housecall-pro').find(
                (o) => o.operation === 'create_job'
            )?.displayName
        ).toBe('Create Job');
        expect(getAgentToolOperations('automation-housecall-pro')).toHaveLength(
            25
        );
        expect(
            getAgentToolOperations('automation-housecall-pro').map(
                (o) => o.operation
            )
        ).toContain('create_job');
    });
    it('exposes four polling triggers separately from agent tools', () => {
        expect(getTriggerOperations('automation-housecall-pro').map((o) => o.operation).sort()).toEqual([
            'on_new_or_updated_customer', 'on_new_or_updated_estimate',
            'on_new_or_updated_job', 'on_new_or_updated_lead',
        ]);
    });
    it('offers a manually pasted API key', () => {
        expect(
            credentialRequirements('automation-housecall-pro').map(
                (r) => methodFromRequirement(r).method_kind
            )
        ).toEqual(['api_key']);
        expect(
            getNodeCredentialInfo('automation-housecall-pro')?.acceptedTypes
        ).toContain('housecall_pro_api_key');
        expect(humanizeCredentialLabel('Housecall Pro API Key')).toBe(
            'Housecall Pro API Key'
        );
    });
});
