import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';
import { SpiroNode } from '~/components/workflow/nodes/integrations/spiro';

describe('Spiro catalog', () => {
    it('discovers the OAuth credential and CRM section', async () => {
        await loadNodeSchemas(['automation-spiro']);
        expect(SpiroNode.category).toBe('crm-sales');
        const methods = credentialRequirements('automation-spiro').map(methodFromRequirement);
        expect(methods).toEqual([expect.objectContaining({ credential_type: 'spiro_oauth', method_kind: 'oauth' })]);
    });
});
