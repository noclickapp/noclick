// Checks that vcita exposes its manual API-token connection in CRM & Sales.
// This protects the discovery metadata used by the connection and catalog screens.
import { describe, expect, it } from 'vitest';
import { VcitaNode } from '~/components/workflow/nodes/integrations/vcita';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

describe('vcita integration', () => {
    it('offers a manual API token in CRM & Sales', async () => {
        await loadNodeSchemas([VcitaNode.type]);
        expect(VcitaNode.category).toBe('crm-sales');
        const requirements = credentialRequirements(VcitaNode.type);
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0])).toMatchObject({
            credential_type: 'vcita_api_token', method_kind: 'api_key', is_oauth: false,
        });
    });
});
