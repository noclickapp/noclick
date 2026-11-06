import { describe, expect, it } from 'vitest';
import { upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

describe('Brex credential selection on canvas add', () => {
    it('selects the saved Brex API token from the node schema', async () => {
        await loadNodeSchemas(['automation-brex']);
        upsertCredentialsIntoCache([
            {
                id: 'brex-test-credential',
                name: 'Brex test',
                credential_type: 'brex_api_token',
                owned_by_me: true,
            },
        ]);

        expect(autoSelectCredentialFromCache('automation-brex')).toEqual({
            brex_api_token: 'brex-test-credential',
        });
    });
});
