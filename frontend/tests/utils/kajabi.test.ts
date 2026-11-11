import { describe, expect, it } from 'vitest';
import { upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

describe('Kajabi credential selection on canvas add', () => {
    it('selects the saved Kajabi access token from the node schema', async () => {
        await loadNodeSchemas(['automation-kajabi']);
        upsertCredentialsIntoCache([
            {
                id: 'kajabi-test-credential',
                name: 'Kajabi test',
                credential_type: 'kajabi_access_token',
                owned_by_me: true,
            },
        ]);

        expect(autoSelectCredentialFromCache('automation-kajabi')).toEqual({
            kajabi_access_token: 'kajabi-test-credential',
        });
    });
});
