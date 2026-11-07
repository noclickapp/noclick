import { describe, expect, it } from 'vitest';
import { upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

describe('Bannerbear credential selection on canvas add', () => {
    it('selects the saved Bannerbear API key from the node schema', async () => {
        await loadNodeSchemas(['automation-bannerbear']);
        upsertCredentialsIntoCache([{
            id: 'bannerbear-test-credential',
            name: 'Bannerbear test',
            credential_type: 'bannerbear_api_key',
            owned_by_me: true,
        }]);

        expect(autoSelectCredentialFromCache('automation-bannerbear')).toEqual({
            bannerbear_api_key: 'bannerbear-test-credential',
        });
    });
});
