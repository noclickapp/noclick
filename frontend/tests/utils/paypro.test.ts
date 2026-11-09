import { describe, expect, it, vi } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/paypro.json';
import meta from '~/schemas/nodeMeta/paypro.json';

vi.mock('~/components/workflow/nodes/nodeRegistry', () => ({
    AVAILABLE_NODES: [], getNodeMetadata: () => undefined,
}));

import { PayProNode } from '~/components/workflow/nodes/integrations/paypro';

describe('PayPro integration metadata', () => {
    it('offers one manually entered API key with a default type tag', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['paypro_api_key']);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
        expect(schema.$defs.PayProAPIKeyCredential.required).toEqual(['api_key']);
        expect(schema.$defs.PayProAPIKeyCredential.properties.credential_type.default).toBe('paypro_api_key');
        expect(meta.credentialTypes['PayPro API Key']).toBe('paypro_api_key');
        expect(meta.autoSelectCredential).toBe(true);
    });
    it('discovers the finance integration and its reviewed icon', () => {
        expect(PayProNode.type).toBe('automation-paypro');
        expect(PayProNode.label).toBe('PayPro');
        expect(PayProNode.category).toBe('finance-accounting');
        expect(PayProNode.Icon).toBeTruthy();
    });
});
