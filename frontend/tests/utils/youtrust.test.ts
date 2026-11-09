import { describe, expect, it } from 'vitest';
import {
    credentialRequirements,
    methodFromRequirement,
} from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';
import { YoutrustNode } from '~/components/workflow/nodes/integrations/youtrust';

await loadNodeSchemas(['automation-youtrust']);

describe('Youtrust connection', () => {
    it('offers a manual API token method in documents', () => {
        expect(YoutrustNode.category).toBe('documents');
        const methods = credentialRequirements(YoutrustNode.type).map(
            methodFromRequirement
        );
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({
            credential_type: 'youtrust_api_token',
            is_oauth: false,
        });
    });
});
