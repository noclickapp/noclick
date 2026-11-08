// Pins CraftMyPDF's discovered credential metadata and its pasted API key method.
// This protects the manual connect flow and provider label from generation drift.
import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/craftmypdf.json';
import meta from '~/schemas/nodeMeta/craftmypdf.json';

describe('CraftMyPDF integration', () => {
    it('offers one API key method with automatic credential selection', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['craftmypdf_api_key']);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
        expect(schema.$defs.CraftmypdfApiKey.required).toEqual(['api_key']);
        expect(meta.credentialTypes.CraftmypdfApiKey).toBe('craftmypdf_api_key');
        expect(meta.autoSelectCredential).toBe(true);
    });
});
