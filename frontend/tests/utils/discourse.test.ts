import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import schema from '~/schemas/nodes/discourse.json';

describe('Discourse credential method', () => {
    it('offers the instance API key with both authentication headers', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['discourse_api_key']);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
        expect(CREDENTIAL_TYPE_MAP.DiscourseApiKeyCredential).toBe('discourse_api_key');
        expect(CREDENTIAL_TYPE_MAP['Discourse API Key']).toBe('discourse_api_key');
        expect(Object.keys(schema.$defs.DiscourseApiKeyCredential.properties)).toEqual([
            'credential_type', 'site_url', 'api_key', 'api_username',
        ]);
    });
});
