import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/itm-platform.json';
import meta from '~/schemas/nodeMeta/itm-platform.json';

describe('ITM Platform manual connection', () => {
    it('offers a session token with both required fields available to type', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map((r) => r.credential_type)).toEqual(['itm_platform_token']);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
        expect(schema.$defs.ITMPlatformTokenCredential.required).toEqual(['company', 'token']);
        expect(schema.$defs.ITMPlatformTokenCredential.properties.credential_type.default).toBe('itm_platform_token');
        expect(meta.autoSelectCredential).toBe(true);
    });
});
