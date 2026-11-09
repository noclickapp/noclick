// Simpro connects with a pasted API key and a provider-bound build URL.
// Pin the connection method so the manual connect catalog stays usable.
import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/simpro.json';
import meta from '~/schemas/nodeMeta/simpro.json';

describe('Simpro connection metadata', () => {
    it('offers the manually entered build URL and API key', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['simpro_api_key']);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
        expect(schema.$defs.SimproAPIKeyCredential.required).toEqual(['build_url', 'api_key']);
        expect(schema.$defs.SimproAPIKeyCredential.properties.credential_type.default).toBe('simpro_api_key');
        expect(meta.credentialTypes['Simpro API Key']).toBe('simpro_api_key');
        expect(meta.autoSelectCredential).toBe(true);
    });
});
