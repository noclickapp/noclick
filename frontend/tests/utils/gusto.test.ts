// Verify the Gusto schema selects the saved token through the shared canvas flow.
// This guards registration without duplicating credential selection logic.
import { describe, expect, it } from 'vitest';
import { upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';

describe('Gusto credential selection on canvas add', () => {
    it('selects the saved Gusto access token from the node schema', async () => {
        await loadNodeSchemas(['automation-gusto']);
        expect(getNodeCredentialInfo('automation-gusto')?.acceptedTypes).toEqual(['gusto_access_token']);
        upsertCredentialsIntoCache([{
            id: 'gusto-test-credential',
            name: 'Gusto demo',
            credential_type: 'gusto_access_token',
            owned_by_me: true,
        }]);
        expect(autoSelectCredentialFromCache('automation-gusto')).toEqual({
            gusto_access_token: 'gusto-test-credential',
        });
    });
});
