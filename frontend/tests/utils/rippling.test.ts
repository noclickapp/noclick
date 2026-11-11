import { describe, expect, it } from 'vitest';
import { upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

describe('Rippling credential selection on canvas add', () => {
    it('selects the saved Rippling API token from the node schema', async () => {
        await loadNodeSchemas(['automation-rippling']);
        upsertCredentialsIntoCache([{
            id: 'rippling-test-credential',
            name: 'Rippling test',
            credential_type: 'rippling_api_token',
            owned_by_me: true,
        }]);

        expect(autoSelectCredentialFromCache('automation-rippling')).toEqual({
            rippling_api_token: 'rippling-test-credential',
        });
    });
});
