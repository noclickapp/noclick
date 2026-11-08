// Pins MaintainX's discovered metadata and manual token method.
// This prevents the API key from being presented as an OAuth sign-in.
import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/maintainx.json';
import meta from '~/schemas/nodeMeta/maintainx.json';

describe('MaintainX integration', () => {
    it('offers a single API key method', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['maintainx_api_key']);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
        expect(schema.$defs.MaintainxApiKey.required).toEqual(['api_key']);
        expect(meta.credentialTypes.MaintainxApiKey).toBe('maintainx_api_key');
        expect(meta.providerLabels.maintainx).toBe('Maintainx API Key');
        expect(meta.autoSelectCredential).toBe(true);
    });
});
