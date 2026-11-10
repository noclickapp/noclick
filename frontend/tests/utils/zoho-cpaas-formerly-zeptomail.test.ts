/** Verifies Zoho CPaaS exposes its API-key connection and channel actions.
 * Guards the generated credential method and the public integration category. */
import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { getAgentToolOperations, loadNodeSchemas } from '~/utils/nodeSchemas';
import { ZohoCPaaSNode } from '~/components/workflow/nodes/integrations/zoho-cpaas-formerly-zeptomail';

await loadNodeSchemas(['automation-zoho-cpaas-formerly-zeptomail']);

describe('Zoho CPaaS', () => {
    it('offers channel actions using a pasted API key', () => {
        const methods = credentialRequirements(ZohoCPaaSNode.type).map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ credential_type: 'zoho_cpaas_api_key', label: 'Zoho Agent API Key', method_kind: 'api_key', is_oauth: false });
        expect(getAgentToolOperations(ZohoCPaaSNode.type).map(op => op.operation)).toContain('send_email');
        expect(ZohoCPaaSNode.category).toBe('communication');
    });
});
