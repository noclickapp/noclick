import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/raisely.json';
import meta from '~/schemas/nodeMeta/raisely.json';

describe('Raisely integration', () => {
    it('offers a pasted API key with discovered metadata', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['raisely_api_key']);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
        expect(schema.$defs.RaiselyAPIKeyCredential.required).toEqual(['api_key']);
        expect(meta.credentialTypes.RaiselyAPIKeyCredential).toBe('raisely_api_key');
        expect(meta.providerLabels.raisely).toBe('Raisely API Key');
        expect(meta.autoSelectCredential).toBe(true);
    });
});
