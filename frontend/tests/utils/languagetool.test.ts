import { beforeAll, describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

beforeAll(() => loadNodeSchemas(['automation-languagetool']));

describe('LanguageTool manual connect', () => {
    it('offers both the account username and API key as fields a person fills in', () => {
        const requirements = credentialRequirements('automation-languagetool');
        expect(requirements).toHaveLength(1);
        const method = methodFromRequirement(requirements[0]);
        expect(method).toMatchObject({ credential_type: 'languagetool_api_key', method_kind: 'api_key', is_oauth: false });
        expect(method.credential_fields?.map(field => field.name).sort()).toEqual(['api_key', 'username']);
        expect(method.credential_fields?.every(field => field.required)).toBe(true);
    });
});
