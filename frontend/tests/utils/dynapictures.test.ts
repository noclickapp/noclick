import { beforeAll, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

beforeAll(() => loadNodeSchemas(['automation-dynapictures']));
it('offers a manual DynaPictures API key with no OAuth dependency', () => {
    const [requirement] = credentialRequirements('automation-dynapictures');
    expect(requirement.label).toBe('Dynapictures API Key');
    expect(methodFromRequirement(requirement)).toMatchObject({
        method_kind: 'api_key', is_oauth: false, credential_type: 'dynapictures_api_key',
    });
});
