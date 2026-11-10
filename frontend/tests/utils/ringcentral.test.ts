import { describe, expect, it } from 'vitest';
import { upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

describe('RingCentral credential selection on canvas add', () => {
    it('selects the saved RingCentral access token from the node schema', async () => {
        await loadNodeSchemas(['automation-ringcentral']);
        upsertCredentialsIntoCache([{
            id: 'ringcentral-test-credential',
            name: 'RingCentral test',
            credential_type: 'ringcentral_access_token',
            owned_by_me: true,
        }]);

        expect(autoSelectCredentialFromCache('automation-ringcentral')).toEqual({
            ringcentral_access_token: 'ringcentral-test-credential',
        });
    });
});
