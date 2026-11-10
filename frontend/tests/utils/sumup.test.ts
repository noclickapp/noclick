import { describe, expect, it } from 'vitest';
import { upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

describe('SumUp credential selection on canvas add', () => {
    it('selects the saved SumUp API key from the node schema', async () => {
        await loadNodeSchemas(['automation-sumup']);
        upsertCredentialsIntoCache([{
            id: 'sumup-test-credential',
            name: 'SumUp test',
            credential_type: 'sumup_api_key',
            owned_by_me: true,
        }]);

        expect(autoSelectCredentialFromCache('automation-sumup')).toEqual({
            sumup_api_key: 'sumup-test-credential',
        });
    });
});
