import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/tomba.json';
import meta from '~/schemas/nodeMeta/tomba.json';
import { TombaNode } from '~/components/workflow/nodes/integrations/tomba';

describe('Tomba integration', () => {
    it('offers a manual API key connection with two secret fields', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['tomba_api_key']);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
        expect(schema.$defs.TombaApiKeyCredential.required).toEqual(['api_key', 'api_secret']);
        expect(meta.credentialTypes.TombaApiKeyCredential).toBe('tomba_api_key');
    });
    it('is discoverable in the sales category', () => {
        expect(TombaNode.type).toBe('automation-tomba');
        expect(TombaNode.category).toBe('crm-sales');
        expect(meta.autoSelectCredential).toBe(true);
    });
});
