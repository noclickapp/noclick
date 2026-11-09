import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

await loadNodeSchemas(['automation-kizeo-forms']);

describe('Kizeo Forms manual connection', () => {
    it('offers a pasted API token', () => {
        const methods = credentialRequirements('automation-kizeo-forms').map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ credential_type: 'kizeo_forms_api_token', method_kind: 'api_key', is_oauth: false });
    });
});
