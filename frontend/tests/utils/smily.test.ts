import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { SmilyNode } from '../../app/components/workflow/nodes/integrations/smily';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '../../app/utils/nodeSchemas';

await loadNodeSchemas(['automation-smily']);

describe('Smily integration', () => {
    it('exposes Channel API operations as tools and belongs to bookings', () => {
        expect(SmilyNode.type).toBe('automation-smily');
        expect(SmilyNode.category).toBe('bookings');
        const operations = getAgentToolOperations('automation-smily').map(op => op.operation);
        expect(operations).toHaveLength(16);
        expect(operations).toContain('create_booking');
        expect(operations).toContain('cancel_booking');
        expect(operations).toContain('create_payment');
    });
    it('offers manual API key connect', () => {
        expect(credentialRequirements('automation-smily').map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
        expect(getNodeCredentialInfo('automation-smily')?.acceptedTypes).toContain('smily_api_key');
    });
});
