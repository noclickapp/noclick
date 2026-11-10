import { describe, expect, it } from 'vitest';
import { upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

describe('Etsy credential selection on canvas add', () => {
    it('selects the saved Etsy token from the node schema', async () => {
        await loadNodeSchemas(['automation-etsy']);
        upsertCredentialsIntoCache([{
            id: 'etsy-test-credential',
            name: 'Etsy test',
            credential_type: 'etsy_token',
            owned_by_me: true,
        }]);

        expect(autoSelectCredentialFromCache('automation-etsy')).toEqual({
            etsy_token: 'etsy-test-credential',
        });
    });
});
