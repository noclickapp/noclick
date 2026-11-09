import { describe, expect, it } from 'vitest';
import { SevdeskNode } from '~/components/workflow/nodes/integrations/sevdesk';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

describe('Sevdesk integration', () => {
    it('discovers the finance category and a single pasted token method', async () => {
        expect(SevdeskNode.type).toBe('automation-sevdesk');
        expect(SevdeskNode.category).toBe('finance-accounting');
        await loadNodeSchemas([SevdeskNode.type]);
        const methods = credentialRequirements(SevdeskNode.type).map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ credential_type: 'sevdesk_api_token', method_kind: 'api_key', is_oauth: false });
    });
});
