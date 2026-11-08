// Pins CompanyCam's discovered metadata and manual token method.
// This prevents the personal token from being presented as an OAuth sign-in.
import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/companycam.json';
import meta from '~/schemas/nodeMeta/companycam.json';

describe('CompanyCam integration', () => {
    it('offers a single personal access token method', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['companycam_personal_access_token']);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
        expect(schema.$defs.CompanycamPersonalAccessToken.required).toEqual(['access_token']);
        expect(meta.credentialTypes.CompanycamPersonalAccessToken).toBe('companycam_personal_access_token');
        expect(meta.providerLabels.companycam).toBe('CompanyCam');
        expect(meta.autoSelectCredential).toBe(true);
    });
});
