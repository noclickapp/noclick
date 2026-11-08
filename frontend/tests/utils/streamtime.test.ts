import { beforeAll, describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

beforeAll(() => loadNodeSchemas(['automation-streamtime']));

describe('Streamtime connection method', () => {
    it('offers the subscriber bearer token as a manual API credential', () => {
        const methods = credentialRequirements('automation-streamtime').map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({
            credential_type: 'streamtime_api_token', method_kind: 'api_key', is_oauth: false,
        });
    });
});
