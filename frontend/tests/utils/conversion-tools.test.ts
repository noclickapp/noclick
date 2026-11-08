// Pins the discovered Conversion Tools credential as a manual API token.
// Generated metadata must keep the provider available to the shared connect UI.
import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/conversion-tools.json';
import meta from '~/schemas/nodeMeta/conversion-tools.json';

describe('Conversion Tools integration', () => {
    it('offers one manual API token method', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['conversion_tools_api_token']);
        expect(methodFromRequirement(requirements[0])).toMatchObject({ method_kind: 'api_key', is_oauth: false });
        expect(schema.$defs.ConversionToolsAPITokenCredential.required).toEqual(['api_token']);
        expect(meta.credentialTypes.ConversionToolsAPITokenCredential).toBe('conversion_tools_api_token');
        expect(meta.providerLabels.conversion_tools).toBe('Conversion Tools API Token');
        expect(meta.autoSelectCredential).toBe(true);
    });
});
