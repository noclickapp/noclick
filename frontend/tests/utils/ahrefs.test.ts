import { describe, expect, it } from 'vitest';
import { upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

describe('Ahrefs credential selection on canvas add', () => {
    it('selects the saved Ahrefs API key from the node schema', async () => {
        await loadNodeSchemas(['automation-ahrefs']);
        upsertCredentialsIntoCache([{
            id: 'ahrefs-test-credential',
            name: 'Ahrefs test',
            credential_type: 'ahrefs_api_key',
            owned_by_me: true,
        }]);

        expect(autoSelectCredentialFromCache('automation-ahrefs')).toEqual({
            ahrefs_api_key: 'ahrefs-test-credential',
        });
    });
});
