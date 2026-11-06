import { describe, expect, it } from 'vitest';
import { upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

describe('Invoice Ninja credential selection on canvas add', () => {
    it('selects the saved Invoice Ninja API token from the node schema', async () => {
        await loadNodeSchemas(['automation-invoiceninja']);
        upsertCredentialsIntoCache([{
            id: 'invoiceninja-test-credential',
            name: 'Invoice Ninja test',
            credential_type: 'invoiceninja_api_token',
            owned_by_me: true,
        }]);

        expect(autoSelectCredentialFromCache('automation-invoiceninja')).toEqual({
            invoiceninja_api_token: 'invoiceninja-test-credential',
        });
    });
});
